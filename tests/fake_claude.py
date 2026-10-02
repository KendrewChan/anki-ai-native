#!/usr/bin/env python3
"""Stand-in for `claude -p --input-format stream-json --output-format stream-json`.

Per user message (keywords in the content): SLEEP:<s> delays, CRASH exits, BADJSON replies
with prose, ERROR / LIMIT reply with is_error. Otherwise replies {"echo": content, "n": turn}.
"""

import json
import re
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


emit({"type": "system", "subtype": "init", "tools": [], "model": "fake-claude-model"})
turn = 0
for line in sys.stdin:
    content = json.loads(line)["message"]["content"]
    turn += 1
    m = re.search(r"SLEEP:([\d.]+)", content)
    if m:
        time.sleep(float(m.group(1)))
    if "CRASH" in content:
        sys.stderr.write("boom\n")
        sys.exit(1)
    if "ERROR" in content or "LIMIT" in content:
        msg = "Claude AI usage limit reached" if "LIMIT" in content else "Invalid API key"
        emit({"type": "result", "subtype": "success", "is_error": True, "result": msg})
        continue
    text = "sure, here you go" if "BADJSON" in content else "```json\n" + json.dumps({"echo": content, "n": turn}) + "\n```"
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
    emit({"type": "result", "subtype": "success", "is_error": False, "result": text})
