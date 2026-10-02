"""Config page logic: AI prompt, reply parsing, validated changes. No Anki imports — unit-testable."""

import json
import os

from .grading import parse_json_reply

MODEL_ALIASES = ("haiku", "sonnet", "opus", "fable")
TIMEOUT_RANGE = (5, 600)

SETTINGS = {
    "model": "Claude model: an alias (haiku, sonnet, opus, fable) or a full model id starting with claude-",
    "ask_timeout_s": "seconds to wait for the sharp question (5-600)",
    "grade_timeout_s": "seconds to wait for a grade (5-600)",
    "missed_append": "true/false — append Missed bullets to the card's Back after grading",
    "claude_path": "absolute path to the claude CLI executable",
}

CONFIG_SYSTEM_PROMPT = """You manage the settings of an Anki add-on that uses Claude as a flashcard tutor. The user talks to you in plain language; you turn requests into changes.

Settings you can change (key: meaning):
""" + "\n".join(f"- {k}: {v}" for k, v in SETTINGS.items()) + """

Custom rules: a numbered list of plain-language instructions added to the tutor's system prompt (e.g. "grade strictly", "ask scenario questions"). Rewrite vague requests into one clear, imperative rule.

Each message gives you the current settings, custom rules and login state, then the user's request.

Reply with JSON only, no code fences:
{"reply": "<one or two short sentences to the user>", "changes": [<change>, ...]}

A change is one of:
{"set": {"<key>": <value>}}
{"add_custom": "<rule>"}
{"remove_custom": <rule number, 1-based>}
{"undo": true}        — revert the user's previous change
{"login": true}       — sign in to Claude (opens the browser)
{"logout": true}      — also signs the user out of Claude Code on this computer; only when they explicitly ask to log out

Only include changes the user asked for. If the request is unclear or impossible, ask a short question in "reply" with "changes": []. Questions about the settings need no changes."""


def config_prompt(cfg: dict, auth: str, message: str) -> str:
    settings = {k: cfg.get(k) for k in SETTINGS}
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(cfg.get("custom") or [], 1)) or "(none)"
    return (
        f"Current settings:\n{json.dumps(settings, indent=1)}\n\n"
        f"Custom rules:\n{rules}\n\nLogin: {auth}\n\nUser: {message}"
    )


def parse_config_reply(text: str) -> dict:
    obj = parse_json_reply(text)
    changes = obj.get("changes") or []
    if not isinstance(changes, list):
        raise ValueError("'changes' is not a list")
    return {"reply": str(obj.get("reply", "")).strip(), "changes": [c for c in changes if isinstance(c, dict)]}


def _validate(key: str, value, is_executable):
    if key == "model":
        v = str(value).strip()
        if v in MODEL_ALIASES or v.startswith("claude-"):
            return v
        raise ValueError(f"unknown model {v!r} — use {', '.join(MODEL_ALIASES)} or a claude-… id")
    if key in ("ask_timeout_s", "grade_timeout_s"):
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number of seconds")
        lo, hi = TIMEOUT_RANGE
        if not lo <= v <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi} seconds")
        return v
    if key == "missed_append":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "on", "yes", "1"):
            return True
        if str(value).lower() in ("false", "off", "no", "0"):
            return False
        raise ValueError("missed_append must be true or false")
    if key == "claude_path":
        v = os.path.expanduser(str(value).strip())
        if not is_executable(v):
            raise ValueError(f"{v} is not an executable file")
        return v
    raise ValueError(f"unknown setting {key!r}")


def apply_changes(cfg: dict, changes: list, history: list, is_executable=None):
    """Validate and apply changes in order.

    history: stack of earlier configs (mutated: push on change, pop on undo).
    Returns (new_cfg, log_lines, auth_actions) where auth_actions ⊆ ["login", "logout"].
    """
    is_executable = is_executable or (lambda p: os.path.isfile(p) and os.access(p, os.X_OK))
    before = _copy(cfg)
    new = _copy(cfg)
    log, auth = [], []
    for ch in changes:
        try:
            if ch.get("undo"):
                if not history:
                    raise ValueError("nothing to undo")
                new = history.pop()
                before = _copy(new)  # an undo is not itself pushed
                log.append("✓ undid the previous change")
            elif "set" in ch:
                for key, value in (ch["set"] or {}).items():
                    v = _validate(key, value, is_executable)
                    log.append(f"✓ {key}: {_show(new.get(key))} → {_show(v)}")
                    new[key] = v
            elif "add_custom" in ch:
                rule = str(ch["add_custom"]).strip()
                if not rule:
                    raise ValueError("empty custom rule")
                new["custom"] = list(new.get("custom") or []) + [rule]
                log.append(f'✓ added custom rule {len(new["custom"])}: "{rule}"')
            elif "remove_custom" in ch:
                rules = list(new.get("custom") or [])
                try:
                    i = int(ch["remove_custom"])
                except (TypeError, ValueError):
                    raise ValueError("remove_custom needs a rule number")
                if not 1 <= i <= len(rules):
                    raise ValueError(f"there is no custom rule {i}")
                removed = rules.pop(i - 1)
                new["custom"] = rules
                log.append(f'✓ removed custom rule {i}: "{removed}"')
            elif ch.get("login"):
                auth.append("login")
            elif ch.get("logout"):
                auth.append("logout")
            else:
                raise ValueError(f"unknown change {json.dumps(ch)}")
        except ValueError as e:
            log.append(f"✗ {e}")
    if new != before:
        history.append(before)
    return new, log, auth


def _copy(cfg: dict) -> dict:
    return json.loads(json.dumps(cfg))


def _show(v) -> str:
    return json.dumps(v) if isinstance(v, bool) else str(v)
