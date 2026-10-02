import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "anki-ai"))

from addon.grading import RETRY_PROMPT, parse_json_reply  # noqa: E402
from addon.session import ClaudeSession  # noqa: E402

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_claude.py")]


@pytest.fixture
def sess(tmp_path):
    s = ClaudeSession(FAKE, str(tmp_path), lambda fn: fn())
    yield s
    s.close()


def call(s, prompt, card_id=1, timeout=5):
    done = threading.Event()
    out = {}

    def cb(cid, result, err):
        out.update(cid=cid, result=result, err=err)
        done.set()

    s.request(card_id, prompt, parse_json_reply, timeout, cb)
    assert done.wait(10), "callback never fired"
    return out


def test_reply_parsed_and_context_kept_across_requests(sess):
    a = call(sess, "first", card_id=7)
    b = call(sess, "second")
    assert a["cid"] == 7 and a["result"]["echo"] == "first" and a["result"]["n"] == 1
    assert b["result"]["n"] == 2  # same process, same conversation


def test_timeout_then_late_reply_is_discarded(sess):
    t = call(sess, "SLEEP:1", timeout=0.3)
    assert t["err"].kind == "timeout"
    nxt = call(sess, "after")
    assert nxt["result"]["echo"] == "after"  # not the late SLEEP reply


def test_crash_reports_and_next_request_respawns(sess):
    c = call(sess, "CRASH")
    assert c["err"].kind == "crashed" and "boom" in c["err"].message
    nxt = call(sess, "again")
    assert nxt["result"]["n"] == 1  # fresh process


def test_bad_json_retried_once(sess):
    r = call(sess, "BADJSON")
    assert r["err"] is None and r["result"]["echo"] == RETRY_PROMPT


def test_error_and_limit_kinds(sess):
    assert call(sess, "ERROR")["err"].kind == "error"
    assert call(sess, "LIMIT")["err"].kind == "limit"


def test_missing_binary_is_unavailable(tmp_path):
    s = ClaudeSession(["/nonexistent/claude"], str(tmp_path), lambda fn: fn())
    try:
        assert call(s, "x")["err"].kind == "unavailable"
    finally:
        s.close()


def test_stop_drops_pending_callbacks(sess):
    fired = []
    sess.request(1, "SLEEP:0.5", parse_json_reply, 5, lambda *a: fired.append(a))
    sess.request(2, "queued", parse_json_reply, 5, lambda *a: fired.append(a))
    sess.stop()
    after = call(sess, "after-stop")
    assert after["result"]["n"] == 1  # new process after stop
    assert fired == []
