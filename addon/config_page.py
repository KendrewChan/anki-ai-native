"""AI Study settings page, shown inside Anki's main window as its own state ("aiStudyConfig")."""

import html
import json
import subprocess
import tempfile
import threading

from aqt import mw

from . import config_ops
from collections import deque

from .session import (PROVIDER_LABELS, auth_command, find_cli, list_models, make_backend, model_for,
                      probe_model, read_auth_status, resolved_model)

STATE = "aiStudyConfig"

CSS = """
<style>
#cfg { max-width: 52em; margin: 1.2em auto; padding: 0 1em; text-align: left; }
#cfg a.back { cursor: pointer; opacity: 0.7; font-size: 0.9em; }
#cfg h2 { margin: 0.4em 0 0.6em; }
#log { max-height: 34vh; overflow-y: auto; font-size: 0.92em; margin-bottom: 0.5em; }
#log .you { margin-top: 0.6em; font-weight: 600; }
#log .ai { margin: 0.2em 0 0 1em; }
#log .chg { margin-left: 1em; font-family: ui-monospace, Menlo, monospace; font-size: 0.9em; }
#log .err { margin-left: 1em; color: #d33; }
#cmd { width: 100%; box-sizing: border-box; padding: 0.6em; font: inherit; border-radius: 6px;
       border: 1px solid #8888; background: transparent; color: inherit; }
#status { font-size: 0.85em; opacity: 0.7; min-height: 1.3em; margin: 0.3em 0 0.8em; }
.sect h3 { margin: 1em 0 0.3em; font-size: 1em; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.7; }
.sect table { border-collapse: collapse; } .sect td { padding: 0.15em 1.2em 0.15em 0; vertical-align: top; }
.sect td.k { opacity: 0.7; } .sect ol { margin: 0.2em 0 0 1.4em; padding: 0; }
.sect button { margin-left: 0.6em; } .sect select { font: inherit; }
.tree { font-size: 0.95em; } .tree details, .tree .leaf { margin-left: 1.1em; }
.tree > details, .tree > .leaf { margin-left: 0; }
.tree summary { cursor: pointer; } .tree .leaf { padding-left: 1em; }
.tree a { cursor: pointer; } .tree a.sel { font-weight: 700; text-decoration: underline; }
.tree .dot { color: #27864a; font-size: 0.8em; margin-left: 0.3em; }
.panel { margin-top: 0.7em; padding: 0.6em 0.8em; border: 1px solid #8884; border-radius: 6px; }
.panel .name { font-weight: 600; margin-bottom: 0.3em; } .panel .inh { opacity: 0.75; margin-top: 0.3em; }
.panel .p { white-space: pre-wrap; }
</style>
"""

JS = """
<script>
window.aiCfg = {
  update(logHtml, sectionsHtml, status, busy) {
    const log = document.getElementById("log");
    log.innerHTML = logHtml; log.scrollTop = log.scrollHeight;
    const sections = document.getElementById("sections");
    const open = new Set(Array.from(sections.querySelectorAll("details[open]")).map(d => d.dataset.deck));
    sections.innerHTML = sectionsHtml;
    sections.querySelectorAll("details").forEach(d => { if (open.has(d.dataset.deck)) d.open = true; });
    document.getElementById("status").textContent = status;
    const cmd = document.getElementById("cmd");
    cmd.disabled = busy; if (!busy) cmd.focus();
  },
  loadModels(e, sel) {
    if (sel.dataset.loaded) return;
    e.preventDefault();
    if (sel.dataset.loading) return;
    sel.dataset.loading = "1";
    sel.add(new Option("loading…", "", false, false));
    sel.options[sel.options.length - 1].disabled = true;
    pycmd("aiCfg:models");
  },
  setModels(options, error) {
    const sel = document.getElementById("model-sel");
    if (!sel) return;
    while (sel.options.length > 1) sel.remove(1);
    options.forEach(([value, label]) => sel.add(new Option(label, value)));
    if (error) { const o = new Option(error, ""); o.disabled = true; sel.add(o); }
    sel.dataset.loaded = "1";
    delete sel.dataset.loading;
    try { sel.showPicker(); } catch (err) { sel.focus(); }
  },
};
document.getElementById("cmd").addEventListener("keydown", function (e) {
  e.stopPropagation();
  if (e.key === "Enter" && !e.isComposing) {
    e.preventDefault();
    const v = this.value.trim();
    if (!v) return;
    this.value = "";
    pycmd("aiCfg:send:" + v);
  }
});
setTimeout(function () { document.getElementById("cmd").focus(); }, 0);
</script>
"""


