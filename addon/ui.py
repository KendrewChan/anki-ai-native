"""HTML/CSS/JS injected into the reviewer. Display-only — nothing here touches the collection."""

import html
import json

from . import grading

CSS = """
<style>
#ai-study { text-align: left; width: min(92vw, 70em); margin: 0 auto 1em; font-size: 0.95em; }
#ai-orig, #ai-orig-plain { margin-bottom: 0.8em; }
#ai-orig > summary { cursor: pointer; opacity: 0.7; font-size: 0.85em; }
.ai-item { margin-bottom: 0.9em; }
.ai-q { font-size: 1.15em; font-weight: 600; margin: 0.2em 0 0.4em; white-space: pre-wrap; }
.ai-part { margin: 0 0 0.3em 1.2em; font-size: 1.05em; }
.ai-q.loading { opacity: 0.55; font-weight: 400; font-style: italic; }
.ai-hint { position: relative; display: inline-block; margin-left: 0.4em; width: 1.2em; height: 1.2em; line-height: 1.2em;
           border-radius: 50%; border: 1px solid #8888; text-align: center; font-size: 0.7em; font-weight: 400;
           cursor: help; vertical-align: middle; opacity: 0.7; }
.ai-hint .tip { display: none; position: absolute; top: calc(100% + 6px); left: -0.6em; z-index: 10; width: max-content;
                max-width: min(24em, calc(100vw - 16px)); white-space: normal; text-align: left; font-size: 1.3em; line-height: 1.4;
                padding: 0.45em 0.7em; border-radius: 6px; background: #2b2b2b; color: #eee; box-shadow: 0 3px 12px #0006; }
.ai-hint:hover, .ai-hint:focus { opacity: 1; } .ai-hint:hover .tip, .ai-hint:focus .tip { display: block; }
.ai-ans { width: 100%; box-sizing: border-box; height: var(--ai-box-h, 35vh); min-height: 6em; resize: vertical;
          padding: 0.6em; font: inherit; border-radius: 6px; border: 1px solid #8888; background: transparent; color: inherit; }
#ai-status { margin-top: 0.2em; font-size: 0.85em; opacity: 0.75; min-height: 1.2em; }
.ai-err { color: #d33; opacity: 1 !important; }
.ai-verdict { text-align: left; width: min(92vw, 70em); box-sizing: border-box; margin: 0 auto 1em; padding: 0.7em 0.9em;
              border-radius: 8px; border: 1px solid #8884; font-size: 0.92em; }
.ai-badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 4px; font-weight: 700;
            color: #fff; font-size: 0.85em; letter-spacing: 0.04em; }
.ai-wrong { background: #c0392b; } .ai-partial { background: #c27c0e; } .ai-correct { background: #27864a; }
.ai-pq { margin: 0.6em 0; } .ai-pq-q { font-weight: 600; white-space: pre-wrap; }
.ai-you { opacity: 0.75; white-space: pre-wrap; margin: 0.2em 0; }
.ai-you.ai-you-marked { opacity: 1; } .ai-you.ai-you-wrong { color: #d33; opacity: 1; } .ai-you.ai-you-partial { color: #d97706; opacity: 1; }
.ai-verdict .ai-claims { margin: 0.2em 0 0.3em 1.2em; padding: 0; white-space: normal; } .ai-claims li { margin: 0.15em 0; }
.ai-why { opacity: 0.8; font-size: 0.92em; }
.ai-mark-correct { color: #27864a; } .ai-mark-partial { color: #d97706; } .ai-mark-wrong { color: #d33; }
.ai-verdict ul { margin: 0.3em 0 0 1.2em; padding: 0; }
</style>
"""

