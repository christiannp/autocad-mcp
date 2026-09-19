"""The verified command registry.

Every AutoCAD command reachable from the UI, with the prompt chain AutoCAD
actually printed when we ran it, the option keywords parsed out of that text,
and a pointer to a dedicated tool where one exists.

The option keywords are the point. AutoCAD prints options as
[Ignore/tOlerance/Done] and expects the *capital letters* - so "tOlerance" is
`_O`. Sending `_T` leaves the command sitting at a prompt, which freezes COM.
Looking the keyword up here removes a whole class of failure.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent.parent / "docs" / "commands.json"

_lock = threading.Lock()
_db: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _db
    with _lock:
        if _db is None:
            if DATA.exists():
                _db = json.loads(DATA.read_text(encoding="utf-8"))
            else:
                _db = {"commands": {}, "totals": {}, "generated": "not built"}
    return _db


def available() -> bool:
    return bool(_load().get("commands"))


def totals() -> dict[str, Any]:
    data = _load()
    return {"generated": data.get("generated"), **data.get("totals", {})}


def normalise(name: str) -> str:
    text = str(name).strip().upper()
    for prefix in ("_.", "_", "."):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def lookup(name: str) -> dict[str, Any] | None:
    commands = _load().get("commands", {})
    key = normalise(name)
    if key in commands:
        return commands[key]
    # an alias?
    for entry in commands.values():
        if key in (entry.get("aliases") or []):
            return entry
    return None


def search(
    query: str | None = None,
    *,
    with_tool: bool | None = None,
    with_options: bool = False,
    only_existing: bool = True,
    limit: int = 50,
) -> list[dict[str, Any]]:
    commands = _load().get("commands", {})
    needle = (query or "").strip().upper()
    hits: list[tuple[int, dict[str, Any]]] = []

    for name, entry in commands.items():
        if only_existing and not entry.get("exists"):
            continue
        if with_tool is True and not entry.get("tool"):
            continue
        if with_tool is False and entry.get("tool"):
            continue
        if with_options and not entry.get("options"):
            continue

        score = 0
        if not needle:
            score = 1
        elif name == needle:
            score = 100
        elif needle in (entry.get("aliases") or []):
            score = 90
        elif name.startswith(needle):
            score = 70
        elif needle in name:
            score = 50
        elif needle in (entry.get("description") or "").upper():
            score = 40      # what it does matters more than what it is called
        elif needle in (entry.get("ui_label") or "").upper():
            score = 35
        else:
            blob = " ".join(entry.get("prompts", [])).upper()
            if needle in blob:
                score = 20
        if not score:
            continue
        # commands the UI actually exposes are more likely what was meant
        score += min(10, entry.get("ui_references", 0))
        hits.append((score, entry))

    hits.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return [entry for _, entry in hits[: max(1, int(limit))]]


def option_keyword(command: str, option: str) -> str | None:
    """Turn a human option name into the letters AutoCAD wants."""
    entry = lookup(command)
    if not entry:
        return None
    options: dict[str, str] = entry.get("options") or {}
    text = str(option).strip().lstrip("_").upper()
    for name, keyword in options.items():
        if name.upper() == text or keyword.upper() == text:
            return keyword
    # allow a unique prefix match, e.g. "toler" -> tOlerance
    matches = [k for n, k in options.items() if n.upper().startswith(text)]
    if len(matches) == 1:
        return matches[0]
    return None


def summarise(entry: dict[str, Any]) -> dict[str, Any]:
    """A compact row for listings."""
    out: dict[str, Any] = {"command": entry["name"]}
    if entry.get("description"):
        out["does"] = entry["description"]
    if entry.get("aliases"):
        out["aliases"] = entry["aliases"]
    if entry.get("tool"):
        out["tool"] = entry["tool"]
    if entry.get("prompts"):
        out["first_prompt"] = entry["prompts"][-1][:110]
    if entry.get("options"):
        out["options"] = list(entry["options"])[:12]
    if entry.get("likely_dialog_in_ui"):
        out["note"] = f"opens a dialog in the UI - use {entry.get('use_instead')}"
    if entry.get("needs_ui_check"):
        out["note"] = "not available in the headless engine; UI only"
    return out
