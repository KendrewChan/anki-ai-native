"""Generate page logic: reference files, AI prompt, reply parsing, validated changes. No Anki imports — unit-testable."""

import json
import os
from pathlib import Path

from .config_ops import _resolve_deck
from .grading import parse_json_reply

TEMP_DECK = "AI Generate"
MAX_REF_CHARS = 150_000  # all reference text sent per message
MAX_FILES = 300
MAX_DECK_CHARS = 120_000  # existing cards sent per message
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

GENERATE_SYSTEM_PROMPT = """You make Anki flashcards for the user from their reference files and requests, and improve their existing cards.

Everything you create or update is staged in a temporary deck "AI Generate" whose subdecks mirror the real decks. The user looks at the staged cards, then clicks Accept (updates are written into the original cards, new cards move to their real deck) or Discard. You never change real cards directly.

Each message gives you: the deck list, the reference files (may be empty), cards of decks you asked to read, the cards currently staged, the recent conversation, then the user's request.

Reply with JSON only, no code fences:
{"reply": "<one or two short sentences: what you staged, or a question>", "read_decks": ["<full deck name>", ...], "changes": [<change>, ...]}

read_decks: decks whose existing cards you need to see (to update them, or to avoid duplicates). When the user asks to update/improve/fix cards, or the references clearly belong to an existing deck, and that deck's cards are not shown yet, return read_decks with "changes": [] — the same request comes back with those cards. Reading a deck includes its subdecks. Otherwise return "read_decks": [].

A change is one of:
{"add": {"deck": "<real deck full name>", "type": "basic", "front": "...", "back": "..."}}
{"add": {"deck": "<real deck full name>", "type": "cloze", "text": "... {{c1::hidden part}} ...", "extra": "..."}}
{"update": {"note_id": <id of a card under Existing cards>, "fields": {"<field name>": "<whole new field content>"}}}
{"edit": {"staged": <staged card number>, "fields": {"<field name>": "<whole new field content>"}}}
{"remove": <staged card number>}

Rules:
- deck: an existing deck, or a new subdeck under an existing top-level deck that follows that deck's structure (e.g. "Biology::Ch4" next to "Biology::Ch3"). Never a new top-level deck, never "AI Generate".
- One fact per card; short, specific fronts; answers as short as possible. Use cloze for definitions, lists and sentences where a key term can be blanked.
- Field content is Anki HTML: <br>, <b>, <i>, <ul><li>, <code>. No Markdown.
- When references are given, base cards on them; don't invent facts they don't contain unless asked. Don't duplicate existing or staged cards.
- update/edit: use the card's own field names, include only fields you change, give their whole new content. Keep any "Missed (date)" section in a field exactly as it is.
- To change a staged card use edit/remove, not a new add.
- If the request is unclear, ask a short question in "reply" with no changes."""


# --- reference files ---

def desktop() -> Path:
    return Path.home() / "Desktop"


def check_reference(path: str, root: Path = None) -> Path:
    """The resolved path if it is a file or folder inside the Desktop (symlinks and .. resolved), else ValueError."""
    root = (root or desktop()).resolve()
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("no reference chosen")
    p = Path(os.path.expanduser(raw))
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if p == root or not p.is_relative_to(root):
        raise ValueError("pick a file or folder inside your Desktop folder")
    if not p.exists():
        raise ValueError(f"{raw} doesn't exist")
    return p


def _read_text(path: Path, limit: int):
    """File text (utf-8), or None when it isn't a text file."""
    try:
        with open(path, "rb") as f:
            data = f.read(limit * 4 + 4)
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        if e.start >= len(data) - 4:  # cut mid-character by the read limit
            return data[:e.start].decode("utf-8")
        return None


