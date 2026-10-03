"""Synced settings: a fake collection here; test_synced_col.py repeats the key cases on a real one."""

import copy

from addon import synced


class FakeDecks:
    def __init__(self, ids):
        self.decks = {i: {"id": i, "name": f"D{i}"} for i in ids}
        self.saved = []

    def all(self):
        return [copy.deepcopy(d) for d in self.decks.values()]

    def save(self, deck):
        self.decks[deck["id"]] = copy.deepcopy(deck)
        self.saved.append(deck["id"])


class FakeCol:
    def __init__(self, ids=(1, 2, 3)):
        self.conf = {}
        self.set_calls = 0
        self.decks = FakeDecks(ids)

    def get_config(self, key, default=None):
        return copy.deepcopy(self.conf.get(key, default))

    def set_config(self, key, value):
        self.set_calls += 1
        self.conf[key] = copy.deepcopy(value)


LOCAL = {"provider": "claude", "models": {"claude": "sonnet", "codex": ""}, "claude_path": "", "codex_path": "",
         "missed_append": True, "ask_timeout_s": 30, "grade_timeout_s": 60, "custom": [],
         "deck_prompts": {}, "deck_ai": {}, "deck_sharp": {}}


def test_local_part_keeps_only_device_settings():
    assert synced.local_part(LOCAL) == {"provider": "claude", "models": {"claude": "sonnet", "codex": ""},
                                        "claude_path": "", "codex_path": ""}


def test_save_then_load_round_trip():
    col = FakeCol()
    cfg = dict(LOCAL, custom=["grade strictly"], missed_append=False,
               deck_prompts={"1": "Use Spanish"}, deck_ai={"2": False}, deck_sharp={"1": True})
    synced.save(col, cfg)
    assert col.decks.decks[1]["anki_ai"] == {"prompt": "Use Spanish", "sharp": True}
    assert col.decks.decks[2]["anki_ai"] == {"ai": False}
    assert "anki_ai" not in col.decks.decks[3]
    # a device with other local settings sees the same synced ones
    other = dict(LOCAL, provider="codex", claude_path="C:/x/claude.exe")
    loaded = synced.load(col, other)
    assert loaded["provider"] == "codex" and loaded["claude_path"] == "C:/x/claude.exe"
    for key in ("custom", "missed_append", "deck_prompts", "deck_ai", "deck_sharp"):
        assert loaded[key] == cfg[key]


def test_save_touches_only_changed_decks():
    col = FakeCol()
    cfg = dict(LOCAL, deck_prompts={"1": "a", "2": "b"})
    synced.save(col, cfg)
    col.decks.saved.clear()
    calls = col.set_calls
    synced.save(col, dict(cfg, deck_prompts={"1": "a", "2": "changed"}))
    assert col.decks.saved == [2]  # only deck 2 gets a newer modification time
    assert col.set_calls == calls  # general settings unchanged: config not rewritten


def test_clearing_removes_the_deck_key():
    col = FakeCol()
    synced.save(col, dict(LOCAL, deck_prompts={"1": "a"}))
    synced.save(col, LOCAL)
    assert "anki_ai" not in col.decks.decks[1]


def test_migrate_copies_saved_settings_once():
    col = FakeCol()
    legacy = {"custom": ["be brief"], "deck_prompts": {"1": "old", "9": "deleted deck"}, "deck_ai": {"2": False}}
    assert synced.migrate(col, legacy)
    assert col.conf["anki_ai"] == {"custom": ["be brief"]}
    assert col.decks.decks[1]["anki_ai"] == {"prompt": "old"}
    assert col.decks.decks[2]["anki_ai"] == {"ai": False}
    assert not synced.migrate(col, legacy)  # nothing left to do


def test_migrate_never_overwrites_synced_settings():
    col = FakeCol()
    synced.save(col, dict(LOCAL, custom=["from the other device"], deck_prompts={"1": "synced"}))
    synced.migrate(col, {"custom": ["stale"], "deck_prompts": {"1": "stale", "2": "new here"}})
    loaded = synced.load(col, LOCAL)
    assert loaded["custom"] == ["from the other device"]
    assert loaded["deck_prompts"] == {"1": "synced", "2": "new here"}


def test_fresh_install_writes_nothing():
    """No meta.json yet: defaults must not land in the collection and overwrite another device's on sync."""
    col = FakeCol()
    assert not synced.migrate(col, {})
    assert col.conf == {} and col.decks.saved == []
