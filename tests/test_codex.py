import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "anki-ai"))

from addon import config_ops, session  # noqa: E402
from addon.grading import parse_json_reply  # noqa: E402
from addon.session import CodexBackend, SessionError, parse_codex_output  # noqa: E402

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_codex.py")]


@pytest.fixture
def codex(tmp_path):
    b = CodexBackend(FAKE, str(tmp_path), lambda fn: fn(), "SYSTEM PROMPT")
    yield b
    b.close()


def call(b, prompt, timeout=10):
    done, out = threading.Event(), {}
    b.request(1, prompt, parse_json_reply, timeout, lambda cid, r, e: (out.update(result=r, err=e), done.set()))
    assert done.wait(15), "callback never fired"
    return out


def test_last_agent_message_is_the_answer_and_system_prompt_is_prepended(codex):
    r = call(codex, "grade this")
    assert r["err"] is None and r["result"] == {"echo": "grade this", "system": True}


def test_bad_json_retry_resends_original_prompt(codex):
    r = call(codex, "BADJSON grade")
    assert r["err"] is None and "not valid JSON" in r["result"]["echo"]


@pytest.mark.parametrize("prompt,kind,text", [
    ("ERROREVENT", "error", "stream disconnected"),
    ("TURNFAILED", "error", "overloaded"),
    ("LIMIT", "limit", "usage limit"),
    ("EXIT1", "error", "not logged in"),
    ("NOANSWER", "error", "no answer"),
])
def test_failures_map_to_session_errors(codex, prompt, kind, text):
    err = call(codex, prompt)["err"]
    assert err.kind == kind and text in err.message


def test_timeout_kills_the_call(codex):
    assert call(codex, "SLEEP:3", timeout=0.5)["err"].kind == "timeout"
    assert call(codex, "next")["result"]["echo"] == "next"


def test_missing_binary_is_unavailable(tmp_path):
    b = CodexBackend(["/nonexistent/codex"], str(tmp_path), lambda fn: fn(), "S")
    try:
        assert call(b, "x")["err"].kind == "unavailable"
    finally:
        b.close()


def test_stop_drops_inflight_reply(codex):
    fired = []
    codex.request(1, "SLEEP:1", parse_json_reply, 10, lambda *a: fired.append(a))
    import time
    time.sleep(0.3)
    codex.stop()
    assert call(codex, "after")["result"]["echo"] == "after"
    assert fired == []


def test_parse_codex_output_ignores_non_json_lines():
    out = 'warning: blah\n{"type":"item.completed","item":{"type":"agent_message","text":"{}"}}\n'
    assert parse_codex_output(out, "", 0) == "{}"
    with pytest.raises(SessionError):
        parse_codex_output("", "boom", 2)


def test_codex_command_is_isolated_and_reads_stdin():
    cmd = session.build_codex_command("/x/codex", "", "/tmp/w")
    for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "shell_tool", 'web_search="disabled"'):
        assert flag in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only" and cmd[-1] == "-" and "-m" not in cmd
    assert session.build_codex_command("/x/codex", "gpt-x", "/tmp/w")[-5:-3] == ["-m", "gpt-x"]


def test_claude_command_omits_model_when_default():
    assert "--model" not in session.build_command("/x/claude", "", "S")
    assert session.build_command("/x/claude", "opus", "S")[-4:-2] == ["--model", "opus"]


def test_make_backend_picks_provider(tmp_path):
    b = session.make_backend({"provider": "codex", "codex_path": "/x/codex"}, "S", str(tmp_path), lambda f: f())
    c = session.make_backend({"claude_path": "/x/claude"}, "S", str(tmp_path), lambda f: f())
    try:
        assert isinstance(b, CodexBackend) and b._cmd[0] == "/x/codex"
        assert isinstance(c, session.ClaudeSession) and c._cmd[0] == "/x/claude"
    finally:
        b.close()
        c.close()


@pytest.mark.parametrize("provider,rc,out,expected", [
    ("codex", 0, "Logged in using ChatGPT\n", (True, "Logged in using ChatGPT")),
    ("codex", 1, "Not logged in\n", (False, "logged out")),
    ("claude", 0, '{"loggedIn": true, "authMethod": "claude.ai"}', (True, "logged in (claude.ai)")),
    ("claude", 0, '{"loggedIn": false}', (False, "logged out")),
])
def test_parse_auth_status(provider, rc, out, expected):
    assert session.parse_auth_status(provider, rc, out) == expected


def test_auth_commands():
    assert session.auth_status_command("codex", "c") == ["c", "login", "status"]
    assert session.auth_command("codex", "c", "logout") == ["c", "logout"]
    assert session.auth_command("claude", "c", "login") == ["c", "auth", "login"]


BASE = {"provider": "claude", "model": "sonnet", "custom": []}


def apply(changes, cfg=None):
    new, log, _ = config_ops.apply_changes(dict(cfg or BASE), changes, [], lambda p: True)
    return new, log


def test_switching_provider_resets_model_to_default():
    new, log = apply([{"set": {"provider": "codex"}}])
    assert new["provider"] == "codex" and new["model"] == ""
    assert log == ["✓ provider: claude → codex", "✓ model: sonnet → default (not valid for codex)"]


def test_switching_provider_with_model_validates_against_new_provider():
    new, _ = apply([{"set": {"model": "gpt-5.5", "provider": "codex"}}])
    assert new == dict(BASE, provider="codex", model="gpt-5.5")
    new, log = apply([{"set": {"provider": "codex", "model": "opus"}}])
    assert new["provider"] == "codex" and new["model"] == ""
    assert any("not an OpenAI model id" in line for line in log)


@pytest.mark.parametrize("value", ["gemini", "openai"])
def test_unknown_provider_rejected(value):
    new, log = apply([{"set": {"provider": value}}])
    assert new == BASE and "unknown provider" in log[0]


def test_model_default_keyword():
    new, log = apply([{"set": {"model": "default"}}])
    assert new["model"] == "" and log == ["✓ model: sonnet → default"]