JS = """
<script>
(function () {
  const list = document.getElementById("ai-items");
  const orig = document.getElementById("ai-orig");
  const status = document.getElementById("ai-status");
  const HINT = __HINT__;
  let submitted = false;
  const boxes = () => Array.from(list.querySelectorAll(".ai-ans"));

  function sizeBoxes() {
    const n = boxes().length;
    list.style.setProperty("--ai-box-h", n > 1 ? "calc(45vh / " + n + ")" : "35vh");
  }

  function submit() {
    const values = boxes().map(b => b.value);
    if (values.every(v => !v.trim())) { pycmd("aiStudy:reveal"); return; }
    submitted = true;
    boxes().forEach(b => b.disabled = true);
    aiStudy.setStatus("Grading…");
    pycmd("aiStudy:submit:" + JSON.stringify(values));
  }

  function wire(box) {
    box.addEventListener("keydown", function (e) {
      e.stopPropagation();  // keep Anki's reviewer keys (space, 1-4, e…) out of the text boxes
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        const all = boxes(), i = all.indexOf(box);
        if (i < all.length - 1) all[i + 1].focus(); else submit();
      }
    });
  }

  function hintIcon(hint) {
    const help = document.createElement("span");
    help.className = "ai-hint";
    help.tabIndex = -1;  // focusable by click (shows the tip), but Tab still goes box to box
    help.textContent = "?";
    const tip = document.createElement("span");
    tip.className = "tip";
    tip.innerHTML = hint;
    help.append(tip);
    const place = () => {  // keep the tip inside the window: shift it left by however much it sticks out
      tip.style.left = "";
      const r = tip.getBoundingClientRect(), over = r.right - (document.documentElement.clientWidth - 8);
      if (over > 0) tip.style.left = "calc(-0.6em - " + over + "px)";
    };
    help.addEventListener("mouseenter", place);
    help.addEventListener("focus", place);
    return help;
  }

  // q: {num, text, hint, parts: [{label, text, hint}]} as safe HTML from ui.display_items, or null (no label)
  function addItem(q) {
    const item = document.createElement("div");
    item.className = "ai-item";
    if (q) {
      const label = document.createElement("div");
      label.className = "ai-q";
      label.innerHTML = (q.num ? q.num + " " : "") + q.text;
      if (q.hint) label.append(hintIcon(q.hint));
      item.append(label);
      q.parts.forEach(p => {
        const row = document.createElement("div");
        row.className = "ai-part";
        row.innerHTML = p.label + " " + p.text;
        if (p.hint) row.append(hintIcon(p.hint));
        item.append(row);
      });
    }
    const box = document.createElement("textarea");
    box.className = "ai-ans";
    if (!boxes().length) box.placeholder = HINT;
    item.append(box);
    list.append(item);
    wire(box);
  }

  window.aiStudy = {
    setQuestions(qs, showOriginal) {
      if (submitted) return;
      if (orig && showOriginal) orig.open = true;
      list.innerHTML = "";
      if (qs.length) qs.forEach(addItem); else addItem(null);  // nothing to add: one box for the card's own question
      sizeBoxes();
      boxes()[0].focus();
      if (window.MathJax && MathJax.typesetPromise)  // Anki typesets the card once; these arrived later
        MathJax.startup.promise.then(() => MathJax.typesetPromise([list])).catch(() => {});
    },
    askFailed(msg) {
      list.innerHTML = "";
      addItem(null);  // no rewritten question: answer the original, opened above
      sizeBoxes();
      boxes()[0].focus();
      if (orig) orig.open = true;
      this.setStatus(msg, true);
    },
    setStatus(msg, isErr) { status.textContent = msg; status.classList.toggle("ai-err", !!isErr); },
    gradeFailed(msg) {
      submitted = false;
      boxes().forEach(b => b.disabled = false);
      boxes()[0].focus();
      this.setStatus(msg + " Enter with all boxes empty shows the answer.", true);
    },
  };

  boxes().forEach(wire);
  sizeBoxes();
  setTimeout(function () { if (boxes().length) boxes()[0].focus(); }, 0);
})();
</script>
"""

