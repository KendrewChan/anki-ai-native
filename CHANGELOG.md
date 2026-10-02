# Changelog

What changed in each version, newest first. How the add-on works today is in [docs/spec.md](docs/spec.md).

## v1.30 — Highlight to ask (2026-10-02)

- Highlight any text on a card and click the blue **AI** bubble at its top-right to ask about it, on the front as well as the back. On the front the AI helps you understand the question without giving away the answer. On the back it answers questions or changes the note. This replaces the Ask AI box above the grading.
- Fixed: on the front, the bubble didn't appear when a drag across the question ended over the answer box.

## v1.29 — Grading in view (2026-10-02)

- Deck Settings: clicking the selected deck again closes it and removes the `Deck prompt for` prefix. The empty Default deck is hidden, as in Anki's deck list.
- The grading and the Ask AI box now sit right below the front of the card instead of above it, so they are on screen as soon as the answer shows (Anki scrolls the front out of view).

## v1.28 — Quick deck prompts (2026-10-02)

- Clicking a deck under Deck Settings fills the chat box with `Deck prompt for "<deck>": ` and puts the cursor at the end. Your own typed message is never overwritten. The chat box now stays pinned at the top while you scroll.
- Decks with a deck prompt but Rewrite question off show the card's question as normal (no Show original fold). The AI adds only what the prompt asks for, such as section boxes, and never repeats the question. When the prompt asks for nothing on the question side, you get the usual single box.

## v1.27 — Clearer tutor prompt; renames (2026-10-02)

- The tutor prompt is rewritten as principles. It describes once what the user sees (questions, one box each, parts, hints), and the patch-style rules from earlier fixes are folded into general ones, e.g. "verdicts agree upward". Behaviour and the reply format are unchanged.
- **Sharp questions** is now **Rewrite question**. Saying "sharp questions" in Settings still works.
- The **Deck Prompts** section in Settings is now **Deck Settings**. It holds each deck's prompt and its switches.
- The tutor knows all questions show on one page. Shared context such as the card's question appears once (opened via Show original) instead of being repeated in every question.

## v1.26 — Ask AI about the card (2026-10-02)

- The box above the verdict is now **Ask AI about this card, or to change it**. Ask a question and get an answer (bold and math rendered), or ask for a change to the note as before.
- Sharp questions: the AI now knows each question gets its own answer box while a question's parts share one. A deck prompt asking for a box per section gets separate boxes, and the card's question isn't repeated when it's shown open.

## v1.25 — Deck prompts apply on both sides (2026-10-02)

- A deck prompt now shapes the question side even when Sharp questions is off. The AI reads the card, keeps its question unless the prompt asks for something else (sections, more boxes, showing the question), and grading follows the prompt as before. Decks without a prompt and with Sharp questions off still skip the question step.

## v1.24 — Sharp questions from the front only (2026-10-02)

- The AI writes sharp questions and hints from the card's front alone and never sees the back at that step. Grading still compares your answer with the back.

## v1.23 — Deck prompts can shape the questions (2026-10-02)

- Deck prompts now override the tutor's defaults: number of questions (up to 8), their wording and sections, what to grade on. The AI can also show the card's own question open above its questions.
- Settings warns when a deck prompt shapes the question side but that deck has Sharp questions off, since such prompts need it on.
- Deck prompts have the highest priority: above Generic Rules, the tutor's defaults and the formatting guide. Only the JSON reply format is fixed.

## v1.22 — Your answer as graded bullet points (2026-10-02)

- The verdict lists your answer as short claims instead of repeating it. Each is green, orange or red, and orange or red ones say what's off and what's right.
- Grades must agree: a question with a partial or wrong claim can't be marked ✓, and the overall grade follows the question grades.

## v1.21 — Numbered sub-questions (2026-10-02)

- Sub-questions are numbered under their question (3.1, 3.2, …) instead of 1), 2), and each part has its own hint.
- The verdict numbers its rows the same way.
- Hint tooltips stay inside the window.

