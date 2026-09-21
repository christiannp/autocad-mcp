"""Replace this machine's user folder with environment placeholders in the
generated JSON, so the committed data does not carry a Windows username.

AutoCAD echoes default filenames into its prompts, e.g.
    Enter file name <C:\\Users\\<you>\\AppData\\Local\\Temp\\...\\scratch.dxf>:
which is how the username ended up in probe_headless.json in the first place.

Idempotent - safe to re-run.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOCAL = os.environ["LOCALAPPDATA"]
ROAMING = os.environ["APPDATA"]
HOME = os.environ["USERPROFILE"]
USER = os.environ["USERNAME"]

# longest first, so the more specific prefix wins
SUBS = [
    (LOCAL, "%LOCALAPPDATA%"),
    (ROAMING, "%APPDATA%"),
    (HOME, "%USERPROFILE%"),
]


def variants(text: str) -> list[str]:
    """The same path as it appears raw and as JSON escapes it."""
    return [text, text.replace("\\", "\\\\"), text.replace("\\", "/")]


def scrub(path: Path) -> int:
    original = path.read_text(encoding="utf-8")
    text = original
    for real, placeholder in SUBS:
        for a, b in zip(variants(real), variants(placeholder)):
            text = text.replace(a, b)
    # anything left carrying the bare username is a miss worth knowing about
    leftover = len(re.findall(re.escape(USER), text, re.I))
    if text != original:
        path.write_text(text, encoding="utf-8")
    return leftover


def main() -> None:
    targets = sorted(ROOT.glob("build/*.json")) + sorted(ROOT.glob("docs/*.json"))
    for path in targets:
        leftover = scrub(path)
        rel = path.relative_to(ROOT)
        print(f"{rel}: {'clean' if not leftover else f'{leftover} left carrying the username'}")


if __name__ == "__main__":
    main()
