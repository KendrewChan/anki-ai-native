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
.ai-q.loading { opacity: 0.55; font-weight: 400; font-style: italic; }
.ai-hint { position: relative; display: inline-block; margin-left: 0.4em; width: 1.2em; height: 1.2em; line-height: 1.2em;
           border-radius: 50%; border: 1px solid #8888; text-align: center; font-size: 0.7em; font-weight: 400;
           cursor: help; vertical-align: middle; opacity: 0.7; }
.ai-hint .tip { display: none; position: absolute; top: calc(100% + 6px); left: -0.6em; z-index: 10; width: max-content;
                max-width: 24em; white-space: normal; text-align: left; font-size: 1.3em; line-height: 1.4;
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
.ai-pq { margin: 0.6em 0; } .ai-pq-q { font-weight: 600; }
.ai-you { opacity: 0.75; white-space: pre-wrap; margin: 0.2em 0; }
.ai-you.ai-you-wrong { color: #d33; opacity: 1; } .ai-you.ai-you-partial { color: #d97706; opacity: 1; }
.ai-model { color: #27864a; }
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

  function addItem(question, hint) {
    const item = document.createElement("div");
    item.className = "ai-item";
    if (question !== null) {
      const label = document.createElement("div");
      label.className = "ai-q";
      label.textContent = question;
      if (hint) {
        const help = document.createElement("span");
        help.className = "ai-hint";
        help.tabIndex = -1;  // focusable by click (shows the tip), but Tab still goes box to box
        help.textContent = "?";
        const tip = document.createElement("span");
        tip.className = "tip";
        tip.textContent = hint;
        help.append(tip);
        label.append(help);
      }
      item.append(label);
    }
    const box = document.createElement("textarea");
    box.className = "ai-ans";
    if (!boxes().length) box.placeholder = HINT;
    item.append(box);
    list.append(item);
    wire(box);
  }

  window.aiStudy = {
    setQuestions(qs, hints) {
      if (submitted) return;
      list.innerHTML = "";
      qs.forEach((q, i) => addItem(qs.length > 1 ? (i + 1) + ". " + q : q, (hints || [])[i]));
      sizeBoxes();
      boxes()[0].focus();
    },
    askFailed(msg) {
      list.innerHTML = "";
      addItem(null);  // no sharp question: answer the original, opened above
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


def question_html(original: str, rewrite: bool) -> str:
    """Wrap Anki's rendered question. rewrite=True starts with no answer box: setQuestions adds one per sharp question.
    rewrite=False (cloze, or sharp questions off) shows the original as the question with its box ready."""
    if rewrite:
        orig = f'<details id="ai-orig"><summary>Show original</summary>{original}</details>'
        item = '<div class="ai-item"><div class="ai-q loading">Thinking of a sharp question…</div></div>'
    else:
        orig = f'<div id="ai-orig-plain">{original}</div>'
        item = f'<div class="ai-item"><textarea class="ai-ans" placeholder="{HINT}"></textarea></div>'
    js = JS.replace("__HINT__", json.dumps(HINT))
    return f'{CSS}<div id="ai-study">{orig}<div id="ai-items">{item}</div><div id="ai-status"></div></div>{js}'


def verdict_html(verdict: dict, questions: list, answers: list) -> str:
    """questions = what was asked (may be empty: cloze / ask failed); answers = one per box."""
    v = verdict["verdict"]
    marks = {"correct": "✓", "partial": "~", "wrong": "✗"}
    per_q = verdict.get("per_question") or []
    rows = []
    if questions and len(per_q) == len(questions):
        for i, (q, pq) in enumerate(zip(questions, per_q)):
            a = answers[i] if i < len(answers) else ""
            rows.append(
                f'<div class="ai-pq"><span class="ai-pq-q">{marks[pq["verdict"]]} {html.escape(q)}</span>'
                f'<div class="ai-you{_you_class(pq["verdict"])}">You: {html.escape(a.strip() or "(blank)")}</div>'
                f'<div>{html.escape(pq["note"])}</div></div>'
            )
    else:
        rows.append(f'<div class="ai-you{_you_class(v)}">You: {html.escape(chr(10).join(a for a in answers if a.strip()))}</div>')
    missed = verdict["missed"]
    missed_part = (
        "<b>Missed:</b><ul>" + "".join(f"<li>{html.escape(m)}</li>" for m in missed) + "</ul>"
        if missed else "<b>Missed:</b> nothing"
    )
    return (
        f'{CSS}<div class="ai-verdict"><span class="ai-badge ai-{v}">{v.upper()}</span>'
        f'{"".join(rows)}'
        f"<div style='margin-top:0.5em'>{html.escape(verdict['feedback'])}</div>"
        f"<div style='margin-top:0.5em'>{missed_part}</div></div>"
    )


def _you_class(verdict: str) -> str:
    """The user's answer turns red when wrong, orange when partial."""
    return {"wrong": " ai-you-wrong", "partial": " ai-you-partial"}.get(verdict, "")


# The Missed section keeps the card's own text colour inside the green model answer.
MISSED_COLOR_JS = ("<script>document.querySelectorAll('.ai-missed-sec').forEach("
                   "e => e.style.color = getComputedStyle(document.body).color);</script>")


def model_answer_html(answer: str) -> str:
    """Graded answer side: the card's back (after <hr id=answer>) in green, except its Missed section."""
    front, back = grading.split_answer(answer)
    back = grading.MISSED_SECTION.sub(lambda m: f'<div class="ai-missed-sec">{m.group(0)}</div>', back)
    return f'{front}<div class="ai-model">{back}</div>{MISSED_COLOR_JS}'


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