## v1.20 — Colour your answer, not the model answer (2026-10-02)

- When grading, the AI quotes the claims in your answer with a verdict each. The parts you got right show green, partly right orange, wrong red.
- The card's answer is no longer green: it shows in its normal colours.

## v1.19 — Formatting guide and math (2026-10-02)

- New `addon/style.md`, a formatting guide added to every AI prompt (tutor, note edit, Generate). It covers sparing bold, Anki HTML in card fields (lists only for parallel items, tables only for comparisons, no underline or colour unless asked) and LaTeX in `\( \)` / `\[ \]`.
- Bold and math now render in questions, hints, feedback, per-question notes and Missed bullets. Sharp questions and hints are typeset with Anki's MathJax.
- A sharp question asking for several parts lists them on separate lines as 1), 2), ….
- LaTeX written with single backslashes no longer breaks reply parsing.
- The per-question ✓ / ~ / ✗ marks are coloured green / orange / red.

## v1.18 — Edit the note after grading (2026-10-02)

- After grading, an **Ask AI to change this note** box sits above the verdict. The AI edits only that note's fields, the card redraws with the change, and Edit → Undo reverts it.

## v1.17 — Hints and coloured grading (2026-10-02)

- Each sharp question has a **?** hint tooltip: a short nudge from the same AI call, never the answer.
- After grading, your answer is red when wrong and orange when partial, and the card's answer is green (the Missed section keeps its normal colour).

## v1.16 — AI Study remembers ON/OFF (2026-10-02)

- The AI Study ON/OFF switch now stays as you left it when Anki restarts, instead of always starting OFF. Stored in `user_files/state.json`, so it isn't part of Settings' undo.

## v1.15 — Renamed to AI Quizzer (2026-10-02)

- The repo is now **anki-ai-quizzer** and the add-on shows as **AI Quizzer** in Anki's add-on list. The study mode keeps its name (AI Study), and the package stays `anki_ai`, so existing installs and settings carry over.

## v1.14 — AI Study per deck; deck panel under the deck (2026-10-02)

- New **AI Study** On/Off button per deck (on by default, same follow/exception rules as Sharp questions): off = that deck's cards use Anki's plain reviewer while AI Study is ON. Also via chat ("no AI for this deck").
- The deck panel opens directly under the clicked deck instead of below the whole tree.
- Fix: pressing a toggle or button in Settings no longer jumps the page back to the top.

## v1.13 — Sharp questions per deck (2026-10-02)

- Sharp questions are now set **per deck**: an On/Off button in the deck panel (or tell Settings "no sharp questions for this deck"). On by default. Switching a deck makes all its subdecks follow; a subdeck switched afterwards stays an exception until a parent is switched again.
- Removed the global **Sharp questions** toggle; the old setting is dropped on the next settings change.
- Fix: a deck prompt like "don't generate sharp questions" had no effect, because the choice is made before any AI call. The Settings AI now uses the new deck setting instead of a prompt.

## v1.12 — No answer box before sharp questions (2026-10-02)

- With **Sharp questions** on, the card no longer shows an answer box while the AI is thinking: the boxes appear with the questions, one per question. If the AI fails, a single box appears under the original. With it off (or for cloze), the box is ready immediately, as before.

## v1.11 — Simpler, safer (2026-10-02)

- **Removed Try AI repair.** It let an AI edit the add-on's own code, and nothing but the prompt stopped it from dropping the isolation flags. Update, Roll back, switch provider and Copy error report remain.
- Learned facts (real model names, last working CLI version) moved out of the settings into `user_files/state.json`: undo no longer rewinds them, and drawing Settings no longer saves the config. Old copies in the settings are dropped on the next change.
- `ChatPage` base class shared by Settings and Generate/Update (page lifecycle, Back, chat box, drafts); the fix buttons talk to Settings through a small public interface.
- Removed the migration for the pre-v1.5 single `model` setting.

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
