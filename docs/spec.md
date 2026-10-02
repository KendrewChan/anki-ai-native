# Anki AI Study add-on — spec

Date: 2026-10-02. Status: approved for implementation.

## Goal

Run an AI study loop inside the Anki desktop reviewer: AI turns the card into a sharp question, the user types a free-text answer, AI grades it, the user picks Anki's own Again / Hard / Good / Easy.

v1 scope: free-text grading only.

## Environment

- macOS, Anki 26.9.2. Claude Code CLI at `~/.local/bin/claude` (subscription login).
- Source in `anki-ai/addon/`, symlinked to `~/Library/Application Support/Anki2/addons21/anki_ai`.

## 1. Claude session (`session.py`)

- One long-running `claude -p --input-format stream-json --output-format stream-json --verbose` process per review session. All cards share one conversation. No card limit.
- Starts lazily on the first request; stops when the main window leaves the `review` state, on profile close, and on app exit.
- **Isolated:** runs in an empty working directory, loads no user/project settings (no hooks, plugins, CLAUDE.md), no MCP servers, no tools. Exact flags verified against the installed CLI.
- API (async, callbacks on the main thread):
  - `ask(card_id, question_text, answer_text)` → `{"question": str}`
  - `grade(card_id, user_answer)` → `{"verdict": "wrong"|"partial"|"correct", "ease": 1-4, "feedback": str, "missed": [str]}`
- One request in flight; later requests queue. Every reply is tagged with its card id; the UI drops replies whose card id is not the current card.
- System prompt = fixed rubric: verdict → ease (wrong 1, partial 2, correct 3, correct + complete and crisp 4), Missed bullets ≤ 12 words each and only facts in the reference answer the user omitted, judge each card only against its own reference answer, reply with JSON only.
- Config (`config.json`): `claude_path`, `model` (default `sonnet`), `missed_append` (default `true`), `ask_timeout_s` (30), `grade_timeout_s` (60).

## 2. Reviewer flow (`__init__.py`, `ui.py`)

Display-only wrapper via `gui_hooks.card_will_show`; nothing is written to the card except Missed bullets.

**Question side** (`reviewQuestion`)
- Sharp question (spinner until `ask` returns) · collapsed **Show original** with Anki's normal rendered question · text box (Enter submits, Shift+Enter newline).
- `ask` fires when the card is shown. Submitting before it returns is allowed (queued).
- Submit → `grade` → on reply, store verdict by card id and call `reviewer._showAnswer()`.
- Empty box + Space → normal answer, no verdict.
- Anki shortcuts must not fire while typing in the box.
- **Cloze cards:** no rewrite; native blanked question shown; text box + grading still apply.

**Answer side** (`reviewAnswer`)
- If a verdict exists for this card: badge (WRONG / PARTIAL / CORRECT), the user's answer, feedback, Missed bullets — above the normal answer HTML.
- Recommended ease button outlined in Anki's bottom bar. User clicks / presses 1–4; Anki schedules. The add-on never calls the scheduler.

**Missed → note field** (when `missed_append` and the list is non-empty)
- Append `<hr><b>Missed (YYYY-MM-DD)</b><ul><li>…</li></ul>` to the first existing field of: `Back` → `Back Extra` → the note's last field.
- Failure shows a red note in the verdict; the review is unaffected.

**Content sent to Claude:** rendered question and answer as plain text (HTML/CSS/scripts stripped). No images in v1.

## 3. Errors

A failure never blocks review — Space always works.

| Failure | Shown | Behaviour |
|---|---|---|
| CLI missing / not logged in | "AI unavailable: <reason>" | retry once on next card, then off for the session |
| Usage limit | "Claude usage limit: <message>" | off for the session |
| Timeout | "AI timed out — press Space" | late reply dropped |
| Non-JSON reply | — | one retry with "JSON only", then error |
| Process crash | "session restarted" | respawn on next call |
| Missed write fails | red note in verdict | review unaffected |
| Anki closes mid-request | — | process killed, late callbacks ignored |

## 4. Layout

```
anki-ai/
  addon/  __init__.py  session.py  grading.py  ui.py  config.json
  tests/  test_grading.py  test_session.py  fake_claude.py
  docs/   spec.md
```

`grading.py` and `session.py` import nothing from Anki.

## 5. Testing

1. **Spike** (throwaway): isolation flags, real stream-json shape, shortcut behaviour while typing, bottom-bar button HTML.
2. **Unit tests** (pytest): `grading.py` pure functions; `session.py` against `fake_claude.py` (lifecycle, queueing, stale drop, crash restart, timeout, bad JSON).
3. **Manual acceptance** in Anki: Basic card, cloze card, Space skip, Ctrl+Z, no add-on `claude` process left after leaving the reviewer.
