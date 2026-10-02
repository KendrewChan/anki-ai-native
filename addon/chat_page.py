"""Shared by ⚙ Settings and ✨ Generate/Update Cards: a main-window page with a chat box, plus Anki helpers."""

import tempfile

from aqt import mw


def load_config(addon: str) -> dict:
    """The user's saved settings. Keys added after they were saved are missing: read them with defaults."""
    return mw.addonManager.getConfig(addon) or {}


def deck_ids() -> dict:
    """Full deck name -> deck id (str), the shape config_ops expects."""
    return {d.name: str(d.id) for d in mw.col.decks.all_names_and_ids(skip_empty_default=True)}  # as Anki's deck list


CSS = """
<style>
#cfg { max-width: 52em; margin: 1.2em auto; padding: 0 1em; text-align: left; }
#cfg a.back { cursor: pointer; opacity: 0.7; font-size: 0.9em; }
#cfg h2 { margin: 0.4em 0 0.6em; }
#log { max-height: 34vh; overflow-y: auto; font-size: 0.92em; margin-bottom: 0.5em; }
#log .you { margin-top: 0.6em; font-weight: 600; }
#log .ai { margin: 0.2em 0 0 1em; white-space: pre-wrap; }
#log .err { margin-left: 1em; color: #d33; white-space: pre-wrap; }
#cmd { width: 100%; box-sizing: border-box; padding: 0.6em; font: inherit; border-radius: 6px;
       border: 1px solid #8888; background: transparent; color: inherit; }
#status { font-size: 0.85em; opacity: 0.7; min-height: 1.3em; margin: 0.3em 0 0.8em; }
.sect h3 { margin: 1em 0 0.3em; font-size: 1em; text-transform: uppercase; letter-spacing: 0.05em; opacity: 0.7; }
.sect table { border-collapse: collapse; } .sect td { padding: 0.15em 1.2em 0.15em 0; vertical-align: top; }
.sect button { margin-left: 0.6em; } .sect select { font: inherit; }
</style>
"""


def chat_js(prefix: str) -> str:
    """Enter in the chat box (#cmd) sends "<prefix>:send:<text>"; every edit is kept as "<prefix>:draft:<text>"."""
    return """
<script>
(function () {
  const cmd = document.getElementById("cmd");
  cmd.addEventListener("keydown", function (e) {
    e.stopPropagation();  // Anki's shortcuts must not fire while typing
    if (e.key === "Enter" && !e.isComposing) {
      e.preventDefault();
      const v = this.value.trim();
      if (!v) return;
      this.value = "";
      pycmd("PREFIX:send:" + v);
    }
  });
  cmd.addEventListener("input", function () { pycmd("PREFIX:draft:" + this.value); });
  setTimeout(function () { cmd.focus(); }, 0);
})();
</script>
""".replace("PREFIX", prefix)


class ChatPage:
    """A main-window state (STATE) whose page talks back through "<PREFIX>:<command>:<arg>" bridge messages.

    Handles entering/leaving, Back, the chat draft and Send. Subclasses implement _page_html, _entered,
    _send(text), _on_message(command, arg) and _stop (end any AI process).
    """

    STATE = ""
    PREFIX = ""

    def __init__(self, addon: str):
        self.addon = addon
        self.cwd = None  # empty temp dir the AI CLI runs in
        self.busy = False  # a message is being answered
        self.draft = ""  # unsent text in the chat box, restored when the page reopens
        setattr(mw, f"_{self.STATE}State", self._enter)
        setattr(mw, f"_{self.STATE}Cleanup", self._leave)

    def open(self):
        mw.moveToState(self.STATE)

    def cfg(self) -> dict:
        return load_config(self.addon)

    def tmpdir(self) -> str:
        self.cwd = self.cwd or tempfile.mkdtemp(prefix=f"anki_ai_{self.PREFIX}_")
        return self.cwd

    def _enter(self, _old_state, *_args):
        mw.bottomWeb.hide()
        mw.web.stdHtml(self._page_html() + chat_js(self.PREFIX), context=self)
        mw.web.set_bridge_command(self._on_bridge, self)
        self._entered()

    def _leave(self, _new_state):
        if not self.busy:  # a message still being answered keeps running; its reply is kept for the next visit
            self._stop()
        mw.bottomWeb.show()

    def _on_bridge(self, message: str):
        prefix, _, rest = message.partition(":")
        if prefix != self.PREFIX:
            return
        command, _, arg = rest.partition(":")
        if command == "back":
            mw.moveToState("deckBrowser")
        elif command == "draft":
            self.draft = arg
        elif command == "send":
            if not self.busy:
                self.draft = ""
                self._send(arg)
        else:
            self._on_message(command, arg)
