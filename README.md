# AI Study for Anki (Claude Code)

Study in the Anki reviewer with Claude as your tutor: it turns each card into sharp questions, you type free-text answers, it grades them and recommends a button — you still press Anki's own Again / Hard / Good / Easy, so scheduling is untouched.

## Requirements

- Anki desktop (built and tested on 26.9.2, macOS).
- One AI CLI, installed and logged in with **your own** subscription — the add-on runs it locally and never sees your credentials:
  - [Claude Code](https://claude.com/claude-code) (`claude auth login`) — default, fastest (keeps one process open per study session), or
  - [Codex CLI](https://github.com/openai/codex) (`codex login`, ChatGPT plan) — ~6 s per card.

## Install

1. Get `anki_ai.ankiaddon` (build it with `python3 scripts/package.py` → `dist/`).
2. Anki → **Tools → Add-ons → Install from file…** → pick the file → restart Anki.

## Use

- Under the deck list (and under **Study Now**): **AI Study: OFF · ⚙ Settings**. Click to turn it on — it is off every time Anki starts. Also in **Tools → AI Study mode**.
- While reviewing: type answers (Enter = next box / submit, Shift+Enter = new line, Enter with all boxes empty = just show the answer). **Show original** reveals the card's real front.
- The verdict shows above the answer; the recommended button is outlined. The card's Back keeps one **Missed (date)** section with your latest misses, replaced each review (turn off in settings).

## Settings (⚙ Settings)

Type what you want in plain words — "use opus", "give me 90 seconds to answer", "grade more strictly", "for this deck, ask for code", "undo that".

- **Configurations** — provider (Claude Code / Codex; "use codex"), model ("default" = the provider's), timeouts, missed-append, CLI path (auto-detected), login.
- **Custom Generic Rules** — apply to every card.
- **Deck Prompts** — one prompt per deck; subdecks inherit their parents'. Click a deck to see what applies to it.

## Notes

- Each review session keeps one `claude` process running and uses your Claude plan's usage.
- Windows and Linux are untested. If the CLI isn't found, tell Settings its path ("claude path is /path/to/claude").

## Development

- `addon/` is the add-on; symlink it into `addons21/anki_ai` to develop live.
- Tests: `pytest tests` (no Anki needed; `session.py` runs against `tests/fake_claude.py`).
- Design: `docs/spec.md`.
