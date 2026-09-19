"""How big is 'everything the AutoCAD UI can do', really?

The UI is defined by the CUIX files: every ribbon button, menu item and
toolbar button carries a macro, and that macro is the command it runs. So the
set of commands reachable from the UI is exactly what we can pull out of them.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from collections import Counter
from pathlib import Path

SUPPORT = [
    Path(r"C:\Users\Wanda\AppData\Roaming\Autodesk\AutoCAD 2025\R25.0\enu\Support"),
    Path(r"C:\Program Files\Autodesk\AutoCAD 2025\UserDataCache\Support"),
    Path(r"C:\Program Files\Autodesk\AutoCAD 2025\Support"),
]

WORK = Path(r"C:\Users\Wanda\AppData\Local\Temp\acadmcp_cui")
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)

# a macro looks like  ^C^C_line  or ^C^C_.erase  or ^P(command "_.xxx")
TOKEN = re.compile(r"\^C\^C_?\.?([A-Za-z][A-Za-z0-9_-]{1,30})")
LISPCMD = re.compile(r'\(command\s+"_?\.?([A-Za-z][A-Za-z0-9_-]{1,30})"')

commands: Counter = Counter()
sources: dict[str, set[str]] = {}

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
        except Exception as exc:  # noqa: BLE001
            print(f"  could not open {cuix.name}: {exc}")
            continue
        found = 0
        # the payload inside a .cuix is .cui files, which are XML
        for xml in list(target.rglob("*.cui")) + list(target.rglob("*.xml")):
            try:
                text = xml.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern in (TOKEN, LISPCMD):
                for m in pattern.finditer(text):
                    name = m.group(1).upper()
                    commands[name] += 1
                    sources.setdefault(name, set()).add(cuix.name)
                    found += 1
        print(f"  {cuix.name:22s} {found:5d} macro references")

print(f"\nDISTINCT COMMANDS REACHABLE FROM THE UI: {len(commands)}")

# compare with what the server already covers with a dedicated tool
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from acadmcp.registry import mcp  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402
import asyncio  # noqa: E402

load_tools()
tools = asyncio.run(mcp.list_tools())
print(f"tools currently registered: {len(tools)}")

# which commands does the code already drive by name?
driven: set[str] = set()
for py in (Path(__file__).resolve().parent.parent.parent / "acadmcp").rglob("*.py"):
    text = py.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r'"_\.-?([A-Za-z][A-Za-z0-9_-]+)"', text):
        driven.add(m.group(1).upper().lstrip("-"))
print(f"commands driven explicitly in our code: {len(driven)}")
print("  " + ", ".join(sorted(driven)))

missing = sorted(set(commands) - driven)
print(f"\nUI commands with no dedicated handling: {len(missing)}")
print("\nTop 120 by how often the UI references them:")
for name, count in commands.most_common(120):
    mark = "*" if name in driven else " "
    print(f"  {mark} {name:24s} {count}")

out = Path(__file__).resolve().parent.parent.parent / "docs" / "ui-commands.txt"
out.parent.mkdir(exist_ok=True)
out.write_text("\n".join(sorted(commands)), encoding="utf-8")
print(f"\nfull list written to {out}")
