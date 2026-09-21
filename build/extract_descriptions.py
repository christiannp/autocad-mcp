"""Pull AutoCAD's own descriptions for every UI command out of the CUIX.

Each <MenuMacro> carries what the interface shows the user:
  <Name>        the label on the button or menu item
  <Command>     the macro, e.g. ^C^C_trim
  <HelpString>  the status-bar description
  <CLICommand>  the command-line name Autodesk maps the button to
  <ToolTip HelpTopic="..."> the help topic id

That is more authoritative than anything scraped from the web, and it is
already on this machine.
"""

from __future__ import annotations

import html
import json
import os
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# written by build_inventory.py - the unpacked CUIX parts
WORK = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "acadmcp_cui"

BLOCK = re.compile(r"<Macro\b.*?</Macro>", re.S)
TAG = {
    "name": re.compile(r"<Name[^>]*>(.*?)</Name>", re.S),
    "command": re.compile(r"<Command[^>]*>(.*?)</Command>", re.S),
    "help": re.compile(r"<HelpString[^>]*>(.*?)</HelpString>", re.S),
    "cli": re.compile(r"<CLICommand[^>]*>(.*?)</CLICommand>", re.S),
}
TOPIC = re.compile(r'<ToolTip[^>]*HelpTopic="([^"]+)"')
MACROCMD = re.compile(r"\^C\^C_?\.?([A-Za-z-][A-Za-z0-9_-]{1,30})")


def clean(text: str | None) -> str:
    if not text:
        return ""
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def main() -> None:
    found: dict[str, dict] = defaultdict(dict)
    labels: dict[str, set] = defaultdict(set)
    scanned = 0

    for part in sorted(WORK.rglob("*.cui")):
        try:
            text = part.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # the folder is the cuix the part came from: acetmain = Express Tools
        origin = part.relative_to(WORK).parts[0].lower()
        for block in BLOCK.findall(text):
            scanned += 1
            name = clean(TAG["name"].search(block).group(1) if TAG["name"].search(block) else "")
            macro = clean(TAG["command"].search(block).group(1) if TAG["command"].search(block) else "")
            helps = clean(TAG["help"].search(block).group(1) if TAG["help"].search(block) else "")
            cli = clean(TAG["cli"].search(block).group(1) if TAG["cli"].search(block) else "")
            topic = TOPIC.search(block)

            targets: set[str] = set()
            if cli:
                targets.add(cli.upper().lstrip("_."))
            for m in MACROCMD.finditer(macro):
                targets.add(m.group(1).upper())
            if topic:
                targets.add(topic.group(1).upper())

            for command in targets:
                entry = found[command]
                if helps and len(helps) > len(entry.get("description", "")):
                    entry["description"] = helps
                if topic and "help_topic" not in entry:
                    entry["help_topic"] = topic.group(1)
                if name:
                    labels[command].add(name)
                entry.setdefault("source", origin)
                if origin == "acetmain":
                    entry["express_tool"] = True

    for command, names in labels.items():
        # the shortest label is usually the command's own name rather than a
        # long menu path like "Draw > Circle > Center, Radius"
        found[command]["ui_labels"] = sorted(names, key=len)[:4]

    out = ROOT / "build" / "descriptions.json"
    out.write_text(json.dumps(found, indent=1, ensure_ascii=False), encoding="utf-8")

    described = sum(1 for e in found.values() if e.get("description"))
    print(f"scanned {scanned} macro blocks")
    print(f"commands with any metadata : {len(found)}")
    print(f"commands with a description: {described}")
    print(f"written to {out}")
    for sample in ("TRIM", "OVERKILL", "TCOUNT", "SHEETSET", "OPTIONS", "BURST"):
        if sample in found:
            print(f"\n  {sample}: {json.dumps(found[sample], ensure_ascii=False)[:220]}")


main()
