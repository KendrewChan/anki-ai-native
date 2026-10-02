"""Generate page: chat with the AI to make / update cards from Desktop reference files, staged in "AI-GEN"."""

import html
import json
import tempfile
from collections import deque

from aqt import mw
from aqt.operations import CollectionOp
from aqt.qt import QFileDialog

from . import generate_col, generate_ops, health
from .config_page import CSS as CONFIG_CSS
from .grading import strip_html
from .session import make_backend

STATE = "aiStudyGenerate"
TEMP = html.escape(generate_ops.TEMP_DECK)
TIMEOUT_S = 300
MAX_READ_ROUNDS = 2  # times the AI may ask to read decks before answering one message

CSS = CONFIG_CSS + """
<style>
#refrow { display: flex; gap: 0.4em; align-items: center; margin: 0.6em 0 0.2em; }
#ref { flex: 1; padding: 0.45em 0.6em; font: inherit; border-radius: 6px; border: 1px dashed #8888;
       background: transparent; color: inherit; cursor: default; outline: none; }
#refinfo { font-size: 0.85em; opacity: 0.75; min-height: 1.2em; margin-bottom: 0.5em; }
#refinfo.bad { color: #d33; opacity: 1; }
.stg .deck { font-weight: 600; margin: 0.8em 0 0.2em; display: flex; justify-content: space-between; }
.stg .deck button { font-weight: normal; }
.stg .card { display: flex; gap: 0.6em; align-items: flex-start; margin: 0.15em 0 0.15em 1em; }
.stg .main { flex: 1; min-width: 0; } .stg .q { white-space: pre-wrap; overflow-wrap: anywhere; }
.stg .plain { padding-left: 1.05em; } .stg .acts { white-space: nowrap; }
.stg .acts button { font-size: 0.8em; margin-left: 0.3em; }
.stg .card.ok .q { opacity: 0.75; } .stg .okmark { color: #27864a; font-size: 0.8em; font-weight: 600; }
.stg .btns .submit { font-weight: 700; margin-left: 1em; } .stg .hint { font-size: 0.8em; opacity: 0.6; margin-top: 0.3em; }
#status.busy { opacity: 1; font-size: 0.95em; color: #2a6fd6; }
.stg summary { cursor: pointer; }
.stg .kind { font-size: 0.75em; padding: 0 0.35em; border-radius: 4px; border: 1px solid #8888; margin-right: 0.4em; }
.stg .kind.upd { color: #b07400; border-color: #b0740088; } .stg .kind.new { color: #27864a; border-color: #27864a88; }
.stg .fld { margin: 0.2em 0 0.4em 1em; } .stg .fld b { opacity: 0.7; font-weight: 500; }
.stg .btns { margin-top: 0.8em; } .stg .btns button { margin: 0 0.5em 0 0; }
</style>
"""

JS = """
<script>
window.aiGen = {
  update(logHtml, refInfo, refBad, stagedHtml, status, busy) {
    const log = document.getElementById("log");
    log.innerHTML = logHtml; log.scrollTop = log.scrollHeight;
    const info = document.getElementById("refinfo");
    info.textContent = refInfo; info.className = refBad ? "bad" : "";
    const stg = document.getElementById("sections");
    const open = new Set(Array.from(stg.querySelectorAll("details[open]")).map(d => d.dataset.id));
    stg.innerHTML = stagedHtml;
    stg.querySelectorAll("details").forEach(d => { if (open.has(d.dataset.id)) d.open = true; });
    const st = document.getElementById("status");
    clearInterval(this.timer);
    if (busy) {
      const t0 = this.since = (this.busy ? this.since : Date.now());
      const tick = () => { st.textContent = "⏳ " + (status || "Working…") + " " + Math.round((Date.now() - t0) / 1000) + "s"; };
      tick(); this.timer = setInterval(tick, 1000);
    } else { st.textContent = status; }
    st.className = busy ? "busy" : "";
    this.busy = busy;
    const cmd = document.getElementById("cmd");
    cmd.disabled = busy; if (!busy) cmd.focus();
  },
  setRef(path) { document.getElementById("ref").value = path; },
};
document.getElementById("cmd").addEventListener("keydown", function (e) {
  e.stopPropagation();
  if (e.key === "Enter" && !e.isComposing) {
    e.preventDefault();
    const v = this.value.trim();
    if (!v) return;
    this.value = "";
    pycmd("aiGen:send:" + v);
  }
});
setTimeout(function () { document.getElementById("cmd").focus(); }, 0);
</script>
"""


