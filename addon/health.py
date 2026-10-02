"""CLI health: version, self-check, update, rollback, error classification. No Anki imports."""

import os
import re
import subprocess

from .session import SessionError, error_kind, startup_check

VERSION = re.compile(r"\d+\.\d+\.\d+")
INCOMPATIBLE = re.compile(
    r"unknown (option|argument|flag|command)|unexpected argument|unrecognized|invalid value for|no such (option|flag)",
    re.I,
)
AUTH = re.compile(r"not logged in|log ?in|unauthori[sz]ed|\b401\b|invalid api key|authenticat", re.I)

# Shared between the reviewer (main.py) and the Settings page: the most recent AI failure.
LAST_ERROR = {}


def _run(cmd: list, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def cli_version(path: str, timeout: float = 20) -> str:
    """'0.152.0' from `codex --version` ('codex-cli 0.152.0') or `claude --version` ('2.1.287 (Claude Code)')."""
    r = _run([path, "--version"], timeout)
    m = VERSION.search(r.stdout or r.stderr or "")
    if not m:
        raise SessionError("unavailable", (r.stderr or r.stdout or "no version output").strip()[-200:])
    return m.group(0)


def self_check(provider: str, path: str, cwd: str) -> tuple:
    """(ok, detail). session.startup_check, with every failure reported instead of raised."""
    try:
        return True, startup_check(provider, path, cwd)
    except FileNotFoundError:
        return False, f"{provider} is not installed (looked for {path})"
    except SessionError as e:
        return False, e.message
    except Exception as e:  # anything else is reported, not raised
        return False, f"{e.__class__.__name__}: {e}"


def classify(message: str) -> str:
    """incompatible | auth | limit | timeout | missing | other — picks which fixes to offer."""
    m = message or ""
    if INCOMPATIBLE.search(m):
        return "incompatible"
    if error_kind(m) == "limit":
        return "limit"
    if AUTH.search(m):
        return "auth"
    if "timed out" in m.lower():
        return "timeout"
    if "not installed" in m.lower() or "cannot start" in m.lower() or "no such file" in m.lower():
        return "missing"
    return "other"


def study_failure(kind: str, message: str, failures: int, disabled) -> tuple:
    """The reviewer's failure policy -> (failures, disabled reason or None, text to show).

    A usage limit turns AI off at once; the 2nd unavailable/crash/error does too. Timeouts never count.
    """
    if kind == "limit":
        disabled = disabled or f"Usage limit: {message}"
    elif kind in ("unavailable", "crashed", "error"):
        failures += 1
        if failures >= 2:
            disabled = disabled or f"AI unavailable: {message}"
    if disabled:
        return failures, disabled, disabled + " — AI off until you reopen the reviewer. Open ⚙ Settings to fix it."
    if kind == "timeout":
        return failures, None, "AI timed out."
    return failures, None, f"AI error: {message} — open ⚙ Settings to fix it."

def update(provider: str, path: str, timeout: float = 600) -> tuple:
    """(ok, output) from `claude update` / `codex update`."""
    try:
        r = _run([path, "update"], timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    out = (r.stdout + "\n" + r.stderr).strip()
    return r.returncode == 0, out[-600:]


# --- rollback to a version that is still on disk ---

def _claude_versions_dir(path: str):
    real = os.path.realpath(path)  # ~/.local/share/claude/versions/2.1.287
    parent = os.path.dirname(real)
    return parent if os.path.basename(parent) == "versions" else None


def _codex_releases_dir(path: str):
    real = os.path.realpath(path)  # ~/.codex/packages/standalone/releases/0.152.0-aarch64-apple-darwin/bin/codex
    release = os.path.dirname(os.path.dirname(real))
    releases = os.path.dirname(release)
    if os.path.basename(releases) == "releases" and os.path.islink(os.path.join(os.path.dirname(releases), "current")):
        return releases
    return None


def installed_versions(provider: str, path: str) -> dict:
    """{version: location} of versions still on disk that rollback can switch to."""
    if provider == "codex":
        releases = _codex_releases_dir(path)
        if not releases:
            return {}
        out = {}
        for name in os.listdir(releases):
            m = VERSION.match(name)
            if m and os.path.isdir(os.path.join(releases, name)):
                out[m.group(0)] = os.path.join(releases, name)
        return out
    versions = _claude_versions_dir(path)
    if not versions:
        return {}
    return {n: os.path.join(versions, n) for n in os.listdir(versions) if VERSION.fullmatch(n)}


def rollback(provider: str, path: str, version: str, timeout: float = 600) -> tuple:
    """(ok, output). Claude: its own `claude install <version>`. Codex (standalone install): repoint `current`."""
    targets = installed_versions(provider, path)
    if version not in targets:
        return False, f"{provider} {version} is not on this computer any more"
    if provider == "codex":
        current = os.path.join(os.path.dirname(_codex_releases_dir(path)), "current")
        tmp = current + ".anki_ai_tmp"
        try:
            if os.path.lexists(tmp):
                os.remove(tmp)
            os.symlink(targets[version], tmp)
            os.replace(tmp, current)  # atomic swap of the symlink
        except OSError as e:
            return False, str(e)
        return True, f"switched Codex to {version}"
    try:
        r = _run([path, "install", version], timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout + "\n" + r.stderr).strip()[-600:]


def error_report(provider: str, version: str, message: str, check: str = "") -> str:
    """Plain text the user can paste to the add-on's author."""
    import platform

    return (
        "AI Study error report\n"
        f"provider: {provider} {version or '?'}\n"
        f"system: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"error: {message}\n" + (f"self-check: {check}\n" if check else "")
    )
