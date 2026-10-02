import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "anki-ai"))

from addon import health, repair  # noqa: E402

HERE = os.path.dirname(__file__)


def _exe(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!{sys.executable}\nimport sys\n{body}\n")
    p.chmod(0o755)
    return str(p)


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
    fake = tmp_path / "codex"
    fake.write_text(f"#!/bin/sh\nexec {sys.executable} {os.path.join(HERE, 'fake_codex.py')} \"$@\"\n")
    fake.chmod(0o755)
    assert health.self_check("codex", str(fake), str(tmp_path)) == (True, "fake-codex-model")


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


def test_codex_rollback_repoints_current(tmp_path):
    path = _codex_layout(tmp_path, ["0.147.0", "0.152.0"], "0.152.0")
    assert set(health.installed_versions("codex", path)) == {"0.147.0", "0.152.0"}
    assert health.rollback("codex", path, "0.147.0") == (True, "switched Codex to 0.147.0")
    assert health.cli_version(path) == "0.147.0"
    assert health.rollback("codex", path, "0.1.0")[0] is False


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


# --- repair ---

@pytest.fixture
def addon_copy(tmp_path):
    root = tmp_path / "addon"
    shutil.copytree(os.path.join(HERE, "..", "addon"), root, ignore=shutil.ignore_patterns("__pycache__", "meta.json"))
    return str(root)


def test_parse_repair():
    r = repair.parse_repair('{"summary":" s ","edits":[{"file":"session.py","old":"a","new":"b"},"junk"]}')
    assert r == {"summary": "s", "edits": [{"file": "session.py", "old": "a", "new": "b"}]}


@pytest.mark.parametrize("edit,msg", [
    ({"file": "main.py", "old": "x", "new": "y"}, "outside the allowed files"),
    ({"file": "../session.py", "old": "x", "new": "y"}, "outside the allowed files"),
    ({"file": "session.py", "old": "not in the file at all", "new": "y"}, "found 0 times"),
    ({"file": "session.py", "old": "import", "new": "y"}, "expected once"),
    ({"file": "session.py", "old": "--ephemeral", "new": "--ephemeral"}, "no-op"),
])
def test_validate_rejects_unsafe_or_ambiguous_edits(addon_copy, edit, msg):
    with pytest.raises(ValueError, match=msg):
        repair.validate([edit], addon_copy)


def test_validate_rejects_empty_proposal(addon_copy):
    with pytest.raises(ValueError, match="no changes"):
        repair.validate([], addon_copy)


def test_apply_backs_up_and_revert_restores(addon_copy, tmp_path):
    path = os.path.join(addon_copy, "session.py")
    original = open(path).read()
    edit = {"file": "session.py", "old": '"--ephemeral",', "new": '"--ephemeral-v2",'}
    backup = repair.apply([edit], addon_copy)
    assert '"--ephemeral-v2",' in open(path).read()
    assert repair.latest_backup(addon_copy) == backup
    repair.revert(backup, addon_copy)
    assert open(path).read() == original and repair.latest_backup(addon_copy) is None


def test_repair_prompt_includes_error_help_and_source():
    p = repair.repair_prompt("unexpected argument '--disable'", "codex", "0.153.0", "Usage: codex exec ...")
    assert "unexpected argument" in p and "Usage: codex exec" in p and "=== session.py ===" in p
    assert "never just delete it" in repair.REPAIR_SYSTEM_PROMPT


def test_load_patched_session_runs_code_from_disk(addon_copy, monkeypatch):
    edit = {"file": "session.py", "old": 'PROVIDER_LABELS = {', "new": 'PATCHED_MARKER = True\nPROVIDER_LABELS = {'}
    repair.apply([edit], addon_copy)
    mod = repair.load_patched_session(addon_copy)
    assert mod.PATCHED_MARKER is True and callable(mod.probe_model)
