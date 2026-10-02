# anki-ai-native

An Anki add-on that turns Claude Code (or Codex) into a study tutor, right inside Anki.

- **AI Study** — the AI asks you questions about each card, you type answers, it grades them and suggests Again / Hard / Good / Easy. You still press the button, so Anki's scheduling is untouched.
- **⚙ Settings** — change behaviour in plain words ("use opus", "grade more strictly").
- **✨ Generate/Update Cards** — make or improve cards from your notes on the Desktop. Cards wait in an `AI-GEN` deck until you approve and submit them.

Uses your own logged-in `claude` or `codex` CLI; no API keys.

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
