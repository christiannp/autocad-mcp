"""Exercise the command registry tools and the option-keyword resolution."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import winui  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402

winui.press_escape(2)
load_tools()

from acadmcp.tools.commands import command_help, command_search  # noqa: E402

passed = failed = 0


def show(label, value, expect=None):
    global passed, failed
    ok = True if expect is None else expect(value)
    passed, failed = (passed + (1 if ok else 0), failed + (0 if ok else 1))
    print(f"[{'ok' if ok else 'FAIL'}] {label}\n"
          f"      {json.dumps(value, ensure_ascii=False)[:430]}\n", flush=True)


print("=== the registry knows itself ===", flush=True)
show("totals", command_search(limit=1)["registry"],
     lambda v: v.get("exist", 0) > 700)

print("=== finding a command by what it does ===", flush=True)
show("search 'duplicate'", command_search("duplicate", limit=4),
     lambda v: any("OVERKILL" in c["command"] for c in v["commands"]))
show("search 'hatch'", command_search("hatch", limit=6),
     lambda v: v["matches"] > 0)
show("search 'text' with options only", command_search("text", only_with_options=True, limit=5),
     lambda v: v["matches"] > 0)

print("=== the option-keyword rule, which is the whole point ===", flush=True)
trim = command_help("TRIM")
show("TRIM: mOde -> O", trim,
     lambda v: v.get("options", {}).get("mOde") == "O")

layer = command_help("-LAYER")
show("-LAYER keywords", {"options": layer.get("options")},
     lambda v: v["options"].get("TRansparency") == "TR"
     and v["options"].get("LWeight") == "LW"
     and v["options"].get("stAte") == "A")

print("=== aliases resolve ===", flush=True)
show("alias 'TR' finds TRIM", command_help("TR"), lambda v: v["command"] == "TRIM")
show("alias 'CO' finds COPY", command_help("CO"), lambda v: v["command"] == "COPY")

print("=== dialog commands point at their scriptable twin ===", flush=True)
show("PURGE", command_help("PURGE"),
     lambda v: v.get("tool") == "purge" or "use_instead" in v)

print("=== commands with no dedicated tool still explained ===", flush=True)
for name in ("UCS", "PEDIT", "DIMEDIT", "SECTIONPLANE", "REVCLOUD", "WIPEOUT"):
    entry = command_help(name)
    show(name, {k: entry.get(k) for k in ("command", "description", "options", "default")},
         lambda v: bool(v.get("description")) or bool(v.get("options")))

print("=== express tools are documented ===", flush=True)
for name in ("BURST", "FLATTEN", "TXT2MTXT", "TCOUNT"):
    entry = command_help(name)
    show(name, {k: entry.get(k) for k in ("command", "description", "exists")},
         lambda v: bool(v.get("description")))

print("=== commands we never ran are honest about it ===", flush=True)
show("QUIT", command_help("QUIT"),
     lambda v: "not run" in json.dumps(v) or "intentionally" in json.dumps(v))

print(f"\n{passed} passed, {failed} failed", flush=True)
sys.exit(1 if failed else 0)
