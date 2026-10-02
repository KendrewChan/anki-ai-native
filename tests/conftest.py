import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from addon import state  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    """Learned facts go to a temp file: tests must never touch the real add-on's user_files (it may be live)."""
    real = state.PATH
    state.reset(str(tmp_path / "state.json"))
    yield
    state.reset(real)
