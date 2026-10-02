"""Fake CLI executables for tests, on any OS."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_CLAUDE = os.path.join(HERE, "fake_claude.py")
FAKE_CODEX = os.path.join(HERE, "fake_codex.py")


def make_exe(folder, name: str, target: str = None, body: str = None) -> str:
    """An executable `name` in folder that runs the Python file `target`, or a script made from `body` (after
    `import sys`). Unix: a sh wrapper. Windows: a .cmd wrapper, the way npm installs claude/codex."""
    folder = str(folder)
    if body is not None:
        target = os.path.join(folder, name + "_impl.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write(f"import sys\n{body}\n")
    if os.name == "nt":
        path = os.path.join(folder, name + ".cmd")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'@"{sys.executable}" "{target}" %*\r\n')
        return path
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{target}" "$@"\n')
    os.chmod(path, 0o755)
    return path