def read_references(path: str, root: Path = None) -> dict:
    """{"path", "files": [(relative name, text)], "skipped": [name], "truncated": bool}. Text files only."""
    p = check_reference(path, root)
    if p.is_file():
        candidates, base = [p], p.parent
    else:
        candidates, base = [], p
        for dirpath, dirnames, filenames in os.walk(p):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS)
            candidates += [Path(dirpath) / f for f in sorted(filenames) if not f.startswith(".")]
    files, skipped, used, truncated = [], [], 0, False
    for f in candidates:
        name = str(f.relative_to(base))
        if len(files) >= MAX_FILES or used >= MAX_REF_CHARS:
            truncated = True
            break
        text = _read_text(f, MAX_REF_CHARS - used)
        if text is None:
            skipped.append(name)
            continue
        if used + len(text) > MAX_REF_CHARS:
            text, truncated = text[:MAX_REF_CHARS - used], True
        files.append((name, text))
        used += len(text)
    return {"path": str(p), "files": files, "skipped": skipped, "truncated": truncated}


def ref_summary(refs: dict) -> str:
    n = len(refs["files"])
    chars = sum(len(t) for _n, t in refs["files"])
    out = f"{n} text file{'s' if n != 1 else ''} ({chars // 1000 or chars and 1}k characters)"
    if refs["skipped"]:
        shown = ", ".join(refs["skipped"][:3]) + (" …" if len(refs["skipped"]) > 3 else "")
        out += f" · skipped {len(refs['skipped'])} non-text: {shown}"
    if refs["truncated"]:
        out += " · too much text, the rest is cut off"
    return out


# --- prompt + reply ---

def generate_prompt(message: str, decks: list, refs: dict = None, existing: dict = None, staged: list = None,
                    history: list = None) -> str:
    """existing: deck name -> [note dict]; staged: [note dict + "deck" (real) + "of"]; history: [(you, ai)].

    A note dict is {"id", "type", "deck", "fields": {name: html}}.
    """
    parts = ["Decks:\n" + ("\n".join(sorted(d for d in decks if not _is_temp(d))) or "(none)")]
    if refs and refs["files"]:
        body = "\n\n".join(f"=== {n} ===\n{t}" for n, t in refs["files"])
        parts.append(f"Reference files ({refs['path']}):\n{body}")
    else:
        parts.append("Reference files: (none)")
    if existing:
        out, used = [], 0
        for name, notes in existing.items():
            out.append(f"--- {name} ({len(notes)} cards) ---")
            for n in notes:
                line = json.dumps({"note_id": n["id"], "type": n["type"], "deck": n["deck"], "fields": n["fields"]},
                                  ensure_ascii=False)
                if used + len(line) > MAX_DECK_CHARS:
                    out.append("(more cards not shown — too many)")
                    break
                out.append(line)
                used += len(line)
        parts.append("Existing cards:\n" + "\n".join(out))
    if staged:
        lines = [json.dumps({"staged": i, "kind": f"update of note {s['of']}" if s.get("of") else "new",
                             "deck": s["deck"], "type": s["type"], "fields": s["fields"]}, ensure_ascii=False)
                 for i, s in enumerate(staged, 1)]
        parts.append("Staged cards (in AI Generate):\n" + "\n".join(lines))
    else:
        parts.append("Staged cards: (none)")
    if history:
        parts.append("Recent conversation:\n" + "\n".join(f"User: {u}\nYou: {a}" for u, a in history))
    parts.append(f"User: {message}")
    return "\n\n".join(parts)


def parse_generate_reply(text: str) -> dict:
    obj = parse_json_reply(text)
    changes = obj.get("changes") or []
    reads = obj.get("read_decks") or []
    if not isinstance(changes, list) or not isinstance(reads, list):
        raise ValueError("'changes' / 'read_decks' is not a list")
    return {"reply": str(obj.get("reply", "")).strip(), "read_decks": [str(d) for d in reads if str(d).strip()],
            "changes": [c for c in changes if isinstance(c, dict)]}


def _is_temp(name: str) -> bool:
    return name == TEMP_DECK or name.startswith(TEMP_DECK + "::")


def resolve_read(name: str, decks: list) -> str:
    """A deck the AI wants to read -> exact full name (never the temp deck)."""
    real = {d: d for d in decks if not _is_temp(d)}
    return _resolve_deck(name, real)