def _ids(text: str) -> list:
    """"12,34" from a button -> staged note ids."""
    return [int(x) for x in text.split(",") if x.strip().isdigit()]


class _Result:
    """CollectionOp wants an object with .changes; carry the counts along."""

    def __init__(self, pair):
        self.changes, self.info = pair


class GeneratePage:
    def __init__(self, addon: str):
        self.addon = addon
        self.cwd = None
        self.replies = deque(maxlen=6)  # (text, "you" | "ai" | "err")
        self.history = deque(maxlen=3)  # (user message, AI reply) sent back as context
        self.ref = ""  # reference path as chosen (validated on every use)
        self.loaded = {}  # deck name -> [note dict] the AI asked to read
        self.busy = False
        self._backend = None
        self._ref_cache = (None, None)  # (path, (info, is_bad)): folders aren't rescanned on every redraw
        setattr(mw, f"_{STATE}State", self._enter)
        setattr(mw, f"_{STATE}Cleanup", self._leave)

    # --- state ---

    def open(self):
        mw.moveToState(STATE)

    def _enter(self, _old_state, *_args):
        self._ref_cache = (None, None)
        mw.bottomWeb.hide()
        mw.web.stdHtml(self._page_html(), context=self)
        mw.web.set_bridge_command(self._on_bridge, self)
        self._update(None)

    def _leave(self, _new_state):
        self._stop()
        self.busy = False
        self.loaded = {}  # deck contents change outside this page
        mw.bottomWeb.show()

    def _stop(self):
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    # --- bridge ---

    def _on_bridge(self, message: str):
        if message == "aiGen:back":
            mw.moveToState("deckBrowser")
        elif message == "aiGen:clearref":
            self.ref = ""
            self._update(None)
        elif message in ("aiGen:pickdir", "aiGen:pickfile"):
            self._pick(message == "aiGen:pickdir")
        elif message.startswith("aiGen:approve") and not self.busy:
            ids = _ids(message[len("aiGen:approve:"):]) if message != "aiGen:approve" else None
            self._run_op(lambda col: _Result(generate_col.approve(col, ids)), lambda _n: self._update(None))
        elif message.startswith("aiGen:unapprove:") and not self.busy:
            ids = _ids(message[len("aiGen:unapprove:"):])
            self._run_op(lambda col: _Result(generate_col.approve(col, ids, ok=False)), lambda _n: self._update(None))
        elif message == "aiGen:submit" and not self.busy:
            self._run_op(lambda col: _Result(generate_col.submit(col)), self._submitted)
        elif message.startswith("aiGen:discard") and not self.busy:
            ids = _ids(message[len("aiGen:discard:"):]) if message != "aiGen:discard" else None
            self._run_op(lambda col: _Result(generate_col.discard(col, ids)),
                         lambda n: self.say(f"Discarded {n} staged card{'s' if n != 1 else ''}. "
                                            "Edit → Undo brings them back."))
        elif message.startswith("aiGen:send:") and not self.busy:
            self._send(message[len("aiGen:send:"):])

    def _pick(self, folder: bool):
        start = str(generate_ops.desktop())
        if folder:
            path = QFileDialog.getExistingDirectory(mw, "Choose a reference folder on your Desktop", start)
        else:
            path = QFileDialog.getOpenFileName(mw, "Choose a reference file on your Desktop", start)[0]
        if path:
            self.ref = path
            mw.web.eval(f"window.aiGen && aiGen.setRef({json.dumps(path)});")
            self._update(None)

    # --- AI ---

    def _send(self, text: str, rounds: int = 0):
        if not rounds:
            self.replies.append((text, "you"))
        refs = None
        if self.ref.strip():
            try:
                refs = generate_ops.read_references(self.ref)
            except ValueError as e:
                self.say(f"Reference: {e}", err=True)
                return
        decks = self._decks()
        staged = generate_col.staged(mw.col)
        prompt = generate_ops.generate_prompt(text, decks, refs, self.loaded, staged, list(self.history))
        self.busy = True
        self._update("Reading your decks, thinking…" if rounds else "Thinking — this can take a minute…")
        self._stop()  # fresh process per message: references are resent each time, a long chat would overflow
        self.cwd = self.cwd or tempfile.mkdtemp(prefix="anki_ai_gen_")
        cfg = mw.addonManager.getConfig(self.addon) or {}
        self._backend = make_backend(cfg, generate_ops.GENERATE_SYSTEM_PROMPT, self.cwd, mw.taskman.run_on_main)
        self._backend.request(0, prompt, generate_ops.parse_generate_reply, TIMEOUT_S,
                              lambda _id, result, err: self._on_reply(text, rounds, staged, decks, result, err))

    def _on_reply(self, text, rounds, staged, decks, result, err):
        self._stop()
        if mw.state != STATE:
            self.busy = False
            return
        if err:
            self.busy = False
            health.LAST_ERROR[(mw.addonManager.getConfig(self.addon) or {}).get("provider") or "claude"] = err.message
            self.say(f"AI error: {err.message} — open ⚙ Settings to fix it.", err=True)
            return
        rejected = []
        new_reads = []
        for name in result["read_decks"]:
            try:
                name = generate_ops.resolve_read(name, decks)
            except ValueError as e:
                rejected.append(f"✗ {e}")
                continue
            if name not in self.loaded:
                self.loaded[name] = generate_col.read_deck(mw.col, name)
                new_reads.append(name)
        if new_reads and not result["changes"] and rounds < MAX_READ_ROUNDS:
            self._send(text, rounds + 1)  # same request again, now with those cards
            return
        existing = {n["id"]: n for notes in self.loaded.values() for n in notes}
        ops, bad = generate_ops.plan_changes(result["changes"], decks, existing, staged)
        rejected += bad
        reply = result["reply"] or "Done."
        self.history.append((text, reply))

        def done(counts=None):
            self.busy = False
            parts = [f"{v} {k}" for k, v in (counts or {}).items() if v]
            summary = f" ({', '.join(parts)} — see AI-GEN below)" if parts else ""
            self.say(" ".join([reply + summary, *rejected]), err=bool(rejected))

        if ops:
            self._run_op(lambda col: _Result(generate_col.apply_ops(col, ops)), done,
                         on_fail=lambda: setattr(self, "busy", False))
        else:
            done()

    def _run_op(self, op, on_done, on_fail=None):
        def failed(e):
            if on_fail:
                on_fail()
            self.say(f"Couldn't change the collection: {e}", err=True)

        CollectionOp(parent=mw, op=op).success(lambda r: on_done(r.info)).failure(failed).run_in_background()

    def _submitted(self, counts):
        self.loaded = {}  # real decks changed: the AI re-reads them when needed
        left = len(generate_col.staged(mw.col))
        self.say(f"Submitted: {counts['updated']} card{'s' if counts['updated'] != 1 else ''} updated, "
                 f"{counts['added']} added to their decks."
                 + (f" {left} unapproved card{'s' if left != 1 else ''} still in {generate_ops.TEMP_DECK}." if left else "")
                 + " Edit → Undo reverses this.")

    # --- rendering ---

    def _decks(self) -> list:
        return [d.name for d in mw.col.decks.all_names_and_ids()]

    def say(self, text: str, err: bool = False):
        self.replies.append((text, "err" if err else "ai"))
        self._update(None)

    def _update(self, status):
        if mw.state != STATE:
            return
        info, bad = self._ref_info()
        args = [self._log_html(), info, bad, self._staged_html(), status or "", self.busy]
        mw.web.eval(f"window.aiGen && aiGen.update({', '.join(json.dumps(a) for a in args)});")

    def _ref_info(self) -> tuple:
        if self._ref_cache[0] != self.ref:
            self._ref_cache = (self.ref, self._scan_ref())
        return self._ref_cache[1]

    def _scan_ref(self) -> tuple:
        if not self.ref.strip():
            return "Optional: a file or folder on your Desktop for the AI to make cards from (text files only).", False
        try:
            return "✓ " + generate_ops.ref_summary(generate_ops.read_references(self.ref)), False
        except ValueError as e:
            return f"✗ {e}", True

    def _log_html(self) -> str:
        if not self.replies:
            return ('<div class="ai">Tell me what cards to make or fix — e.g. "10 cards from these notes into '
                    'Biology::Ch3", "improve my Chem cards using this file", "make card 3 shorter". New and updated '
                    'cards wait in the AI-GEN deck until you approve and Submit them.</div>')
        return "".join(f'<div class="you">{html.escape(t)}</div>' if kind == "you"
                       else f'<div class="{kind}">&gt; {html.escape(t)}</div>' for t, kind in self.replies)

    def _staged_html(self) -> str:
        staged = generate_col.staged(mw.col)
        if not staged:
            return f'<div class="sect stg"><h3>{TEMP}</h3><div style="opacity:.6">Nothing staged yet.</div></div>'
        out, deck = [], None
        for i, s in enumerate(staged, 1):
            if s["deck"] != deck:
                deck = s["deck"]
                in_deck = [x for x in staged if x["deck"] == deck]
                ids = ",".join(str(x["id"]) for x in in_deck)
                pending = ",".join(str(x["id"]) for x in in_deck if not x["ok"])
                approve = (f'<button onclick="pycmd(\'aiGen:approve:{pending}\')">Approve deck</button>' if pending
                          else f'<button onclick="pycmd(\'aiGen:unapprove:{ids}\')">Unapprove deck</button>')
                out.append(f'<div class="deck">{html.escape(deck or "(no deck)")}<span class="acts">{approve}'
                           f'<button onclick="pycmd(\'aiGen:discard:{ids}\')">Discard deck</button></span></div>')
            kind = ('<span class="kind upd">UPDATE</span>' if s["of"] else '<span class="kind new">NEW</span>')
            values = list(s["fields"].items())
            question = f'{i}. {kind}<span class="q">{html.escape(strip_html(values[0][1]) if values else "")}</span>'
            rest = "".join(f'<div class="fld"><b>{html.escape(k)}:</b> {html.escape(strip_html(v))}</div>'
                           for k, v in values[1:] if v.strip())  # the question is already in the summary
            body = (f'<details data-id="{s["id"]}"><summary>{question}</summary>{rest}</details>' if rest
                    else f'<div class="plain">{question}</div>')
            approve = (f'<span class="okmark">✓ Approved</span>'
                      f'<button onclick="pycmd(\'aiGen:unapprove:{s["id"]}\')">Unapprove</button>' if s["ok"]
                      else f'<button onclick="pycmd(\'aiGen:approve:{s["id"]}\')">Approve</button>')
            acts = (f'<span class="acts">{approve}'
                    f'<button onclick="pycmd(\'aiGen:discard:{s["id"]}\')">Discard</button></span>')
            out.append(f'<div class="card{" ok" if s["ok"] else ""}"><div class="main">{body}</div>{acts}</div>')
        ok = sum(1 for s in staged if s["ok"])
        pending = len(staged) - ok
        submit = (f'<button class="submit" onclick="pycmd(\'aiGen:submit\')">Submit {ok} approved</button>' if ok
                  else '<button class="submit" disabled>Submit (approve cards first)</button>')
        buttons = (f'<div class="btns">'
                   + (f'<button onclick="pycmd(\'aiGen:approve\')">Approve all ({pending})</button>' if pending else "")
                   + f'<button onclick="pycmd(\'aiGen:discard\')">Discard all</button>{submit}</div>'
                   f'<div class="hint">Approved cards stay here until you Submit — keep generating meanwhile.</div>')
        return f'<div class="sect stg"><h3>{TEMP} — waiting for you</h3>{"".join(out)}{buttons}</div>'

    def _page_html(self) -> str:
        return (
            f'{CSS}<div id="cfg"><a class="back" onclick="pycmd(\'aiGen:back\')">← Back</a>'
            f"<h2>Generate cards</h2>"
            f'<div id="log">{self._log_html()}</div>'
            f'<div id="refrow"><input id="ref" readonly tabindex="-1" value="{html.escape(self.ref)}" '
            f'placeholder="No reference chosen (optional)">'
            f'<button onclick="pycmd(\'aiGen:pickdir\')">Choose folder…</button>'
            f'<button onclick="pycmd(\'aiGen:pickfile\')">Choose file…</button>'
            f'<button title="Clear" onclick="aiGen.setRef(\'\');pycmd(\'aiGen:clearref\')">×</button></div>'
            f'<div id="refinfo"></div>'
            f'<input id="cmd" placeholder="What cards should I make or fix?">'
            f'<div id="status"></div><div id="sections"></div></div>{JS}'
        )
