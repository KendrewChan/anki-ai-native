# Changelog

What changed in each version, newest first. How the add-on works today is in [docs/spec.md](docs/spec.md).

## v1.10.1 — Cleanup (2026-10-02)

- Fix: the Codex self-check now also starts the exact `--json` study command, so a CLI that rejects it can no longer pass Settings while studying fails. AI repair verifies with the same check.
- Fix: one rule decides "usage limit" for both the reviewer and Settings (they used to disagree).
- Single sources for the provider list, Claude model names, default provider, deck lookup and config loading; the reviewer's failure policy is now a tested function.
- Provider-neutral wording in the Settings AI prompt and the guide.

## v1.10 — Sharp questions on/off (2026-10-02)

- New setting `sharp_questions` (default on; chat: "turn off sharp questions"). Off = every card behaves like a cloze card: no ask call, one answer box, one AI call per card. Configs saved before the setting existed count as on.
- **Sharp questions** and **Missed append** are On/Off toggle buttons under Configurations, applied through `apply_changes` like a chat change.
- Each toggle has a small **?** help bubble (hover, click or Tab); long text wraps.

## v1.9.2 — Approve, then Submit (2026-10-02)

- **Approve** (card / deck / all) only marks staged cards; **Submit N approved** ports them. Unapproved cards stay staged; **Discard** deletes at once.
- An AI edit of an approved card clears its approval.
- Renamed **Generate** → **Generate/Update Cards**.
- UPDATE cards get **Show Original / Show Update**.
- **Approve all** becomes **Unapprove all (N)** once every card is approved.
- Fix: "target undo op not found" on Submit of ~15+ cards — every action now uses a few batched collection ops (Anki keeps only ~30 undo steps).
- Chat drafts and in-flight replies survive leaving Settings or Generate/Update. Fixes Settings staying disabled after leaving mid-reply.

## v1.9.1 — AI-GEN (2026-10-02)

- Staging deck renamed `AI Generate` → **AI-GEN**. Staged cards may now target a new top-level deck (lives as `AI-GEN::<Path>` until submitted).
- Accept / Discard per card and per deck, besides all.
- The user's message is echoed in the log; a live "⏳ Thinking… Ns" status shows while the AI works.
- Staged rows show the full question; expanding shows the other fields only.

## v1.9 — Generate cards (2026-10-02)

- New **✨ Generate** page: chat, reference file/folder picker (inside `~/Desktop` only), cards staged in a temporary deck, read existing decks to update their cards, Accept all / Discard all as one undo step each.

## v1.8 — Updates, self-check, fixes, AI repair (2026-10-02)

- CLI version row + **Update**; self-check on opening Settings.
- Failures are diagnosed and offered fix buttons (roll back, update, log in, more time, switch provider, copy report).
- Opt-in **Try AI repair** with validation, backup, self-check and auto-restore.

## v1.7 — Live model dropdown (2026-10-02)

- Model row is a dropdown filled from the CLI's live model list.
- The Settings AI is told it cannot see available models and points to the dropdown instead.

## v1.6 — Actual model names (2026-10-02)

- Settings shows the real model id (never "default"), read from the CLI's own output and cached in `resolved_models`.

## v1.5 — Settings polish (2026-10-02)

- Provider is a dropdown.
- Per-provider models (`models: {claude, codex}`); the legacy `model` key is migrated on the next save.
- Chat log shows the latest 3 replies; rejected changes appear in red inside the reply.

## v1.4 — Providers: Claude Code + Codex (2026-10-02)

- New `provider` setting: `claude` or `codex`.
- Requests are stateless: each prompt carries everything it needs.
- Codex runs one isolated `codex exec` per message.
- Per-provider login and CLI path.

## v1.3 — Single Missed section (2026-10-02)

- Each graded review **replaces** the card's Missed section instead of appending another one (`…: nothing` for a clean review).

## v1.2 — Deck prompts (2026-10-02)

- Settings gets **Custom Generic Rules** and **Deck Prompts**: one prompt per deck, inherited by subdecks, stored by deck id.

## v1.1 (2026-10-02)

- Up to 4 sharp questions per card, each with its own answer box; per-question marks in the grade.
- **AI Study ON/OFF** toggle on the home screen, deck overview and Tools menu. Off at every start.
- **⚙ Settings** page with a plain-English chat that edits the config.

## v1 (2026-10-02)

- Reviewer study loop: sharp question → typed answer → AI grade → recommended ease. Anki's own buttons still schedule.
- One isolated long-running `claude` process per review session.
- Missed bullets written to the card.
- Errors never block review.
