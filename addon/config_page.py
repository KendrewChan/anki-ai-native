"""AI Study settings page, shown inside Anki's main window as its own state ("aiStudyConfig")."""

import html
import json
import os
import subprocess
import threading
from collections import deque

from aqt import mw

from . import chat_page, config_ops
from .chat_page import ChatPage, deck_ids
from .fixes import Fixer
from .session import (PROC_KW, PROVIDER_LABELS, auth_command, find_cli, list_models, make_backend, model_for,
                      probe_model, provider_of, read_auth_status, resolved_model)

CSS = chat_page.CSS + """
<style>
#log .acts { margin: 0.3em 0 0.2em; } #log .acts button { margin: 0 0.4em 0.3em 0; color: initial; }
.sect td.k .kl { opacity: 0.7; } .sect ol { margin: 0.2em 0 0 1.4em; padding: 0; }
.sect button.tog { margin-left: 0; min-width: 3.6em; } .sect button.tog.on { color: #27864a; font-weight: 600; }
.help { position: relative; display: inline-block; width: 1.25em; height: 1.25em; line-height: 1.2em; margin-left: 0.4em;
        border: 1px solid #8889; border-radius: 50%; font-size: 0.75em; font-weight: 600; text-align: center;
        cursor: help; vertical-align: 0.15em; outline: none; }
.help:hover, .help:focus { z-index: 20; border-color: #3b82f6; }
.help .tip { display: none; position: absolute; top: calc(100% + 6px); left: -0.6em; z-index: 10; width: max-content;
             max-width: 22em; white-space: normal; text-align: left; font-size: 1.25em; font-weight: 400; line-height: 1.4;
             padding: 0.5em 0.75em; border-radius: 6px; background: #2b2b2b; color: #eee; border: 1px solid #8886;
             box-shadow: 0 3px 12px #0006; }
.help .tip div + div { margin-top: 0.35em; }
.help:hover .tip, .help:focus .tip { display: block; }
.tree { font-size: 0.95em; } .tree details, .tree .leaf { margin-left: 1.1em; }
.tree > details, .tree > .leaf { margin-left: 0; }
.tree summary { cursor: pointer; } .tree .leaf { padding-left: 1em; }
.tree a { cursor: pointer; } .tree a.sel { font-weight: 700; text-decoration: underline; }
.tree .dot { color: #27864a; font-size: 0.8em; margin-left: 0.3em; }
.panel { margin: 0.3em 0 0.5em; padding: 0.6em 0.8em; border: 1px solid #8884; border-radius: 6px; }
.panel .name { font-weight: 600; margin-bottom: 0.3em; } .panel .inh { opacity: 0.75; margin-top: 0.3em; }
.panel .p { white-space: pre-wrap; }
#cmd-bar { position: sticky; top: 0; z-index: 5; padding: 0.4em 0; background: var(--canvas, Canvas); }
</style>
"""

def deck_prefix(deck: str) -> str:
    """Chat-box start when a deck is clicked under Deck Settings."""
    return f'Deck prompt for "{deck}": '


JS = """
<script>
window.aiCfg = {
  update(logHtml, sectionsHtml, status, busy) {
    const log = document.getElementById("log");
    log.innerHTML = logHtml; log.scrollTop = log.scrollHeight;
    const sections = document.getElementById("sections");
    const y = window.scrollY;  // keep the view where the user clicked
    const open = new Set(Array.from(sections.querySelectorAll("details[open]")).map(d => d.dataset.deck));
    sections.innerHTML = sectionsHtml;
    sections.querySelectorAll("details").forEach(d => { if (open.has(d.dataset.deck)) d.open = true; });
    document.getElementById("status").textContent = status;
    const cmd = document.getElementById("cmd");
    cmd.disabled = busy; if (!busy) cmd.focus({preventScroll: true});
    window.scrollTo(0, y);
  },
  prefill(prefix) {  // clicking a deck starts a message about it, unless the user already typed their own
    const cmd = document.getElementById("cmd"), v = cmd.value;
    if (!v.trim()) cmd.value = prefix;
    else if (this.prefix && v.startsWith(this.prefix)) cmd.value = prefix + v.slice(this.prefix.length);
    else return;
    this.prefix = prefix;
    cmd.focus({preventScroll: true});
    cmd.setSelectionRange(cmd.value.length, cmd.value.length);
    cmd.dispatchEvent(new Event("input"));  // keep the saved draft in step
  },
  deselect(deck) {
    const d = document.querySelector(`#sections details[data-deck="${CSS.escape(deck)}"]`);
    if (d) d.open = false;
    const cmd = document.getElementById("cmd");
    if (this.prefix && cmd.value.startsWith(this.prefix)) {
      cmd.value = cmd.value.slice(this.prefix.length);
      cmd.dispatchEvent(new Event("input"));
    }
    this.prefix = null;
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
</script>
"""


