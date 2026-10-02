"""Prompts, reply parsing and note-field helpers. No Anki imports — unit-testable."""

import html
import json
import re
from pathlib import Path

# How the AI formats text (bold, HTML fields, LaTeX); appended to every system prompt.
STYLE_GUIDE = Path(__file__).with_name("style.md").read_text(encoding="utf-8").strip()

SYSTEM_PROMPT = """You are a strict flashcard tutor inside Anki. The user studies one card at a time; this whole conversation is one study session.

Two kinds of message arrive:

1. NEW CARD — you get the card's question and reference answer. Turn the question into sharp, concrete questions that force out the key facts of the reference answer. Prefer a specific scenario or "explain X and why Y" over "tell me about X". Never leak the answer, and never steer toward a different point than the reference answer makes.
   - Normally return ONE question. If the card bundles several distinct points (e.g. "X (a, b, c)" or "What is X? Why Y?"), return one question per point, at most 4 (deck rules may ask for more, up to 8).
   - If the question is already a single concrete question, return it unchanged.
   - If one question asks for several parts, return it as {"question": "<stem>", "parts": ["<part>", ...]} instead of a string; don't number the parts yourself.
   - hints: one per question, in order — a nudge of at most 12 words that points toward the idea without giving the answer. For a question with parts, its hint is a list with one hint per part.
   - show_original: true when the user should see the card's own question as written above your questions (e.g. a deck rule says to present it); otherwise false (it stays folded).
   Reply: {"questions": ["<question>" or {"question": "...", "parts": [...]}, ...], "hints": ["<hint>" or ["<hint per part>", ...], ...], "show_original": false}

2. GRADE — you get the card again plus the user's free-text answer to each question asked. Judge ONLY against this card's reference answer; ignore earlier cards. Match each answer to its own question; a blank answer is wrong for that question.
   - per_question: for each question in order, {"verdict": "wrong"|"partial"|"correct", "note": "<at most 15 words>", "parts": [{"text": "<one claim from the user's answer>", "verdict": "wrong"|"partial"|"correct", "why": "<partial/wrong: what is off and what is right, at most 15 words; \"\" when correct>"}, ...]}.
     parts: the user's answer clipped into its separate claims, in order, in the user's own words (trim filler, never add facts). [] for a blank answer.
     Be consistent: a question is "correct" only if none of its parts is partial or wrong, and its note must not call a partial or wrong part right.
   - verdict (overall, for the whole card; must follow the per-question verdicts — "correct" only if every question is correct): "wrong" (missing or incorrect core idea), "partial" (core idea right, key facts missing), "correct" (all key facts).
   - ease: wrong=1, partial=2, correct=3, correct AND complete and crisp=4.
   - feedback: one or two blunt sentences — fix what is wrong, add the single most important missing piece. No praise.
   - missed: facts in the reference answer the user did not give, each at most 12 words, specific facts not vague topics. [] if nothing.
   The reference answer may end with a "Missed (date)" section: what the user missed the last time they reviewed this card, and when. It is NOT part of the required answer. If the user misses the same point again, say so plainly in feedback.
   Reply: {"per_question": [...], "verdict": "...", "ease": N, "feedback": "...", "missed": ["..."]}

A card may come with "Deck rules" — instructions for the deck it belongs to, outermost deck first; inner (more specific) decks win on conflict. Follow them for that card only. Priority, highest first: deck rules, then the user's general rules, then everything else in these instructions (defaults such as how many questions, their wording and sections, what to grade on, and the formatting guide). Only the JSON reply format is fixed.

Reply with the JSON object only. No prose, no code fences."""

def system_prompt(custom: list) -> str:
    """Tutor system prompt plus the user's custom rules from the config page."""
    rules = [r for r in (custom or []) if str(r).strip()]
    base = f"{SYSTEM_PROMPT}\n\n{STYLE_GUIDE}"
    if not rules:
        return base
    listed = "\n".join(f"- {r}" for r in rules)
    return f"{base}\n\nUser's general rules (follow them unless they conflict with the JSON reply format; a card's deck rules win over them):\n{listed}"



VERDICTS = ("wrong", "partial", "correct")


def strip_html(text: str) -> str:
    """Rendered card HTML -> plain text."""
    text = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def split_answer(answer_html: str) -> tuple:
    """(front, back): Anki's rendered answer usually repeats the question above <hr id=answer>. No marker = all back."""
    m = re.search(r"(?i)<hr[^>]*id=[\"']?answer[\"']?[^>]*>", answer_html)
    return (answer_html[:m.end()], answer_html[m.end():]) if m else ("", answer_html)


def answer_only(answer_html: str) -> str:
    return split_answer(answer_html)[1]


