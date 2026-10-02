"""Config page logic: AI prompt, reply parsing, validated changes. No Anki imports — unit-testable."""

import json
import os

from .grading import parse_json_reply
from .session import CLAUDE_ALIASES, PROVIDERS, model_for, provider_of

TIMEOUT_RANGE = (5, 600)

SETTINGS = {
    "provider": "which AI runs the tutor: \"claude\" (Claude Code CLI, Claude subscription) or \"codex\" (OpenAI Codex CLI, ChatGPT subscription)",
    "model": "model for the CURRENT provider (each provider remembers its own); \"\" = the provider's default. claude: haiku, sonnet, opus, fable or a claude-… id. codex: an OpenAI model id",
    "ask_timeout_s": "seconds to wait for the sharp question (5-600)",
    "grade_timeout_s": "seconds to wait for a grade (5-600)",
    "missed_append": "true/false — append Missed bullets to the card's Back after grading",
    "claude_path": "absolute path to the claude CLI executable, or \"\" to auto-detect",
    "codex_path": "absolute path to the codex CLI executable, or \"\" to auto-detect",
}

# On/off settings shown as toggle buttons on the settings page: key -> (label, tooltip lines). A missing key = on.
TOGGLES = {
    "missed_append": ("Missed append", (
        "On: after each graded review, what you missed is written onto the card's Back as one "
        "\"Missed (date)\" section, replacing the previous one, so the answer side shows your latest gaps.",
        "Off: cards are never changed.")),
}


# Per-deck on/off settings: name -> (config key, label). On by default; setting a deck makes its subdecks follow.
DECK_TOGGLES = {
    "ai": ("deck_ai", "AI Study"),
    "sharp": ("deck_sharp", "Sharp questions"),
}


def toggle_on(cfg: dict, key: str) -> bool:
    return bool(cfg.get(key, True))


def toggle_change(cfg: dict, key: str) -> dict:
    """The change that flips a toggle (KeyError for anything that isn't one)."""
    TOGGLES[key]
    return {"set": {key: not toggle_on(cfg, key)}}


CONFIG_SYSTEM_PROMPT = """You manage the settings of an Anki add-on that uses an AI CLI (Claude Code or Codex) as a flashcard tutor. The user talks to you in plain language; you turn requests into changes.

Settings you can change (key: meaning):
""" + "\n".join(f"- {k}: {v}" for k, v in SETTINGS.items()) + """

Custom generic rules: a numbered list of plain-language instructions that apply to EVERY card (e.g. "grade strictly"). Rewrite vague requests into one clear, imperative rule.

Deck prompts: each Anki deck can have ONE free-text prompt that applies to cards in that deck and all its subdecks (subdecks inherit parent prompts). Use these when the user mentions a deck or "this deck" (= the selected deck). Use the exact full deck name from the deck list. Setting a deck prompt replaces the old one — when the user says "also …", merge the old prompt and the new request into one prompt. Never copy a parent deck's prompt into a subdeck's — it is already inherited.

Deck on/off settings (set_deck_ai, set_deck_sharp): on by default. Setting one on a deck makes all its subdecks follow (their own settings are dropped); set a subdeck afterwards to make an exception.
- AI Study (set_deck_ai): off = that deck's cards use Anki's plain reviewer, no AI.
- Sharp questions (set_deck_sharp): the AI first turns each card into sharp questions. Off = the user answers the card's own question as written (one AI call per card, faster).
A deck prompt CANNOT switch these — whenever the user wants AI Study or sharp questions on/off for a deck, use these changes, never a deck prompt. If a deck prompt only says to skip sharp questions, clear it in the same reply.

Each message gives you the current settings, custom rules, deck list, deck prompts, the selected deck and login state, then the user's request.

Reply with JSON only, no code fences:
{"reply": "<one or two short sentences to the user>", "changes": [<change>, ...]}

A change is one of:
{"set": {"<key>": <value>}}
{"add_custom": "<rule>"}
{"remove_custom": <rule number, 1-based>}
{"set_deck_prompt": {"deck": "<full deck name>", "prompt": "<the whole prompt>"}}
{"clear_deck_prompt": "<full deck name>"}
{"set_deck_ai": {"deck": "<full deck name>", "on": true | false | null}}      — null = remove the deck's setting (follow the parent deck; default on)
{"set_deck_sharp": {"deck": "<full deck name>", "on": true | false | null}}   — same, for sharp questions
{"undo": true}        — revert the user's previous change
{"login": true}       — sign in to the current provider's CLI (opens the browser)
{"logout": true}      — also signs the user out of that CLI on this computer; only when they explicitly ask to log out

Models: you cannot see which models the user's plan offers, and your own knowledge of model names is out of date. Never list, guess or recommend model names. If asked what models exist, tell the user to click the Model dropdown in Configurations — it loads the live list from their CLI. If the user names a model, set it exactly as given.

Only include changes the user asked for. If the request is unclear or impossible, ask a short question in "reply" with "changes": []. Questions about the settings need no changes."""


