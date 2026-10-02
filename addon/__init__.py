"""AI Quizzer for Anki — rewritten questions, free-text answer, AI grade, native Again/Hard/Good/Easy."""

try:
    from aqt import mw
except ImportError:  # imported outside Anki (unit tests)
    mw = None

if mw is not None:
    from . import main

    main.setup()
