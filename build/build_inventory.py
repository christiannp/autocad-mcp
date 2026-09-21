"""Assemble the candidate command list from AutoCAD itself.

Sources, in order of authority:
  1. the CUIX files that define the UI on this machine - every ribbon button,
     menu item, toolbar button and double-click action
  2. acad.pgp - the command aliases, which name commands the UI may not
  3. the hyphen-prefixed twin of every command, because that is how Autodesk
     exposes dialog commands to scripts
"""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "acadmcp_cui"

# AutoCAD's own support folders, roaming (customised) first: a CUIX the user has
# edited lives there and shadows the shipped one.
RELEASE = os.environ.get("ACADMCP_ACAD_RELEASE", "AutoCAD 2025")
VERSION = os.environ.get("ACADMCP_ACAD_VERSION", "R25.0")
LANG = os.environ.get("ACADMCP_ACAD_LANG", "enu")

SUPPORT = [
    Path(os.environ["APPDATA"]) / "Autodesk" / RELEASE / VERSION / LANG / "Support",
    Path(r"C:\Program Files\Autodesk") / RELEASE / "UserDataCache" / "Support",
    Path(r"C:\Program Files\Autodesk") / RELEASE / "Support",
]
PGP = SUPPORT[0] / "acad.pgp"

# A macro can carry control prefixes between ^C^C and the command name, e.g.
# "^C^C_^Rrevcloud _R" - ^R suppresses the Ribbon, ^P toggles the prompt echo.
# Skipping them is the difference between finding REVCLOUD and missing it.
MACRO = re.compile(r"\^C\^C[_.^A-Z]*?_?\.?([A-Za-z-][A-Za-z0-9_-]{1,30})")
LISPCMD = re.compile(r'\(command\s+"_?\.?([A-Za-z-][A-Za-z0-9_-]{1,30})"')
# AutoCAD states the command a UI element maps to outright - the most reliable
# source of all, and it needs no parsing of macro syntax.
CLICMD = re.compile(r"<CLICommand[^>]*>([A-Za-z-][A-Za-z0-9_-]{1,30})</CLICommand>")
TOOLTIP = re.compile(r'<ToolTip[^>]*HelpTopic="([A-Za-z-][A-Za-z0-9_-]{1,30})"')
ALIAS = re.compile(r"^\s*([A-Za-z0-9_]+)\s*,\s*\*([A-Za-z0-9_-]+)", re.M)

# these would block a headless session waiting for something we cannot give
SKIP = {
    "QUIT", "EXIT", "CLOSE", "CLOSEALL", "NEW", "QNEW", "OPEN", "RECOVER",
    "RECOVERALL", "SAVE", "SAVEAS", "QSAVE", "WSSAVE", "RESUME", "SCRIPT",
    "RSCRIPT", "DELAY", "SHELL", "BROWSER", "NETLOAD", "APPLOAD", "VLIDE",
    "VLISP", "ARX", "SIGVALIDATE", "ATTACHURL", "LOGFILEON", "LOGFILEOFF",
}


def from_cuix() -> Counter:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()
    for folder in SUPPORT:
        if not folder.is_dir():
            continue
        for cuix in sorted(folder.glob("*.cuix")):
            if cuix.name.lower().endswith(".bak.cuix"):
                continue
            target = WORK / cuix.stem
            try:
                with zipfile.ZipFile(cuix) as zf:
                    zf.extractall(target)
            except Exception:  # noqa: BLE001
                continue
            for part in list(target.rglob("*.cui")) + list(target.rglob("*.xml")):
                try:
                    text = part.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for pattern in (MACRO, LISPCMD, CLICMD, TOOLTIP):
                    for m in pattern.finditer(text):
                        counts[m.group(1).upper()] += 1
    return counts


def from_pgp() -> set[str]:
    if not PGP.exists():
        return set()
    text = PGP.read_text(encoding="utf-8", errors="replace")
    return {m.group(2).upper() for m in ALIAS.finditer(text)}


def main() -> None:
    ui = from_cuix()
    pgp = from_pgp()

    names: set[str] = set(ui) | pgp
    names = {n for n in names if n and not n[0].isdigit()}

    # add the hyphen twin of every plain command, and the plain form of every
    # hyphen command - the probe will tell us which of them actually exist
    twins: set[str] = set()
    for n in names:
        twins.add("-" + n if not n.startswith("-") else n.lstrip("-"))
    names |= twins

    usable = sorted(n for n in names if n.lstrip("-") not in SKIP)

    payload = {
        "commands": usable,
        "counts": {
            "from_ui_cuix": len(ui),
            "from_pgp_aliases": len(pgp),
            "with_hyphen_twins": len(names),
            "probed": len(usable),
            "skipped_as_unsafe": sorted(SKIP),
        },
        "ui_reference_counts": dict(ui.most_common()),
    }
    out = ROOT / "build" / "inventory.json"
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print(f"UI commands from CUIX : {len(ui)}")
    print(f"aliases from acad.pgp : {len(pgp)}")
    print(f"after adding twins    : {len(names)}")
    print(f"to probe              : {len(usable)}  (skipping {len(SKIP)} unsafe)")
    print(f"written to {out}")


main()