HINT = "Enter: next box / submit · Shift+Enter: new line · Enter with all boxes empty: just show the answer"


def question_html(original: str, mode: str) -> str:
    """Wrap Anki's rendered question. mode (main.rewrite_enabled):
    "sharp" — original folded under Show original; no box until setQuestions adds one per rewritten question.
    "keep"  — original shown as the question; no box until setQuestions adds what the deck prompt asks for (or one box).
    ""      — original shown as the question with its box ready (cloze, or no question step)."""
    loading = '<div class="ai-item"><div class="ai-q loading">Preparing the questions…</div></div>'
    if mode == "sharp":
        orig = f'<details id="ai-orig"><summary>Show original</summary>{original}</details>'
        item = loading
    else:
        orig = f'<div id="ai-orig-plain">{original}</div>'
        item = loading if mode else f'<div class="ai-item"><textarea class="ai-ans" placeholder="{HINT}"></textarea></div>'
    js = JS.replace("__HINT__", json.dumps(HINT))
    return f'{CSS}<div id="ai-study">{orig}<div id="ai-items">{item}</div><div id="ai-status"></div></div>{js}'


ASK_CSS = """
<style>
#ai-ask-bubble { display: none; position: absolute; z-index: 20; padding: 0.2em 0.6em; border-radius: 6px; cursor: pointer;
                 font-size: 0.8em; background: #2b2b2b; color: #eee; box-shadow: 0 2px 8px #0005; user-select: none; }
#ai-ask-pop { display: none; position: absolute; z-index: 20; width: min(26em, calc(100vw - 16px)); box-sizing: border-box;
              padding: 0.5em 0.6em; border-radius: 8px; text-align: left; font-size: 0.9em; line-height: 1.4;
              background: var(--canvas, Canvas); color: inherit; border: 1px solid #8886; box-shadow: 0 4px 16px #0004; }
#ai-ask-quote { font-size: 0.85em; opacity: 0.7; border-left: 3px solid #8886; padding-left: 0.5em; margin-bottom: 0.4em;
                max-height: 4.2em; overflow: hidden; white-space: pre-wrap; }
#ai-ask-input { width: 100%; box-sizing: border-box; padding: 0.35em 0.5em; font: inherit; border-radius: 6px;
                border: 1px solid #8888; background: transparent; color: inherit; }
#ai-ask-out { margin-top: 0.4em; white-space: pre-wrap; max-height: 40vh; overflow-y: auto; }
#ai-ask-out:empty { display: none; }
#ai-ask-out.ai-err { color: #d33; }
#ai-ask-toast { display: none; position: fixed; z-index: 20; left: 50%; bottom: 12px; transform: translateX(-50%);
                width: max-content; max-width: min(30em, calc(100vw - 16px)); padding: 0.45em 0.8em; border-radius: 8px;
                font-size: 0.9em; text-align: left; white-space: pre-wrap; cursor: pointer;
                background: #2b2b2b; color: #eee; box-shadow: 0 3px 12px #0006; }
</style>
"""

