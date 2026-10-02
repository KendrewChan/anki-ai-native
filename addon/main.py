"""Anki wiring: reviewer hooks, the pycmd bridge, Missed append. Only module that imports aqt."""

import datetime
import json
import tempfile

from anki.consts import MODEL_CLOZE
from aqt import gui_hooks, mw
from aqt.operations.note import update_note
from aqt.reviewer import Reviewer

from . import grading, ui
from .session import ClaudeSession, build_command

ADDON = __name__.split(".")[0]


class State:
    def __init__(self):
        self.session = None
        self.cwd = None
        self.reset()

    def reset(self):
        """Per review session."""
        self.card_id = None
        self.ctx = {}  # card_id -> {"q", "a", "questions"}
        self.verdicts = {}  # card_id -> (verdict, questions, answers)
        self.failures = 0
        self.disabled = None  # reason string once AI is off for this session


S = State()


def cfg() -> dict:
    return mw.addonManager.getConfig(ADDON) or {}


def session() -> ClaudeSession:
    if S.session is None:
        c = cfg()
        S.cwd = S.cwd or tempfile.mkdtemp(prefix="anki_ai_")
        cmd = build_command(c.get("claude_path", "claude"), c.get("model", "sonnet"), grading.SYSTEM_PROMPT)
        S.session = ClaudeSession(cmd, S.cwd, mw.taskman.run_on_main)
    return S.session


def rewrite_enabled(card) -> bool:
    return card.note_type()["type"] != MODEL_CLOZE


def eval_card(js: str):
    if mw.reviewer and mw.reviewer.web:
        mw.reviewer.web.eval(js)


def on_error(err) -> str:
    """Apply the failure policy; return the message to show."""
    if err.kind == "limit":
        S.disabled = f"Claude usage limit: {err.message}"
    elif err.kind in ("unavailable", "crashed", "error"):
        S.failures += 1
        if S.failures >= 2:
            S.disabled = f"AI unavailable: {err.message}"
    if S.disabled:
        return S.disabled + " — AI off until you reopen the reviewer."
    if err.kind == "timeout":
        return "AI timed out."
    return f"AI error: {err.message}"


# --- hooks ---

def on_card_will_show(text: str, card, kind: str) -> str:
    if kind == "reviewQuestion" and not S.disabled:
        return ui.question_html(text, rewrite_enabled(card))
    if kind == "reviewAnswer" and card.id in S.verdicts:
        return ui.verdict_html(*S.verdicts[card.id]) + text
    return text


def on_show_question(card):
    S.card_id = card.id
    S.verdicts.pop(card.id, None)
    if S.disabled:
        return
    q = grading.strip_html(card.question())
    a = grading.strip_html(grading.answer_only(card.answer()))
    S.ctx[card.id] = {"q": q, "a": a, "questions": []}
    if not rewrite_enabled(card):
        return
    c = cfg()
    session().request(card.id, grading.ask_prompt(q, a), grading.parse_questions,
                      c.get("ask_timeout_s", 30), on_asked)


def on_asked(card_id, result, err):
    if card_id != S.card_id or mw.reviewer.state != "question":
        return
    if err:
        eval_card(ui.js_call("askFailed", on_error(err)))
        return
    S.failures = 0
    S.ctx[card_id]["questions"] = result["questions"]
    eval_card(ui.js_call("setQuestions", result["questions"]))


def on_js_message(handled, message: str, context):
    if not isinstance(context, Reviewer) or not message.startswith("aiStudy:"):
        return handled
    if message == "aiStudy:reveal":
        if mw.reviewer.state == "question":
            mw.reviewer._showAnswer()
    elif message.startswith("aiStudy:submit:"):
        submit(message[len("aiStudy:submit:"):])
    return (True, None)


def submit(payload: str):
    card_id = S.card_id
    ctx = S.ctx.get(card_id)
    if ctx is None or S.disabled:
        mw.reviewer._showAnswer()
        return
    answers = [str(a) for a in json.loads(payload)]
    questions = list(ctx["questions"])  # snapshot: what the user saw when submitting
    prompt = grading.grade_prompt(ctx["q"], questions, ctx["a"], answers)

    def on_graded(cid, result, err):
        if cid != S.card_id or mw.reviewer.state != "question":
            return
        if err:
            eval_card(ui.js_call("gradeFailed", on_error(err)))
            return
        S.failures = 0
        S.verdicts[cid] = (result, questions, answers)
        mw.reviewer._showAnswer()
        append_missed(result["missed"])

    session().request(card_id, prompt, grading.parse_grade, cfg().get("grade_timeout_s", 60), on_graded)


def append_missed(missed: list):
    if not missed or not cfg().get("missed_append", True):
        return
    note = mw.reviewer.card.note()
    field = grading.pick_missed_field(list(note.keys()))
    if field is None:
        return
    note[field] += grading.missed_html(missed, datetime.date.today().isoformat())
    (
        update_note(parent=mw, note=note)
        .failure(lambda e: eval_card(ui.append_verdict_note_js(f"Missed notes not saved: {e}")))
        .run_in_background(initiator=mw.reviewer)
    )


def on_show_answer(card):
    if card.id in S.verdicts:
        ease = S.verdicts[card.id][0]["ease"]
        mw.reviewer.bottom.web.eval(f"setTimeout(function(){{ {ui.outline_button_js(ease)} }}, 50);")


def end_session(*_args):
    if S.session is not None:
        S.session.stop()
    S.reset()


def close(*_args):
    if S.session is not None:
        S.session.close()
        S.session = None
    S.reset()


def setup():
    gui_hooks.card_will_show.append(on_card_will_show)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)
    gui_hooks.reviewer_will_end.append(end_session)
    gui_hooks.profile_will_close.append(close)
