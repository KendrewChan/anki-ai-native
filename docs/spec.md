# Anki AI Study add-on — spec

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
| `config_page.py`, `generate_page.py` | ⚙ Settings and ✨ Generate/Update Cards pages | yes |
| `session.py` | Provider CLIs: find, isolate, run, parse; login; model lookup | no |
| `grading.py` | Tutor prompts, reply parsing, Missed HTML | no |
| `config_ops.py` | Settings chat prompt, validated config changes, toggles | no |
| `generate_ops.py` | Generate prompt, reference reading, reply validation | no |
| `generate_col.py` | AI-GEN staging ops on a `Collection` passed in | no |
| `health.py`, `repair.py` | Self-check + error classification; AI repair validate/apply/restore | no |
| `fixes.py` | Fix buttons (update, roll back, log in, repair) | yes |
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
- **Models**: `models: {claude, codex}`; `""` = the CLI's default. Settings always shows the real model id, read from the CLI's own output (Claude's stream-json `init` event, Codex's stderr `model:` header), cached in `resolved_models`. A legacy single `model` key is read as the active provider's model and migrated on the next save.
- **Login**: Claude `claude auth status|login|logout`; Codex `codex login status` / `codex login` / `codex logout`.

## Reviewer flow (`main.py`, `ui.py`, `grading.py`)

Only active while **AI Study** is ON. The ON/OFF link is on the home screen, on the deck overview and in **Tools → AI Study mode**. It is off at every Anki start. Off means the plain reviewer runs and no AI process starts; turning it off kills the session. The flow is display-only, through `gui_hooks.card_will_show`: nothing is written to the card except the Missed section.

**Question side**
- With `sharp_questions` on (default), an ask request returns `{"questions": [1–4]}`, one per distinct point the card bundles. Otherwise the card's own question is used.
- Cloze cards always use their own blanked question.
- Layout: a collapsed **Show original** (Anki's normal question) at the top, then a question + answer box pair for each question.
- **Enter** moves to the next box; Enter in the last box submits all. **Shift+Enter** inserts a newline. Enter with every box empty shows the plain answer, with no verdict.
- Anki shortcuts don't fire while typing. Submitting before `ask` returns is allowed (it queues).

**Answer side**
- A grade request returns `{"verdict": "wrong"|"partial"|"correct", "ease": 1-4, "feedback", "missed": [str], "per_question": [...]}`.
- The full card is sent again, so grading works even if `ask` failed or was skipped.
- The rubric is fixed: wrong 1, partial 2, correct 3, correct + complete and crisp 4. Missed bullets are ≤ 12 words, and contain only reference facts the user left out.
- The answer side shows a verdict badge, the user's answers, feedback, per-question marks and Missed bullets, all above the normal answer. The recommended ease button is outlined; the user presses it (or another).

**Missed section** (`missed_append`, default on)
- After each graded review, the card's Missed section is **replaced** with exactly one `<hr><b>Missed (YYYY-MM-DD)</b><ul>…</ul>` (or `…</b>: nothing`).
- It goes into the first existing field of `Back` → `Back Extra` → the note's last field.
- The tutor prompt treats it as past gaps, not required content.
- A write failure shows a red note; the review is unaffected.

**Prompt context**: rendered question and answer as plain text (no images). Custom Generic Rules go in the system prompt; each card sends its own home deck's prompt chain (`card.odid or card.did`, root → leaf, inner wins).

## ⚙ Settings (`config_page.py`, `config_ops.py`)

A main-window state (`aiStudyConfig`, **← Back** → deck list).

- **Chat**: each message goes to a separate CLI call; the AI replies `{"reply", "changes"}`. `config_ops.apply_changes` validates each change: `set` known keys with type/range checks, `add_custom` / `remove_custom`, `set_deck_prompt` / `clear_deck_prompt`, `undo` (snapshot restore), `login` / `logout`. Saving uses `addonManager.writeConfig`.
- The log shows the latest 3 replies; rejected changes appear in red inside the reply. The Settings AI gets the real model in use, never lists or guesses model names, and points to the Model dropdown.
- **Configurations**:
  - Provider and Model rows: dropdowns. The model list is loaded live from the CLI and never stored.
  - Login state, timeouts, and the CLI version with **Update**.
  - **Sharp questions** and **Missed append**: On/Off toggles. `config_ops.TOGGLES` is the single source for each toggle's label and help text. Clicks go through `apply_changes`. Each toggle has a CSS **?** help bubble.
  - Plain controls always work, even when the provider's AI is broken.
- **Custom Generic Rules**: numbered rules, applied to every card.
- **Deck Prompts**:
  - The real deck tree, with ● marking decks that have a prompt.
  - Selecting a deck shows its own prompt and the ones it inherits.
  - Stored as `deck_prompts: {deck_id: prompt}`, so prompts survive deck renames. Prompts of deleted decks are pruned on save.
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

## Errors, self-check, repair (`health.py`, `fixes.py`, `repair.py`)

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
  - The repair flow runs the same check against the patched code.
  - A pass records `last_good[provider] = version`.
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
- **Try AI repair**:
  - Offered for incompatible/other failures, and it runs on a *working* provider.
  - The AI returns find/replace edits to `session.py` / `health.py` only. `repair.validate` requires each `old` text to occur exactly once and allows no no-ops.
  - **Apply** backs up to `.repair_backup/<ts>`, then self-checks the patched code. If the self-check fails, the backup is restored automatically.
  - **Revert AI repair** stays available while a backup exists. Restart Anki to run the repaired code.

## Testing

- `pytest tests`: pure logic, plus `session.py` against `fake_claude.py` / `fake_codex.py`, which give no real AI calls and no plan usage. Covers lifecycle, queueing, stale drop, crash restart, timeout and bad JSON.
- `tests/test_generate_col.py` runs on a real temp collection with Anki's own Python and is skipped elsewhere.
- Manual acceptance in Anki: Basic card, cloze card, Space skip, Ctrl+Z, and no add-on CLI process left after leaving the reviewer.
