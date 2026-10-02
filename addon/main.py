"""Anki wiring: reviewer hooks, pycmd bridge, Missed append, main-page toggle + settings link."""

import datetime
import json
import tempfile

from anki.consts import MODEL_CLOZE
from aqt import gui_hooks, mw
from aqt.deckbrowser import DeckBrowser
from aqt.operations.note import update_note
from aqt.overview import Overview
from aqt.qt import QAction
from aqt.reviewer import Reviewer

from . import config_ops, grading, health, ui
from .config_page import ConfigPage
from .generate_page import GeneratePage
from .session import make_backend

ADDON = __name__.split(".")[0]


class State:
    def __init__(self):
        self.enabled = False  # AI Study mode; off at every Anki start
        self.session = None
        self.cwd = None
        self.page = None
        self.gen_page = None
        self.action = None
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


def session():
    if S.session is None:
        c = cfg()
        S.cwd = S.cwd or tempfile.mkdtemp(prefix="anki_ai_")
        S.session = make_backend(c, grading.system_prompt(c.get("custom")), S.cwd, mw.taskman.run_on_main)
    return S.session


def active() -> bool:
    return S.enabled and not S.disabled


def deck_names() -> dict:
    """Full deck name -> deck id (str), the shape config_ops expects."""
    return {d.name: str(d.id) for d in mw.col.decks.all_names_and_ids()}


def deck_rules(card, c: dict) -> list:
    """Prompt chain for the card's own deck (its home deck when it sits in a filtered deck)."""
    did = card.odid or card.did
    return config_ops.deck_chain(mw.col.decks.name(did), deck_names(), c.get("deck_prompts") or {})


def rewrite_enabled(card) -> bool:
    """Ask the AI for sharp questions first? Not for cloze cards, nor when the user turned it off."""
    return cfg().get("sharp_questions", True) and card.note_type()["type"] != MODEL_CLOZE


def eval_card(js: str):
    if mw.reviewer and mw.reviewer.web:
        mw.reviewer.web.eval(js)


def on_error(err) -> str:
    """Apply the failure policy; return the message to show. Settings diagnoses the last error on open."""
    health.LAST_ERROR[cfg().get("provider") or "claude"] = err.message
    if err.kind == "limit":
        S.disabled = f"Usage limit: {err.message}"
    elif err.kind in ("unavailable", "crashed", "error"):
        S.failures += 1
        if S.failures >= 2:
            S.disabled = f"AI unavailable: {err.message}"
    if S.disabled:
        return S.disabled + " — AI off until you reopen the reviewer. Open ⚙ Settings to fix it."
    if err.kind == "timeout":
        return "AI timed out."
    return f"AI error: {err.message} — open ⚙ Settings to fix it."


# --- hooks ---

def on_card_will_show(text: str, card, kind: str) -> str:
    if kind == "reviewQuestion" and active():
        return ui.question_html(text, rewrite_enabled(card))
    if kind == "reviewAnswer" and card.id in S.verdicts:
        return ui.verdict_html(*S.verdicts[card.id]) + text
    return text


def on_show_question(card):
    S.card_id = card.id
    S.verdicts.pop(card.id, None)
    if not active():
        return
    q = grading.strip_html(card.question())
    a = grading.strip_html(grading.answer_only(card.answer()))
    c = cfg()
    rules = deck_rules(card, c)
    S.ctx[card.id] = {"q": q, "a": a, "questions": [], "rules": rules}
    if not rewrite_enabled(card):
        return
    session().request(card.id, grading.ask_prompt(q, a, rules), grading.parse_questions,
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
    if not message.startswith("aiStudy:"):
        return handled
    if isinstance(context, (DeckBrowser, Overview)):
        if message == "aiStudy:toggle":
            set_enabled(not S.enabled)
        elif message == "aiStudy:settings":
            S.page.open()
        elif message == "aiStudy:generate":
            S.gen_page.open()
        return (True, None)
    if not isinstance(context, Reviewer):
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
    if ctx is None or not active():
        mw.reviewer._showAnswer()
        return
    answers = [str(a) for a in json.loads(payload)]
    questions = list(ctx["questions"])  # snapshot: what the user saw when submitting
    prompt = grading.grade_prompt(ctx["q"], questions, ctx["a"], answers, ctx["rules"])

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
    """Replace the card's Missed section with this review's misses (or "nothing") + today's date."""
    if not cfg().get("missed_append", True):
        return
    note = mw.reviewer.card.note()
    field = grading.pick_missed_field(list(note.keys()))
    if field is None:
        return
    note[field] = grading.replace_missed(note[field], missed, datetime.date.today().isoformat())
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
    """Leaving the reviewer: kill the process; the next session rebuilds it from the current config."""
    if S.session is not None:
        S.session.close()
        S.session = None
    S.reset()


def close(*_args):
    if S.session is not None:
        S.session.close()
        S.session = None
    S.reset()


# --- toggle + settings link ---

def set_enabled(on: bool):
    S.enabled = on
    if not on:
        end_session()
    if S.action is not None:
        S.action.setChecked(on)
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()
    elif mw.state == "overview":
        mw.overview.refresh()


def controls_html() -> str:
    on = "ON" if S.enabled else "OFF"
    color = "#27864a" if S.enabled else "#888"
    return (
        '<div style="margin:1em auto;text-align:center;font-size:0.95em">'
        f'<a href=# onclick="pycmd(\'aiStudy:toggle\');return false;" style="text-decoration:none">'
        f'AI Study: <b style="color:{color}">{on}</b></a>'
        ' &nbsp;·&nbsp; '
        '<a href=# onclick="pycmd(\'aiStudy:settings\');return false;">⚙ Settings</a>'
        ' &nbsp;·&nbsp; '
        '<a href=# onclick="pycmd(\'aiStudy:generate\');return false;">✨ Generate/Update Cards</a></div>'
    )


def on_deck_browser(_browser, content):
    content.stats += controls_html()


def on_overview(_overview, content):
    content.table += controls_html()  # right under "Study Now"


def setup_menu():
    S.action = QAction("AI Study mode", mw)
    S.action.setCheckable(True)
    S.action.setChecked(S.enabled)
    S.action.toggled.connect(lambda on: on != S.enabled and set_enabled(on))
    mw.form.menuTools.addAction(S.action)


def setup():
    S.page = ConfigPage(ADDON, end_session)
    S.gen_page = GeneratePage(ADDON)
    setup_menu()
    gui_hooks.deck_browser_will_render_content.append(on_deck_browser)
    gui_hooks.overview_will_render_content.append(on_overview)
    gui_hooks.card_will_show.append(on_card_will_show)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_show_answer.append(on_show_answer)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)
    gui_hooks.reviewer_will_end.append(end_session)
    gui_hooks.profile_will_close.append(close)
