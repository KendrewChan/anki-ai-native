import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addon import generate_ops as g  # noqa: E402

DECKS = ["Default", "Biology", "Biology::Ch3", "Biology::Ch3::Cells", "Chem", "AI-GEN", "AI-GEN::Biology"]


@pytest.fixture
def desk(tmp_path):
    d = tmp_path / "Desktop"
    (d / "notes" / "sub").mkdir(parents=True)
    (d / "notes" / "a.md").write_text("# Cells\nMitochondria make ATP.")
    (d / "notes" / "sub" / "b.txt").write_text("Ribosomes make protein.")
    (d / "notes" / "pic.png").write_bytes(b"\x89PNG\0\0binary")
    (d / "notes" / ".hidden").write_text("secret")
    (tmp_path / "outside.txt").write_text("nope")
    (d / "link").symlink_to(tmp_path / "outside.txt")
    return d


def test_reference_must_be_inside_desktop(desk):
    assert g.check_reference(str(desk / "notes"), desk) == (desk / "notes").resolve()
    assert g.check_reference("notes/a.md", desk) == (desk / "notes" / "a.md").resolve()  # relative = on Desktop
    for bad in (str(desk), str(desk / ".." / "outside.txt"), str(desk / "link"), "/etc/hosts", ""):
        with pytest.raises(ValueError):
            g.check_reference(bad, desk)
    with pytest.raises(ValueError, match="doesn't exist"):
        g.check_reference(str(desk / "missing"), desk)


def test_read_folder_text_only(desk):
    refs = g.read_references(str(desk / "notes"), desk)
    assert [n for n, _ in refs["files"]] == ["a.md", "sub/b.txt"]
    assert refs["skipped"] == ["pic.png"] and not refs["truncated"]
    assert "2 text files" in g.ref_summary(refs) and "pic.png" in g.ref_summary(refs)


def test_read_single_file_and_truncation(desk, monkeypatch):
    refs = g.read_references(str(desk / "notes" / "a.md"), desk)
    assert refs["files"] == [("a.md", "# Cells\nMitochondria make ATP.")]
    monkeypatch.setattr(g, "MAX_REF_CHARS", 10)
    refs = g.read_references(str(desk / "notes"), desk)
    assert sum(len(t) for _, t in refs["files"]) == 10 and refs["truncated"]


def test_target_deck():
    assert g.target_deck("biology::ch3", DECKS) == "Biology::Ch3"
    assert g.target_deck("Cells", DECKS) == "Biology::Ch3::Cells"  # unique leaf
    assert g.target_deck("biology::Ch4", DECKS) == "Biology::Ch4"  # new subdeck, real spelling of parent
    assert g.target_deck("Biology::ch3::Membranes", DECKS) == "Biology::Ch3::Membranes"
    assert g.target_deck("Physics::Waves", DECKS) == "Physics::Waves"  # new top-level deck is fine
    for bad in ("AI-GEN", "AI-GEN::Biology", "ai-gen::Physics"):  # the temp deck is never a target
        with pytest.raises(ValueError):
            g.target_deck(bad, DECKS)
    with pytest.raises(ValueError):
        g.resolve_read("AI-GEN", DECKS)


def test_plan_changes():
    note = {"id": 7, "type": "Basic", "deck": "Biology::Ch3", "fields": {"Front": "Q", "Back": "A"}}
    staged = [{"id": 100, "deck": "Biology", "of": None, "type": "Basic", "fields": {"Front": "x", "Back": "y"}}]
    ops, rejected = g.plan_changes([
        {"add": {"deck": "Biology::Ch3", "type": "basic", "front": "F", "back": "B"}},
        {"add": {"deck": "Chem", "type": "cloze", "text": "{{c1::H2O}} is water"}},
        {"update": {"note_id": "7", "fields": {"Back": "A2"}}},
        {"edit": {"staged": 1, "fields": {"Back": "z"}}},
        {"remove": 1},
        {"add": {"deck": "AI-GEN::Biology", "front": "F", "back": "B"}},
        {"add": {"deck": "Chem", "type": "cloze", "text": "no blanks"}},
        {"update": {"note_id": 8, "fields": {"Back": "?"}}},
        {"update": {"note_id": 7, "fields": {"Back": "A"}}},
        {"update": {"note_id": 7, "fields": {"Extra": "e"}}},
        {"remove": 2},
        {"rename": "x"},
    ], DECKS, {7: note}, staged)
    assert ops == [("add", "Biology::Ch3", "basic", ["F", "B"]), ("add", "Chem", "cloze", ["{{c1::H2O}} is water", ""]),
                   ("update", note, {"Back": "A2"}), ("edit", 100, {"Back": "z"}), ("remove", 100)]
    assert len(rejected) == 7 and all(r.startswith("✗ ") for r in rejected)
    assert "nothing changed" in rejected[3] and "no field 'Extra'" in rejected[4]


def test_prompt_and_reply():
    refs = {"path": "/d/notes", "files": [("a.md", "ATP")], "skipped": [], "truncated": False}
    staged = [{"id": 100, "deck": "Biology", "of": 7, "type": "Basic", "fields": {"Front": "x", "Back": "y"}}]
    p = g.generate_prompt("make cards", DECKS, refs, {"Biology": [{"id": 7, "type": "Basic", "deck": "Biology",
                                                                    "fields": {"Front": "Q", "Back": "A"}}]},
                          staged, [("hi", "hello")])
    assert "=== a.md ===\nATP" in p and '"note_id": 7' in p and '"kind": "update of note 7"' in p
    assert "AI-GEN" not in p.split("Reference")[0]  # temp deck hidden from the deck list
    assert p.endswith("User: make cards") and "User: hi\nYou: hello" in p
    r = g.parse_generate_reply('```json\n{"reply": "ok", "read_decks": ["Biology"], "changes": [{"remove": 1}, 3]}\n```')
    assert r == {"reply": "ok", "read_decks": ["Biology"], "changes": [{"remove": 1}]}
    with pytest.raises(ValueError):
        g.parse_generate_reply('{"changes": {"remove": 1}}')
