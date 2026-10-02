"""Generate: stage, list, approve, submit, discard cards in the "AI-GEN" deck. Takes an anki Collection; no aqt.

Every action does a few batched collection ops (not one per card): Anki keeps only ~30 undo steps, and the
custom undo entry that groups an action must still be in the queue when it is merged.
"""

from .generate_ops import TEMP_DECK

TAG = "ai_generate"
OF = "ai_generate_of_"  # + original note id, on a staged copy that updates that note
OK = "ai_generate_ok"  # staged card the user approved; Submit ports only these
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
    """Staged notes, sorted by real deck: note dict with "deck" = real deck (prefix removed), "of", "ok"."""
    if col.decks.id_for_name(TEMP_DECK) is None:
        return []
    out = []
    for nid in col.find_notes(_search_deck(col, TEMP_DECK)):
        note = col.get_note(nid)
        d = _note_dict(col, note)
        d["deck"] = d["deck"][len(TEMP_DECK) + 2:]  # "" when sitting in AI-GEN itself
        d["of"] = _original_of(note)
        d["ok"] = OK in note.tags
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


def _finish(col, pos):
    """Merge everything since `pos` into one undo step. If the bookmark still fell out of Anki's undo queue,
    the changes are already saved: report them rather than fail (they just aren't a single undo step)."""
    try:
        return col.merge_undo_entries(pos)
    except Exception as e:
        if "undo" not in str(e).lower():
            raise
        from anki.collection import OpChanges
        return OpChanges(card=True, note=True, deck=True, tag=True, browser_table=True, browser_sidebar=True,
                         note_text=True, study_queues=True)


def apply_ops(col, ops) -> tuple:
    """Run plan_changes ops as one undo step. Returns (OpChanges, summary counts)."""
    from anki.collection import AddNoteRequest

    pos = col.add_custom_undo_entry(TEMP_DECK)
    counts = {"added": 0, "updated": 0, "edited": 0, "removed": 0}
    by_original = {s["of"]: s["id"] for s in staged(col) if s["of"]}
    adds, changed, removed = [], {}, set()  # changed: staged note id -> Note
    new_copies = {}  # original id -> copy created in this batch
    dids = {}

    def did(real_deck):
        if real_deck not in dids:
            dids[real_deck] = _staged_did(col, real_deck)
        return dids[real_deck]

    def existing(nid):
        if nid not in changed:
            changed[nid] = col.get_note(nid)
        return changed[nid]

    for op in ops:
        if op[0] == "add":
            _, deck, kind, values = op
            note = col.new_note(_notetype(col, kind))
            for i, v in enumerate(values):
                note.fields[i] = v
            note.tags = [TAG]
            adds.append(AddNoteRequest(note=note, deck_id=did(deck)))
            counts["added"] += 1
        elif op[0] == "update":
            _, orig, fields = op
            if orig["id"] in new_copies:
                copy = new_copies[orig["id"]]
            elif orig["id"] in by_original:  # already staged: change that copy
                copy = existing(by_original[orig["id"]])
            else:
                src = col.get_note(orig["id"])
                copy = col.new_note(src.note_type())
                for k, v in src.items():
                    copy[k] = v
                copy.tags = list(src.tags) + [TAG, f"{OF}{src.id}"]
                new_copies[orig["id"]] = copy
                adds.append(AddNoteRequest(note=copy, deck_id=did(orig["deck"])))
            for k, v in fields.items():
                copy[k] = v
            copy.tags = [t for t in copy.tags if t != OK]  # changed by the AI: needs a fresh look
            counts["updated"] += 1
        elif op[0] == "edit":
            _, nid, fields = op
            note = existing(nid)
            for k, v in fields.items():
                note[k] = v
            note.tags = [t for t in note.tags if t != OK]
            counts["edited"] += 1
        elif op[0] == "remove":
            removed.add(op[1])
            counts["removed"] += 1
    if adds:
        col.add_notes(adds)
    notes = [n for nid, n in changed.items() if nid not in removed]
    if notes:
        col.update_notes(notes)
    if removed:
        col.remove_notes(list(removed))
    return _finish(col, pos), counts


def _cleanup(col):
    """Remove AI-GEN subdecks left without cards, and AI-GEN itself once empty — in one removal."""
    temp = [d.name for d in col.decks.all_names_and_ids() if d.name == TEMP_DECK or d.name.startswith(TEMP_DECK + "::")]
    empty = {n for n in temp if not col.find_cards(_search_deck(col, n))}
    top = [n for n in empty if "::".join(n.split("::")[:-1]) not in empty]  # a removed parent takes its children
    if top:
        col.decks.remove([col.decks.id_for_name(n) for n in top])


def approve(col, ids=None, ok: bool = True) -> tuple:
    """Mark staged cards (all, or the note ids given) approved — or not, with ok=False. They stay in AI-GEN."""
    pos = col.add_custom_undo_entry(f"{'Approve' if ok else 'Unapprove'} {TEMP_DECK} cards")
    notes = []
    for s in staged(col):
        if (ids is None or s["id"] in ids) and s["ok"] != ok:
            note = col.get_note(s["id"])
            note.tags = [t for t in note.tags if t != OK] + ([OK] if ok else [])
            notes.append(note)
    if notes:
        col.update_notes(notes)
    return _finish(col, pos), len(notes)


def submit(col) -> tuple:
    """Port the approved cards out of AI-GEN: updates -> written into the original notes, new cards -> their real deck
    (created if missing). Cards not approved stay staged. Emptied AI-GEN decks are removed. One undo step."""
    from anki.errors import NotFoundError

    pos = col.add_custom_undo_entry(f"Submit {TEMP_DECK}")
    counts = {"updated": 0, "added": 0}
    drop, notes, moves = [], [], {}  # moves: real deck -> card ids
    for s in staged(col):
        if not s["ok"]:
            continue
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
            notes.append(orig)
            drop.append(note.id)
            counts["updated"] += 1
        else:
            moves.setdefault(s["deck"] or "Default", []).extend(note.card_ids())
            note.tags = [t for t in note.tags if t not in (TAG, OK) and not t.startswith(OF)]
            notes.append(note)
            counts["added"] += 1
    for deck, cids in moves.items():
        col.set_deck(cids, col.decks.id(deck, create=True))
    if notes:
        col.update_notes(notes)
    if drop:
        col.remove_notes(drop)
    _cleanup(col)
    return _finish(col, pos), counts


def discard(col, ids=None) -> tuple:
    """Delete staged cards (all, or the staged note ids given); originals are untouched. One undo step."""
    pos = col.add_custom_undo_entry(f"Discard {TEMP_DECK}")
    drop = [s["id"] for s in staged(col) if ids is None or s["id"] in ids]
    if drop:
        col.remove_notes(drop)
    _cleanup(col)
    return _finish(col, pos), len(drop)