def deck_rules_block(deck_rules: list) -> str:
    """deck_rules: [(deck name, prompt)] outermost first."""
    if not deck_rules:
        return ""
    return "\n\nDeck rules (outer → inner):\n" + "\n".join(f"- {name}: {p}" for name, p in deck_rules)


def ask_prompt(question: str, answer: str, deck_rules: list = ()) -> str:
    return f"NEW CARD\n\nQuestion:\n{question}\n\nReference answer:\n{answer}{deck_rules_block(deck_rules)}"


def grade_prompt(question: str, asked: list, answer: str, user_answers: list, deck_rules: list = ()) -> str:
    """asked = questions shown (empty when no rewrite happened: cloze or ask failed)."""
    asked = asked or [question]
    pairs = "\n\n".join(
        f"Q{i}: {q}\nUser's answer {i}: {a.strip() or '(blank)'}"
        for i, (q, a) in enumerate(zip(asked, _pad(user_answers, len(asked))), 1)
    )
    return (f"GRADE\n\nCard question:\n{question}\n\nReference answer:\n{answer}"
            f"{deck_rules_block(deck_rules)}\n\n{pairs}")


def _pad(items: list, n: int) -> list:
    """Fit the answers to n questions: pad with blanks, fold any extras into the last."""
    items = list(items)
    if len(items) > n:
        items = items[:n - 1] + ["\n".join(items[n - 1:])]
    return items + [""] * (n - len(items))


def parse_json_reply(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates code fences / stray prose)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    raw = text[start:end + 1]
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # LaTeX written with single backslashes (\( \sqrt …) is invalid JSON: double the stray ones and retry.
        obj = json.loads(re.sub(r"\\(.)", lambda m: m.group(0) if m.group(1) in '"\\/bfnrtu' else "\\\\" + m.group(1),
                                raw, flags=re.S))
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return _fix_latex(obj)


_LATEX_CTRL = {"\b": "\\b", "\f": "\\f", "\t": "\\t", "\r": "\\r"}


def _fix_latex(value):
    """Single-backslash \\frac, \\times, \\beta, \\right parse as control characters: turn them back into LaTeX."""
    if isinstance(value, str):
        return re.sub(r"[\b\f\t\r](?=[A-Za-z])", lambda m: _LATEX_CTRL[m.group()], value)
    if isinstance(value, list):
        return [_fix_latex(v) for v in value]
    if isinstance(value, dict):
        return {k: _fix_latex(v) for k, v in value.items()}
    return value


def rich(text: str) -> str:
    """AI short text -> safe HTML: escaped, **bold** -> <b>. LaTeX \\( \\) passes through for Anki's MathJax."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


MAX_QUESTIONS = 8  # the prompt asks for at most 4 unless deck rules want more


def parse_questions(text: str) -> dict:
    """{"questions": [plain text per question, parts as numbered lines — for prompts and the verdict],
        "items": [{"num", "text", "hint", "parts": [{"label", "text", "hint"}]}] — for the question side}.
    Parts are numbered 3.1, 3.2… under question 3 (1., 2. when there is one question); hints sit on the smallest unit."""
    obj = parse_json_reply(text)
    qs = obj.get("questions", obj.get("question"))
    if isinstance(qs, (str, dict)):
        qs = [qs]
    if not isinstance(qs, list):
        raise ValueError("reply has no 'questions'")
    hints = obj.get("hints") if isinstance(obj.get("hints"), list) else []
    raw = []
    for q, h in zip(qs, hints + [None] * len(qs)):
        if isinstance(q, dict):
            parts = q.get("parts") if isinstance(q.get("parts"), list) else []
            stem, parts = str(q.get("question", "")).strip(), [str(p).strip() for p in parts if str(p).strip()]
        else:
            stem, parts = str(q or "").strip(), []
        if stem or parts:
            raw.append((stem, parts, h))
    raw = raw[:MAX_QUESTIONS]
    if not raw:
        raise ValueError("reply has no 'questions'")
    many = len(raw) > 1
    questions, items = [], []
    for i, (stem, parts, h) in enumerate(raw, 1):
        hs = [str(x).strip() for x in h] if isinstance(h, list) else [str(h).strip() if h else ""]
        labels = [f"{i}.{k}" if many else f"{k}." for k in range(1, len(parts) + 1)]
        part_hints = (hs + [""] * len(parts))[:len(parts)]
        items.append({"num": f"{i}." if many else "", "text": stem, "hint": "" if parts else hs[0],
                      "parts": [{"label": lb, "text": p, "hint": ph} for lb, p, ph in zip(labels, parts, part_hints)]})
        questions.append("\n".join([stem] + [f"{lb} {p}" for lb, p in zip(labels, parts)]).strip())
    return {"questions": questions, "items": items, "show_original": obj.get("show_original") is True}


def parse_grade(text: str) -> dict:
    obj = parse_json_reply(text)
    verdict = str(obj.get("verdict", "")).lower()
    if verdict not in VERDICTS:
        raise ValueError(f"bad verdict: {verdict!r}")
    try:
        ease = min(4, max(1, int(obj.get("ease"))))
    except (TypeError, ValueError):
        ease = {"wrong": 1, "partial": 2, "correct": 3}[verdict]
    missed = obj.get("missed") or []
    if not isinstance(missed, list):
        missed = [missed]
    per_question = []
    for pq in obj.get("per_question") or []:
        if isinstance(pq, dict):
            v = str(pq.get("verdict", "")).lower()
            parts = pq.get("parts") if isinstance(pq.get("parts"), list) else []
            parts = [{"text": str(x.get("text", "")).strip(), "verdict": str(x.get("verdict", "")).lower(),
                      "why": str(x.get("why") or "").strip()} for x in parts if isinstance(x, dict)]
            per_question.append({"verdict": v if v in VERDICTS else "partial", "note": str(pq.get("note", "")).strip(),
                                 "parts": [x for x in parts if x["text"] and x["verdict"] in VERDICTS]})
    return {
        "per_question": per_question,
        "verdict": verdict,
        "ease": ease,
        "feedback": str(obj.get("feedback", "")).strip(),
        "missed": [str(m).strip() for m in missed if str(m).strip()],
    }


# A Missed section as written by this add-on (tolerant of editor reformatting).
MISSED_SECTION = re.compile(
    r"\s*<hr[^>]*>\s*<b>\s*Missed\s*\([^)]*\)\s*</b>\s*(?::\s*nothing|<ul>.*?</ul>)?", re.I | re.S
)


def missed_html(bullets: list, date: str) -> str:
    if not bullets:
        return f"<hr><b>Missed ({date})</b>: nothing"
    items = "".join(f"<li>{rich(b)}</li>" for b in bullets)
    return f"<hr><b>Missed ({date})</b><ul>{items}</ul>"


def replace_missed(field_html: str, bullets: list, date: str) -> str:
    """Keep exactly one Missed section: the latest review's misses (or "nothing") and its date."""
    return MISSED_SECTION.sub("", field_html).rstrip() + missed_html(bullets, date)