class ConfigPage(ChatPage):
    STATE = "aiStudyConfig"
    PREFIX = "aiCfg"

    def __init__(self, addon: str, on_config_changed):
        super().__init__(addon)
        self.on_config_changed = on_config_changed
        self.session = None
        self.replies = deque(maxlen=3)  # (text, is_error, actions): only the latest replies are shown
        self._actions = {}  # button id -> callable, for buttons inside replies
        self._next_id = 0  # for _actions keys
        self.fixer = Fixer(self)
        self.history = []  # config snapshots for undo
        self.auth = "checking…"
        self.logged_in = None
        self.selected = None  # full deck name chosen in the Deck Settings tree
        self._probing = set()  # (provider, model) lookups in flight

    # --- the interface fixes.Fixer uses (cfg() comes from ChatPage) ---

    def provider(self, cfg=None) -> tuple:
        """(provider, CLI path)."""
        cfg = cfg or self.cfg()
        provider = provider_of(cfg)
        return provider, find_cli(provider, cfg.get(f"{provider}_path", ""))

    def apply(self, changes, rejected=None) -> list:
        """Validate + save changes; rejected ones go into `rejected`. Returns requested auth actions."""
        cfg = self.cfg()
        decks = deck_ids()
        new, log, auth = config_ops.apply_changes(cfg, changes, self.history, decks=decks)
        new = config_ops.prune_deck_prompts(new, set(decks.values()))
        if rejected is not None:
            rejected += [line for line in log if line.startswith("✗")]
        if new != cfg:
            chat_page.save_config(self.addon, new, cfg)
            self.on_config_changed()
            self._stop()
            if provider_of(new) != provider_of(cfg):
                self._refresh_auth()
        return auth

    def login(self):
        self._run_auth("login")

    def refresh(self):
        self._update(None)

    # --- page ---

    def _entered(self):
        self._refresh_auth()
        self.fixer.check_on_open()
        if self.busy:  # a message sent before leaving is still being answered
            self._update("Thinking…")

    def _on_message(self, command: str, arg: str):
        if command == "select" and arg and arg == self.selected:  # second click: fold it and drop the prefix
            self.selected = None
            self._update(None)
            if mw.state == self.STATE:
                mw.web.eval(f"window.aiCfg && aiCfg.deselect({json.dumps(arg)});")
        elif command == "select":
            self.selected = arg
            self._update(None)
            if mw.state == self.STATE and arg:
                mw.web.eval(f"window.aiCfg && aiCfg.prefill({json.dumps(deck_prefix(arg))});")
        elif command == "models":
            self._load_models()
        elif command == "model":
            self.apply([{"set": {"model": arg}}])
            self._update(None)
        elif command == "toggle" and arg in config_ops.TOGGLES:
            self.apply([config_ops.toggle_change(self.cfg(), arg)])
            self._update(None)
        elif command == "decktoggle":
            toggle, _, deck = arg.partition(":")
            if toggle in config_ops.DECK_TOGGLES and deck in deck_ids():
                self.apply([config_ops.deck_toggle_change(self.cfg(), toggle, deck, deck_ids())])
                self._update(None)
        elif command == "provider":
            self.apply([{"set": {"provider": arg}}])
            self._update(None)
        elif command == "act":
            fn = self._actions.pop(arg, None)
            if fn:
                fn()
        elif command == "update":
            self.fixer.update()
        elif command == "login":
            self.login()

    def _send(self, text: str):
        cfg = self.cfg()
        self.busy = True
        self._update("Thinking…")
        provider, _path = self.provider(cfg)
        in_use = resolved_model(provider, model_for(cfg))
        prompt = config_ops.config_prompt(cfg, self.auth, text, deck_ids(), self.selected, in_use)
        self._session(cfg).request(0, prompt, config_ops.parse_config_reply, 90, self._on_reply)

    def _on_reply(self, _id, result, err):
        self.busy = False
        if err:
            self.say(f"AI error: {err.message}", err=True)
            self._update("")
            if mw.state != self.STATE:
                self._stop()
            return
        rejected = []
        actions = self.apply(result["changes"], rejected)
        reply = " ".join(filter(None, [result["reply"], *rejected])) or "Done."
        self.say(reply, err=bool(rejected))
        for action in actions:
            self._run_auth(action)
        self._update("")
        if mw.state != self.STATE:  # answered after the user left: don't keep the CLI running
            self._stop()

    def _session(self, cfg):
        if self.session is None:
            self.session = make_backend(cfg, config_ops.CONFIG_SYSTEM_PROMPT, self.tmpdir(), mw.taskman.run_on_main)
        return self.session

    def _stop(self):
        """Config changed (provider, model, path) or page left: the next message starts a fresh backend."""
        if self.session is not None:
            self.session.close()
            self.session = None

    def _refresh_auth(self):
        provider, path = self.provider()

        def work():
            try:
                ok, text = read_auth_status(provider, path)
            except Exception as e:  # missing binary, bad JSON, timeout — show it, don't crash the page
                ok, text = False, f"unknown ({e.__class__.__name__}: {e})"
            mw.taskman.run_on_main(lambda: self._set_auth(ok, text))

        threading.Thread(target=work, daemon=True).start()

    def _load_models(self):
        """Fill the Model dropdown with what the CLI offers right now (current model stays first)."""
        cfg = self.cfg()
        provider, path = self.provider(cfg)
        configured = model_for(cfg)
        cwd = self.tmpdir()

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
        """The real model id (saved by session.py whenever a CLI reports it); looked up in the background once."""
        actual = resolved_model(provider, configured)
        if actual:
            return actual
        key = (provider, configured)
        if key not in self._probing:
            self._probing.add(key)
            cwd = self.tmpdir()

            def work():
                try:
                    probe_model(provider, path, configured, cwd)
                except Exception:  # stays "checking…"; the next real call fills it in
                    pass

                def done():
                    self._probing.discard(key)
                    self._update(None)

                mw.taskman.run_on_main(done)

            threading.Thread(target=work, daemon=True).start()
            return "checking…"
        return configured or "checking…"

    def _set_auth(self, ok, text):
        self.logged_in, self.auth = ok, text
        if mw.state == self.STATE:
            self._update(None)

    def _run_auth(self, action: str):
        """login opens the browser via Claude Code's own flow; the add-on never sees credentials."""
        provider, path = self.provider()
        label = PROVIDER_LABELS[provider]
        # Windows: the CLI's sign-in may print a link and wait for a pasted code, which a hidden process can't
        # show or receive, so it runs in its own console window there.
        console = action == "login" and os.name == "nt"
        note = {"login": f"A {label} window opened: sign in in your browser (if the browser didn't open, use the "
                         "link in that window) and paste the code there if it asks for one…" if console else
                         f"Opening your browser to sign in to {label}…",
                "logout": f"Logging out of {label} (this also signs it out everywhere on this computer)…"}[action]
        self.say(note, err=False)
        self._update(None)

        def work():
            try:
                if console:
                    r = subprocess.run(auth_command(provider, path, action), timeout=600,
                                       creationflags=subprocess.CREATE_NEW_CONSOLE)
                    msg = None if r.returncode == 0 else f"exit code {r.returncode}"
                else:
                    r = subprocess.run(auth_command(provider, path, action), capture_output=True, text=True,
                                       timeout=300, stdin=subprocess.DEVNULL, **PROC_KW)
                    msg = None if r.returncode == 0 else (r.stderr or r.stdout).strip()[-300:]
            except Exception as e:
                msg = str(e)

            def done():
                if msg:
                    cmd = " ".join(auth_command(provider, provider, action))
                    self.say(f"{action} failed: {msg} — try `{cmd}` in a terminal.", err=True)
                self._refresh_auth()

            mw.taskman.run_on_main(done)

        threading.Thread(target=work, daemon=True).start()

    # --- rendering ---

    def _update(self, status):
        if mw.state != self.STATE:
            return
        status = "" if status is None else status
        args = [self._log_html(), self._sections_html(), status, self.busy]
        mw.web.eval(f"window.aiCfg && aiCfg.update({', '.join(json.dumps(a) for a in args)});")

    def say(self, text: str, err: bool = False, actions=()):
        """Add a reply; `actions` = [(label, callable)] rendered as buttons under it."""
        ids = []
        for label, fn in actions:
            self._next_id += 1
            key = str(self._next_id)
            self._actions[key] = fn
            ids.append((label, key))
        self.replies.append((text, err, ids))
        live = {k for _t, _e, acts in self.replies for _l, k in acts}
        self._actions = {k: f for k, f in self._actions.items() if k in live}
        self._update(None)

    def _log_html(self) -> str:
        if not self.replies:
            return ('<div class="ai">Tell me what to change, in plain words — e.g. "use opus", '
                    '"give me 90 seconds to answer", "grade more strictly", "undo that".</div>')
        out = []
        for t, bad, acts in self.replies:
            buttons = "".join(
                f'<button onclick="pycmd(\'aiCfg:act:{k}\')">{html.escape(label)}</button>' for label, k in acts)
            out.append(f'<div class="{"err" if bad else "ai"}">&gt; {html.escape(t)}'
                       + (f'<div class="acts">{buttons}</div>' if buttons else "") + "</div>")
        return "".join(out)

    def _sections_html(self) -> str:
        cfg = self.cfg()
        login = html.escape(self.auth)
        if self.logged_in is False:
            login += ' <button onclick="pycmd(\'aiCfg:login\')">Log in</button>'
        provider, found = self.provider(cfg)
        # A plain control, not the chat: if the current provider is broken, the chat can't fix it.
        options = "".join(
            f'<option value="{p}"{" selected" if p == provider else ""}>{html.escape(label)}</option>'
            for p, label in PROVIDER_LABELS.items()
        )
        select = f'<select onchange="pycmd(\'aiCfg:provider:\' + this.value)">{options}</select>'
        rows = [("Provider", select), ("Login", login)] + [
            (label, html.escape(str(cfg.get(key))))
            for label, key in (("Ask timeout (s)", "ask_timeout_s"), ("Grade timeout (s)", "grade_timeout_s"))
        ] + [self._toggle_row(cfg, key) for key in config_ops.TOGGLES]
        configured = model_for(cfg)
        current = html.escape(self._model_name(provider, found, configured))
        model_select = (f'<select id="model-sel" onmousedown="aiCfg.loadModels(event, this)" '
                        f'onchange="pycmd(\'aiCfg:model:\' + this.value)">'
                        f'<option value="{html.escape(configured)}" selected>{current}</option></select>')
        rows.insert(2, ("Model", model_select))
        version = self.fixer.version.get(provider, "checking…")
        rows.insert(3, ("Version", html.escape(version)
                        + ' <button onclick="pycmd(\'aiCfg:update\')">Update</button>'))
        path = cfg.get(f"{provider}_path") or ""
        rows.append((f"{PROVIDER_LABELS[provider]} path",
                     html.escape(path if path and path != "auto" else f"auto → {found}")))
        table = "".join(f'<tr><td class="k"><span class="kl">{k}</span>{"".join(h)}</td><td>{v}</td></tr>'
                        for k, v, *h in rows)
        custom = cfg.get("custom") or []
        rules = ("<ol>" + "".join(f"<li>{html.escape(r)}</li>" for r in custom) + "</ol>"
                 if custom else '<div style="opacity:.6">none yet</div>')
        return (f'<div class="sect"><h3>Configurations</h3><table>{table}</table></div>'
                f'<div class="sect"><h3>Custom Generic Rules</h3>{rules}</div>'
                f'<div class="sect"><h3>Deck Settings</h3>{self._deck_html(cfg)}</div>')

    def _toggle_row(self, cfg, key) -> tuple:
        """(label, On/Off button, ? help bubble — shown on hover, or on click/tab for focus)."""
        label, tip = config_ops.TOGGLES[key]
        on = config_ops.toggle_on(cfg, key)
        button = (f'<button class="tog{" on" if on else ""}" '
                  f'onclick="pycmd(\'aiCfg:toggle:{key}\')">{"On" if on else "Off"}</button>')
        lines = "".join(f"<div>{html.escape(line)}</div>" for line in tip)
        return label, button, f'<span class="help" tabindex="0">?<span class="tip">{lines}</span></span>'


    @staticmethod
    def _deck_toggle(cfg, toggle: str, sel: str, decks: dict) -> str:
        """'<label>: [On/Off] (from <parent> | default) — subdecks follow' for the selected deck."""
        on, src = config_ops.deck_toggle_source(cfg, toggle, sel, decks)
        where = "" if src == sel else f" (from {src})" if src else " (default)"
        if toggle == "sharp" and config_ops.ask_mode(cfg, sel, decks) == "keep":
            where += " — the deck prompt still shapes the questions"
        js = html.escape(f"pycmd({json.dumps(f'aiCfg:decktoggle:{toggle}:{sel}')})", quote=True)
        return (f'<div class="inh">{config_ops.DECK_TOGGLES[toggle][1]}: '
                f'<button class="tog{" on" if on else ""}" onclick="{js}">{"On" if on else "Off"}</button>'
                f'{html.escape(where)} — subdecks follow</div>')

    def _deck_html(self, cfg) -> str:
        decks = deck_ids()
        prompts = cfg.get("deck_prompts") or {}
        names = sorted(decks, key=lambda n: n.lower())
        sel = self.selected if self.selected in decks else None
        ancestors = {"::".join(sel.split("::")[:i]) for i in range(1, sel.count("::") + 1)} if sel else set()

        if sel:
            own = prompts.get(decks[sel], "").strip()
            chain = [(n, p) for n, p in config_ops.deck_chain(sel, decks, prompts) if n != sel]
            inh = "".join(f'<div class="inh">↳ {html.escape(n)}: <span class="p">{html.escape(p)}</span></div>'
                          for n, p in chain)
            toggles = "".join(self._deck_toggle(cfg, t, sel, decks) for t in config_ops.DECK_TOGGLES)
            panel = (f'<div class="panel"><div class="name">{html.escape(sel)}</div>'
                     f'<div class="p">{html.escape(own) if own else "<i>no prompt — tell the AI what this deck needs</i>"}</div>'
                     f'{inh}{toggles}</div>')
        else:
            panel = ""

        def node(name: str) -> str:
            depth = name.count("::") + 1
            kids = [n for n in names if n.startswith(name + "::") and n.count("::") + 1 == depth + 1]
            label = html.escape(name.split("::")[-1])
            dot = '<span class="dot">●</span>' if prompts.get(decks[name], "").strip() else ""
            cls = ' class="sel"' if name == sel else ""
            js = html.escape(f"pycmd({json.dumps('aiCfg:select:' + name)});event.preventDefault();", quote=True)
            link = f'<a{cls} onclick="{js}">{label}</a>{dot}'
            here = panel if name == sel else ""  # the selected deck's panel sits right under it
            if not kids:
                return f'<div class="leaf">{link}{here}</div>'
            is_open = " open" if name in ancestors or name == sel else ""
            return (f'<details data-deck="{html.escape(name)}"{is_open}><summary>{link}</summary>{here}'
                    + "".join(node(k) for k in kids) + "</details>")

        tree = "".join(node(n) for n in names if "::" not in n)
        hint = "" if sel else '<div class="panel" style="opacity:.6">Click a deck to see its prompt.</div>'
        return f'<div class="tree">{tree}</div>{hint}'


    def _page_html(self) -> str:
        return (
            f'{CSS}<div id="cfg"><a class="back" onclick="pycmd(\'aiCfg:back\')">← Back</a>'
            f"<h2>AI Study settings</h2>"
            f'<div id="log">{self._log_html()}</div>'
            f'<div id="cmd-bar"><input id="cmd" value="{html.escape(self.draft)}" placeholder="Tell the AI what to change…">'
            f'<div id="status"></div></div><div id="sections">{self._sections_html()}</div></div>{JS}'
        )
