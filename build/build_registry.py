"""Turn the probe results into a verified command registry.

The valuable part is the option keywords. AutoCAD prints its options as
[Ignore/tOlerance/Plines/Done] and the keyword you must type is the *capital
letters* of each option - so "tOlerance" is O, not T, and "TRansparency" is TR.
Guessing that wrong leaves AutoCAD sitting at a prompt, which is exactly the
bug that cost us an hour with OVERKILL. Extracting it mechanically from the
real prompt text means it is never guessed again.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = os.environ.get("ACADMCP_ACAD_RELEASE", "AutoCAD 2025")
VERSION = os.environ.get("ACADMCP_ACAD_VERSION", "R25.0")
LANG = os.environ.get("ACADMCP_ACAD_LANG", "enu")
PGP = (
    Path(os.environ["APPDATA"])
    / "Autodesk"
    / RELEASE
    / VERSION
    / LANG
    / "Support"
    / "acad.pgp"
)

BRACKET = re.compile(r"\[([^\]]+)\]")
DEFAULT = re.compile(r"<([^>]{1,40})>\s*:?\s*$")
ALIAS = re.compile(r"^\s*([A-Za-z0-9_]+)\s*,\s*\*([A-Za-z0-9_-]+)", re.M)

# prompts that mean "this wants you to pick something on screen"
PICK = re.compile(
    r"\b(select|specify|pick|click|enter point|first point|second point|"
    r"base point|insertion point)\b",
    re.I,
)


def keyword(option: str) -> str:
    """The letters AutoCAD actually accepts for an option.

    The capitals in the option name are the keyword: Make -> M,
    tOlerance -> O, TRansparency -> TR, LWeight -> LW, stAte -> A.
    """
    caps = "".join(ch for ch in option if ch.isupper())
    return caps or option[:1].upper()


def parse_options(prompts: list[str]) -> dict[str, str]:
    options: dict[str, str] = {}
    for line in prompts:
        for group in BRACKET.findall(line):
            for raw in group.split("/"):
                name = raw.strip()
                if not name or " " in name and len(name) > 24:
                    continue
                # strip trailing explanatory text like "Ttr (tan tan radius)"
                short = name.split("(")[0].strip()
                if not short:
                    continue
                options[short] = keyword(short)
    return options


def parse_default(prompts: list[str]) -> str | None:
    for line in reversed(prompts):
        m = DEFAULT.search(line.strip())
        if m:
            return m.group(1)
    return None


def load_aliases() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if PGP.exists():
        text = PGP.read_text(encoding="utf-8", errors="replace")
        for m in ALIAS.finditer(text):
            out.setdefault(m.group(2).upper(), []).append(m.group(1).upper())
    return {k: sorted(set(v)) for k, v in out.items()}


def dedicated_tools() -> dict[str, str]:
    """Which commands already have a first-class tool in the server."""
    return {
        "LINE": "draw_line", "PLINE": "draw_polyline", "RECTANG": "draw_rectangle",
        "CIRCLE": "draw_circle", "ARC": "draw_arc", "ELLIPSE": "draw_ellipse",
        "SPLINE": "draw_spline", "POINT": "draw_point", "HATCH": "draw_hatch",
        "-HATCH": "draw_hatch", "XLINE": "draw_construction_line",
        "RAY": "draw_construction_line",
        "MOVE": "entity_move", "COPY": "entity_copy", "ROTATE": "entity_rotate",
        "SCALE": "entity_scale", "MIRROR": "entity_mirror", "OFFSET": "entity_offset",
        "ARRAY": "entity_array", "-ARRAY": "entity_array", "ERASE": "entity_delete",
        "TRIM": "entity_trim", "EXTEND": "entity_extend", "FILLET": "entity_fillet",
        "CHAMFER": "entity_chamfer", "JOIN": "entity_join", "EXPLODE": "entity_explode",
        "BREAK": "entity_break", "OVERKILL": "entity_overkill",
        "-OVERKILL": "entity_overkill", "MATCHPROP": "match_properties",
        "PROPERTIES": "entity_properties", "CHPROP": "entity_properties",
        "LAYER": "layer_set", "-LAYER": "layer_set", "LAYMRG": "layer_merge",
        "-LAYMRG": "layer_merge", "LAYISO": "layer_state", "LAYUNISO": "layer_state",
        "LINETYPE": "linetype", "-LINETYPE": "linetype",
        "STYLE": "text_style", "-STYLE": "text_style",
        "DIMSTYLE": "dim_style", "-DIMSTYLE": "dim_style",
        "TEXT": "draw_text", "DTEXT": "draw_text", "MTEXT": "draw_mtext",
        "-MTEXT": "draw_mtext", "LEADER": "draw_leader", "QLEADER": "draw_leader",
        "MLEADER": "draw_leader", "TABLE": "draw_table", "-TABLE": "draw_table",
        "FIND": "text_find_replace", "DDEDIT": "text_edit", "TEXTEDIT": "text_edit",
        "DIMLINEAR": "draw_dimension", "DIMALIGNED": "draw_dimension",
        "DIMANGULAR": "draw_dimension", "DIMRADIUS": "draw_dimension",
        "DIMDIAMETER": "draw_dimension", "DIMORDINATE": "draw_dimension",
        "DIMARC": "draw_dimension", "DIM": "draw_dimension",
        "BLOCK": "block_define", "-BLOCK": "block_define",
        "INSERT": "block_insert", "-INSERT": "block_insert",
        "WBLOCK": "block_export", "-WBLOCK": "block_export",
        "ATTEDIT": "block_attributes", "-ATTEDIT": "block_attributes",
        "EATTEDIT": "block_attributes", "BATTMAN": "block_attributes",
        "XREF": "xref", "-XREF": "xref", "XATTACH": "xref", "ATTACH": "xref",
        "LAYOUT": "layout_manage", "-LAYOUT": "layout_manage",
        "PAGESETUP": "page_setup", "MVIEW": "viewport_create",
        "-VPORTS": "viewport_create", "VPORTS": "viewport_create",
        "PLOT": "plot", "-PLOT": "plot", "PUBLISH": "plot", "-PUBLISH": "plot",
        "EXPORT": "export", "DXFOUT": "export", "SAVEAS": "doc_save",
        "PURGE": "purge", "-PURGE": "purge", "AUDIT": "purge",
        "ZOOM": "zoom", "REGEN": "regen", "REGENALL": "regen",
        "SETVAR": "sysvar", "DATAEXTRACTION": "data_extract",
        "-DATAEXTRACTION": "data_extract", "EATTEXT": "data_extract",
        "LIST": "entity_info", "DBLIST": "entity_summary",
        "DIST": "measure", "MEASUREGEOM": "measure", "AREA": "measure",
        "QSELECT": "entity_select", "FILTER": "entity_select",
        "SCRIPT": "cad_script",
        # added with the 2026-09-22 tool set
        "UNDO": "undo",
        "U": "undo",
        "REDO": "undo",
        "MREDO": "undo",
        "VIEW": "view",
        "-VIEW": "view",
        "UCS": "ucs",
        "STRETCH": "entity_stretch",
        "ALIGN": "entity_align",
        "LENGTHEN": "entity_lengthen",
        "PEDIT": "polyline_edit",
        "REVERSE": "polyline_edit",
        "DIVIDE": "entity_divide",
        "MEASURE": "entity_divide",
        "DRAWORDER": "draw_order",
        "HATCHTOBACK": "draw_order",
        "TEXTTOFRONT": "draw_order",
        "CHSPACE": "entity_change_space",
        "GROUP": "group",
        "-GROUP": "group",
        "POLYGON": "draw_polygon",
        "REVCLOUD": "draw_revcloud",
        "WIPEOUT": "draw_wipeout",
        "REGION": "region",
        "UNION": "region",
        "SUBTRACT": "region",
        "INTERSECT": "region",
        "BOUNDARY": "boundary",
        "-BOUNDARY": "boundary",
        "BPOLY": "boundary",
        "MLEADER": "draw_mleader",
        "DIMCONTINUE": "dimension_chain",
        "DIMBASELINE": "dimension_chain",
        "DIMEDIT": "dimension_edit",
        "DIMTEDIT": "dimension_edit",
        "TABLEDIT": "table_edit",
        "DATALINKUPDATE": "table_edit",
        "TXT2MTXT": "text_combine",
        "OBJECTSCALE": "annotation_scale",
        "-OBJECTSCALE": "annotation_scale",
        "SCALELISTEDIT": "annotation_scale",
        "-SCALELISTEDIT": "annotation_scale",
        "LAYERSTATE": "layer_states",
        "-LAYERSTATE": "layer_states",
        "LAYERSTATESAVE": "layer_states",
        "ADCENTER": "standards_import",
        "LAYTRANS": "standards_import",
        "-LAYTRANS": "standards_import",
        "ATTSYNC": "attribute_sync",
        "IMAGEATTACH": "underlay",
        "-IMAGE": "underlay",
        "IMAGE": "underlay",
        "IMAGEADJUST": "underlay",
        "-IMAGEADJUST": "underlay",
        "PDFATTACH": "underlay",
        "-PDFATTACH": "underlay",
        "PDFIMPORT": "pdf_import",
        "-PDFIMPORT": "pdf_import",
        "SAVEIMG": "render",
        "-PLOT": "plot",
    }


def load_ui_probe() -> dict[str, dict]:
    path = ROOT / "build" / "probe_ui.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


DIALOG_WORDS = re.compile(
    r"\b(dialog|dialogue|palette|manager|wizard|browser|editor window|"
    r"opens the|displays the|launches)\b", re.I
)
PALETTE_SUFFIX = ("CLOSE", "OPEN", "PALETTE", "PALETTECLOSE")


def classify(name: str, entry: dict, meta: dict) -> str:
    """What kind of thing is this command, for someone deciding how to use it."""
    text = (meta.get("description") or "").lower()
    if meta.get("express_tool"):
        return "express tool"
    if name.endswith(PALETTE_SUFFIX) and ("palette" in text or "close" in text
                                          or name.endswith("CLOSE")):
        return "palette toggle"
    if entry.get("prompts") and entry.get("options"):
        return "command line"
    if DIALOG_WORDS.search(text):
        return "dialog"
    if entry.get("prompts"):
        return "command line"
    return "other"


def load_descriptions() -> dict[str, dict]:
    path = ROOT / "build" / "descriptions.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


# Commands deliberately never probed: running them would close AutoCAD, lose
# unsaved work, or load arbitrary code. They are not unknown - we know exactly
# what they do, and most already have a dedicated tool.
NEVER_PROBED = {
    "QUIT": ("Closes AutoCAD", None),
    "EXIT": ("Closes AutoCAD", None),
    "CLOSE": ("Closes the current drawing", "doc_close"),
    "CLOSEALL": ("Closes every open drawing", "doc_close"),
    "NEW": ("Starts a new drawing", "doc_new"),
    "QNEW": ("Starts a new drawing from the default template", "doc_new"),
    "OPEN": ("Opens an existing drawing", "doc_open"),
    "SAVE": ("Saves the drawing", "doc_save"),
    "QSAVE": ("Saves the drawing without prompting", "doc_save"),
    "SAVEAS": ("Saves the drawing under a new name or format", "doc_save"),
    "RECOVER": ("Repairs and opens a damaged drawing", "doc_open"),
    "RECOVERALL": ("Repairs a drawing and all its xrefs", None),
    "WSSAVE": ("Saves the current workspace", None),
    "APPLOAD": ("Loads an application (LISP/ARX/.NET)", None),
    "ARX": ("Loads or unloads ObjectARX applications", None),
    "NETLOAD": ("Loads a .NET assembly", None),
    "VLIDE": ("Opens the Visual LISP editor", "cad_lisp"),
    "BROWSER": ("Opens a web browser", None),
    "DELAY": ("Pauses a running script", None),
}


def _coverage(registry: dict[str, dict], ui_counts: dict[str, int]) -> dict:
    """How much of the AutoCAD UI can this server reach, stated honestly.

    Three tiers, because they are genuinely different levels of confidence:
      verified   - we ran it and captured the prompts it asks
      documented - AutoCAD's own UI definition wires a button to it and gives
                   a description, but we did not execute it
      unknown    - neither
    Every tier is still *reachable* through cad_command; the tiers describe how
    much is known about how to drive it, not whether it can be invoked.
    """
    ui_commands = [n for n in ui_counts if not n.startswith("-")]
    verified, documented, unknown = [], [], []
    for name in ui_commands:
        entry = registry.get(name, {})
        twin = registry.get("-" + name, {})
        if entry.get("prompts") or twin.get("prompts"):
            verified.append(name)
        elif entry.get("description") or entry.get("in_ui"):
            documented.append(name)
        else:
            unknown.append(name)
    total = max(1, len(ui_commands))
    return {
        "ui_commands": len(ui_commands),
        "verified_by_running_them": len(verified),
        "documented_from_autocad_ui_definition": len(documented),
        "unknown": len(unknown),
        "percent_verified": round(100 * len(verified) / total, 1),
        "percent_covered": round(100 * (len(verified) + len(documented)) / total, 1),
        "reachable_via_cad_command": "all of them",
        "unknown_list": sorted(unknown)[:60],
    }


def main() -> None:
    probe = json.loads((ROOT / "build" / "probe_headless.json").read_text(encoding="utf-8"))
    ui_probe = load_ui_probe()
    inventory = json.loads((ROOT / "build" / "inventory.json").read_text(encoding="utf-8"))
    ui_counts: dict[str, int] = inventory.get("ui_reference_counts", {})
    aliases = load_aliases()
    tools = dedicated_tools()
    meta_all = load_descriptions()

    names = sorted(probe)
    exists = {n for n in names if probe[n].get("exists_headless")}

    registry: dict[str, dict] = {}
    for name in names:
        info = probe[name]
        prompts = [
            p for p in info.get("output", [])
            if p and not p.startswith("Unknown command")
        ]
        plain = name.lstrip("-")
        twin = ("-" + plain) if not name.startswith("-") else plain

        ui = ui_probe.get(name, {})
        if ui:
            # the running application is the authority: accoreconsole simply
            # does not have the palette, dialog and Express Tools commands
            ui_lines = [
                l for l in ui.get("output", [])
                if l and not l.startswith("Unknown command")
            ]
            if ui.get("exists_ui") and not prompts:
                prompts = ui_lines

        entry: dict = {
            "name": name,
            "exists": bool(info.get("exists_headless")) or bool(ui.get("exists_ui")),
            "in_ui": ui_counts.get(name, 0) > 0,
            "ui_references": ui_counts.get(name, 0),
        }
        if ui:
            entry["verified_in_application"] = bool(ui.get("exists_ui"))
            if not info.get("exists_headless") and ui.get("exists_ui"):
                entry["headless"] = False
                entry["note"] = (
                    "only available in the AutoCAD window, not in the headless engine"
                )
            if ui.get("dialog"):
                entry["opens_dialog"] = ui["dialog"]
        if aliases.get(name):
            entry["aliases"] = aliases[name]
        if info.get("exists_headless") is None:
            entry["needs_ui_check"] = True
            entry["note"] = info.get("note", "")
        if prompts:
            entry["prompts"] = prompts[:8]
            opts = parse_options(prompts)
            if opts:
                entry["options"] = opts
            default = parse_default(prompts)
            if default:
                entry["default"] = default
            entry["interactive"] = bool(PICK.search(" ".join(prompts)))
        if twin in exists and name in exists:
            entry["command_line_twin"] = twin if twin.startswith("-") else None
            if not name.startswith("-"):
                entry["likely_dialog_in_ui"] = True
                entry["use_instead"] = twin
        if name in tools:
            entry["tool"] = tools[name]

        meta = meta_all.get(name) or meta_all.get(plain) or {}
        if meta.get("description"):
            entry["description"] = meta["description"]
        if meta.get("ui_labels"):
            entry["ui_label"] = meta["ui_labels"][0]
        if meta.get("express_tool"):
            entry["express_tool"] = True
        if meta.get("help_topic"):
            entry["help_topic"] = meta["help_topic"]
        entry["kind"] = classify(name, entry, meta)

        # Say plainly how much is actually known about each command.
        if entry.get("prompts"):
            entry["confidence"] = "verified - these prompts were captured by running it"
        elif entry.get("in_ui"):
            entry["confidence"] = (
                "documented - AutoCAD's own UI wires a button to this command, "
                "but it was not run, so its prompts are unknown"
            )
            entry["exists"] = True
        else:
            entry["confidence"] = "unknown - not found in the UI definition or by probing"

        registry[name] = {k: v for k, v in entry.items() if v not in (None, [], {})}

    for name, (description, tool) in NEVER_PROBED.items():
        entry = registry.get(name, {"name": name})
        entry.update({
            "name": name,
            "exists": True,
            "in_ui": True,
            "description": entry.get("description") or description,
            "kind": "command line",
            "confidence": "documented - intentionally not run during probing",
            "not_probed_because": (
                "running this would close AutoCAD, discard unsaved work, or load "
                "arbitrary code, so it was never executed automatically"
            ),
        })
        if tool:
            entry["tool"] = tool
        if name not in ui_counts:
            ui_counts[name] = 1
        registry[name] = entry

    real = {n: e for n, e in registry.items() if e.get("exists")}
    unknown = {n: e for n, e in registry.items() if not e.get("exists")}
    ui_only = {n: e for n, e in unknown.items() if e.get("in_ui")}

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "autocad": "2025 (25.0)",
        "how_to_read": {
            "options": "option name -> the letters to send, e.g. tOlerance -> O. "
                       "Prefix with _ when sending: '_O'.",
            "interactive": "the command asks you to pick points or objects; pass "
                           "them as arguments to cad_command in prompt order",
            "likely_dialog_in_ui": "in the UI this opens a dialog; use the "
                                   "hyphen twin named in use_instead",
            "tool": "a dedicated tool exists and is easier than cad_command",
        },
        "totals": {
            "probed": len(registry),
            "exist": len(real),
            "with_prompts": sum(1 for e in real.values() if e.get("prompts")),
            "with_options": sum(1 for e in real.values() if e.get("options")),
            "with_dedicated_tool": sum(1 for e in real.values() if e.get("tool")),
            "dialog_in_ui_with_twin": sum(
                1 for e in real.values() if e.get("likely_dialog_in_ui")
            ),
            "verified_in_the_application": sum(
                1 for e in registry.values() if e.get("verified_in_application")
            ),
            "application_only_not_headless": sum(
                1 for e in registry.values() if e.get("headless") is False
            ),
            "open_a_dialog": sum(
                1 for e in registry.values() if e.get("opens_dialog")
            ),
            "not_available_headless": len(unknown),
            "of_those_present_in_the_ui": len(ui_only),
        },
        "ui_coverage": _coverage(registry, ui_counts),
        "commands": registry,
    }

    out = ROOT / "docs" / "commands.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    for key, value in payload["totals"].items():
        print(f"  {key:32s} {value}")
    print(f"\nwritten to {out}  ({out.stat().st_size // 1024} KB)")

    print("\nsample - TRIM:")
    print(json.dumps(registry.get("TRIM", {}), indent=2)[:900])
    print("\nsample - -OVERKILL:")
    print(json.dumps(registry.get("-OVERKILL", registry.get("OVERKILL", {})), indent=2)[:700])


main()
