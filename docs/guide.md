# AI Quizzer for Anki — full guide

Study in the Anki reviewer with an AI tutor (Claude Code or Codex): it turns each card into rewritten questions, you type free-text answers, it grades them and recommends a button — you still press Anki's own Again / Hard / Good / Easy, so scheduling is untouched.

## Requirements

- Anki desktop (built and tested on 26.9.2, macOS).
- One AI CLI, installed and logged in with **your own** subscription — the add-on runs it locally and never sees your credentials:
  - [Claude Code](https://claude.com/claude-code) (`claude auth login`) — default, fastest (keeps one process open per study session), or
  - [Codex CLI](https://github.com/openai/codex) (`codex login`, ChatGPT plan) — ~6 s per card.

## Install

1. Get `anki_ai.ankiaddon` (build it with `python3 scripts/package.py` → `dist/`).
2. Anki → **Tools → Add-ons → Install from file…** → pick the file → restart Anki.

## Use

- Under the deck list (and under **Study Now**): **AI Study: OFF · ⚙ Settings · ✨ Generate/Update Cards**. Click to turn it on or off — Anki remembers your choice next time it starts. Also in **Tools → AI Study mode**.
- While reviewing: type answers (Enter = next box / submit, Shift+Enter = new line, Enter with all boxes empty = just show the answer). **Show original** reveals the card's real front. Rewrite question is on by default and the answer boxes appear once they arrive; hover a **?** for a hint. A question with several parts lists them as 3.1, 3.2, … with a hint on each part. Formulas show as rendered math, and the AI bolds at most one key term. To answer a deck's cards as written (faster: one AI call per card), tell Settings "don't rewrite questions for <deck>"; subdecks follow.
- The verdict shows right below the front of the card (already in view when the answer appears), above the card's answer; the recommended button is outlined. Your answer is broken into bullet points: green when right, orange when partly right, red when wrong, each orange or red one with a short reason; the card's own answer keeps its normal colours. The card's Back keeps one **Missed (date)** section with your latest misses, replaced each review (**Missed append** in settings).
- **Highlight to ask:** while AI Study is on, highlight any text on the card and click the blue **AI** bubble that appears at its top-right. Type your question and press Enter; the answer shows right there. On the front it helps you understand the question without giving away the answer (e.g. "what does this term mean?"). On the back you can also ask it to change the note (e.g. "reword this", "add an example after this"). A change redraws the card and its result shows at the bottom; Edit → Undo reverts it.

## Settings (⚙ Settings)

Type what you want in plain words — "use opus", "give me 90 seconds to answer", "grade more strictly", "for this deck, ask for code", "undo that".

- **Configurations** — provider (Claude Code / Codex; "use codex"), model ("default" = the provider's), timeouts, **Missed append** On/Off button (hover the **?** for what they do), CLI path (auto-detected), login.
- **Custom Generic Rules** — apply to every card.
- **Deck Settings** — click a deck and the chat box starts with `Deck prompt for "<deck>": `, so you only type the prompt and press Enter. Click it again to close it and clear the prefix. One prompt per deck; subdecks inherit their parents'. Each deck's panel opens right under it and has **AI Study** and **Rewrite question** On/Off buttons (or say "no rewritten questions for this deck"); AI Study off = that deck reviews normally, without AI. Switching a deck makes all its subdecks follow; switch a subdeck afterwards to make an exception, which lasts until a parent is switched again. Click a deck to see what applies to it. A deck prompt can reshape the questions, e.g. "show the question as written, then one box each for Requirements, APIs, Data Store" (up to 8). This works even with **Rewrite question** off. Off then means the AI keeps the card's question unless the deck prompt says otherwise.

## Generate/Update Cards (✨ Generate/Update Cards)

Next to ⚙ Settings. Optionally pick a **reference** — a file or folder on your **Desktop** (Choose folder… / Choose file…; text files only, e.g. .txt, .md, code). Then say what you want: "10 cards from these notes into Biology::Ch3", "improve my Chem cards using this file", "make card 3 shorter".

- New and updated cards wait in a temporary deck, **AI-GEN**, whose subdecks mirror where they'll go (`AI-GEN::Biology::Ch3`, or `AI-GEN::Physics` for a brand-new deck). Nothing in your real decks changes yet — you can study or edit them there.
- On an UPDATE card, **Show Original** shows the card as it is now, fully expanded (click **Show Update** to go back).
- **Approve** cards (each card, a whole deck, or all) — they stay in AI-GEN with a ✓ so you can keep generating; **Unapprove** changes your mind, **Discard** throws a card away.
- **Submit** moves only the approved cards: updates are written into the original cards (review history kept), new cards go into their real decks, created if needed. Unapproved cards stay in AI-GEN. AI-GEN disappears once it's empty. Everything can be undone with Edit → Undo.

## When something breaks

Open **⚙ Settings**: it checks your AI CLI on open. If something's wrong you get a plain explanation with buttons — **Update**, **Roll back** to the last version that worked, **Log in**, **Allow more time**, switch provider, or **Copy error report** to send to the author.

## Notes

- Studying uses your own plan's usage (Claude or ChatGPT). Claude keeps one `claude` process open per review session; Codex starts one per message.
- Windows and Linux are untested. If the CLI isn't found, tell Settings its path ("claude path is /path/to/claude", or the same for codex).

## Development

- `addon/` is the add-on; symlink it into `addons21/anki_ai` to develop live.
- Tests: `pytest tests` (no Anki needed; `session.py` runs against `tests/fake_claude.py`). `tests/test_generate_col.py` needs Anki's Python (see its docstring) and is skipped otherwise.
- Design: `spec.md`.
