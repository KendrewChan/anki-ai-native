import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "anki-ai"))

from addon import config_ops, grading  # noqa: E402

BASE = {"claude_path": "/bin/claude", "model": "sonnet", "missed_append": True,
        "ask_timeout_s": 30, "grade_timeout_s": 60, "custom": []}


def apply(changes, cfg=None, history=None, executable=True):
    history = [] if history is None else history
    new, log, auth = config_ops.apply_changes(dict(cfg or BASE), changes, history, lambda p: executable)
    return new, log, auth, history


def test_set_model_and_timeout_logged():
    new, log, _, hist = apply([{"set": {"model": "opus", "grade_timeout_s": "90"}}])
    assert new["model"] == "opus" and new["grade_timeout_s"] == 90
    assert log == ["✓ model: sonnet → opus", "✓ grade_timeout_s: 60 → 90"]
    assert hist == [BASE]


@pytest.mark.parametrize("change,msg", [
    ({"set": {"model": "gpt-4"}}, "unknown model"),
    ({"set": {"ask_timeout_s": 2}}, "between 5 and 600"),
    ({"set": {"missed_append": "maybe"}}, "true or false"),
    ({"set": {"colour": "red"}}, "unknown setting"),
    ({"remove_custom": 3}, "no custom rule 3"),
    ({"undo": True}, "nothing to undo"),
    ({"explode": True}, "unknown change"),
])
def test_invalid_changes_rejected_without_touching_config(change, msg):
    new, log, _, hist = apply([change])
    assert new == BASE and hist == []
    assert log[0].startswith("✗") and msg in log[0]


def test_claude_path_must_be_executable():
    new, log, _, _ = apply([{"set": {"claude_path": "/nope"}}], executable=False)
    assert new["claude_path"] == "/bin/claude" and "not an executable" in log[0]


def test_full_model_id_accepted():
    new, _, _, _ = apply([{"set": {"model": "claude-opus-5-5"}}])
    assert new["model"] == "claude-opus-5-5"


def test_custom_add_and_remove():
    new, log, _, _ = apply([{"add_custom": " grade strictly "}, {"add_custom": "scenario questions"}])
    assert new["custom"] == ["grade strictly", "scenario questions"]
    new, log, _, _ = apply([{"remove_custom": 1}], cfg=new)
    assert new["custom"] == ["scenario questions"] and log == ['✓ removed custom rule 1: "grade strictly"']


def test_undo_restores_previous_config():
    history = []
    changed, _, _, _ = apply([{"set": {"model": "opus"}}], history=history)
    restored, log, _, _ = apply([{"undo": True}], cfg=changed, history=history)
    assert restored == BASE and history == [] and log == ["✓ undid the previous change"]


def test_auth_actions_returned_not_applied():
    new, log, auth, hist = apply([{"login": True}])
    assert auth == ["login"] and new == BASE and log == [] and hist == []


def test_parse_config_reply():
    r = config_ops.parse_config_reply('```json\n{"reply":" ok ","changes":[{"set":{"model":"opus"}},"junk"]}\n```')
    assert r == {"reply": "ok", "changes": [{"set": {"model": "opus"}}]}


def test_config_prompt_lists_settings_rules_and_login():
    p = config_ops.config_prompt(dict(BASE, custom=["be strict"]), "logged in (claude.ai)", "use opus")
    assert '"model": "sonnet"' in p and "1. be strict" in p and "logged in" in p and p.endswith("User: use opus")


def test_tutor_system_prompt_appends_custom_rules():
    assert grading.system_prompt([]) == grading.SYSTEM_PROMPT
    sp = grading.system_prompt(["grade strictly", " "])
    assert sp.startswith(grading.SYSTEM_PROMPT) and sp.endswith("- grade strictly")
