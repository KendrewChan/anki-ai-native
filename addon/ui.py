"""HTML/CSS/JS injected into the reviewer. Display-only — nothing here touches the collection."""

import html
import json

CSS = """
<style>
#ai-study { text-align: left; width: min(92vw, 70em); margin: 0 auto 1em; font-size: 0.95em; }
#ai-q { font-size: 1.15em; font-weight: 600; margin: 0.4em 0 0.8em; white-space: pre-wrap; }
#ai-q.loading { opacity: 0.55; font-weight: 400; font-style: italic; }
#ai-orig { margin-bottom: 0.8em; }
#ai-orig > summary { cursor: pointer; opacity: 0.7; font-size: 0.85em; }
#ai-ans { width: 100%; box-sizing: border-box; height: 35vh; min-height: 6em; resize: vertical; padding: 0.6em; font: inherit;
          border-radius: 6px; border: 1px solid #8888; background: transparent; color: inherit; }
#ai-status { margin-top: 0.4em; font-size: 0.85em; opacity: 0.75; min-height: 1.2em; }
.ai-err { color: #d33; opacity: 1 !important; }
.ai-verdict { text-align: left; max-width: 46em; margin: 0 auto 1em; padding: 0.7em 0.9em;
              border-radius: 8px; border: 1px solid #8884; font-size: 0.92em; }
.ai-badge { display: inline-block; padding: 0.1em 0.55em; border-radius: 4px; font-weight: 700;
            color: #fff; font-size: 0.85em; letter-spacing: 0.04em; }
.ai-wrong { background: #c0392b; } .ai-partial { background: #c27c0e; } .ai-correct { background: #27864a; }
.ai-you { opacity: 0.75; white-space: pre-wrap; margin: 0.5em 0; }
.ai-verdict ul { margin: 0.3em 0 0 1.2em; padding: 0; }
</style>
"""

JS = """
<script>
(function () {
  const q = document.getElementById("ai-q");
  const orig = document.getElementById("ai-orig");
  const ans = document.getElementById("ai-ans");
  const status = document.getElementById("ai-status");
  window.aiStudy = {
    setQuestion(text) { if (q) { q.textContent = text; q.classList.remove("loading"); } },
    askFailed(msg) {
      if (q) q.remove();
      if (orig) orig.open = true;
      this.setStatus(msg, true);
    },
    setStatus(msg, isErr) { status.textContent = msg; status.classList.toggle("ai-err", !!isErr); },
    gradeFailed(msg) {
      ans.disabled = false; ans.focus();
      this.setStatus(msg + " Enter on an empty box shows the answer.", true);
    },
  };
  ans.addEventListener("keydown", function (e) {
    e.stopPropagation();  // keep Anki's reviewer keys (space, 1-4, e…) out of the text box
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      const v = ans.value.trim();
      if (!v) { pycmd("aiStudy:reveal"); return; }
      ans.disabled = true;
      aiStudy.setStatus("Grading…");
      pycmd("aiStudy:submit:" + v);
    }
  });
  setTimeout(function () { ans.focus(); }, 0);
})();
</script>
"""


def question_html(original: str, rewrite: bool) -> str:
    """Wrap Anki's rendered question. rewrite=False (cloze) shows the original as the question."""
    if rewrite:
        top = '<div id="ai-q" class="loading">Thinking of a sharp question…</div>'
        orig = f'<details id="ai-orig"><summary>Show original</summary>{original}</details>'
    else:
        top = ""
        orig = f'<div id="ai-orig-plain">{original}</div>'
    box = (
        '<textarea id="ai-ans" placeholder="Type your answer — Enter to submit, '
        'Shift+Enter for a new line, Enter on empty to just show the answer"></textarea>'
        '<div id="ai-status"></div>'
    )
    return f'{CSS}<div id="ai-study">{top}{orig}{box}</div>{JS}'


def verdict_html(verdict: dict, user_answer: str, note: str = "") -> str:
    v = verdict["verdict"]
    missed = verdict["missed"]
    missed_part = (
        "<b>Missed:</b><ul>" + "".join(f"<li>{html.escape(m)}</li>" for m in missed) + "</ul>"
        if missed else "<b>Missed:</b> nothing"
    )
    note_part = f'<div class="ai-err">{html.escape(note)}</div>' if note else ""
    return (
        f'{CSS}<div class="ai-verdict"><span class="ai-badge ai-{v}">{v.upper()}</span>'
        f'<div class="ai-you">You: {html.escape(user_answer)}</div>'
        f"<div>{html.escape(verdict['feedback'])}</div>"
        f"<div style='margin-top:0.5em'>{missed_part}</div>{note_part}</div>"
    )


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
