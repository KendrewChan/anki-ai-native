---
name: anki-update-addon
description: Use when changing, fixing, extending, testing, packaging, or releasing the "AI Study" Anki add-on in this repo (anki_ai, AI study mode in the Anki reviewer, Claude Code / Codex provider, settings page, deck prompts, Generate/Update Cards, self-check/repair) — any edit under addon/ or a request to "update the anki plugin/add-on".
---

# Anki Update Add-on

## Overview

This repo is the add-on. For development, `addon/` is **symlinked** into Anki as `~/Library/Application Support/Anki2/addons21/anki_ai`, so every edit lands in the user's real Anki the next time it starts. Work against the spec, keep logic testable without Anki, run the fake-CLI tests, then commit with a descriptive message.

## Layout

| Path | Role |
|---|---|
| `docs/spec.md` | Design + recorded implementation decisions — read first, append decisions after |
| `addon/__init__.py` | Guards `from aqt import mw` so modules import outside Anki |
| `addon/main.py`, `ui.py`, `config_page.py`, `generate_page.py` | Anki/Qt-facing: hooks, reviewer UI, ⚙ Settings page, ✨ Generate/Update Cards page |
| `addon/session.py` | Long-running `claude` (stream-json) / stateless `codex exec` provider sessions |
| `addon/grading.py`, `config_ops.py`, `generate_ops.py` | Prompt building, grading, plain-English settings ops, Generate planning (no Anki imports) |
| `addon/generate_col.py` | Generate collection ops on the AI-GEN staging deck (takes a `Collection`, no aqt) |
| `addon/health.py`, `fixes.py`, `repair.py` | CLI version/self-check/update/rollback, fix buttons, opt-in AI repair |
| `addon/config.json` | Shipped defaults. `addon/meta.json` = **user's live settings** (gitignored) |
| `tests/` | pytest; `fake_claude.py` / `fake_codex.py` stand in for real CLIs |
| `scripts/package.py` | Builds `dist/anki_ai.ankiaddon` (skips meta.json, caches, `.repair_backup`) |

## Workflow

1. **Orient**: `git status` (another session may be editing, so don't clobber its uncommitted work). Read `docs/spec.md` and the modules you'll touch.
2. **Confirm Anki APIs before using them.** Anki is compiled, so grep the bytecode:
   ```bash
   cd /Applications/Anki.app/Contents/Resources/app_packages
   for h in reviewer_did_show_question webview_did_receive_js_message; do printf "%s: " $h; grep -c -a "$h" _aqt/hooks.pyc; done
   strings aqt/reviewer.pyc | grep -E "_showAnswer|_bottomHTML" | sort -u
   ```
   Built/tested on Anki 26.9.2 (macOS).
3. **Implement.** Keep non-Qt logic in Anki-free modules with tests. New provider/CLI behaviour gets a fake-CLI test (no real AI calls, no plan usage). Collection ops are batched (Anki keeps only ~30 undo steps).
4. **Verify** (from the repo root):
   ```bash
   uvx --native-tls pytest -q -p no:cacheprovider tests   # python3 -m pytest: pytest isn't installed
   python3 -m py_compile addon/*.py                        # catches syntax errors in Anki-only modules
   ANKI_PY=~/Library/Application\ Support/AnkiProgramFiles/.venv/bin/python3
   uvx --native-tls --python "$ANKI_PY" pytest -q -p no:cacheprovider tests/test_generate_col.py  # real collection
   ```
5. **Package check** (when packaging, imports, or CLI detection changed):
   ```bash
   python3 scripts/package.py
   D=<scratchpad>/inst; rm -rf $D; mkdir -p $D/anki_ai
   python3 -c "import zipfile;zipfile.ZipFile('dist/anki_ai.ankiaddon').extractall('$D/anki_ai')"
   cd $D && env -i PATH=/usr/bin:/bin HOME=$HOME python3 -c "import anki_ai, anki_ai.session as s; print(s.find_claude(''))"
   ```
   The `env -i` PATH mimics Anki launched from the Dock (no shell PATH). The CLI must still be found.
6. **Record**: append decisions to `docs/spec.md`; update `docs/guide.md` (and `README.md` if the summary changes) for anything user-visible.
7. **Commit + push**: `git add -A && git commit -F <msgfile>` (subject: what changed), then `git push`. This repo is **public**: no personal paths, deck names, emails, or secrets in code, docs, tests, or commit messages.
8. **Hand off**: Anki loads add-ons **only at startup**. Tell the user to restart Anki and name exactly what to click to see the change. Don't quit Anki yourself, because they may be mid-review. For live poking: Debug Console `Ctrl+Shift+;`.

## Common Mistakes

| Mistake | Fix |
|---|---|
| `rm addon/meta.json` / overwriting it (e.g. to test packaging) | Never. It's the user's live settings via the symlink. `package.py` already excludes it |
| Importing `aqt` at module top in a logic module | Breaks tests. Only `main.py`/UI modules touch `aqt` |
| Guessing hook/method names from docs of another Anki version | Grep the installed `.pyc` (step 2) |
| Hard-coding model name lists | Models come live from the CLI (dropdown); don't maintain a list |
| Claiming "works in Anki" after tests pass | Tests use fake CLIs. Say it's unverified in Anki until the user restarts and confirms |
| Committing `dist/`, `meta.json`, `.repair_backup/` | All gitignored; check `git status` before committing |
| Personal info in a commit (real deck names, `/Users/<name>` paths) | Use generic examples; the repo is public |
