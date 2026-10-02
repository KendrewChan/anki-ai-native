"""AI backends. No Anki imports.

- ClaudeSession: one long-running `claude -p` stream-json process per study session.
- CodexBackend: one `codex exec` call per message (Codex has no long-running mode).
Both are stateless per request: every prompt carries everything the model needs.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
from collections import deque

from .grading import RETRY_PROMPT

# Isolation: no user/project settings, hooks, plugins, CLAUDE.md, MCP servers or tools.
# (--bare would be stricter but cannot use subscription/OAuth login.)
ISOLATION_FLAGS = [
    "--safe-mode",
    "--setting-sources", "",
    "--strict-mcp-config",
    "--tools", "",
    "--disable-slash-commands",
    "--no-session-persistence",
]


# Codex: no shell, apps, browser, computer use, plugins or web search; read-only sandbox; no user config,
# rules or session files. Verified on codex-cli 0.152.0.
CODEX_ISOLATION_FLAGS = [
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--skip-git-repo-check",
    "-s", "read-only",
    "--disable", "shell_tool",
    "--disable", "apps",
    "--disable", "browser_use",
    "--disable", "computer_use",
    "--disable", "plugins",
    "-c", 'web_search="disabled"',
]

PROVIDERS = ("claude", "codex")

# Anki started from the Dock/Start menu doesn't inherit the shell PATH, so look in the usual install spots too.
CLI_CANDIDATES = {
    name: [
        f"~/.local/bin/{name}",
        f"~/.{name}/local/{name}",
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
        f"/usr/bin/{name}",
        f"~/.local/bin/{name}.exe",
        f"~/AppData/Roaming/npm/{name}.cmd",
    ]
    for name in PROVIDERS
}
CLAUDE_CANDIDATES = CLI_CANDIDATES["claude"]


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_cli(name: str, configured: str = "") -> str:
    """configured path if set, else PATH, else the usual install locations.

    Falls back to the bare name so the error message names what was tried.
    """
    if configured and configured.strip().lower() != "auto":
        return os.path.expanduser(configured.strip())
    found = shutil.which(name)
    if found:
        return found
    candidates = CLAUDE_CANDIDATES if name == "claude" else CLI_CANDIDATES.get(name, [])
    for cand in candidates:
        path = os.path.expanduser(cand)
        if _is_executable(path):
            return path
    return name


def find_claude(configured: str = "") -> str:
    return find_cli("claude", configured)


def build_command(claude_path: str, model: str, system_prompt: str) -> list:
    return [
        claude_path, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        *ISOLATION_FLAGS,
        *(["--model", model] if model else []),
        "--system-prompt", system_prompt,
    ]


def build_codex_command(codex_path: str, model: str, cwd: str) -> list:
    """The prompt goes on stdin ("-")."""
    return [codex_path, "exec", "--json", *CODEX_ISOLATION_FLAGS,
            *(["-m", model] if model else []), "-C", cwd, "-"]


def make_backend(cfg: dict, system_prompt: str, cwd: str, dispatch):
    """The configured provider's backend. `cfg` is the add-on config."""
    provider = cfg.get("provider") or "claude"
    model = cfg.get("model") or ""
    if provider == "codex":
        cmd = build_codex_command(find_cli("codex", cfg.get("codex_path", "")), model, cwd)
        return CodexBackend(cmd, cwd, dispatch, system_prompt)
    cmd = build_command(find_cli("claude", cfg.get("claude_path", "")), model, system_prompt)
    return ClaudeSession(cmd, cwd, dispatch)


