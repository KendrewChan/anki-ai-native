import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addon import health, session, state  # noqa: E402
from fakes import FAKE_CODEX, make_exe  # noqa: E402



UNIX_LAYOUT = pytest.mark.skipif(os.name == "nt", reason="symlinked Mac/Linux install layout")


def _exe(tmp_path, name, body):
    return make_exe(tmp_path, name, body=body)


def test_cli_version_parses_both_formats(tmp_path):
    assert health.cli_version(_exe(tmp_path, "a", 'print("codex-cli 0.152.0")')) == "0.152.0"
    assert health.cli_version(_exe(tmp_path, "b", 'print("2.1.287 (Claude Code)")')) == "2.1.287"


@pytest.mark.parametrize("msg,kind", [
    ("error: unexpected argument '--disable' found", "incompatible"),
    ("error: unknown option '--safe-mode'", "incompatible"),
    ("You've hit your usage limit.", "limit"),
    ("Error: not logged in", "auth"),
    ("AI timed out.", "timeout"),
    ("cannot start codex (/x): [Errno 2] No such file or directory", "missing"),
    ("model overloaded", "other"),
])
def test_classify(msg, kind):
    assert health.classify(msg) == kind


def test_self_check_passes_with_fake_codex(tmp_path):
    fake = make_exe(tmp_path, "codex", FAKE_CODEX)
    assert health.self_check("codex", fake, str(tmp_path)) == (True, "fake-codex-model")


def test_self_check_reports_incompatible_flag(tmp_path):
    bad = _exe(tmp_path, "codex", 'sys.stdin.read(); sys.stderr.write("error: unexpected argument \'--disable\' found\\n"); sys.exit(2)')
    ok, detail = health.self_check("codex", bad, str(tmp_path))
    assert not ok and health.classify(detail) == "incompatible" and "--disable" in detail


def test_self_check_missing_binary(tmp_path):
    ok, detail = health.self_check("codex", str(tmp_path / "nope"), str(tmp_path))
    assert not ok and "not installed" in detail


def _codex_layout(tmp_path, versions, current):
    root = tmp_path / "standalone"
    for v in versions:
        b = root / "releases" / f"{v}-aarch64-apple-darwin" / "bin"
        b.mkdir(parents=True)
        (b / "codex").write_text(f"#!/bin/sh\necho codex-cli {v}\n")
        (b / "codex").chmod(0o755)
    os.symlink(root / "releases" / f"{current}-aarch64-apple-darwin", root / "current")
    link = tmp_path / "codex"
    os.symlink(root / "current" / "bin" / "codex", link)
    return str(link)


@UNIX_LAYOUT
def test_codex_rollback_repoints_current(tmp_path):
    path = _codex_layout(tmp_path, ["0.147.0", "0.152.0"], "0.152.0")
    assert set(health.installed_versions("codex", path)) == {"0.147.0", "0.152.0"}
    assert health.rollback("codex", path, "0.147.0") == (True, "switched Codex to 0.147.0")
    assert health.cli_version(path) == "0.147.0"
    assert health.rollback("codex", path, "0.1.0")[0] is False


@UNIX_LAYOUT
def test_claude_versions_listed_from_versions_dir(tmp_path):
    vdir = tmp_path / "versions"
    vdir.mkdir()
    for v in ("2.1.286", "2.1.287"):
        (vdir / v).write_text("#!/bin/sh\n")
        (vdir / v).chmod(0o755)
    (vdir / "junk").write_text("")
    link = tmp_path / "claude"
    os.symlink(vdir / "2.1.287", link)
    assert set(health.installed_versions("claude", str(link))) == {"2.1.286", "2.1.287"}


def test_error_report_mentions_provider_and_error():
    r = health.error_report("codex", "0.153.0", "unexpected argument", "fail")
    assert "codex 0.153.0" in r and "unexpected argument" in r and "self-check: fail" in r


def test_self_check_catches_codex_rejecting_json(tmp_path):
    """The model probe runs without --json; the self-check must still start the exact --json study command."""
    bad = _exe(tmp_path, "codex", 'sys.stdin.read()\n'
               'if "--json" in sys.argv: sys.stderr.write("error: unexpected argument \'--json\' found\\n"); sys.exit(2)\n'
               'sys.stderr.write("model: fake-codex-model\\n")')
    ok, detail = health.self_check("codex", bad, str(tmp_path))
    assert not ok and "--json" in detail and health.classify(detail) == "incompatible"


@pytest.mark.parametrize("msg,kind", [
    ("Claude AI usage limit reached", "limit"),
    ("5-hour limit reached ∙ resets 3pm", "limit"),
    ("You've hit your limit · resets 6pm", "limit"),
    ("Rate limit exceeded", "limit"),
    ("prompt exceeds the context window", "error"),
])
def test_one_limit_rule_for_reviewer_and_settings(msg, kind):
    assert session.error_kind(msg) == kind
    assert (health.classify(msg) == "limit") == (kind == "limit")


def test_study_failure_policy():
    f, off, text = health.study_failure("timeout", "slow", 0, None)
    assert (f, off, text) == (0, None, "AI timed out.")  # timeouts never switch AI off
    f, off, text = health.study_failure("error", "boom", f, off)
    assert f == 1 and off is None and text.startswith("AI error: boom")
    f, off, text = health.study_failure("crashed", "again", f, off)
    assert f == 2 and off == "AI unavailable: again" and "AI off until you reopen" in text
    assert health.study_failure("limit", "quota", 0, None)[1] == "Usage limit: quota"
    assert health.study_failure("limit", "quota", 0, "AI unavailable: x")[1] == "AI unavailable: x"  # first reason kept


def test_state_persists_and_skips_unchanged_writes(tmp_path):
    state.put("last_good", "codex", "1.2.3")
    path = state.PATH
    mtime = os.path.getmtime(path)
    state.put("last_good", "codex", "1.2.3")  # unchanged: no write
    assert os.path.getmtime(path) == mtime
    state.reset(path)  # fresh process: read back from disk
    assert state.get("last_good", "codex") == "1.2.3" and state.get("models", "x") is None


def test_learned_model_names_go_to_state_not_config(tmp_path):
    session.remember_model("claude", "sonnet", "claude-sonnet-5-5")
    assert session.resolved_model("claude", "sonnet") == "claude-sonnet-5-5"
    assert state.get("models", "claude:sonnet") == "claude-sonnet-5-5"


def test_damaged_state_file_starts_over(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    state.reset(str(bad))
    assert state.get("last_good", "claude") is None
    state.put("last_good", "claude", "2.0.0")
    assert state.get("last_good", "claude") == "2.0.0"
