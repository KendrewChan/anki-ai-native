"""When the AI breaks: diagnose in plain words and offer fixes as buttons on a Settings reply.

Built-in fixes (update, roll back, switch provider, log in, more time, copy a report) come first.
"Try AI repair" is only offered for problems in the add-on's CLI integration, and nothing is
written until the user approves the proposed change.
"""

import os
import subprocess
import tempfile
import threading

from aqt import mw
from aqt.qt import QApplication

from . import health, repair
from .session import PROVIDER_LABELS, PROVIDERS, find_cli, make_backend


def _background(work, done):
    """work() off the main thread, then done(result_or_exception) on it."""
    def run():
        try:
            result = work()
        except Exception as e:  # handed to done(), which reports it
            result = e
        mw.taskman.run_on_main(lambda: done(result))

    threading.Thread(target=run, daemon=True).start()


class Fixer:
    def __init__(self, page):
        self.page = page

    # --- helpers ---

    def _cwd(self) -> str:
        self.page.cwd = self.page.cwd or tempfile.mkdtemp(prefix="anki_ai_cfg_")
        return self.page.cwd

    def _cfg(self) -> dict:
        return self.page._cfg()

    def _save(self, **fields):
        """Bookkeeping that isn't a user setting (no undo entry, no backend restart)."""
        mw.addonManager.writeConfig(self.page.addon, dict(self._cfg(), **fields))

    def _other(self, provider: str):
        other = next(p for p in PROVIDERS if p != provider)
        path = find_cli(other, self._cfg().get(f"{other}_path", ""))
        return other, path, os.path.isfile(path)

    # --- health check ---

    def check_on_open(self, announce: bool = False):
        """Version + self-check for the current provider; diagnose if it fails."""
        provider, path = self.page._provider()

        def work():
            try:
                version = health.cli_version(path)
            except Exception:
                version = None
            ok, detail = health.self_check(provider, path, self._cwd())
            return version, ok, detail

        def done(result):
            if isinstance(result, Exception):
                return
            version, ok, detail = result
            self.page.version[provider] = version or "not found"
            label = PROVIDER_LABELS[provider]
            if ok:
                if version:
                    self._save(last_good=dict(self._cfg().get("last_good") or {}, **{provider: version}))
                study_error = health.LAST_ERROR.pop(provider, None)
                if announce:
                    self.page.say(f"✓ {label} {version} works with AI Study.")
                elif study_error and health.classify(study_error) != "incompatible":
                    self.diagnose(provider, study_error)  # CLI is fine; explain what went wrong while studying
                else:
                    self.page._update(None)
            else:
                health.LAST_ERROR.pop(provider, None)
                self.diagnose(provider, detail)

        _background(work, done)

    # --- diagnosis ---

    def diagnose(self, provider: str, message: str):
        cfg = self._cfg()
        _provider, path = self.page._provider(cfg)
        label = PROVIDER_LABELS[provider]
        version = self.page.version.get(provider) or "?"
        kind = health.classify(message)
        actions = []
        if kind == "incompatible":
            text = f"{label} {version} changed something AI Study relies on."
            good = (cfg.get("last_good") or {}).get(provider)
            if good and good != version and good in health.installed_versions(provider, path):
                actions.append((f"Roll back to {good} (last working)", lambda: self.rollback(provider, good)))
            actions.append(("Update", self.update))
        elif kind == "auth":
            text = f"{label} isn't logged in."
            actions.append(("Log in", lambda: self.page._run_auth("login")))
        elif kind == "limit":
            text = (f"You've reached your {label} usage limit. Wait for it to reset, pick a lighter model, "
                    f"or switch provider.")
        elif kind == "timeout":
            text = f"{label} took too long to answer."
            actions.append(("Allow more time", self.raise_timeouts))
        elif kind == "missing":
            text = f"AI Study can't find {label} on this computer. Install it, or switch provider."
        else:
            text = f"{label} isn't working."
            actions.append(("Update", self.update))
        other, _other_path, has_other = self._other(provider)
        if has_other:
            actions.append((f"Use {PROVIDER_LABELS[other]}", lambda: self.switch(other)))
        if kind in ("incompatible", "other"):
            actions.append(("Try AI repair", lambda: self.try_repair(provider, path, version, message)))
        actions.append(("Copy error report", lambda: self.copy_report(provider, version, message)))
        detail = f"\n{message[:300]}" if kind in ("incompatible", "other") else ""
        self.page.say(text + detail, err=True, actions=actions)

    # --- built-in fixes ---

    def switch(self, provider: str):
        self.page._apply([{"set": {"provider": provider}}])
        self.check_on_open(announce=True)

    def raise_timeouts(self):
        cfg = self._cfg()
        ask = min(600, int(cfg.get("ask_timeout_s", 30)) * 2)
        grade = min(600, int(cfg.get("grade_timeout_s", 60)) * 2)
        self.page._apply([{"set": {"ask_timeout_s": ask, "grade_timeout_s": grade}}])
        self.page.say(f"Doubled the time limits: {ask}s for questions, {grade}s for grading.")

    def update(self):
        provider, path = self.page._provider()
        label = PROVIDER_LABELS[provider]
        before = self.page.version.get(provider, "?")
        self.page.say(f"Updating {label}…")

        def done(result):
            ok, out = result if not isinstance(result, Exception) else (False, str(result))
            if not ok:
                self.page.say(f"Update failed: {out[-300:]}", err=True,
                              actions=[("Copy error report", lambda: self.copy_report(provider, before, out))])
                return
            self.page.say(f"{label} update finished.")
            self.check_on_open(announce=True)

        _background(lambda: health.update(provider, path), done)

    def rollback(self, provider: str, version: str):
        _p, path = self.page._provider()
        label = PROVIDER_LABELS[provider]
        self.page.say(f"Switching {label} back to {version}…")

        def done(result):
            ok, out = result if not isinstance(result, Exception) else (False, str(result))
            if not ok:
                self.page.say(f"Roll back failed: {out[-300:]}", err=True)
                return
            self.check_on_open(announce=True)

        _background(lambda: health.rollback(provider, path, version), done)

    def copy_report(self, provider: str, version: str, message: str):
        QApplication.clipboard().setText(health.error_report(provider, version, message))
        self.page.say("Copied an error report — paste it to the add-on's author.")

    # --- AI repair (offered per incident, applied only on approval) ---

    def try_repair(self, provider: str, path: str, version: str, message: str):
        cfg = self._cfg()
        other, other_path, has_other = self._other(provider)
        self.page.say("Looking for a working AI to propose a fix…")

        def work():
            # Prefer the other provider: the broken one may not be able to run at all.
            candidates = ([(other, other_path)] if has_other else []) + [(provider, path)]
            fixer = next((p for p, cli in candidates if health.self_check(p, cli, self._cwd())[0]), None)
            help_cmd = [path, "exec", "--help"] if provider == "codex" else [path, "--help"]
            try:
                help_text = subprocess.run(help_cmd, capture_output=True, text=True, timeout=20,
                                           stdin=subprocess.DEVNULL).stdout
            except Exception as e:
                help_text = f"(could not read --help: {e})"
            return fixer, help_text

        def asked(result):
            if isinstance(result, Exception) or result[0] is None:
                self.page.say("No working AI is available to propose a fix. Try Update or Roll back, "
                              "or send an error report.", err=True,
                              actions=[("Copy error report", lambda: self.copy_report(provider, version, message))])
                return
            fixer, help_text = result
            backend = make_backend(dict(cfg, provider=fixer), repair.REPAIR_SYSTEM_PROMPT, self._cwd(),
                                   mw.taskman.run_on_main)
            self.page.say(f"Asking {PROVIDER_LABELS[fixer]} for a fix…")

            def proposed(_id, reply, err):
                backend.close()
                self.proposed(provider, path, version, message, reply, err)

            backend.request(0, repair.repair_prompt(message, provider, version, help_text),
                            repair.parse_repair, 300, proposed)

        _background(work, asked)

    def proposed(self, provider, path, version, message, reply, err):
        report = ("Copy error report", lambda: self.copy_report(provider, version, message))
        if err:
            self.page.say(f"Couldn't get a fix: {err.message}", err=True, actions=[report])
            return
        if not reply["edits"]:
            self.page.say(reply["summary"] or "The AI couldn't find a safe fix.", err=True, actions=[report])
            return
        try:
            edits = repair.validate(reply["edits"])
        except ValueError as e:
            self.page.say(f"The proposed fix wasn't safe to apply ({e}), so I left everything as it was.",
                          err=True, actions=[report])
            return
        apply = ("Apply fix", lambda: self.apply_repair(provider, path, version, message, edits))
        cancel = ("Cancel", lambda: self.page.say("OK, nothing was changed."))
        show = ("Show changes", lambda: self.page.say(repair.describe(edits), actions=[apply, cancel]))
        self.page.say(f"Proposed fix: {reply['summary']}", actions=[apply, show, cancel])

    def apply_repair(self, provider, path, version, message, edits):
        try:
            backup = repair.apply(edits)
        except (ValueError, OSError) as e:
            self.page.say(f"Couldn't apply the fix ({e}); nothing was changed.", err=True)
            return
        self.page.say("Applied — checking that it works…")

        def work():
            patched = repair.load_patched_session()
            try:
                return True, patched.probe_model(provider, path, "", self._cwd())
            except Exception as e:
                return False, getattr(e, "message", str(e))

        def done(result):
            ok, detail = result if not isinstance(result, Exception) else (False, str(result))
            label = PROVIDER_LABELS[provider]
            if ok:
                self.page.say(f"Fixed — {label} works with AI Study again. Restart Anki to use the repaired add-on.",
                              actions=[("Revert AI repair", self.revert_repair)])
            else:
                repair.revert(backup)
                self.page.say(f"The fix didn't work, so I undid it. ({detail[:200]})", err=True,
                              actions=[("Copy error report", lambda: self.copy_report(provider, version, message))])

        _background(work, done)

    def repair_applied(self) -> bool:
        return repair.latest_backup() is not None

    def revert_repair(self):
        backup = repair.latest_backup()
        if not backup:
            self.page.say("There's no AI repair to revert.")
            return
        repair.revert(backup)
        self.page.say("Reverted the AI repair. Restart Anki to load the original code.")
