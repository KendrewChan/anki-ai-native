"""Runs against a real (temporary) Anki collection; skipped where Anki's Python packages aren't importable.

Run with Anki's own interpreter, e.g.
  ANKI_PY=~/Library/Application\\ Support/AnkiProgramFiles/.venv/bin/python3
  uvx --native-tls --python "$ANKI_PY" pytest -q -p no:cacheprovider tests/test_generate_col.py
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "anki-ai"))
APP = "/Applications/Anki.app/Contents/Resources/app_packages"
if os.path.isdir(APP):
    sys.path.append(APP)

Collection = pytest.importorskip("anki.collection").Collection

from addon import generate_col as gc, generate_ops as g  # noqa: E402


@pytest.fixture
def col(tmp_path):
    c = Collection(str(tmp_path / "c.anki2"))
    note = c.new_note(c.models.by_name("Basic"))
    note["Front"], note["Back"] = "What makes ATP?", "Mitochondria"
    note.tags = ["bio"]
    c.add_note(note, c.decks.id("Biology::Ch3"))
    yield c
    c.close()


def decks(c):
    return [d.name for d in c.decks.all_names_and_ids()]


def stage(c, changes):
    existing = {n["id"]: n for n in gc.read_deck(c, "Biology")}
    ops, rejected = g.plan_changes(changes, decks(c), existing, gc.staged(c))
    assert rejected == []
    return gc.apply_ops(c, ops)[1]


def test_stage_accept(col):
    orig = gc.read_deck(col, "Biology")[0]
    counts = stage(col, [
        {"add": {"deck": "Biology::Ch4", "type": "basic", "front": "Ribosomes?", "back": "Protein"}},
        {"add": {"deck": "Biology::Ch3", "type": "cloze", "text": "{{c1::Mitochondria}} make ATP"}},
        {"update": {"note_id": orig["id"], "fields": {"Back": "Mitochondria (cellular respiration)"}}},
    ])
    assert counts == {"added": 2, "updated": 1, "edited": 0, "removed": 0}
    s = gc.staged(col)
    assert [(x["deck"], x["of"]) for x in s] == [("Biology::Ch3", None), ("Biology::Ch3", orig["id"]),
                                                 ("Biology::Ch4", None)]
    assert "AI Generate::Biology::Ch4" in decks(col) and "Biology::Ch4" not in decks(col)
    assert col.get_note(orig["id"])["Back"] == "Mitochondria"  # original untouched until Accept
    assert len(gc.read_deck(col, "Biology")) == 1  # staged copies aren't "existing" cards

    # a second update of the same note changes the staged copy, not a new one
    stage(col, [{"update": {"note_id": orig["id"], "fields": {"Back": "Mitochondria!"}}}])
    assert len(gc.staged(col)) == 3

    _, counts = gc.accept(col)
    assert counts == {"updated": 1, "added": 2}
    assert col.get_note(orig["id"])["Back"] == "Mitochondria!" and col.get_note(orig["id"]).tags == ["bio"]
    assert not any(n.startswith("AI Generate") for n in decks(col)) and "Biology::Ch4" in decks(col)
    cards = gc.read_deck(col, "Biology")
    assert len(cards) == 3 and {c["deck"] for c in cards} == {"Biology::Ch3", "Biology::Ch4"}
    assert all(gc.TAG not in col.get_note(c["id"]).tags for c in cards)


def test_edit_remove_discard_undo(col):
    stage(col, [{"add": {"deck": "Biology", "front": "a", "back": "b"}},
                {"add": {"deck": "Biology", "front": "c", "back": "d"}}])
    stage(col, [{"edit": {"staged": 1, "fields": {"Back": "B"}}}, {"remove": 2}])
    s = gc.staged(col)
    assert [x["fields"]["Back"] for x in s] == ["B"]
    _, n = gc.discard(col)
    assert n == 1 and gc.staged(col) == [] and col.decks.id_for_name("AI Generate") is None
    assert col.note_count() == 1
    col.undo()  # one undo step brings the whole staged deck back
    assert len(gc.staged(col)) == 1
