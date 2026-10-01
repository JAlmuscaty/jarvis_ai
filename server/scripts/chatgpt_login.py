"""Hermes ChatGPT (openai-codex) device sign-in without a terminal.

Run with Hermes' own venv python. Emits JSON lines on stdout:
  {"event": "code", "code": "...", "url": "..."}   user must approve this code
  {"event": "done"}                                 tokens saved to Hermes auth.json
  {"event": "error", "message": "..."}
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

HERMES_AGENT = Path(
    os.environ.get("HERMES_AGENT_DIR")
    or Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "hermes-agent"
)
DEVICE_URL = "https://auth.openai.com/codex/device"
_OUT = sys.stdout


def emit(**kw) -> None:
    _OUT.write(json.dumps(kw) + "\n")
    _OUT.flush()


class _CodeSniffer(io.TextIOBase):
    """_codex_device_code_login prints the code on the line after 'Enter this code'."""

    def __init__(self) -> None:
        self.buf = ""
        self.armed = False
        self.sent = False

    def write(self, s: str) -> int:
        self.buf += re.sub(r"\x1b\[[0-9;]*m", "", s)
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.strip()
            if not line or self.sent:
                continue
            if self.armed:
                emit(event="code", code=line, url=DEVICE_URL)
                self.sent = True
            elif "enter this code" in line.lower():
                self.armed = True
        return len(s)


def main() -> int:
    sys.path.insert(0, str(HERMES_AGENT))
    os.chdir(HERMES_AGENT)
    try:
        from hermes_cli import auth as A

        with contextlib.redirect_stdout(_CodeSniffer()):
            creds = A._codex_device_code_login()
        A._save_codex_tokens(creds["tokens"], creds.get("last_refresh"))
    except SystemExit:
        emit(event="error", message="Sign-in cancelled.")
        return 1
    except Exception as exc:
        emit(event="error", message=str(exc) or type(exc).__name__)
        return 1
    emit(event="done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
