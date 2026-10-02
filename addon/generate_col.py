"""Generate: stage, list, accept, discard cards in the "AI Generate" deck. Takes an anki Collection; no aqt."""

from .generate_ops import TEMP_DECK

TAG = "ai_generate"
OF = "ai_generate_of_"  # + original note id, on a staged copy that updates that note
CLOZE = 1  # notetype["type"] of cloze note types


def _search_deck(col, name: str) -> str:
    from anki.collection import SearchNode
    return col.build_search_string(SearchNode(deck=name))  # includes subdecks; escapes the name


def _note_dict(col, note) -> dict:
    card = note.cards()[0]
    return {"id": note.id, "type": note.note_type()["name"], "deck": col.decks.name(card.odid or card.did),
            "fields": dict(note.items())}


def _original_of(note):
    ids = [t[len(OF):] for t in note.tags if t.startswith(OF)]
    return int(ids[0]) if ids and ids[0].isdigit() else None


def read_deck(col, name: str) -> list:
    """Existing cards (note dicts) of a deck and its subdecks, staged copies excluded."""
    out = []
    for nid in col.find_notes(_search_deck(col, name)):
        note = col.get_note(nid)
        if TAG not in note.tags:
            out.append(_note_dict(col, note))
    return out


def staged(col) -> list:
    """Staged notes, sorted by real deck: note dict with "deck" = real deck (prefix removed) and "of"."""
    if col.decks.id_for_name(TEMP_DECK) is None:
        return []
    out = []
    for nid in col.find_notes(_search_deck(col, TEMP_DECK)):
        note = col.get_note(nid)
        d = _note_dict(col, note)
        d["deck"] = d["deck"][len(TEMP_DECK) + 2:]  # "" when sitting in AI Generate itself
        d["of"] = _original_of(note)
        out.append(d)
    return sorted(out, key=lambda d: (d["deck"].lower(), d["id"]))


def _notetype(col, kind: str):
    want = "Cloze" if kind == "cloze" else "Basic"
    nt = col.models.by_name(want)
    if nt and (nt["type"] == CLOZE) == (kind == "cloze") and len(nt["flds"]) >= 2:
        return nt
    for nt in col.models.all():  # renamed / localized stock note types
        if (nt["type"] == CLOZE) == (kind == "cloze") and len(nt["flds"]) >= 2:
            return nt
    raise ValueError(f"no {want} note type in this collection")


def _staged_did(col, real_deck: str):
    return col.decks.id(f"{TEMP_DECK}::{real_deck}", create=True)


def apply_ops(col, ops) -> tuple:
    """Run plan_changes ops as one undo step. Returns (OpChanges, summary counts)."""
    pos = col.add_custom_undo_entry("AI Generate")
    counts = {"added": 0, "updated": 0, "edited": 0, "removed": 0}
    by_original = {s["of"]: s["id"] for s in staged(col) if s["of"]}
    for op in ops:
        if op[0] == "add":
            _, deck, kind, values = op
            note = col.new_note(_notetype(col, kind))
            for i, v in enumerate(values):
                note.fields[i] = v
            note.tags = [TAG]
            col.add_note(note, _staged_did(col, deck))
            counts["added"] += 1
        elif op[0] == "update":
            _, orig, fields = op
            if orig["id"] in by_original:  # already staged: change that copy
                copy = col.get_note(by_original[orig["id"]])
            else:
                src = col.get_note(orig["id"])
                copy = col.new_note(src.note_type())
                for k, v in src.items():
                    copy[k] = v
                copy.tags = list(src.tags) + [TAG, f"{OF}{src.id}"]
            for k, v in fields.items():
                copy[k] = v
            if copy.id:
                col.update_note(copy)
            else:
                col.add_note(copy, _staged_did(col, orig["deck"]))
                by_original[orig["id"]] = copy.id
            counts["updated"] += 1
        elif op[0] == "edit":
            _, nid, fields = op
            note = col.get_note(nid)
            for k, v in fields.items():
                note[k] = v
            col.update_note(note)
            counts["edited"] += 1
        elif op[0] == "remove":
            col.remove_notes([op[1]])
            counts["removed"] += 1
    return col.merge_undo_entries(pos), counts


def accept(col) -> tuple:
    """Updates -> written into the original notes; new cards -> their real deck; AI Generate deleted. One undo step."""
    from anki.errors import NotFoundError

    pos = col.add_custom_undo_entry("Accept AI Generate")
    counts = {"updated": 0, "added": 0}
    drop = []
    for s in staged(col):
        note = col.get_note(s["id"])
        orig = None
        if s["of"]:
            try:
                orig = col.get_note(s["of"])
            except NotFoundError:  # original deleted meanwhile: keep the copy as a new card
                pass
        if orig is not None:
            for k, v in note.items():
                if k in orig:
                    orig[k] = v
            col.update_note(orig)
            drop.append(note.id)
            counts["updated"] += 1
        else:
            col.set_deck(note.card_ids(), col.decks.id(s["deck"] or "Default", create=True))
            note.tags = [t for t in note.tags if t != TAG and not t.startswith(OF)]
            col.update_note(note)
            counts["added"] += 1
    if drop:
        col.remove_notes(drop)
    did = col.decks.id_for_name(TEMP_DECK)
    if did is not None:
        col.decks.remove([did])
    return col.merge_undo_entries(pos), counts


def discard(col) -> tuple:
    """Delete AI Generate with every staged card; originals are untouched. One undo step."""
    pos = col.add_custom_undo_entry("Discard AI Generate")
    n = len(staged(col))
    did = col.decks.id_for_name(TEMP_DECK)
    if did is not None:
        col.decks.remove([did])
    return col.merge_undo_entries(pos), n
