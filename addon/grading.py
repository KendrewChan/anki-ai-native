"""Prompts, reply parsing and note-field helpers. No Anki imports — unit-testable."""

import html
import json
import re

SYSTEM_PROMPT = """You are a strict flashcard tutor inside Anki. The user studies one card at a time; this whole conversation is one study session.

Two kinds of message arrive:

1. NEW CARD — you get the card's question and reference answer. Turn the question into ONE sharp, concrete question that forces out the key facts of the reference answer. Prefer a specific scenario or "explain X and why Y" over "tell me about X". Never leak the answer, and never steer toward a different point than the reference answer makes. If the question is already concrete, return it unchanged.
   Reply: {"question": "<the question>"}

2. GRADE — you get the card again plus the user's free-text answer. Judge ONLY against this card's reference answer; ignore earlier cards.
   - verdict: "wrong" (missing or incorrect core idea), "partial" (core idea right, key facts missing), "correct" (all key facts).
   - ease: wrong=1, partial=2, correct=3, correct AND complete and crisp=4.
   - feedback: one or two blunt sentences — fix what is wrong, add the single most important missing piece. No praise.
   - missed: facts in the reference answer the user did not give, each at most 12 words, specific facts not vague topics. [] if nothing.
   If you notice the user repeating a gap from earlier in this session, say so in feedback.
   Reply: {"verdict": "...", "ease": N, "feedback": "...", "missed": ["..."]}

Reply with the JSON object only. No prose, no code fences."""

RETRY_PROMPT = "Your last reply was not valid JSON. Reply again with the JSON object only."

VERDICTS = ("wrong", "partial", "correct")


def strip_html(text: str) -> str:
    """Rendered card HTML -> plain text."""
    text = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def answer_only(answer_html: str) -> str:
    """Anki's rendered answer usually repeats the question above <hr id=answer>; keep what follows."""
    m = re.search(r"(?i)<hr[^>]*id=[\"']?answer[\"']?[^>]*>", answer_html)
    return answer_html[m.end():] if m else answer_html


def ask_prompt(question: str, answer: str) -> str:
    return f"NEW CARD\n\nQuestion:\n{question}\n\nReference answer:\n{answer}"


def grade_prompt(question: str, sharp_question: str, answer: str, user_answer: str) -> str:
    asked = f"\n\nQuestion as asked:\n{sharp_question}" if sharp_question else ""
    return (
        f"GRADE\n\nCard question:\n{question}{asked}\n\n"
        f"Reference answer:\n{answer}\n\nUser's answer:\n{user_answer}"
    )


def parse_json_reply(text: str) -> dict:
    """Extract the first JSON object from a model reply (tolerates code fences / stray prose)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


def parse_question(text: str) -> dict:
    obj = parse_json_reply(text)
    q = obj.get("question")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("reply has no 'question'")
    return {"question": q.strip()}


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
    return {
        "verdict": verdict,
        "ease": ease,
        "feedback": str(obj.get("feedback", "")).strip(),
        "missed": [str(m).strip() for m in missed if str(m).strip()],
    }


def missed_html(bullets: list, date: str) -> str:
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
    return f"<hr><b>Missed ({date})</b><ul>{items}</ul>"


def pick_missed_field(field_names: list):
    """Back -> Back Extra -> last field. None if the note has no fields."""
    for name in ("Back", "Back Extra"):
        if name in field_names:
            return name
    return field_names[-1] if field_names else None
