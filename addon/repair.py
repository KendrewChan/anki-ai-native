"""AI repair of the add-on's own code — offered only when something breaks, applied only on approval.

The AI never gets write access: it returns find/replace edits as text; this module validates them,
backs up the files, applies them, and can restore the backup. No Anki imports.
"""

import importlib.util
import os
import shutil
import sys
import time

from .grading import parse_json_reply

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(ADDON_DIR, ".repair_backup")
REPAIRABLE = ("session.py", "health.py")  # where the CLI integration lives

REPAIR_SYSTEM_PROMPT = """You repair an Anki add-on that drives an AI command-line tool (Claude Code or Codex CLI). A CLI update or change broke it. You get the error, the CLI's version and --help output, and the add-on's CLI integration source files.

Propose the SMALLEST change that makes the add-on work with this CLI version again. Typical cause: a renamed or removed command-line flag.

Hard rules:
- Keep every safety restriction: no tools/shell, read-only sandbox, no web search, no user config, no plugins. If a safety flag was renamed, use the new name; never just delete it. If you cannot keep a restriction, propose no edits.
- Only edit these files: """ + ", ".join(REPAIRABLE) + """.
- Each edit replaces an exact snippet that appears exactly once in the file.

Reply with JSON only, no code fences:
{"summary": "<one or two plain sentences for a non-technical user>", "edits": [{"file": "session.py", "old": "<exact existing text>", "new": "<replacement>"}]}
If you can't find a safe fix: {"summary": "<why>", "edits": []}"""


def repair_prompt(error: str, provider: str, version: str, help_text: str, root: str = ADDON_DIR) -> str:
    files = "\n\n".join(
        f"=== {name} ===\n{open(os.path.join(root, name), encoding='utf-8').read()}" for name in REPAIRABLE
    )
    return (f"Error:\n{error}\n\nCLI: {provider} {version}\n\n`--help` output:\n{help_text[-6000:]}\n\n"
            f"Add-on source:\n{files}")


def parse_repair(text: str) -> dict:
    obj = parse_json_reply(text)
    edits = obj.get("edits") or []
    if not isinstance(edits, list):
        raise ValueError("'edits' is not a list")
    return {"summary": str(obj.get("summary", "")).strip(), "edits": [e for e in edits if isinstance(e, dict)]}


def validate(edits: list, root: str = ADDON_DIR) -> list:
    """Raise ValueError unless every edit targets an allowed file and its `old` text occurs exactly once
    (after the earlier edits in the list). Returns the edits."""
    if not edits:
        raise ValueError("no changes proposed")
    staged = {}
    for e in edits:
        name = str(e.get("file", ""))
        if name not in REPAIRABLE or os.path.basename(name) != name:
            raise ValueError(f"edit outside the allowed files: {name!r}")
        old, new = str(e.get("old", "")), str(e.get("new", ""))
        if not old or old == new:
            raise ValueError(f"empty or no-op edit in {name}")
        text = staged.get(name)
        if text is None:
            text = open(os.path.join(root, name), encoding="utf-8").read()
        if text.count(old) != 1:
            raise ValueError(f"the text to replace in {name} was found {text.count(old)} times, expected once")
        staged[name] = text.replace(old, new)
    return edits


def describe(edits: list) -> str:
    """Readable before/after for the "Show changes" view."""
    return "\n\n".join(f"{e['file']}:\n- {e['old'].strip()}\n+ {e['new'].strip()}" for e in edits)


def apply(edits: list, root: str = ADDON_DIR, backup_root: str = None) -> str:
    """Back up the touched files, then apply. Returns the backup directory."""
    validate(edits, root)
    backup = os.path.join(backup_root or os.path.join(root, ".repair_backup"), time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(backup, exist_ok=True)
    for name in {e["file"] for e in edits}:
        shutil.copy2(os.path.join(root, name), os.path.join(backup, name))
    for e in edits:
        path = os.path.join(root, e["file"])
        text = open(path, encoding="utf-8").read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(e["old"], e["new"]))
    return backup


def latest_backup(root: str = ADDON_DIR, backup_root: str = None):
    base = backup_root or os.path.join(root, ".repair_backup")
    if not os.path.isdir(base):
        return None
    dirs = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)))
    return os.path.join(base, dirs[-1]) if dirs else None


def revert(backup: str, root: str = ADDON_DIR):
    """Restore the files saved in `backup`, then drop that backup."""
    for name in os.listdir(backup):
        if name in REPAIRABLE:
            shutil.copy2(os.path.join(backup, name), os.path.join(root, name))
    shutil.rmtree(backup, ignore_errors=True)


def load_patched_session(root: str = ADDON_DIR):
    """Import session.py from disk under a throwaway name, so the self-check runs the patched code
    without restarting Anki (relative imports resolve against the already-loaded package)."""
    package = __name__.rsplit(".", 1)[0]
    name = f"{package}._session_repair_check"
    spec = importlib.util.spec_from_file_location(name, os.path.join(root, "session.py"))
    module = importlib.util.module_from_spec(spec)
    module.__package__ = package
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(name, None)
    return module
