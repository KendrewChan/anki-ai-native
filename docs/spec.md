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
- **Isolated:** runs in an empty working directory, loads no user/project settings (no hooks, plugins, CLAUDE.md), no MCP servers, no tools: `--safe-mode --setting-sources "" --strict-mcp-config --tools "" --disable-slash-commands --no-session-persistence` (verified on CLI 2.1.287; `--bare` rejected — it cannot use subscription login).
- API (async, callbacks on the main thread):
  - `ask(card_id, question_text, answer_text)` → `{"question": str}`
  - `grade(card_id, question, sharp_question, answer, user_answer)` — sends the full card again (robust if `ask` failed or was skipped, e.g. cloze) → `{"verdict": "wrong"|"partial"|"correct", "ease": 1-4, "feedback": str, "missed": [str]}`
- One request in flight; later requests queue. Every reply is tagged with its card id; the UI drops replies whose card id is not the current card.
- System prompt = fixed rubric: verdict → ease (wrong 1, partial 2, correct 3, correct + complete and crisp 4), Missed bullets ≤ 12 words each and only facts in the reference answer the user omitted, judge each card only against its own reference answer, reply with JSON only.
- Config (`config.json`): `claude_path`, `model` (default `sonnet`), `missed_append` (default `true`), `ask_timeout_s` (30), `grade_timeout_s` (60).

## 2. Reviewer flow (`__init__.py`, `ui.py`)

Display-only wrapper via `gui_hooks.card_will_show`; nothing is written to the card except Missed bullets.

**Question side** (`reviewQuestion`)
- Sharp question (spinner until `ask` returns) · collapsed **Show original** with Anki's normal rendered question · text box (Enter submits, Shift+Enter newline).
- `ask` fires when the card is shown. Submitting before it returns is allowed (queued).
- Submit → `grade` → on reply, store verdict by card id and call `reviewer._showAnswer()`.
- Enter on an empty box → normal answer, no verdict (Space types into the focused box; clicking outside it and pressing Space also works).
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
  addon/  __init__.py (loads main.py only inside Anki)  main.py (hooks)  session.py  grading.py  ui.py  config.json
  tests/  test_grading.py  test_session.py  fake_claude.py
  docs/   spec.md