def config_prompt(cfg: dict, auth: str, message: str, decks: dict = None, selected: str = None,
                  model_in_use: str = None) -> str:
    """decks: full deck name -> id (as str). model_in_use: the real model id the CLI reports."""
    decks = decks or {}
    settings = {k: cfg.get(k) for k in SETTINGS}
    settings["model"] = model_for(cfg) or "(provider default)"
    if model_in_use:
        settings["model in use"] = model_in_use
    settings["models (per provider)"] = {p: model_for(cfg, p) for p in PROVIDERS}
    rules = "\n".join(f"{i}. {r}" for i, r in enumerate(cfg.get("custom") or [], 1)) or "(none)"
    names = {v: k for k, v in decks.items()}
    prompts = "\n".join(
        f"- {names[i]}: {p}" for i, p in (cfg.get("deck_prompts") or {}).items() if i in names
    ) or "(none)"
    toggles = "\n".join(
        f"- {names[i]}: {label} {'on' if v else 'off'}"
        for key, label in DECK_TOGGLES.values() for i, v in (cfg.get(key) or {}).items() if i in names
    ) or "(none)"
    if selected:
        chain = deck_chain(selected, decks, cfg.get("deck_prompts") or {})
        inherited = "\n".join(f"  {n}: {p}" for n, p in chain) or "  (no prompts on this path)"
        here = ", ".join(f"{label} {'on' if deck_toggle_on(cfg, t, selected, decks) else 'off'}"
                         for t, (_, label) in DECK_TOGGLES.items())
        sel = f"{selected}\nPrompts that apply to it (outer → inner):\n{inherited}\nHere: {here}"
    else:
        sel = "(none)"
    return (
        f"Current settings:\n{json.dumps(settings, indent=1)}\n\n"
        f"Custom generic rules:\n{rules}\n\n"
        f"Decks:\n" + ("\n".join(sorted(decks)) or "(none)") + "\n\n"
        f"Deck prompts:\n{prompts}\n\nDeck on/off settings (default on):\n{toggles}\n\nSelected deck: {sel}\n\n"
        f"Login: {auth}\n\nUser: {message}"
    )


def deck_chain(deck_name: str, decks: dict, prompts: dict) -> list:
    """[(deck name, prompt)] for the deck and its parents that have a prompt, outermost first."""
    parts = deck_name.split("::")
    chain = []
    for i in range(1, len(parts) + 1):
        name = "::".join(parts[:i])
        p = prompts.get(str(decks.get(name)), "").strip() if name in decks else ""
        if p:
            chain.append((name, p))
    return chain


def deck_toggle_source(cfg: dict, toggle: str, deck_name: str, decks: dict):
    """(on, deck name that decides it) — innermost deck setting on the path, else (True, None): on by default."""
    overrides = cfg.get(DECK_TOGGLES[toggle][0]) or {}
    parts = deck_name.split("::")
    for i in range(len(parts), 0, -1):
        name = "::".join(parts[:i])
        v = overrides.get(str(decks.get(name))) if name in decks else None
        if v is not None:
            return bool(v), name
    return True, None


def deck_toggle_on(cfg: dict, toggle: str, deck_name: str, decks: dict) -> bool:
    return deck_toggle_source(cfg, toggle, deck_name, decks)[0]


def deck_toggle_change(cfg: dict, toggle: str, deck_name: str, decks: dict) -> dict:
    """The change that flips a deck toggle for a deck (its subdecks follow)."""
    return {f"set_deck_{toggle}": {"deck": deck_name, "on": not deck_toggle_on(cfg, toggle, deck_name, decks)}}


def prune_deck_prompts(cfg: dict, deck_ids: set) -> dict:
    """Drop prompts and deck toggle settings of decks that no longer exist."""
    out = cfg
    for key in ("deck_prompts", *(k for k, _ in DECK_TOGGLES.values())):
        old = out.get(key) or {}
        kept = {i: v for i, v in old.items() if i in deck_ids}
        if kept != old:
            out = dict(out, **{key: kept})
    return out


def resolve_deck(name, decks: dict) -> str:
    """Deck name from the AI -> exact full name. Exact, then case-insensitive, then unique last component."""
    name = str(name or "").strip()
    if name in decks:
        return name
    lower = {k.lower(): k for k in decks}
    if name.lower() in lower:
        return lower[name.lower()]
    tail = [k for k in decks if k.split("::")[-1].lower() == name.lower()]
    if len(tail) == 1:
        return tail[0]
    if tail:
        raise ValueError(f"deck {name!r} is ambiguous: {', '.join(sorted(tail))}")
    raise ValueError(f"no deck named {name!r}")


def parse_config_reply(text: str) -> dict:
    obj = parse_json_reply(text)
    changes = obj.get("changes") or []
    if not isinstance(changes, list):
        raise ValueError("'changes' is not a list")
    return {"reply": str(obj.get("reply", "")).strip(), "changes": [c for c in changes if isinstance(c, dict)]}


