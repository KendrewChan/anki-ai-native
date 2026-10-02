#!/usr/bin/env python3
"""Stand-in for `codex exec --json ... -`: reads the prompt from stdin, prints JSONL events.

Keywords in the prompt: SLEEP:<s>, ERROREVENT, TURNFAILED, LIMIT, EXIT1, NOANSWER, BADJSON (unless the
retry note is present). Otherwise the final agent message is {"echo": <last line>, "system": <bool>}.
"""

import json
import re
import sys
import time

sys.stdin.reconfigure(encoding="utf-8")  # like the real CLIs: raw UTF-8 both ways, on every OS
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


if sys.argv[1:3] == ["debug", "models"]:
    print(json.dumps({"models": [
        {"slug": "hidden-one", "visibility": "hide", "priority": 1},
        {"slug": "model-b", "visibility": "list", "priority": 8},
        {"slug": "model-a", "visibility": "list", "priority": 5},
    ]}))
    sys.exit(0)
prompt = sys.stdin.read()
sys.stderr.write("OpenAI Codex v0\n--------\nmodel: fake-codex-model\nprovider: openai\n--------\n")
sys.stderr.flush()
emit({"type": "thread.started", "thread_id": "t"})
emit({"type": "turn.started"})
m = re.search(r"SLEEP:([\d.]+)", prompt)
if m:
    time.sleep(float(m.group(1)))
if "EXIT1" in prompt:
    sys.stderr.write("Error: not logged in\n")
    sys.exit(1)
if "ERROREVENT" in prompt:
    emit({"type": "error", "message": "stream disconnected"})
    sys.exit(1)
if "LIMIT" in prompt:
    emit({"type": "turn.failed", "error": {"message": "You've hit your usage limit."}})
    sys.exit(1)
if "TURNFAILED" in prompt:
    emit({"type": "turn.failed", "error": {"message": "model overloaded"}})
    sys.exit(1)
if "NOANSWER" in prompt:
    emit({"type": "turn.completed"})
    sys.exit(0)
emit({"type": "item.completed", "item": {"type": "agent_message", "text": "Let me think."}})
if "BADJSON" in prompt and "not valid JSON" not in prompt:
    text = "sure, here you go"
else:
    text = json.dumps({"echo": prompt.strip().splitlines()[-1], "system": prompt.startswith("SYSTEM")})
emit({"type": "item.completed", "item": {"type": "agent_message", "text": text}})
emit({"type": "turn.completed", "usage": {}})
