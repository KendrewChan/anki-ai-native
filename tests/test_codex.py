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
    b = session.make_backend({"provider": "codex", "codex_path": "/x/codex", "models": {"codex": "gpt-x"}},
                             "S", str(tmp_path), lambda f: f())
    c = session.make_backend({"claude_path": "/x/claude"}, "S", str(tmp_path), lambda f: f())
    try:
        assert isinstance(b, CodexBackend) and b._cmd[0] == "/x/codex" and "gpt-x" in b._cmd
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


BASE = {"provider": "claude", "models": {"claude": "sonnet", "codex": ""}, "custom": []}


def apply(changes, cfg=None):
    new, log, _ = config_ops.apply_changes(dict(cfg or BASE), changes, [], lambda p: True)
    return new, log


def test_each_provider_remembers_its_own_model():
    new, log = apply([{"set": {"provider": "codex"}}, {"set": {"model": "gpt-5.5"}}])
    assert new["models"] == {"claude": "sonnet", "codex": "gpt-5.5"}
    assert log == ["✓ provider: claude → codex (model: default)", "✓ codex model: default → gpt-5.5"]
    back, log = apply([{"set": {"provider": "claude"}}], cfg=new)
    assert session.model_for(back) == "sonnet" and log == ["✓ provider: codex → claude (model: sonnet)"]


def test_model_is_validated_against_the_provider_set_in_the_same_change():
    new, _ = apply([{"set": {"model": "gpt-5.5", "provider": "codex"}}])
    assert new["provider"] == "codex" and new["models"]["codex"] == "gpt-5.5" and new["models"]["claude"] == "sonnet"
    new, log = apply([{"set": {"provider": "codex", "model": "opus"}}])
    assert new["models"]["codex"] == "" and any("not an OpenAI model id" in line for line in log)


def test_legacy_single_model_key_migrates_to_active_provider():
    legacy = {"provider": "codex", "model": "gpt-5.5", "custom": []}
    assert session.model_for(legacy) == "gpt-5.5" and session.model_for(legacy, "claude") == ""
    new, _ = apply([{"add_custom": "x"}], cfg=legacy)
    assert "model" not in new and new["models"] == {"claude": "", "codex": "gpt-5.5"}
    assert session.model_for({"custom": []}) == ""  # nothing set: provider default


@pytest.mark.parametrize("value", ["gemini", "openai"])
def test_unknown_provider_rejected(value):
    new, log = apply([{"set": {"provider": value}}])
    assert new == BASE and "unknown provider" in log[0]


def test_model_default_keyword():
    new, log = apply([{"set": {"model": "default"}}])
    assert new["models"]["claude"] == "" and log == ["✓ claude model: sonnet → default"]


def _fake_cli(tmp_path, body):
    p = tmp_path / "cli"
    p.write_text(f"#!{sys.executable}\nimport sys\n{body}\n")
    p.chmod(0o755)
    return str(p)


def test_read_auth_status_codex_reads_stderr(tmp_path):
    # real codex 0.152.0 prints "Logged in using ChatGPT" on stderr with an empty stdout
    path = _fake_cli(tmp_path, 'sys.stderr.write("Logged in using ChatGPT\\n")')
    assert session.read_auth_status("codex", path) == (True, "Logged in using ChatGPT")


def test_read_auth_status_claude_reads_stdout_json(tmp_path):
    path = _fake_cli(tmp_path, 'print(\'{"loggedIn": true, "authMethod": "claude.ai"}\')')
    assert session.read_auth_status("claude", path) == (True, "logged in (claude.ai)")


FAKE_CLAUDE = os.path.join(os.path.dirname(__file__), "fake_claude.py")
FAKE_CODEX = os.path.join(os.path.dirname(__file__), "fake_codex.py")


def _exe(tmp_path, name, target):
    p = tmp_path / name
    p.write_text(f"#!/bin/sh\nexec {sys.executable} {target} \"$@\"\n")
    p.chmod(0o755)
    return str(p)


def test_probe_model_reads_codex_header(tmp_path):
    name = session.probe_model("codex", _exe(tmp_path, "codex", FAKE_CODEX), "", str(tmp_path))
    assert name == "fake-codex-model" and session.resolved_model("codex", "") == "fake-codex-model"


def test_probe_model_reads_claude_init(tmp_path):
    name = session.probe_model("claude", _exe(tmp_path, "claude", FAKE_CLAUDE), "sonnet", str(tmp_path))
    assert name == "fake-claude-model" and session.resolved_model("claude", "sonnet") == "fake-claude-model"


def test_probe_model_fails_cleanly(tmp_path):
    with pytest.raises(SessionError):
        session.probe_model("codex", _exe(tmp_path, "x", "-c 'import sys; sys.stdin.read()'"), "", str(tmp_path), timeout=5)


def test_real_claude_calls_record_the_model(tmp_path):
    s = session.ClaudeSession([sys.executable, FAKE_CLAUDE], str(tmp_path), lambda f: f(), "opus")
    try:
        done = threading.Event()
        s.request(1, "hi", parse_json_reply, 5, lambda *a: done.set())
        assert done.wait(10) and session.resolved_model("claude", "opus") == "fake-claude-model"
    finally:
        s.close()