```

Only `main.py` imports Anki; everything else is unit-tested with plain pytest.

## 5. Testing

1. **Spike** (throwaway): isolation flags, real stream-json shape, shortcut behaviour while typing, bottom-bar button HTML.
2. **Unit tests** (pytest): `grading.py` pure functions; `session.py` against `fake_claude.py` (lifecycle, queueing, stale drop, crash restart, timeout, bad JSON).
3. **Manual acceptance** in Anki: Basic card, cloze card, Space skip, Ctrl+Z, no add-on `claude` process left after leaving the reviewer.

## v1.1 (2026-10-02)

**Multiple questions per card.** `ask` returns `{"questions": [1–4]}` — one per distinct point the Front bundles, else one. Layout: **Show original** at the top, then question + answer box pairs. Enter → next box, Enter in the last box submits all, Shift+Enter newline, Enter with all boxes empty → plain answer. Boxes share ~45vh (single box 35vh), min ~4 lines, resizable. Grade adds `per_question` (✓/~/✗ + note per question); still one overall verdict + one ease, since Anki schedules per card. Cloze unchanged (one box).

**AI Study toggle.** `AI Study: ON/OFF · ⚙ Settings` on the deck list (`deck_browser_will_render_content` → `stats`) and deck overview (`overview_will_render_content` → `table`), plus **Tools → AI Study mode**. Off at every Anki start; off = plain reviewer and no `claude` process. Turning off kills the session.

**Settings page** (`config_page.py`, main-window state `aiStudyConfig` via `mw._aiStudyConfigState/_aiStudyConfigCleanup`; `← Back` → deck list).
- Top: chat input; every message goes to a separate `claude` session (option B — no commands to learn).
- AI replies `{"reply", "changes"}`; `config_ops.apply_changes` validates each change (`set` known keys with range/type checks, `add_custom`, `remove_custom`, `undo` = snapshot restore, `login`/`logout` → `claude auth login|logout`) and echoes `✓`/`✗` lines. Saved with `addonManager.writeConfig`.
- Below: **Configurations** (login state from `claude auth status`, model, timeouts, missed append, claude path; **Log in** button when logged out) and **Custom** (numbered rules, appended to the tutor system prompt via `grading.system_prompt`).
- The study session is rebuilt from config at each review session start, so changes apply next session.

## v1.2 — deck prompts (2026-10-02)

- Settings page sections: **Configurations** · **Custom Generic Rules** (every card; in the tutor system prompt) · **Deck Prompts**.
- **Deck Prompts** shows the real Anki deck tree (collapsible; ● = has prompt). Clicking a deck selects it; a panel shows its own prompt plus inherited ones. One free-text prompt per deck, edited via the CLI (`set_deck_prompt {deck, prompt}` replaces; `clear_deck_prompt`). The AI gets the deck list, existing prompts and the selected deck; names resolve exact → case-insensitive → unique leaf name, else rejected (ambiguous / unknown).
- Stored as `deck_prompts: {deck_id: prompt}` — survives renames; prompts of deleted decks are pruned on the next save.
- While studying, each card sends its **own home deck's** chain (`card.odid or card.did`; root → leaf, inner wins) inside the ask/grade message, since one session mixes subdecks.

## v1.3 — single Missed section (2026-10-02)

Each graded review **replaces** the card's Missed section (in the field chosen by `Back` → `Back Extra` → last field) with exactly one `<hr><b>Missed (YYYY-MM-DD)</b><ul>…</ul>` — or `…</b>: nothing` for a clean review — so the Back always shows the latest misses and when the card was last worked on. One date, in the title. Older Missed sections are removed on the next write. The tutor prompt labels the section as past gaps, not required content. Per-request conversation memory is not needed: the card itself carries the history.

## v1.4 — providers: Claude Code + Codex (2026-10-02)

- `provider`: `claude` (default) or `codex`. API keys and other CLIs (Gemini, opencode) deferred.
- Requests are **stateless**: each prompt carries the card, questions, answers, deck rules, and the card's last Missed section — no conversation memory needed. Claude keeps its long-running process only to skip startup.
- **Codex backend**: one `codex exec --json … -` per message, system prompt prepended on stdin, answer = last `agent_message` event; `error` / `turn.failed` / non-zero exit → errors ("limit" in text → usage limit). Isolation verified live on codex-cli 0.152.0: `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check -s read-only --disable shell_tool|apps|browser_use|computer_use|plugins -c web_search="disabled"`, run in an empty temp dir. ~6 s per call.
- `model` = `""` → provider default; switching provider resets a model that doesn't fit (e.g. `sonnet` under codex). Codex models: any OpenAI id.
- Login per provider: Claude `claude auth status|login|logout` (JSON); Codex `codex login status` / `codex login` / `codex logout`.
- Settings page: Provider row with **Use <other>** buttons (works even when the current provider's AI is broken), model shows "default", CLI path per provider (`claude_path`, `codex_path`, auto-detected).

## v1.5 — settings polish (2026-10-02)

- **Provider is a dropdown** (Claude Code / Codex) in Configurations — a plain control so a broken provider can always be switched without the chat.
- **Per-provider models**: `models: {"claude": …, "codex": …}`; "use opus" sets the current provider's model; switching provider restores that provider's own model. Legacy single `model` key is read as the active provider's model and migrated on the next save. The Model row shows the current provider's model ("default" = the CLI's own default).
- **Chat log**: only the latest 3 AI replies are shown; no per-change ✓ lines. A rejected change (✗ reason) is folded into that reply and shown in red. Dropdown changes are silent (Configurations shows the result).
