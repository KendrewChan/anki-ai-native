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

## Generate/Update Cards (✨ Generate/Update Cards)

Next to ⚙ Settings. Optionally pick a **reference** — a file or folder on your **Desktop** (Choose folder… / Choose file…; text files only, e.g. .txt, .md, code). Then say what you want: "10 cards from these notes into Biology::Ch3", "improve my Chem cards using this file", "make card 3 shorter".

- New and updated cards wait in a temporary deck, **AI-GEN**, whose subdecks mirror where they'll go (`AI-GEN::Biology::Ch3`, or `AI-GEN::Physics` for a brand-new deck). Nothing in your real decks changes yet — you can study or edit them there.
- On an UPDATE card, **Show original** shows the card as it is now (click **Show update** to go back).
- **Approve** cards (each card, a whole deck, or all) — they stay in AI-GEN with a ✓ so you can keep generating; **Unapprove** changes your mind, **Discard** throws a card away.
- **Submit** moves only the approved cards: updates are written into the original cards (review history kept), new cards go into their real decks, created if needed. Unapproved cards stay in AI-GEN. AI-GEN disappears once it's empty. Everything can be undone with Edit → Undo.

## When something breaks

Open **⚙ Settings**: it checks your AI CLI on open. If something's wrong you get a plain explanation with buttons — **Update**, **Roll back** to the last version that worked, **Log in**, **Allow more time**, switch provider, or **Copy error report** to send to the author. For problems in the add-on itself it can offer **Try AI repair**: another AI proposes a small fix, you approve it, and it's checked and undone automatically if it doesn't work (**Revert AI repair** undoes it later).

## Notes

- Each review session keeps one `claude` process running and uses your Claude plan's usage.
- Windows and Linux are untested. If the CLI isn't found, tell Settings its path ("claude path is /path/to/claude").

## Development

- `addon/` is the add-on; symlink it into `addons21/anki_ai` to develop live.
- Tests: `pytest tests` (no Anki needed; `session.py` runs against `tests/fake_claude.py`). `tests/test_generate_col.py` needs Anki's Python (see its docstring) and is skipped otherwise.
- Design: `docs/spec.md`.
