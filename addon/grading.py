"""Prompts, reply parsing and note-field helpers. No Anki imports — unit-testable."""

import html
import json
import re

SYSTEM_PROMPT = """You are a strict flashcard tutor inside Anki. The user studies one card at a time; this whole conversation is one study session.

Two kinds of message arrive:

1. NEW CARD — you get the card's question and reference answer. Turn the question into sharp, concrete questions that force out the key facts of the reference answer. Prefer a specific scenario or "explain X and why Y" over "tell me about X". Never leak the answer, and never steer toward a different point than the reference answer makes.
   - Normally return ONE question. If the card bundles several distinct points (e.g. "X (a, b, c)" or "What is X? Why Y?"), return one question per point, at most 4.
   - If the question is already a single concrete question, return it unchanged.
   Reply: {"questions": ["<question>", ...]}

2. GRADE — you get the card again plus the user's free-text answer to each question asked. Judge ONLY against this card's reference answer; ignore earlier cards. Match each answer to its own question; a blank answer is wrong for that question.
   - per_question: for each question in order, {"verdict": "wrong"|"partial"|"correct", "note": "<at most 15 words>"}.
   - verdict (overall, for the whole card): "wrong" (missing or incorrect core idea), "partial" (core idea right, key facts missing), "correct" (all key facts).
   - ease: wrong=1, partial=2, correct=3, correct AND complete and crisp=4.
   - feedback: one or two blunt sentences — fix what is wrong, add the single most important missing piece. No praise.
   - missed: facts in the reference answer the user did not give, each at most 12 words, specific facts not vague topics. [] if nothing.
   If you notice the user repeating a gap from earlier in this session, say so in feedback.
   Reply: {"per_question": [...], "verdict": "...", "ease": N, "feedback": "...", "missed": ["..."]}

Reply with the JSON object only. No prose, no code fences."""

def system_prompt(custom: list) -> str:
    """Tutor system prompt plus the user's custom rules from the config page."""
    rules = [r for r in (custom or []) if str(r).strip()]
    if not rules:
        return SYSTEM_PROMPT
    listed = "\n".join(f"- {r}" for r in rules)
    return f"{SYSTEM_PROMPT}\n\nUser's rules (follow them unless they conflict with the JSON reply format):\n{listed}"


RETRY_PROMPT ="Your last reply was not valid JSON. Reply again with the JSON object only."

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


def grade_prompt(question: str, asked: list, answer: str, user_answers: list) -> str:
    """asked = questions shown (empty when no rewrite happened: cloze or ask failed)."""
    asked = asked or [question]
    pairs = "\n\n".join(
        f"Q{i}: {q}\nUser's answer {i}: {a.strip() or '(blank)'}"
        for i, (q, a) in enumerate(zip(asked, _pad(user_answers, len(asked))), 1)
    )
    return f"GRADE\n\nCard question:\n{question}\n\nReference answer:\n{answer}\n\n{pairs}"


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
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


MAX_QUESTIONS = 4


def parse_questions(text: str) -> dict:
    obj = parse_json_reply(text)
    qs = obj.get("questions", obj.get("question"))
    if isinstance(qs, str):
        qs = [qs]
    if not isinstance(qs, list):
        raise ValueError("reply has no 'questions'")
    qs = [str(q).strip() for q in qs if str(q).strip()][:MAX_QUESTIONS]
    if not qs:
        raise ValueError("reply has no 'questions'")
    return {"questions": qs}


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
            per_question.append({"verdict": v if v in VERDICTS else "partial", "note": str(pq.get("note", "")).strip()})
    return {
        "per_question": per_question,
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
