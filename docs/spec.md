# AI Quizzer add-on for Anki — spec

How the add-on works **now**. Version history is in [CHANGELOG.md](../CHANGELOG.md); the user guide is [guide.md](guide.md). When behaviour changes, update the section here and add a changelog entry.

Built and tested on macOS, Anki 26.9.2.

## Goal

Run an AI study loop inside the Anki desktop reviewer: the AI turns each card into sharp questions, the user types free-text answers, the AI grades them and recommends an ease, and the user still presses Anki's own Again / Hard / Good / Easy. The add-on never calls the scheduler.

## Layout

| Module | Role | Imports Anki? |
|---|---|---|
| `__init__.py` | Loads `main.py` only inside Anki | guarded |
| `main.py` | Hooks, AI Study toggle, reviewer glue | yes |
| `ui.py` | Reviewer HTML/JS | no |
| `chat_page.py` | `ChatPage` base for both pages (state enter/leave, Back, chat box, bridge routing); `load_config`, `deck_ids` | yes |
| `config_page.py`, `generate_page.py` | ⚙ Settings and ✨ Generate/Update Cards pages | yes |
| `session.py` | Provider CLIs: find, isolate, run, parse; login; model lookup | no |
| `grading.py` | Tutor prompts, reply parsing, Missed HTML | no |
| `config_ops.py` | Settings chat prompt, validated config changes, toggles | no |
| `generate_ops.py` | Generate prompt, reference reading, reply validation | no |
| `generate_col.py` | AI-GEN staging ops on a `Collection` passed in | no |
| `health.py` | Self-check, error classification, reviewer failure policy, update / rollback | no |
| `fixes.py` | Fix buttons on Settings replies; talks to the page only through `cfg`, `provider`, `apply`, `login`, `say`, `refresh` | yes |
| `state.py` | What the add-on learns about the CLIs: real model names, `last_good` versions. `user_files/state.json`, kept by Anki across updates; never in the config or its undo history | no |
| `style.md` | Formatting guide (bold, note-field HTML, LaTeX) appended to the tutor, note-edit and Generate system prompts | — |
| `config.json` | Shipped defaults (the user's settings live in the gitignored `meta.json`) | — |

Everything that doesn't import `aqt` is unit-tested with plain pytest.

## Providers and sessions (`session.py`)

- `provider`: `claude` (default) or `codex`. Uses the user's logged-in CLI; no API keys. CLI paths `claude_path` / `codex_path` are auto-detected when empty, including when Anki is launched from the Dock (no shell `PATH`).
- **Stateless requests**: every prompt carries the card, questions, answers, deck prompts and the card's last Missed section. No conversation memory is relied on.
- **Claude**: one long-running `claude -p --input-format stream-json --output-format stream-json --verbose` per review session, kept only to skip startup. Starts on first request; stops when review ends, on profile close and on app exit.
- **Codex**: one `codex exec --json … -` per message, system prompt prepended on stdin; answer = last `agent_message` event.
- **Isolation** (both run in an empty temp directory with no user settings, hooks, plugins, MCP servers or tools):
  - Claude: `--safe-mode --setting-sources "" --strict-mcp-config --tools "" --disable-slash-commands --no-session-persistence`. `--bare` is not usable: it can't use subscription login.
  - Codex: `--ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check -s read-only --disable shell_tool|apps|browser_use|computer_use|plugins -c web_search="disabled"`.
- API: `request(card_id, prompt, parse, timeout, callback)` — callbacks on the main thread; the "ask" and "grade" prompts come from `grading.py`. One request in flight, later ones queue. Replies are tagged with their card id; replies for a card no longer shown are dropped.
- **Models**: `models: {claude, codex}`; `""` = the CLI's default. Settings always shows the real model id, read from the CLI's own output (Claude's stream-json `init` event, Codex's stderr `model:` header), saved by `session.remember_model` into `state.py` the moment a probe or real call reports it (rendering never writes). The two keys older versions kept in the config (`resolved_models`, `last_good`) are dropped on the next settings change.
- **Login**: Claude `claude auth status|login|logout`; Codex `codex login status` / `codex login` / `codex logout`.

## Reviewer flow (`main.py`, `ui.py`, `grading.py`)

Only active while **AI Study** is ON, and only for cards whose home deck has AI Study on (per-deck setting, default on; see Deck Prompts in Settings). The ON/OFF link is on the home screen, on the deck overview and in **Tools → AI Study mode**. It stays as the user last left it across Anki restarts (`state.json` → `ui.ai_study`; off on first install). Off means the plain reviewer runs and no AI process starts; turning it off kills the session. The flow is display-only, through `gui_hooks.card_will_show`: nothing is written to the card except the Missed section.

**Question side**
- Sharp questions are on by default and set per deck (see Deck Prompts in Settings). When on for the card's home deck, an ask request carries only the card's front (question) and deck rules, never the back, and returns `{"questions": [1–4], "hints": [...]}`, one question per distinct point the card bundles (at most 4 by default; deck rules override the defaults, up to 8 questions). `"show_original": true` opens **Show original** above the questions, e.g. when a deck rule says to present the card's question as written. A question that asks for several parts comes as `{"question": stem, "parts": [...]}` and its hint as a list, one per part. The add-on numbers questions `1.`, `2.` (only when there are several) and parts `3.1`, `3.2` (or `1.`, `2.` under a single question). Each hint (≤ 12 words, never the answer) shows as a **?** tooltip on the smallest unit: after each part, or after the question when it has no parts. Missing hints are allowed. A question with parts still has one answer box. `parse_questions` returns plain-text `questions` (parts as numbered lines, used by the grade and edit prompts and the verdict, which numbers its rows the same way) and `items` for the question side. Otherwise the card's own question is used.
- Cloze cards always use their own blanked question.
- Layout: a collapsed **Show original** (Anki's normal question) at the top, then a question + answer box pair for each question. With sharp questions, no box is shown until `ask` returns (only "Thinking of a sharp question…"). If `ask` fails, one box appears under the opened original. Without sharp questions (or for cloze), the original is shown with its box ready at once.
- **Enter** moves to the next box; Enter in the last box submits all. **Shift+Enter** inserts a newline. Enter with every box empty shows the plain answer, with no verdict.
- Anki shortcuts don't fire while typing. While `ask` is pending there is no box to type in, so Anki's own keys (e.g. Space to show the answer) still work.

**Answer side**
- A grade request returns `{"verdict": "wrong"|"partial"|"correct", "ease": 1-4, "feedback", "missed": [str], "per_question": [...]}`.
- The full card is sent again, so grading works even if `ask` failed or was skipped.
- The rubric is fixed: wrong 1, partial 2, correct 3, correct + complete and crisp 4. Missed bullets are ≤ 12 words, and contain only reference facts the user left out.
- The answer side shows a verdict badge, the user's answers, feedback, per-question marks and Missed bullets, all above the normal answer. The per-question marks are coloured ✓ green, ~ orange, ✗ red. Each `per_question` item also carries `parts`: the user's answer clipped into its claims (the user's own words, filler trimmed), each with a verdict and, when partial or wrong, a `why` (≤ 15 words: what's off and what's right). The verdict lists these claims as bullets under "You:" in place of the full answer, green / orange / red, with the why after an em dash. The prompt requires consistency: a question is correct only if none of its parts is partial or wrong, and the overall verdict follows the per-question ones. Without parts, the whole answer is shown: red when graded wrong and orange when partial (the overall verdict when there are no per-question marks). The card's own answer is shown in its normal colours. The recommended ease button is outlined; the user presses it (or another).

**Edit this note** (answer side, after grading)
- A text box above the verdict: "Ask AI to change this note". Enter sends the request. Anki's keys don't fire while typing; Esc leaves the box.
- It is a separate CLI backend (`grading.EDIT_SYSTEM_PROMPT`), started on first use and closed with the review session, so the tutor conversation stays clean. The prompt carries the note's raw fields, the questions and answers, the grade and the deck rules.
- The reply is `{"reply", "fields": {name: html}}`. Only existing fields that actually change are written; unknown field names are reported. The save is one `update_note` without an initiator, so the reviewer redraws the card with the new text. It is one undo step (Edit → Undo).
- The result line survives the redraw. A failed edit doesn't count toward the study failure policy.

**Missed section** (`missed_append`, default on)
- After each graded review, the card's Missed section is **replaced** with exactly one `<hr><b>Missed (YYYY-MM-DD)</b><ul>…</ul>` (or `…</b>: nothing`).
- It goes into the first existing field of `Back` → `Back Extra` → the note's last field.
- The tutor prompt treats it as past gaps, not required content.
- A write failure shows a red note; the review is unaffected.

**Formatting** (`style.md`, `grading.rich`)
- `style.md` is appended to every system prompt (tutor, note edit, Generate), so all providers follow one guide: plain text first; in short texts (questions, hints, notes, feedback, Missed) at most one `**bold**` key term; in note fields Anki HTML (`<b>`, `<i>`, lists for 3+ parallel items, tables for comparisons, `<code>`), no colour unless asked; math as LaTeX in `\( \)` / `\[ \]`, never `$`.
- Short texts are shown through `grading.rich`: HTML-escaped, then `**x**` → `<b>x</b>`. The same goes for Missed bullets saved into the note.
- Math: Anki's reviewer typesets each card with MathJax, which covers the verdict. Sharp questions and hints arrive later, so `setQuestions` runs `MathJax.typesetPromise` on them.
- Replies are JSON, so LaTeX needs doubled backslashes. `parse_json_reply` repairs the usual slip: invalid escapes such as `\(` or `\sqrt` are doubled and parsing retried, and control characters that single-backslash `\frac`, `\times`, `\beta` or `\right` decode to (form feed, tab, backspace, CR before a letter) are turned back into LaTeX. A single-backslash `\n…` command (`\neq`) can't be told apart from a newline, so it stays broken.

**Prompt context**: rendered question and answer as plain text (no images); the ask request gets the question only, grading gets both. Custom Generic Rules go in the system prompt; each card sends its own home deck's prompt chain (`card.odid or card.did`, root → leaf, inner wins). Priority, highest first: deck rules, Generic Rules, then the built-in tutor defaults and `style.md`; only the JSON reply format is fixed. The note-edit prompt gives deck rules the same top priority. Deck rules reach the question side only when Sharp questions is on for the deck: the switch is decided in code before any AI call, so with it off the AI sees the card (and its deck rules) only when grading.

## ⚙ Settings (`config_page.py`, `config_ops.py`)

A main-window state (`aiStudyConfig`, **← Back** → deck list).

- **Chat**: each message goes to a separate CLI call; the AI replies `{"reply", "changes"}`. `config_ops.apply_changes` validates each change: `set` known keys with type/range checks, `add_custom` / `remove_custom`, `set_deck_prompt` / `clear_deck_prompt`, `set_deck_ai` / `set_deck_sharp` (`on`: true / false / null = follow parent), `undo` (snapshot restore), `login` / `logout`. Saving uses `addonManager.writeConfig`.
- The log shows the latest 3 replies; rejected changes appear in red inside the reply. The Settings AI gets the real model in use, never lists or guesses model names, and points to the Model dropdown.
- **Configurations**:
  - Provider and Model rows: dropdowns. The model list is loaded live from the CLI and never stored.
  - Login state, timeouts, and the CLI version with **Update**.
  - **Missed append**: On/Off toggle. `config_ops.TOGGLES` is the single source for each toggle's label and help text. Clicks go through `apply_changes`. Each toggle has a CSS **?** help bubble.
  - Plain controls always work, even when the provider's AI is broken.
- **Custom Generic Rules**: numbered rules, applied to every card.
- **Deck Prompts**:
  - The real deck tree, with ● marking decks that have a prompt.
  - Selecting a deck shows its panel directly under it in the tree (a selected parent expands): its own prompt, the ones it inherits, and the deck toggles with which deck decides each.
  - Deck toggles (`config_ops.DECK_TOGGLES`): **AI Study** (`deck_ai`; off = plain reviewer for that deck's cards) and **Sharp questions** (`deck_sharp`), each `{deck_id: bool}`. The innermost deck on the path with a setting wins; none = on. Each panel On/Off button flips the selected deck's effective value. Setting a deck (button or chat) drops its subdecks' own settings, so they follow it at once. A subdeck set afterwards stays as an exception until one of its ancestors is set again. Updates keep the page's scroll position. A deck prompt can't switch them: the decision is made before any AI call, so the Settings AI uses `set_deck_sharp`. The old global `sharp_questions` key is dropped on the next settings change.
  - Stored as `deck_prompts: {deck_id: prompt}`, so prompts survive deck renames. Prompts and toggle settings of deleted decks are pruned on save.
  - Deck names resolve exact → case-insensitive → unique leaf name; anything else is rejected.
- Changes apply from the next review session. Unsent drafts and in-flight replies survive leaving the page (in memory until Anki restarts).

## ✨ Generate/Update Cards (`generate_page.py`, `generate_ops.py`, `generate_col.py`)

A main-window state (`aiStudyGenerate`). It works whether AI Study is on or off, with the same chat pattern as Settings.

- **References**:
  - Chosen with **Choose folder…** / **Choose file…** (native pickers opening on the Desktop) or cleared with **×**. The path box is read-only.
  - Must resolve to something strictly inside `~/Desktop`.
  - Text files only. Binary and non-UTF-8 files are listed as skipped. Hidden files, `.git`, `node_modules`, `__pycache__` and venvs are ignored.
  - Limits: ≤ 300 files and ≤ 150k characters per message; anything cut off is reported.
  - Re-read on every message.
- **Fresh CLI process per message**: references and cards would overflow one long conversation, so the last 3 exchanges are resent as context.
- **Updating existing cards**:
  - The AI may return `read_decks`. The add-on then loads those decks' notes (subdecks included, raw field HTML, ≤ 120k chars) and resends the request, for at most 2 rounds.
  - `update {note_id, fields}` stages a copy tagged `ai_generate_of_<nid>`; a second update edits that copy.
- **AI-GEN staging deck**:
  - A temporary top-level deck, created when first needed. Its subdecks mirror real deck paths.
  - New cards are Basic or Cloze. They may target any deck path, including a new top-level deck; only `AI-GEN` itself is never a target.
  - Staged cards carry the `ai_generate` tag. State lives in the collection, so staged cards survive restarts and can be edited in the Browser.
- **Approve → Submit**:
  - **Approve / Unapprove** (card, deck or all) toggles the `ai_generate_ok` tag. An AI edit of an approved card clears its approval, and the AI is told to leave approved cards alone unless asked.
  - **Submit N approved**:
    - Updates are written into the originals, keeping review history; if the original was deleted, the update is kept as a new card.
    - New cards move to their real deck, which is created if missing, with the tag removed.
    - Emptied AI-GEN decks are removed.
  - **Discard** deletes the card or deck immediately.
- **Show Original / Show Update** on UPDATE cards: client-side, and the choice survives redraws.
- **Undo**: every action, including each AI change batch, is one undo step (`add_custom_undo_entry` + `merge_undo_entries` in a `CollectionOp`). Actions use a few batched ops, because Anki keeps only ~30 undo steps. If a merge still fails, the saved changes are reported instead of an error.

## Errors, self-check, fixes (`health.py`, `fixes.py`)

A failure never blocks review: Space always works.

| Failure | Shown | Behaviour |
|---|---|---|
| CLI missing / not logged in / crash / other error | "AI error: <message> — open ⚙ Settings to fix it." | crashed process respawns on next call; 2nd failure → "AI unavailable: <message>", AI off until the reviewer is reopened |
| Usage limit | "Usage limit: <message>" | AI off until the reviewer is reopened |
| Timeout (`ask_timeout_s` 30, `grade_timeout_s` 60) | "AI timed out." | late reply dropped |
| Non-JSON reply | — | one retry with "JSON only", then error |
| Missed write fails | red note in verdict | review unaffected |
| Anki closes mid-request | — | process killed, late callbacks ignored |

- **Self-check** (`health.self_check`):
  - Runs when Settings opens and after update or rollback.
  - `session.startup_check` starts the real study command and stops before any answer, so a pass proves the CLI accepts every add-on flag. Claude: until its `init` event names the model. Codex: the command without `--json` until its header names the model, then the exact `--json` command until its first event.
  - A pass records `last_good[provider] = version` in `state.py` (the Roll back target).
- **Diagnosis**:
  - Reviewer errors are stored in `health.LAST_ERROR`.
  - "Usage limit" is decided by one rule, `session.error_kind`, which both the reviewer and Settings use.
  - The reviewer's failure policy is `health.study_failure` (pure, tested).
  - `health.classify` sorts them into incompatible | auth | limit | timeout | missing | other, which picks the fix buttons:
    - **Roll back to <last working>**
    - **Update**
    - **Log in**
    - **Allow more time** (×2, cap 600 s)
    - **Use <other provider>**
    - **Copy error report**
## Testing

- `pytest tests`: pure logic, plus `session.py` against `fake_claude.py` / `fake_codex.py`, which give no real AI calls and no plan usage. Covers lifecycle, queueing, stale drop, crash restart, timeout and bad JSON.
- `tests/test_generate_col.py` runs on a real temp collection with Anki's own Python and is skipped elsewhere.
- Manual acceptance in Anki: Basic card, cloze card, Space skip, Ctrl+Z, and no add-on CLI process left after leaving the reviewer.