class ConfigPage:
    def __init__(self, addon: str, on_config_changed):
        self.addon = addon
        self.on_config_changed = on_config_changed
        self.session = None
        self.cwd = None
        self.replies = deque(maxlen=3)  # (text, is_error): only the latest AI replies are shown
        self.history = []  # config snapshots for undo
        self.auth = "checking…"
        self.logged_in = None
        self.busy = False
        self.selected = None  # full deck name chosen in the Deck Prompts tree
        self._probing = set()  # (provider, model) lookups in flight
        setattr(mw, f"_{STATE}State", self._enter)
        setattr(mw, f"_{STATE}Cleanup", self._leave)

    # --- state ---

    def open(self):
        mw.moveToState(STATE)

    def _enter(self, _old_state, *_args):
        mw.bottomWeb.hide()
        mw.web.stdHtml(self._page_html(), context=self)
        mw.web.set_bridge_command(self._on_bridge, self)
        self._refresh_auth()

    def _leave(self, _new_state):
        if self.session is not None:
            self.session.close()
            self.session = None
        mw.bottomWeb.show()

    # --- bridge ---

    def _on_bridge(self, message: str):
        if message == "aiCfg:back":
            mw.moveToState("deckBrowser")
        elif message.startswith("aiCfg:select:"):
            self.selected = message[len("aiCfg:select:"):]
            self._update(None)
        elif message == "aiCfg:models":
            self._load_models()
        elif message.startswith("aiCfg:model:"):
            self._apply([{"set": {"model": message[len("aiCfg:model:"):]}}])
            self._update(None)
        elif message.startswith("aiCfg:provider:"):
            self._apply([{"set": {"provider": message[len("aiCfg:provider:"):]}}])
            self._update(None)
        elif message == "aiCfg:login":
            self._run_auth("login")
        elif message.startswith("aiCfg:send:") and not self.busy:
            self._send(message[len("aiCfg:send:"):])

    def _send(self, text: str):
        cfg = self._cfg()
        self.busy = True
        self._update("Thinking…")
        provider, _path = self._provider(cfg)
        in_use = resolved_model(provider, model_for(cfg)) or (cfg.get("resolved_models") or {}).get(
            f"{provider}:{model_for(cfg)}")
        prompt = config_ops.config_prompt(cfg, self.auth, text, self._decks(), self.selected, in_use)
        self._session(cfg).request(0, prompt, config_ops.parse_config_reply, 90, self._on_reply)

    def _on_reply(self, _id, result, err):
        self.busy = False
        if err:
            self.replies.append((f"AI error: {err.message}", True))
            self._update("")
            return
        rejected = []
        actions = self._apply(result["changes"], rejected)
        reply = " ".join(filter(None, [result["reply"], *rejected])) or "Done."
        self.replies.append((reply, bool(rejected)))
        for action in actions:
            self._run_auth(action)
        self._update("")

    def _apply(self, changes, rejected=None) -> list:
        """Validate + save changes; rejected ones go into `rejected`. Returns requested auth actions."""
        cfg = self._cfg()
        decks = self._decks()
        new, log, auth = config_ops.apply_changes(cfg, changes, self.history, decks=decks)
        new = config_ops.prune_deck_prompts(new, set(decks.values()))
        if rejected is not None:
            rejected += [line for line in log if line.startswith("✗")]
        if new != cfg:
            mw.addonManager.writeConfig(self.addon, new)
            self.on_config_changed()
            self._drop_session()
            if (new.get("provider") or "claude") != (cfg.get("provider") or "claude"):
                self._refresh_auth()
        return auth

    # --- claude ---

    def _session(self, cfg):
        if self.session is None:
            self.cwd = self.cwd or tempfile.mkdtemp(prefix="anki_ai_cfg_")
            self.session = make_backend(cfg, config_ops.CONFIG_SYSTEM_PROMPT, self.cwd, mw.taskman.run_on_main)
        return self.session

    def _drop_session(self):
        """Config changed (provider, model, path): the next message starts a fresh backend."""
        if self.session is not None:
            self.session.close()
            self.session = None

    def _provider(self, cfg=None) -> tuple:
        cfg = cfg or self._cfg()
        provider = cfg.get("provider") or "claude"
        return provider, find_cli(provider, cfg.get(f"{provider}_path", ""))

    def _refresh_auth(self):
        provider, path = self._provider()

        def work():
            try:
                ok, text = read_auth_status(provider, path)
            except Exception as e:  # missing binary, bad JSON, timeout — show it, don't crash the page
                ok, text = False, f"unknown ({e.__class__.__name__}: {e})"
            mw.taskman.run_on_main(lambda: self._set_auth(ok, text))

        threading.Thread(target=work, daemon=True).start()

    def _load_models(self):
        """Fill the Model dropdown with what the CLI offers right now (current model stays first)."""
        cfg = self._cfg()
        provider, path = self._provider(cfg)
        configured = model_for(cfg)
        cwd = self.cwd = self.cwd or tempfile.mkdtemp(prefix="anki_ai_cfg_")

        def work():
            error = None
            try:
                options = list_models(provider, path, cwd)
                default = resolved_model(provider, "") or probe_model(provider, path, "", cwd)
                if configured:
                    options.insert(0, ("", f"{default} (default)"))
            except Exception as e:
                options, error = [], f"couldn't load models: {e}"
            current = resolved_model(provider, configured) or configured
            options = [(v, label) for v, label in options if v != configured and label.split(" ")[0] != current]
            mw.taskman.run_on_main(lambda: mw.web.eval(
                f"window.aiCfg && aiCfg.setModels({json.dumps(options)}, {json.dumps(error)});"))

        threading.Thread(target=work, daemon=True).start()

    def _model_name(self, provider: str, path: str, configured: str) -> str:
        """The real model id; looks it up in the background the first time."""
        saved = self._cfg().get("resolved_models") or {}
        actual = resolved_model(provider, configured) or saved.get(f"{provider}:{configured}")
        if actual:
            if saved.get(f"{provider}:{configured}") != actual:
                self._save_resolved(provider, configured, actual)  # a real call reported a newer name
            return actual
        key = (provider, configured)
        if key not in self._probing:
            self._probing.add(key)
            cwd = self.cwd = self.cwd or tempfile.mkdtemp(prefix="anki_ai_cfg_")

            def work():
                try:
                    actual = probe_model(provider, path, configured, cwd)
                except Exception:  # stays "checking…"; the next real call fills it in
                    actual = None

                def done():
                    self._probing.discard(key)
                    if actual:
                        self._save_resolved(provider, configured, actual)
                    self._update(None)

                mw.taskman.run_on_main(done)

            threading.Thread(target=work, daemon=True).start()
            return "checking…"
        return configured or "checking…"

    def _save_resolved(self, provider: str, configured: str, actual: str):
        """Persist the model name so it shows immediately after a restart (not a user setting: no undo)."""
        cfg = self._cfg()
        names = dict(cfg.get("resolved_models") or {}, **{f"{provider}:{configured}": actual})
        mw.addonManager.writeConfig(self.addon, dict(cfg, resolved_models=names))

    def _set_auth(self, ok, text):
        self.logged_in, self.auth = ok, text
        if mw.state == STATE:
            self._update(None)

    def _run_auth(self, action: str):
        """login opens the browser via Claude Code's own flow; the add-on never sees credentials."""
        provider, path = self._provider()
        label = PROVIDER_LABELS[provider]
        note = {"login": f"Opening your browser to sign in to {label}…",
                "logout": f"Logging out of {label} (this also signs it out everywhere on this computer)…"}[action]
        self.replies.append((note, False))
        self._update(None)

        def work():
            try:
                r = subprocess.run(auth_command(provider, path, action), capture_output=True, text=True,
                                   timeout=300, stdin=subprocess.DEVNULL)
                msg = None if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
            except Exception as e:
                msg = str(e)

            def done():
                if msg:
                    cmd = " ".join(auth_command(provider, provider, action))
                    self.replies.append((f"{action} failed: {msg} — try `{cmd}` in a terminal.", True))
                self._refresh_auth()

            mw.taskman.run_on_main(done)

        threading.Thread(target=work, daemon=True).start()

    # --- rendering ---

    def _decks(self) -> dict:
        return {d.name: str(d.id) for d in mw.col.decks.all_names_and_ids()}

    def _cfg(self) -> dict:
        return mw.addonManager.getConfig(self.addon) or {}

    def _update(self, status):
        if mw.state != STATE:
            return
        status = "" if status is None else status
        args = [self._log_html(), self._sections_html(), status, self.busy]
        mw.web.eval(f"window.aiCfg && aiCfg.update({', '.join(json.dumps(a) for a in args)});")

    def _log_html(self) -> str:
        if not self.replies:
            return ('<div class="ai">Tell me what to change, in plain words — e.g. "use opus", '
                    '"give me 90 seconds to answer", "grade more strictly", "undo that".</div>')
        return "".join(f'<div class="{"err" if bad else "ai"}">&gt; {html.escape(t)}</div>' for t, bad in self.replies)

    def _sections_html(self) -> str:
        cfg = self._cfg()
        login = html.escape(self.auth)
        if self.logged_in is False:
            login += ' <button onclick="pycmd(\'aiCfg:login\')">Log in</button>'
        provider, found = self._provider(cfg)
        # A plain control, not the chat: if the current provider is broken, the chat can't fix it.
        options = "".join(
            f'<option value="{p}"{" selected" if p == provider else ""}>{html.escape(label)}</option>'
            for p, label in PROVIDER_LABELS.items()
        )
        select = f'<select onchange="pycmd(\'aiCfg:provider:\' + this.value)">{options}</select>'
        rows = [("Provider", select), ("Login", login)] + [
            (label, html.escape(str(cfg.get(key))))
            for label, key in (("Ask timeout (s)", "ask_timeout_s"),
                               ("Grade timeout (s)", "grade_timeout_s"), ("Missed append", "missed_append"))
        ]
        configured = model_for(cfg)
        current = html.escape(self._model_name(provider, found, configured))
        model_select = (f'<select id="model-sel" onmousedown="aiCfg.loadModels(event, this)" '
                        f'onchange="pycmd(\'aiCfg:model:\' + this.value)">'
                        f'<option value="{html.escape(configured)}" selected>{current}</option></select>')
        rows.insert(2, ("Model", model_select))
        path = cfg.get(f"{provider}_path") or ""
        rows.append((f"{PROVIDER_LABELS[provider]} path",
                     html.escape(path if path and path != "auto" else f"auto → {found}")))
        table = "".join(f'<tr><td class="k">{k}</td><td>{v}</td></tr>' for k, v in rows)
        custom = cfg.get("custom") or []
        rules = ("<ol>" + "".join(f"<li>{html.escape(r)}</li>" for r in custom) + "</ol>"
                 if custom else '<div style="opacity:.6">none yet</div>')
        return (f'<div class="sect"><h3>Configurations</h3><table>{table}</table></div>'
                f'<div class="sect"><h3>Custom Generic Rules</h3>{rules}</div>'
                f'<div class="sect"><h3>Deck Prompts</h3>{self._deck_html(cfg)}</div>')

    def _deck_html(self, cfg) -> str:
        decks = self._decks()
        prompts = cfg.get("deck_prompts") or {}
        names = sorted(decks, key=lambda n: n.lower())
        sel = self.selected if self.selected in decks else None
        ancestors = {"::".join(sel.split("::")[:i]) for i in range(1, sel.count("::") + 1)} if sel else set()

        def node(name: str) -> str:
            depth = name.count("::") + 1
            kids = [n for n in names if n.startswith(name + "::") and n.count("::") + 1 == depth + 1]
            label = html.escape(name.split("::")[-1])
            dot = '<span class="dot">●</span>' if prompts.get(decks[name], "").strip() else ""
            cls = ' class="sel"' if name == sel else ""
            js = html.escape(f"pycmd({json.dumps('aiCfg:select:' + name)});event.preventDefault();", quote=True)
            link = f'<a{cls} onclick="{js}">{label}</a>{dot}'
            if not kids:
                return f'<div class="leaf">{link}</div>'
            is_open = " open" if name in ancestors else ""
            return (f'<details data-deck="{html.escape(name)}"{is_open}><summary>{link}</summary>'
                    + "".join(node(k) for k in kids) + "</details>")

        tree = "".join(node(n) for n in names if "::" not in n)
        if sel:
            own = prompts.get(decks[sel], "").strip()
            chain = [(n, p) for n, p in config_ops.deck_chain(sel, decks, prompts) if n != sel]
            inh = "".join(f'<div class="inh">↳ {html.escape(n)}: <span class="p">{html.escape(p)}</span></div>'
                          for n, p in chain)
            panel = (f'<div class="panel"><div class="name">{html.escape(sel)}</div>'
                     f'<div class="p">{html.escape(own) if own else "<i>no prompt — tell the AI what this deck needs</i>"}</div>'
                     f'{inh}</div>')
        else:
            panel = '<div class="panel" style="opacity:.6">Click a deck to see its prompt.</div>'
        return f'<div class="tree">{tree}</div>{panel}'


    def _page_html(self) -> str:
        return (
            f'{CSS}<div id="cfg"><a class="back" onclick="pycmd(\'aiCfg:back\')">← Back</a>'
            f"<h2>AI Study settings</h2>"
            f'<div id="log">{self._log_html()}</div>'
            f'<input id="cmd" placeholder="Tell the AI what to change…">'
            f'<div id="status"></div><div id="sections">{self._sections_html()}</div></div>{JS}'
        )
