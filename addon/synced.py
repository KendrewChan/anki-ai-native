"""Settings that travel with the collection through Anki sync. Takes a Collection; no aqt imports.

Anki syncs add-on files (meta.json, user_files) nowhere, but it syncs the collection:
- Deck settings (prompt, AI Study, Rewrite question) live on each deck object under DECK_KEY. Anki merges decks one
  by one (the newer deck wins), so edits to different decks on different devices both survive.
- General settings (custom rules, Missed append, timeouts) live in one collection config entry, CONFIG_KEY. Anki
  sends the whole config table from whichever side changed its collection last, so an edit made on one device
  before syncing can be overwritten by the other device's copy if that device changed its collection later.
- Everything else (provider, models, CLI paths) depends on the computer and stays in meta.json.
"""

DECK_KEY = CONFIG_KEY = "anki_ai"
SHARED = ("custom", "missed_append", "ask_timeout_s", "grade_timeout_s")
# config key -> field in the deck's DECK_KEY dict
DECK_FIELDS = {"deck_prompts": "prompt", "deck_ai": "ai", "deck_sharp": "sharp"}


def local_part(cfg: dict) -> dict:
    """What stays in meta.json."""
    return {k: v for k, v in cfg.items() if k not in SHARED and k not in DECK_FIELDS}


def deck_settings(decks: list) -> dict:
    """Deck dicts -> {"deck_prompts": {id: prompt}, "deck_ai": {id: bool}, "deck_sharp": {id: bool}}."""
    out = {key: {} for key in DECK_FIELDS}
    for deck in decks:
        mine = deck.get(DECK_KEY) or {}
        for key, field in DECK_FIELDS.items():
            if field in mine:
                out[key][str(deck["id"])] = mine[field]
    return out


def deck_value(cfg: dict, deck_id: str) -> dict:
    """The DECK_KEY dict a deck should carry for cfg ({} = nothing set)."""
    return {field: cfg[key][deck_id] for key, field in DECK_FIELDS.items() if deck_id in (cfg.get(key) or {})}


def load(col, local: dict) -> dict:
    """meta.json settings (with defaults) overlaid with the collection's synced ones."""
    cfg = dict(local)
    cfg.update({k: v for k, v in (col.get_config(CONFIG_KEY, None) or {}).items() if k in SHARED})
    cfg.update(deck_settings(col.decks.all()))
    return cfg


def save(col, cfg: dict):
    """Write the synced part of cfg to the collection, touching only what changed (so only changed decks get a
    newer modification time and win the next sync)."""
    shared = {k: cfg[k] for k in SHARED if k in cfg}
    if shared != (col.get_config(CONFIG_KEY, None) or {}):
        col.set_config(CONFIG_KEY, shared)
    for deck in col.decks.all():
        want = deck_value(cfg, str(deck["id"]))
        if want != (deck.get(DECK_KEY) or {}):
            if want:
                deck[DECK_KEY] = want
            else:
                deck.pop(DECK_KEY, None)
            col.decks.save(deck)


def migrate(col, legacy: dict) -> bool:
    """First run on a collection: copy settings older versions kept in meta.json into it.

    General settings only if the collection has none yet (another device may have synced its own); deck settings
    only onto decks that carry none. Returns True if anything was written.
    """
    wrote = False
    if col.get_config(CONFIG_KEY, None) is None and any(k in legacy for k in SHARED):
        col.set_config(CONFIG_KEY, {k: legacy[k] for k in SHARED if k in legacy})
        wrote = True
    for deck in col.decks.all():
        if DECK_KEY in deck:
            continue
        want = deck_value(legacy, str(deck["id"]))
        if want:
            deck[DECK_KEY] = want
            col.decks.save(deck)
            wrote = True
    return wrote
