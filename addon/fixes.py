"""When the AI breaks: diagnose in plain words and offer fixes as buttons on a Settings reply.

Fixes: update, roll back to the last working version, switch provider, log in, allow more time, copy a report.

The Settings page it reports to provides: cfg(), provider(cfg=None) -> (provider, cli path), apply(changes),
login(), say(text, err, actions) and refresh().
"""

import os
import tempfile
import threading

from aqt import mw
from aqt.qt import QApplication

from . import health, state
from .config_ops import TIMEOUT_RANGE
from .session import PROVIDER_LABELS, PROVIDERS, find_cli


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
        self.version = {}  # provider -> CLI version string, shown in Configurations
        self._cwd = None

    def cwd(self) -> str:
        self._cwd = self._cwd or tempfile.mkdtemp(prefix="anki_ai_check_")
        return self._cwd

    def _other(self, provider: str):
        other = next(p for p in PROVIDERS if p != provider)
        path = find_cli(other, self.page.cfg().get(f"{other}_path", ""))
        return other, path, os.path.isfile(path)

    def check_on_open(self, announce: bool = False):
        """Version + self-check for the current provider; diagnose if it fails."""
        provider, path = self.page.provider()

        def work():
            try:
                version = health.cli_version(path)
            except Exception:
                version = None
            ok, detail = health.self_check(provider, path, self.cwd())
            return version, ok, detail

        def done(result):
            if isinstance(result, Exception):
                return
            version, ok, detail = result
            self.version[provider] = version or "not found"
            label = PROVIDER_LABELS[provider]
            if ok:
                if version:
                    state.put("last_good", provider, version)
                study_error = health.LAST_ERROR.pop(provider, None)
                if announce:
                    self.page.say(f"✓ {label} {version} works with AI Study.")
                elif study_error and health.classify(study_error) != "incompatible":
                    self.diagnose(provider, study_error)  # CLI is fine; explain what went wrong while studying
                else:
                    self.page.refresh()
            else:
                health.LAST_ERROR.pop(provider, None)
                self.diagnose(provider, detail)

        _background(work, done)

    # --- diagnosis ---

    def diagnose(self, provider: str, message: str):
        _provider, path = self.page.provider()
        label = PROVIDER_LABELS[provider]
        version = self.version.get(provider) or "?"
        kind = health.classify(message)
        actions = []
        if kind == "incompatible":
            text = f"{label} {version} changed something AI Study relies on."
            good = state.get("last_good", provider)
            if good and good != version and good in health.installed_versions(provider, path):
                actions.append((f"Roll back to {good} (last working)", lambda: self.rollback(provider, good)))
            actions.append(("Update", self.update))
        elif kind == "auth":
            text = f"{label} isn't logged in."
            actions.append(("Log in", self.page.login))
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
        actions.append(("Copy error report", lambda: self.copy_report(provider, version, message)))
        detail = f"\n{message[:300]}" if kind in ("incompatible", "other") else ""
        self.page.say(text + detail, err=True, actions=actions)

    # --- fixes ---

    def switch(self, provider: str):
        self.page.apply([{"set": {"provider": provider}}])
        self.check_on_open(announce=True)

    def raise_timeouts(self):
        cfg = self.page.cfg()
        ask = min(TIMEOUT_RANGE[1], int(cfg.get("ask_timeout_s", 30)) * 2)
        grade = min(TIMEOUT_RANGE[1], int(cfg.get("grade_timeout_s", 60)) * 2)
        self.page.apply([{"set": {"ask_timeout_s": ask, "grade_timeout_s": grade}}])
        self.page.say(f"Doubled the time limits: {ask}s for questions, {grade}s for grading.")

    def update(self):
        provider, path = self.page.provider()
        label = PROVIDER_LABELS[provider]
        before = self.version.get(provider, "?")
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
        _p, path = self.page.provider()
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
