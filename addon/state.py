"""Facts the add-on learns about the CLIs, and UI state it remembers — not user settings, so never in the config
or its undo history.

- "models": "provider:configured" -> the real model id the CLI reported (shown instantly after a restart)
- "last_good": provider -> last CLI version that passed the self-check (the Roll back target)
- "ui": "ai_study" -> whether AI Study mode was ON when last switched (restored at Anki start)

Stored in user_files/state.json, which Anki keeps when the add-on is updated. No Anki imports.
"""

import json
import os
import threading

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_files", "state.json")

_lock = threading.Lock()
_data = None  # loaded on first use


def get(section: str, key: str):
    with _lock:
        return _load().get(section, {}).get(key)


def put(section: str, key: str, value):
    """Set one value; writes the file only when it changed. Safe from any thread."""
    with _lock:
        data = _load()
        if data.get(section, {}).get(key) == value:
            return
        data.setdefault(section, {})[key] = value
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, PATH)


def reset(path: str):
    """Point at another file and forget what was loaded (tests)."""
    global PATH, _data
    with _lock:
        PATH, _data = path, None


def _load() -> dict:
    global _data
    if _data is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _data = json.load(f)
        except (OSError, ValueError):  # first run, or a damaged file: start over
            _data = {}
    return _data