def _validate(key: str, value, is_executable, provider: str = "claude"):
    if key == "provider":
        v = str(value).strip().lower()
        if v not in PROVIDERS:
            raise ValueError(f"unknown provider {v!r} — use {' or '.join(PROVIDERS)}")
        return v
    if key == "model":
        v = str(value).strip()
        if v.lower() in ("", "default"):
            return ""
        if provider == "codex":
            if v in CLAUDE_ALIASES or v.startswith("claude-") or " " in v:
                raise ValueError(f"{v!r} is not an OpenAI model id — Codex needs e.g. a gpt-… model, or default")
            return v
        if v in CLAUDE_ALIASES or v.startswith("claude-"):
            return v
        raise ValueError(f"unknown model {v!r} — use {', '.join(CLAUDE_ALIASES)} or a claude-… id")
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
        return _bool(key, value)
    if key in ("claude_path", "codex_path"):
        if str(value).strip().lower() in ("", "auto"):
            return ""
        v = os.path.expanduser(str(value).strip())
        if not is_executable(v):
            raise ValueError(f"{v} is not an executable file")
        return v
    raise ValueError(f"unknown setting {key!r}")


def _bool(key: str, value) -> bool:
    if isinstance(value, bool):
        return value
    if str(value).lower() in ("true", "on", "yes", "1"):
        return True
    if str(value).lower() in ("false", "off", "no", "0"):
        return False
    raise ValueError(f"{key} must be true or false")


def apply_changes(cfg: dict, changes: list, history: list, is_executable=None, decks: dict = None):
    """Validate and apply changes in order. decks: full deck name -> id (as str).

    history: stack of earlier configs (mutated: push on change, pop on undo).
    Returns (new_cfg, log_lines, auth_actions) where auth_actions ⊆ ["login", "logout"].
    """
    is_executable = is_executable or (lambda p: os.path.isfile(p) and os.access(p, os.X_OK))
    before = _normalize(cfg)
    new = _copy(before)
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
                items = sorted((ch["set"] or {}).items(), key=lambda kv: kv[0] != "provider")
                for key, value in items:
                    provider = provider_of(new)
                    try:
                        v = _validate(key, value, is_executable, provider)
                    except ValueError as e:
                        log.append(f"✗ {e}")
                        continue
                    if key == "model":
                        log.append(f"✓ {provider} model: {_show(new['models'].get(provider, ''))} → {_show(v)}")
                        new["models"][provider] = v
                    elif key == "provider":
                        log.append(f"✓ provider: {_show(provider)} → {v} (model: {_show(new['models'].get(v, ''))})")
                        new[key] = v
                    else:
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
            elif "set_deck_prompt" in ch:
                spec = ch["set_deck_prompt"] if isinstance(ch["set_deck_prompt"], dict) else {}
                name = resolve_deck(spec.get("deck"), decks or {})
                prompt = str(spec.get("prompt", "")).strip()
                if not prompt:
                    raise ValueError("empty deck prompt — ask to clear it instead")
                new["deck_prompts"] = dict(new.get("deck_prompts") or {}, **{str(decks[name]): prompt})
                log.append(f'✓ prompt for {name}: "{prompt}"')
            elif "clear_deck_prompt" in ch:
                name = resolve_deck(ch["clear_deck_prompt"], decks or {})
                prompts = dict(new.get("deck_prompts") or {})
                if prompts.pop(str(decks[name]), None) is None:
                    raise ValueError(f"{name} has no prompt")
                new["deck_prompts"] = prompts
                log.append(f"✓ cleared prompt for {name}")
            elif any(f"set_deck_{t}" in ch for t in DECK_TOGGLES):
                toggle = next(t for t in DECK_TOGGLES if f"set_deck_{t}" in ch)
                key, label = DECK_TOGGLES[toggle]
                spec = ch[f"set_deck_{toggle}"] if isinstance(ch[f"set_deck_{toggle}"], dict) else {}
                name = resolve_deck(spec.get("deck"), decks or {})
                on = spec.get("on")
                if on is not None:
                    on = _bool(label, on)
                overrides = dict(new.get(key) or {})
                if on is None:
                    if overrides.pop(str(decks[name]), None) is None:
                        raise ValueError(f"{name} has no {label} setting")
                    log.append(f"✓ {label} for {name}: follow parent (default on)")
                else:
                    # Subdecks follow immediately: drop their own settings.
                    subs = [str(i) for n, i in decks.items() if n.startswith(name + "::") and str(i) in overrides]
                    for i in subs:
                        del overrides[i]
                    overrides[str(decks[name])] = on
                    follow = f" ({len(subs)} subdeck setting(s) now follow it)" if subs else ""
                    log.append(f"✓ {label} for {name} and its subdecks: {'on' if on else 'off'}{follow}")
                new[key] = overrides
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


def _normalize(cfg: dict) -> dict:
    """Copy with a model entry per provider. Drops learned facts older versions kept here (now in state.py)
    and the old global sharp_questions toggle (now per deck: deck_sharp)."""
    out = _copy(cfg)
    out["models"] = {p: model_for(cfg, p) for p in PROVIDERS}
    for key in ("resolved_models", "last_good", "sharp_questions"):
        out.pop(key, None)
    return out


def _copy(cfg: dict) -> dict:
    return json.loads(json.dumps(cfg))


def _show(v) -> str:
    if v == "":
        return "default"
    return json.dumps(v) if isinstance(v, bool) else str(v)