def target_deck(name, decks: list) -> str:
    """Where a new card goes: an existing deck, or a new path under an existing top-level deck."""
    real = {d: d for d in decks if not _is_temp(d)}
    try:
        return _resolve_deck(name, real)
    except ValueError as e:
        if "ambiguous" in str(e):
            raise
    parts = [p.strip() for p in str(name or "").split("::")]
    if not all(parts):
        raise ValueError(f"bad deck name {name!r}")
    tops = {d.lower(): d for d in real if "::" not in d}
    if parts[0].lower() not in tops:
        raise ValueError(f"no top-level deck {parts[0]!r} — new cards go under an existing deck")
    # keep the real spelling of every existing ancestor
    for i in range(len(parts), 0, -1):
        prefix = "::".join(parts[:i]).lower()
        match = next((d for d in real if d.lower() == prefix), None)
        if match:
            return "::".join([match] + parts[i:])
    return "::".join(parts)


def _fields(raw, allowed, what: str) -> dict:
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"{what}: no fields given")
    unknown = [k for k in raw if k not in allowed]
    if unknown:
        raise ValueError(f"{what}: no field {unknown[0]!r} (fields: {', '.join(allowed)})")
    return {k: str(v) for k, v in raw.items()}


def plan_changes(changes: list, decks: list, existing: dict, staged: list):
    """Validate AI changes. existing: note id -> note dict; staged: as listed in the prompt (1-based numbers).

    Returns (ops, rejected): ops are ("add", deck, kind, [field values]) | ("update", note dict, fields)
    | ("edit", staged note id, fields) | ("remove", staged note id); rejected are "✗ reason" lines.
    """
    ops, rejected = [], []

    def staged_at(n, what):
        try:
            i = int(n)
        except (TypeError, ValueError):
            raise ValueError(f"{what} needs a staged card number")
        if not 1 <= i <= len(staged):
            raise ValueError(f"there is no staged card {i}")
        return staged[i - 1]

    for ch in changes:
        try:
            if "add" in ch:
                spec = ch["add"] if isinstance(ch["add"], dict) else {}
                deck = target_deck(spec.get("deck"), decks)
                kind = str(spec.get("type") or "basic").lower()
                if kind == "basic":
                    front, back = str(spec.get("front") or "").strip(), str(spec.get("back") or "").strip()
                    if not front or not back:
                        raise ValueError("a basic card needs a front and a back")
                    ops.append(("add", deck, "basic", [front, back]))
                elif kind == "cloze":
                    text = str(spec.get("text") or "").strip()
                    if "{{c" not in text or "::" not in text:
                        raise ValueError("a cloze card needs {{c1::…}} in its text")
                    ops.append(("add", deck, "cloze", [text, str(spec.get("extra") or "").strip()]))
                else:
                    raise ValueError(f"unknown card type {kind!r} — use basic or cloze")
            elif "update" in ch:
                spec = ch["update"] if isinstance(ch["update"], dict) else {}
                try:
                    note = existing[int(spec.get("note_id"))]
                except (TypeError, ValueError, KeyError):
                    raise ValueError(f"note {spec.get('note_id')!r} isn't one of the cards I read")
                fields = _fields(spec.get("fields"), list(note["fields"]), f"note {note['id']}")
                if all(note["fields"][k] == v for k, v in fields.items()):
                    raise ValueError(f"note {note['id']}: nothing changed")
                ops.append(("update", note, fields))
            elif "edit" in ch:
                spec = ch["edit"] if isinstance(ch["edit"], dict) else {}
                s = staged_at(spec.get("staged"), "edit")
                ops.append(("edit", s["id"], _fields(spec.get("fields"), list(s["fields"]), "staged card")))
            elif "remove" in ch:
                ops.append(("remove", staged_at(ch["remove"], "remove")["id"]))
            else:
                raise ValueError(f"unknown change {json.dumps(ch)[:120]}")
        except ValueError as e:
            rejected.append(f"✗ {e}")
    return ops, rejected
