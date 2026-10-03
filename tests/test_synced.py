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
    synced.save(col, cfg, LOCAL)
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
    synced.save(col, cfg, LOCAL)
    col.decks.saved.clear()
    calls = col.set_calls
    synced.save(col, dict(cfg, deck_prompts={"1": "a", "2": "changed"}), cfg)
    assert col.decks.saved == [2]  # only deck 2 gets a newer modification time
    assert col.set_calls == calls  # general settings unchanged: config not rewritten


def test_clearing_removes_the_deck_key():
    col = FakeCol()
    synced.save(col, dict(LOCAL, deck_prompts={"1": "a"}), LOCAL)
    synced.save(col, LOCAL, dict(LOCAL, deck_prompts={"1": "a"}))
    assert "anki_ai" not in col.decks.decks[1]


def test_migrate_copies_saved_settings_once():
    col = FakeCol()
    legacy = {"custom": ["be brief"], "deck_prompts": {"1": "old", "9": "deleted deck"}, "deck_ai": {"2": False}}
    assert synced.migrate(col, legacy)
    assert col.conf["anki_ai"] == {"custom": ["be brief"]}
    assert col.decks.decks[1]["anki_ai"] == {"prompt": "old"}
    assert col.decks.decks[2]["anki_ai"] == {"ai": False}
    assert not synced.migrate(col, legacy)  # nothing left to do


def test_migrate_merges_with_another_devices_settings():
    """Mac's settings (meta.json) meet ones a second computer already synced: both kept, the synced side wins only
    where both set the same thing."""
    col = FakeCol()
    synced.save(col, dict(LOCAL, custom=["from Windows"], deck_prompts={"1": "synced"}, deck_ai={"2": False}), LOCAL)
    synced.migrate(col, {"custom": ["from Mac", "from Windows"], "grade_timeout_s": 120,
                         "deck_prompts": {"1": "stale", "2": "mac prompt", "3": "new here"}, "deck_ai": {"1": False}})
    loaded = synced.load(col, LOCAL)
    assert loaded["custom"] == ["from Windows", "from Mac"]
    assert loaded["grade_timeout_s"] == 120
    assert loaded["deck_prompts"] == {"1": "synced", "2": "mac prompt", "3": "new here"}
    assert loaded["deck_ai"] == {"1": False, "2": False}


def test_deck_edit_never_writes_general_defaults():
    """Changing only a deck on a fresh computer must leave general settings unwritten, so another device's
    timeouts and rules aren't hidden behind this one's defaults when it migrates."""
    col = FakeCol()
    synced.save(col, dict(LOCAL, deck_prompts={"1": "p"}), LOCAL)
    assert "anki_ai" not in col.conf
    synced.migrate(col, {"ask_timeout_s": 90})
    assert synced.load(col, LOCAL)["ask_timeout_s"] == 90


def test_save_writes_only_changed_general_settings():
    col = FakeCol()
    col.conf["anki_ai"] = {"custom": ["a"], "ask_timeout_s": 90}
    synced.save(col, dict(LOCAL, custom=["a"], ask_timeout_s=90, missed_append=False),
                dict(LOCAL, custom=["a"], ask_timeout_s=90))
    assert col.conf["anki_ai"] == {"custom": ["a"], "ask_timeout_s": 90, "missed_append": False}


def test_fresh_install_writes_nothing():
    """No meta.json yet: defaults must not land in the collection and overwrite another device's on sync."""
    col = FakeCol()
    assert not synced.migrate(col, {})
    assert col.conf == {} and col.decks.saved == []