def pick_missed_field(field_names: list):
    """Back -> Back Extra -> last field. None if the note has no fields."""
    for name in ("Back", "Back Extra"):
        if name in field_names:
            return name
    return field_names[-1] if field_names else None

EDIT_SYSTEM_PROMPT = """You edit one Anki note at a time, on the user's request, right after they reviewed it. Every message is independent: it gives the note's fields (raw HTML), what the user was asked and answered, the grade, and the user's request. Never touch any other note.

Change only what the request asks for; keep each field's existing HTML style. A field may end with a "Missed (date)" section the add-on maintains — leave it as it is unless the user asks about it. If the request is unclear, or asks for nothing about the note, change nothing and say why in "reply". Deck rules, when given, take priority over everything else here (including the formatting guide) except the JSON reply format.

Reply with JSON only, no code fences:
{"reply": "<one short sentence to the user>", "fields": {"<field name>": "<the whole new field HTML>", ...}}
Include only the fields you change; {} for none."""
EDIT_SYSTEM_PROMPT += "\n\n" + STYLE_GUIDE


def edit_prompt(fields: dict, request: str, questions: list, answers: list, verdict: dict,
                deck_rules: list = ()) -> str:
    """fields: field name -> raw HTML of the note right now."""
    note = "\n\n".join(f"[{name}]\n{value}" for name, value in fields.items())
    asked = questions or ["(the card's own question)"]
    pairs = "\n".join(f"Q: {q}\nUser: {a.strip() or '(blank)'}" for q, a in zip(asked, _pad(answers, len(asked))))
    return (f"NOTE FIELDS\n\n{note}{deck_rules_block(deck_rules)}\n\nReview:\n{pairs}\n"
            f"Grade: {verdict.get('verdict')} — {verdict.get('feedback', '')}\n\nUser's request:\n{request}")


def parse_edit_reply(text: str) -> dict:
    obj = parse_json_reply(text)
    fields = obj.get("fields") or {}
    if not isinstance(fields, dict):
        raise ValueError("'fields' is not an object")
    return {"reply": str(obj.get("reply", "")).strip(), "fields": {str(k): str(v) for k, v in fields.items()}}


def plan_field_edit(current: dict, proposed: dict) -> tuple:
    """(changes, rejected): changes = fields that exist and actually differ; rejected = unknown field names."""
    changes = {k: v for k, v in proposed.items() if k in current and v != current[k]}
    return changes, [k for k in proposed if k not in current]