ASK_JS = """
<script>
(function () {
  const $ = id => document.getElementById(id);
  const bubble = $("ai-ask-bubble"), pop = $("ai-ask-pop"), quote = $("ai-ask-quote");
  const input = $("ai-ask-input"), out = $("ai-ask-out"), toastEl = $("ai-ask-toast");
  let sel = "", rect = null, timer = null;
  const mine = el => el && (bubble.contains(el) || pop.contains(el) || toastEl.contains(el));
  const typeset = el => { if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise([el]).catch(() => {}); };

  function place(el) {  // just under the highlight, kept inside the window
    el.style.display = "block";
    const base = el.offsetParent ? el.offsetParent.getBoundingClientRect() : {top: 0, left: 0};
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - el.offsetWidth - 8));
    el.style.left = (left - base.left) + "px";
    el.style.top = (rect.bottom + 6 - base.top) + "px";
  }
  function close() { pop.style.display = "none"; bubble.style.display = "none"; }
  function toast(html, err) {
    toastEl.innerHTML = html; toastEl.style.color = err ? "#f88" : "";
    toastEl.style.display = "block"; typeset(toastEl);
    clearTimeout(timer); timer = setTimeout(() => { toastEl.style.display = "none"; }, 12000);
  }

  bubble.addEventListener("mousedown", function (e) {  // mousedown: before the click clears the selection
    e.preventDefault(); e.stopPropagation();
    bubble.style.display = "none";
    quote.textContent = sel.length > 300 ? sel.slice(0, 300) + "…" : sel;
    out.innerHTML = ""; out.className = ""; input.value = ""; input.disabled = false;
    place(pop); input.focus({preventScroll: true});
  });
  input.addEventListener("keydown", function (e) {
    e.stopPropagation();  // keep Anki's keys (1-4, space, e…) out of the box
    if (e.key === "Escape") { close(); return; }
    if (e.key !== "Enter" || e.isComposing || !input.value.trim()) return;
    e.preventDefault();
    pycmd("aiStudy:ask:" + JSON.stringify({sel: sel, text: input.value.trim()}));
    input.value = ""; input.disabled = true;
    out.className = ""; out.textContent = "Thinking…";
  });
  toastEl.addEventListener("click", () => { toastEl.style.display = "none"; });

  window.aiAsk = {
    up(e) {
      if (mine(e.target) || (e.target.closest && e.target.closest("textarea, input, select"))) return;
      setTimeout(function () {
        const s = window.getSelection(), text = s.rangeCount ? s.toString().trim() : "";
        if (!text) { bubble.style.display = "none"; return; }
        sel = text; rect = s.getRangeAt(0).getBoundingClientRect();
        pop.style.display = "none"; place(bubble);
      }, 0);
    },
    down(e) { if (!mine(e.target)) close(); },
    reply(html, err) {  // in the open box, else as a toast (e.g. after an edit redrew the card)
      if (pop.style.display !== "block") { toast(html, err); return; }
      out.innerHTML = html; out.className = err ? "ai-err" : ""; typeset(out);
      input.disabled = false; input.focus({preventScroll: true});
    },
  };
  if (!window.aiAskBound) {  // once per page; the handlers act only while this card has the bubble
    window.aiAskBound = true;
    document.addEventListener("mouseup", e => { if ($("ai-ask-pop")) window.aiAsk.up(e); });
    document.addEventListener("mousedown", e => { if ($("ai-ask-pop")) window.aiAsk.down(e); });
  }
  const first = __TOAST__;
  if (first) toast(first[0], first[1]);
})();
</script>
"""

ASK_PLACEHOLDER = {
    "question": "Ask about this — e.g. what does this term mean? (Enter)",
    "answer": "Ask about this, or change it — e.g. why? · reword this · add an example (Enter)",
}


def ask_html(side: str, toast=None) -> str:
    """Highlight-to-ask: selecting card text shows an "Ask AI" bubble that opens a box at the highlight.
    side = "question" | "answer"; toast = (text, is_error) to show on load (the reply to an edit that redrew the card)."""
    first = [grading.rich(toast[0]), toast[1]] if toast else None
    return (f'{ASK_CSS}<div id="ai-ask-bubble">Ask AI</div>'
            f'<div id="ai-ask-pop"><div id="ai-ask-quote"></div>'
            f'<input id="ai-ask-input" placeholder="{html.escape(ASK_PLACEHOLDER[side])}"><div id="ai-ask-out"></div></div>'
            f'<div id="ai-ask-toast"></div>' + ASK_JS.replace("__TOAST__", json.dumps(first)))


def ask_reply_js(text: str, err: bool) -> str:
    """Show the AI's reply to a highlight question on the open card."""
    return f"window.aiAsk && aiAsk.reply({json.dumps(grading.rich(text))}, {json.dumps(err)});"


