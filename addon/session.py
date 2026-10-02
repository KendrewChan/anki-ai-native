"""One long-running `claude -p` stream-json process per study session. No Anki imports."""

import json
import queue
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


def build_command(claude_path: str, model: str, system_prompt: str) -> list:
    return [
        claude_path, "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        *ISOLATION_FLAGS,
        "--model", model,
        "--system-prompt", system_prompt,
    ]


class SessionError(Exception):
    """kind: unavailable | crashed | timeout | limit | error | bad_reply"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class ClaudeSession:
    """Serialises requests to one claude process on a worker thread.

    `dispatch(fn)` runs fn on the caller's thread of choice (Anki: mw.taskman.run_on_main).
    Callbacks: callback(card_id, result_dict_or_None, SessionError_or_None).
    """

    def __init__(self, cmd: list, cwd: str, dispatch):
        self._cmd = cmd
        self._cwd = cwd
        self._dispatch = dispatch
        self._jobs = queue.Queue()
        self._proc = None
        self._lines = None
        self._stderr = deque(maxlen=20)
        self._discard = 0  # results still owed to requests that timed out
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
                        result = parse(self._exchange(RETRY_PROMPT, timeout))
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

    def _stderr_tail(self) -> str:
        return " | ".join(list(self._stderr)[-3:])

    def _drop_proc(self, proc):
        if self._proc is proc:
            self._proc = None
        _terminate(proc)

    def _kill(self):
        proc, self._proc = self._proc, None
        if proc is not None:
            _terminate(proc)


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
