# anki-ai-native

An Anki add-on that turns Claude Code (or Codex) into a study tutor, right inside Anki.

- **AI Study** — the AI asks you questions about each card, you type answers, it grades them and suggests Again / Hard / Good / Easy. You still press the button, so Anki's scheduling is untouched.
- **⚙ Settings** — change behaviour in plain words ("use opus", "grade more strictly").
- **✨ Generate/Update Cards** — make or improve cards from your notes on the Desktop. Cards wait in an `AI-GEN` deck until you approve and submit them.

Uses your own logged-in `claude` or `codex` CLI; no API keys.

## Screenshots

**Home** — the add-on's links sit under the deck list.

<img src="docs/images/home.png" alt="Anki deck list with AI Study, Settings and Generate/Update Cards links" width="600">

**AI Study** — while reviewing, the card becomes sharp questions, each with its own answer box. **Show original** reveals the real card.

<img src="docs/images/review.png" alt="Reviewing a card: four sharp questions with answer boxes" width="600">

**⚙ Settings** — tell the AI what to change; current configuration, rules and deck prompts below.

<img src="docs/images/settings.png" alt="AI Study settings page" width="600">

**✨ Generate/Update Cards** — new and updated cards wait in AI-GEN for you to approve, then submit.

<img src="docs/images/generate.png" alt="Generate/Update Cards page with staged cards in AI-GEN" width="600">

## Install

```bash
python3 scripts/package.py        # builds dist/anki_ai.ankiaddon
```

Anki → **Tools → Add-ons → Install from file…** → pick the file → restart Anki.

For development, symlink `addon/` into Anki's `addons21/anki_ai` instead.

## Test

```bash
pytest tests
```

## More

- [docs/guide.md](docs/guide.md) — full user guide
- [docs/spec.md](docs/spec.md) — design and decisions