def display_items(items: list) -> list:
    """grading.parse_questions items with the AI's text made safe HTML for setQuestions (labels are ours)."""
    r = grading.rich
    return [dict(it, text=r(it["text"]), hint=r(it["hint"]),
                 parts=[dict(p, text=r(p["text"]), hint=r(p["hint"])) for p in it["parts"]]) for it in items]

def verdict_html(verdict: dict, questions: list, answers: list) -> str:
    """questions = what was asked (may be empty: cloze / ask failed); answers = one per box."""
    v = verdict["verdict"]
    marks = {"correct": "✓", "partial": "~", "wrong": "✗"}
    per_q = verdict.get("per_question") or []
    rows = []
    if questions and len(per_q) == len(questions):
        for i, (q, pq) in enumerate(zip(questions, per_q)):
            num = f"{i + 1}. " if len(questions) > 1 else ""
            a = answers[i] if i < len(answers) else ""
            rows.append(
                f'<div class="ai-pq"><span class="ai-pq-q"><span class="ai-mark-{pq["verdict"]}">{marks[pq["verdict"]]}</span> {num}{grading.rich(q)}</span>'
                f'{_you_html(a, pq["verdict"], pq.get("parts"))}'
                f'<div>{grading.rich(pq["note"])}</div></div>'
            )
    else:
        parts = per_q[0].get("parts") if len(per_q) == 1 else None
        rows.append(_you_html(chr(10).join(a for a in answers if a.strip()), v, parts))
    missed = verdict["missed"]
    missed_part = (
        "<b>Missed:</b><ul>" + "".join(f"<li>{grading.rich(m)}</li>" for m in missed) + "</ul>"
        if missed else "<b>Missed:</b> nothing"
    )
    return (
        f'{CSS}<div class="ai-verdict"><span class="ai-badge ai-{v}">{v.upper()}</span>'
        f'{"".join(rows)}'
        f"<div style='margin-top:0.5em'>{grading.rich(verdict['feedback'])}</div>"
        f"<div style='margin-top:0.5em'>{missed_part}</div></div>"
    )


def _you_class(verdict: str) -> str:
    """The user's answer turns red when wrong, orange when partial."""
    return {"wrong": " ai-you-wrong", "partial": " ai-you-partial"}.get(verdict, "")


def _you_html(answer: str, verdict: str, parts) -> str:
    """The user's answer as the AI's clipped claims (coloured, with why for partial/wrong); without claims the whole
    answer, red/orange by its grade."""
    if parts:
        items = "".join(
            f'<li><span class="ai-mark-{p["verdict"]}">{html.escape(p["text"])}</span>'
            + (f'<span class="ai-why"> — {grading.rich(p["why"])}</span>' if p["verdict"] != "correct" and p.get("why") else "")
            + "</li>" for p in parts)
        return f'<div class="ai-you ai-you-marked">You:<ul class="ai-claims">{items}</ul></div>'
    return f'<div class="ai-you{_you_class(verdict)}">You: {html.escape(answer.strip() or "(blank)")}</div>'

def append_verdict_note_js(note: str) -> str:
    snippet = json.dumps(f'<div class="ai-err">{html.escape(note)}</div>')
    return f"(function(v){{ if (v) v.insertAdjacentHTML('beforeend', {snippet}); }})(document.querySelector('.ai-verdict'));"


def js_call(fn: str, *args) -> str:
    return f"window.aiStudy && aiStudy.{fn}({', '.join(json.dumps(a) for a in args)});"


def outline_button_js(ease: int) -> str:
    return (
        "document.querySelectorAll('button[data-ease]').forEach(b => b.style.outline = '');"
        f"(function(b){{ if (b) {{ b.style.outline = '3px solid #3b82f6'; b.style.outlineOffset = '2px'; }} }})"
        f"(document.querySelector('button[data-ease=\"{int(ease)}\"]'));"
    )