class SessionError(Exception):
    """kind: unavailable | crashed | timeout | limit | error | bad_reply"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class _Backend:
    """Serialises requests on a worker thread; subclasses implement _exchange and _kill.

    `dispatch(fn)` runs fn on the caller's thread of choice (Anki: mw.taskman.run_on_main).
    Callbacks: callback(card_id, result_dict_or_None, SessionError_or_None).
    """

    def __init__(self, cmd: list, cwd: str, dispatch):
        self._cmd = cmd
        self._cwd = cwd
        self._dispatch = dispatch
        self._jobs = queue.Queue()
        self._proc = None
        self._stderr = deque(maxlen=20)
        self._gen = 0  # bumped by stop(); stale jobs and callbacks are dropped
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # --- public API (any thread) ---

    def request(self, card_id, prompt: str, parse, timeout: float, callback):
        self._jobs.put((self._gen, card_id, prompt, parse, timeout, callback))

    def stop(self):
        """Kill the process and drop everything pending. The next request starts a fresh process."""
        self._gen += 1
        try:
            while True:
                self._jobs.get_nowait()
        except queue.Empty:
            pass
        self._kill()

    def close(self):
        self.stop()
        self._jobs.put(None)

    # --- worker thread ---

    def _run(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            gen, card_id, prompt, parse, timeout, callback = job
            if gen != self._gen:
                continue
            result, error = None, None
            try:
                try:
                    result = parse(self._exchange(prompt, timeout))
                except ValueError:
                    try:
                        result = parse(self._exchange(self._retry_prompt(prompt), timeout))
                    except ValueError as e:
                        raise SessionError("bad_reply", str(e))
            except SessionError as e:
                error = e
            self._deliver(gen, callback, card_id, result, error)

    def _deliver(self, gen, callback, card_id, result, error):
        def fire():
            if gen == self._gen:
                callback(card_id, result, error)

        self._dispatch(fire)

    def _retry_prompt(self, prompt: str) -> str:
        """Stateless backends must resend the original prompt with the retry note."""
        return f"{prompt}\n\n{RETRY_PROMPT}"

    def _stderr_tail(self) -> str:
        return " | ".join(list(self._stderr)[-3:])

    def _kill(self):
        proc, self._proc = self._proc, None
        if proc is not None:
            _terminate(proc)

    def _exchange(self, prompt: str, timeout: float) -> str:
        raise NotImplementedError


class ClaudeSession(_Backend):
    """One long-running claude process; the conversation persists only to save startup time."""

    def __init__(self, cmd: list, cwd: str, dispatch):
        self._lines = None
        self._discard = 0  # results still owed to requests that timed out
        super().__init__(cmd, cwd, dispatch)

    def _retry_prompt(self, prompt: str) -> str:
        return RETRY_PROMPT  # the original prompt is already in this conversation

    def _exchange(self, prompt: str, timeout: float) -> str:
        proc, lines = self._ensure_proc()
        msg = {"type": "user", "message": {"role": "user", "content": prompt}}
        try:
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            self._drop_proc(proc)
            raise SessionError("crashed", "Claude session crashed; it will restart on the next card. " + self._stderr_tail())
        while True:
            try:
                line = lines.get(timeout=timeout)
            except queue.Empty:
                self._discard += 1
                raise SessionError("timeout", "AI timed out.")
            if line is None:
                self._drop_proc(proc)
                raise SessionError("crashed", "Claude session crashed; it will restart on the next card. " + self._stderr_tail())
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("type") != "result":
                continue
            if self._discard:
                self._discard -= 1
                continue
            text = obj.get("result") or obj.get("subtype") or ""
            if obj.get("is_error"):
                kind = "limit" if "limit" in text.lower() else "error"
                raise SessionError(kind, text or "Claude returned an error.")
            return text

    def _ensure_proc(self):
        proc = self._proc
        if proc is not None and proc.poll() is None:
            return proc, self._lines
        self._discard = 0
        try:
            proc = subprocess.Popen(
                self._cmd, cwd=self._cwd, text=True, bufsize=1,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as e:
            raise SessionError("unavailable", f"cannot start claude ({self._cmd[0]}): {e}")
        lines = queue.Queue()
        threading.Thread(target=self._read_stdout, args=(proc, lines), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()
        self._proc, self._lines = proc, lines
        return proc, lines

    @staticmethod
    def _read_stdout(proc, lines):
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def _read_stderr(self, proc):
        for line in proc.stderr:
            self._stderr.append(line.rstrip())

    def _drop_proc(self, proc):
        if self._proc is proc:
            self._proc = None
        _terminate(proc)


class CodexBackend(_Backend):
    """One `codex exec --json` process per message; the system prompt is prepended to each prompt."""

    def __init__(self, cmd: list, cwd: str, dispatch, system_prompt: str):
        self._system_prompt = system_prompt
        super().__init__(cmd, cwd, dispatch)

    def _exchange(self, prompt: str, timeout: float) -> str:
        try:
            proc = subprocess.Popen(
                self._cmd, cwd=self._cwd, text=True,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        except OSError as e:
            raise SessionError("unavailable", f"cannot start codex ({self._cmd[0]}): {e}")
        self._proc = proc
        try:
            out, err = proc.communicate(f"{self._system_prompt}\n\n---\n\n{prompt}", timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate(proc)
            raise SessionError("timeout", "AI timed out.")
        except (OSError, ValueError):  # killed by stop() mid-call
            raise SessionError("crashed", "codex was stopped.")
        finally:
            if self._proc is proc:
                self._proc = None
        return parse_codex_output(out, err, proc.returncode)


def parse_codex_output(out: str, err: str, returncode) -> str:
    """Last agent_message text from `codex exec --json` events; errors -> SessionError."""
    text, failure = None, None
    for line in out.splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        item = obj.get("item") or {}
        if obj.get("type") == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text") or ""
        elif obj.get("type") == "error":
            failure = obj.get("message") or str(obj)
        elif obj.get("type") == "turn.failed":
            failure = (obj.get("error") or {}).get("message") or str(obj)
    if failure is None and text is None and returncode not in (0, None):
        failure = (err or "").strip()[-400:] or f"codex exited with code {returncode}"
    if failure is not None:
        kind = "limit" if "limit" in failure.lower() else "error"
        raise SessionError(kind, failure)
    if text is None:
        raise SessionError("error", "codex returned no answer.")
    return text


def _terminate(proc):
    if proc.poll() is not None:
        return
    try:
        proc.stdin.close()
    except OSError:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


# --- login state per provider (the add-on never handles credentials; the CLIs do) ---

PROVIDER_LABELS = {"claude": "Claude Code", "codex": "Codex"}


def auth_status_command(provider: str, path: str) -> list:
    return [path, "login", "status"] if provider == "codex" else [path, "auth", "status"]


def parse_auth_status(provider: str, returncode: int, out: str) -> tuple:
    """-> (logged_in, text). Claude prints JSON; Codex prints a sentence."""
    if provider == "codex":
        line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
        ok = returncode == 0 and "logged in" in line.lower() and "not" not in line.lower()
        return ok, (line or "logged out") if ok else "logged out"
    st = json.loads(out)
    ok = bool(st.get("loggedIn"))
    return ok, f"logged in ({st.get('authMethod', '?')})" if ok else "logged out"


def read_auth_status(provider: str, path: str, timeout: float = 20) -> tuple:
    """Run the provider's status command -> (logged_in, text). Codex prints its status on stderr."""
    r = subprocess.run(auth_status_command(provider, path), capture_output=True, text=True,
                       timeout=timeout, stdin=subprocess.DEVNULL)
    out = r.stdout if r.stdout.strip() else r.stderr
    return parse_auth_status(provider, r.returncode, out)


def auth_command(provider: str, path: str, action: str) -> list:
    """action: login | logout."""
    return [path, action] if provider == "codex" else [path, "auth", action]
