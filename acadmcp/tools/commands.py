"""Discovering and understanding AutoCAD's own commands."""

from __future__ import annotations

from typing import Any

from .. import commands_db
from ..errors import AcadError, NotFound
from ..registry import tool


@tool(readonly=True, description=(
    "Search AutoCAD's commands. Every command reachable from the AutoCAD UI is "
    "here with the prompts it actually asks and the option keywords it accepts, "
    "captured by running it. Use this to find out how to do something the "
    "dedicated tools do not cover, then run it with cad_command."
))
def command_search(
    query: str | None = None,
    with_dedicated_tool: bool | None = None,
    only_with_options: bool = False,
    limit: int = 40,
) -> dict[str, Any]:
    if not commands_db.available():
        raise AcadError(
            "The command registry has not been built on this machine yet. "
            "Run build/probe_commands.py then build/build_registry.py."
        )
    hits = commands_db.search(
        query,
        with_tool=with_dedicated_tool,
        with_options=only_with_options,
        limit=limit,
    )
    return {
        "matches": len(hits),
        "commands": [commands_db.summarise(h) for h in hits],
        "registry": commands_db.totals(),
    }


@tool(readonly=True, description=(
    "Everything known about one AutoCAD command: its real prompt sequence, the "
    "option keywords (the letters AutoCAD wants, e.g. tOlerance is 'O'), its "
    "aliases, whether it opens a dialog, and whether a dedicated tool already "
    "does the job. Check this before driving an unfamiliar command."
))
def command_help(name: str) -> dict[str, Any]:
    if not commands_db.available():
        raise AcadError(
            "The command registry has not been built on this machine yet."
        )
    entry = commands_db.lookup(name)
    if not entry:
        near = commands_db.search(name, limit=8)
        raise NotFound(
            f"No command called {name!r}. "
            + ("Did you mean: " + ", ".join(e["name"] for e in near) + "?" if near else "")
        )

    out: dict[str, Any] = {
        "command": entry["name"],
        "description": entry.get("description"),
        "exists": entry.get("exists", False),
        "in_autocad_ui": entry.get("in_ui", False),
    }
    for key in ("ui_label", "kind", "aliases", "prompts", "options", "default",
                "tool", "use_instead", "note", "express_tool", "help_topic",
                "confidence", "not_probed_because"):
        if entry.get(key):
            out[key] = entry[key]
    out = {k: v for k, v in out.items() if v is not None}
    if entry.get("interactive"):
        out["interactive"] = (
            "asks you to pick points or select objects - pass them to "
            "cad_command as arguments, in the order the prompts ask"
        )
    if entry.get("likely_dialog_in_ui"):
        out["dialog"] = (
            "in the AutoCAD window this opens a dialog box; the hyphen version "
            f"({entry.get('use_instead')}) asks the same questions on the "
            "command line and is what you should script"
        )
    if entry.get("needs_ui_check"):
        out["availability"] = (
            "not present in AutoCAD's headless engine - it is a UI-only or "
            "Express Tools command, so it must run in the open AutoCAD window"
        )
    if entry.get("options"):
        out["how_to_send_options"] = {
            "example": [f"_{k}" for k in list(entry["options"].values())[:3]],
            "rule": "prefix the keyword with an underscore so it works whatever "
                    "language AutoCAD is running in",
        }
    if entry.get("tool"):
        out["advice"] = (
            f"the {entry['tool']} tool wraps this command and handles the "
            "prompt sequence for you"
        )
    return out
