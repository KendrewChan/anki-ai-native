"""Synced settings on real Anki collections; skipped where Anki's Python packages aren't importable.

Run with Anki's own interpreter (see test_generate_col.py) or the PyPI wheel:
  uvx --native-tls --python 3.13 --with anki pytest -q -p no:cacheprovider tests/test_synced_col.py
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
APP = "/Applications/Anki.app/Contents/Resources/app_packages"
if os.path.isdir(APP):
    sys.path.append(APP)

Collection = pytest.importorskip("anki.collection").Collection

from addon import synced  # noqa: E402

LOCAL = {"provider": "claude", "custom": [], "missed_append": True,
         "deck_prompts": {}, "deck_ai": {}, "deck_sharp": {}}


@pytest.fixture
def col(tmp_path):
    c = Collection(str(tmp_path / "c.anki2"))
    yield c
    c.close()


def test_settings_survive_reopening(tmp_path):
    path = str(tmp_path / "c.anki2")
    c = Collection(path)
    did = str(c.decks.id("Biology::Ch3"))
    synced.save(c, dict(LOCAL, custom=["grade strictly"], deck_prompts={did: "Use Latin names"}, deck_sharp={did: False}), LOCAL)
    c.close()
    c = Collection(path)
    loaded = synced.load(c, LOCAL)
    c.close()
    assert loaded["custom"] == ["grade strictly"]
    assert loaded["deck_prompts"] == {did: "Use Latin names"} and loaded["deck_sharp"] == {did: False}


def test_deck_rename_keeps_settings(col):
    did = col.decks.id("Old")
    synced.save(col, dict(LOCAL, deck_prompts={str(did): "p"}), LOCAL)
    col.decks.rename(col.decks.get(did), "New")
    assert synced.load(col, LOCAL)["deck_prompts"] == {str(did): "p"}


def test_unchanged_deck_keeps_its_mtime(col):
    a, b = col.decks.id("A"), col.decks.id("B")
    first = dict(LOCAL, deck_prompts={str(a): "x", str(b): "y"})
    synced.save(col, first, LOCAL)
    before = col.decks.get(a)["mod"]
    synced.save(col, dict(LOCAL, deck_prompts={str(a): "x", str(b): "changed"}), first)
    assert col.decks.get(a)["mod"] == before
