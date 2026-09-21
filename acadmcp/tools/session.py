"""Connection, drawings, system variables, view control, housekeeping."""

from __future__ import annotations

import os
from typing import Any

from .. import com, lisp
from ..errors import AcadError, NotFound
from ..registry import tool

# AcSaveAsType, verified empirically against AutoCAD 2025 by saving a file with
# each number and reading the DWG version stamp back out of the header.
SAVE_FORMATS = {
    "native": 64, "2018": 64, "2013": 60, "2010": 48, "2007": 36,
    "2004": 24, "2000": 12, "r14": 8,
    "dxf2018": 65, "dxf2013": 61, "dxf2010": 49, "dxf2007": 37,
    "dxf2004": 25, "dxf2000": 13, "dxfr12": 1,
}

#: the file extension each format must be written with
FORMAT_EXT = {name: (".dxf" if name.startswith("dxf") else ".dwg") for name in SAVE_FORMATS}

UNIT_NAMES = {
    0: "unitless", 1: "inches", 2: "feet", 3: "miles", 4: "millimetres",
    5: "centimetres", 6: "metres", 7: "kilometres", 8: "microinches",
    9: "mils", 10: "yards", 11: "angstroms", 12: "nanometres",
    13: "microns", 14: "decimetres", 15: "decametres", 16: "hectometres",
    17: "gigametres", 18: "astronomical units", 19: "light years", 20: "parsecs",
}


def _doc_summary(doc: Any, active_name: str | None = None) -> dict[str, Any]:
    name = str(com.quiet(lambda: doc.Name, "?"))
    return {
        "name": name,
        "path": str(com.quiet(lambda: doc.FullName, "") or ""),
        "saved": bool(com.quiet(lambda: doc.Saved, True)),
        "read_only": bool(com.quiet(lambda: doc.ReadOnly, False)),
        "active": (name == active_name) if active_name else None,
        "model_entities": com.quiet(lambda: int(doc.ModelSpace.Count)),
    }


@tool(readonly=True, description="Check the AutoCAD connection and report version, open drawings, units and the state of the AutoLISP bridge. Call this first if anything seems wrong.")
def acad_status() -> dict[str, Any]:
    def work() -> dict[str, Any]:
        app = com.app()
        info: dict[str, Any] = {
            "connected": True,
            "version": str(app.Version),
            "caption": str(com.quiet(lambda: app.Caption, "")),
            "visible": bool(com.quiet(lambda: app.Visible, True)),
            "documents": com.doc_count(),
            "lisp_transport": "streamed eval (no file load, SECURELOAD safe)",
        }
        if info["documents"]:
            doc = app.ActiveDocument
            info["active_document"] = str(doc.Name)
            info["path"] = str(com.quiet(lambda: doc.FullName, "") or "(never saved)")
            units = com.quiet(lambda: int(doc.GetVariable("INSUNITS")), 0)
            info["units"] = f"{UNIT_NAMES.get(units, units)} (INSUNITS={units})"
            info["model_entities"] = int(doc.ModelSpace.Count)
            info["layers"] = int(doc.Layers.Count)
            info["active_space"] = (
                "model" if int(com.quiet(lambda: doc.ActiveSpace, 1)) == 1 else "paper"
            )
            info["active_layout"] = str(com.quiet(lambda: doc.ActiveLayout.Name, ""))
            info["command_active"] = bool(com.quiet(lambda: int(doc.GetVariable("CMDACTIVE")), 0))
        return info

    return com.run_com(work, timeout=90)


@tool(description="Get AutoCAD back to a clean command prompt after it has been left waiting for input, and confirm it responds again. Use this if a tool reports AutoCAD is busy.")
def acad_cancel() -> dict[str, Any]:
    ok = lisp.cancel()
    lisp.forget_library()
    return {
        "responsive": ok,
        "note": "AutoCAD is back at the Command prompt" if ok
        else "AutoCAD is still busy - look for a dialog box open on screen",
    }


@tool(readonly=True, description="List the drawings currently open in AutoCAD.")
def doc_list() -> dict[str, Any]:
    def work() -> dict[str, Any]:
        app = com.app()
        count = com.doc_count()
        active = str(com.active_doc().Name) if count else None
        return {
            "count": count,
            "active": active,
            "drawings": [
                _doc_summary(app.Documents.Item(i), active) for i in range(count)
            ],
        }

    return com.run_com(work, timeout=60)


@tool(description="Create a new drawing, optionally from a .dwt template. Returns the new drawing's name.")
def doc_new(template: str | None = None) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        app = com.app()
        # Right after closing a drawing, late binding can fail to resolve
        # Documents.Add ("AttributeError: <unknown>.Add") while AutoCAD is
        # still tidying up - that is busy, not broken, so ride it out.
        if template:
            com.retry(lambda: app.Documents.Add(str(template)), timeout=180, attr_is_busy=True)
        else:
            com.retry(lambda: app.Documents.Add(), timeout=180, attr_is_busy=True)
        # Documents.Add can hand back an object late binding cannot read; the
        # new drawing is the active one, so read it from there instead.
        doc = com.retry(
            lambda: app.ActiveDocument, timeout=60, attr_is_busy=True,
            context="reading the new drawing",
        )
        return {
            "name": str(com.prop(doc, "Name", "?")),
            "template": template or "(default)",
        }

    result = com.run_com(work, timeout=180)
    lisp.forget_library()
    return result


@tool(description="Open a .dwg or .dxf file in AutoCAD and make it the active drawing.")
def doc_open(path: str, read_only: bool = False) -> dict[str, Any]:
    target = os.path.abspath(os.path.expanduser(str(path)))
    if not os.path.isfile(target):
        raise AcadError(f"There is no file at {target}")

    def work() -> dict[str, Any]:
        app = com.app()
        com.retry(
            lambda: app.Documents.Open(target, bool(read_only)),
            timeout=300,
            context=f"opening {os.path.basename(target)}",
        )
        doc = com.retry(
            lambda: app.ActiveDocument, timeout=60, attr_is_busy=True,
            context="reading the opened drawing",
        )
        return _doc_summary(doc, str(com.prop(doc, "Name", "")))

    result = com.run_com(work, timeout=360)
    lisp.forget_library()
    return result


@tool(description="Save the active drawing, or save it under a new name/format. Formats: native, 2018, 2013, 2010, 2007, 2004, 2000, dxf2018 ... dxf2000.")
def doc_save(
    path: str | None = None,
    format: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if path:
            target = os.path.abspath(os.path.expanduser(str(path)))
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            if format:
                key = str(format).strip().lower()
                if key not in SAVE_FORMATS:
                    raise AcadError(
                        f"unknown format {format!r}; choose one of "
                        + ", ".join(sorted(SAVE_FORMATS))
                    )
                # AutoCAD refuses the save outright if the extension does not
                # match the format, so make them agree.
                wanted = FORMAT_EXT[key]
                if not target.lower().endswith(wanted):
                    target = os.path.splitext(target)[0] + wanted
                com.retry(lambda: doc.SaveAs(target, SAVE_FORMATS[key]), timeout=300)
            else:
                if not target.lower().endswith((".dwg", ".dxf", ".dwt")):
                    target += ".dwg"
                com.retry(lambda: doc.SaveAs(target), timeout=300)
            return {"saved": target, "format": format or "native"}
        if not str(com.quiet(lambda: doc.FullName, "")):
            raise AcadError(
                "This drawing has never been saved, so it has no file name yet - "
                "pass a path."
            )
        com.retry(lambda: doc.Save(), timeout=300)
        return {"saved": str(doc.FullName)}

    return com.run_com(work, timeout=360)


@tool(description="Close a drawing. By default changes are discarded, so pass save=true to keep them.")
def doc_close(drawing: str | None = None, save: bool = False) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        name = str(doc.Name)
        if save and not str(com.quiet(lambda: doc.FullName, "")):
            raise AcadError(
                f"{name} has never been saved to a file; save it with doc_save first "
                "or close with save=false."
            )
        com.retry(lambda: doc.Close(bool(save)), timeout=180)
        return {"closed": name, "saved": bool(save)}

    result = com.run_com(work, timeout=240)
    lisp.forget_library()
    return result


@tool(description="Make one of the open drawings the active one.")
def doc_activate(drawing: str) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        com.retry(lambda: doc.Activate(), timeout=60)
        return {"active": str(doc.Name)}

    return com.run_com(work, timeout=90)


@tool(description="Read or write an AutoCAD system variable (OSMODE, INSUNITS, DIMSCALE, CLAYER ...). Omit value to read. Pass several at once with settings.")
def sysvar(
    name: str | None = None,
    value: Any = None,
    settings: dict[str, Any] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not name and not settings:
        raise AcadError("give a variable name, or a settings dictionary")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        out: dict[str, Any] = {}
        pairs: list[tuple[str, Any]] = []
        if name:
            pairs.append((name, value))
        for k, v in (settings or {}).items():
            pairs.append((k, v))
        for var, val in pairs:
            key = str(var).upper()
            if val is None:
                got = com.retry(lambda v=key: doc.GetVariable(v), context=f"reading {key}")
                out[key] = com.unwrap(got)
            else:
                before = com.quiet(lambda v=key: com.unwrap(doc.GetVariable(v)))
                com.retry(lambda v=key, x=val: doc.SetVariable(v, x), context=f"setting {key}")
                out[key] = {"was": before, "now": com.unwrap(doc.GetVariable(key))}
        return out

    return com.run_com(work, timeout=90)


@tool(description="Change the view: zoom extents/all/window/centre/scale, or zoom to given objects.")
def zoom(
    mode: str = "extents",
    corner1: list[float] | None = None,
    corner2: list[float] | None = None,
    center: list[float] | None = None,
    magnification: float | None = None,
    scale: float | None = None,
    handles: list[str] | None = None,
) -> dict[str, Any]:
    key = str(mode).strip().lower()

    if key in ("object", "objects") or handles:
        if not handles:
            raise AcadError("zoom to objects needs handles")
        lisp.evaluate(
            lisp.progn(
                lisp.command("_.ZOOM", "_O", lisp.ss_from(handles), ""),
            )
        )
        return {"zoom": "objects", "count": len(handles)}

    def work() -> dict[str, Any]:
        app = com.app()
        if key in ("extents", "e"):
            com.retry(lambda: app.ZoomExtents())
        elif key in ("all", "a"):
            com.retry(lambda: app.ZoomAll())
        elif key in ("window", "w"):
            if not (corner1 and corner2):
                raise AcadError("zoom window needs corner1 and corner2")
            com.retry(lambda: app.ZoomWindow(com.pt(corner1), com.pt(corner2)))
        elif key in ("center", "centre", "c"):
            if not center:
                raise AcadError("zoom centre needs a center point")
            com.retry(lambda: app.ZoomCenter(com.pt(center), float(magnification or 1.0)))
        elif key in ("scale", "s"):
            if scale is None:
                raise AcadError("zoom scale needs a scale factor")
            com.retry(lambda: app.ZoomScaled(float(scale), 1))  # 1 = relative to paper
        elif key in ("previous", "p"):
            return {"zoom": "previous", "note": "use cad_command('_.ZOOM','_P') instead"}
        else:
            raise AcadError(
                f"unknown zoom mode {mode!r}; use extents, all, window, center, "
                "scale or object"
            )
        return {"zoom": key}

    return com.run_com(work, timeout=90)


@tool(description="Regenerate the drawing (REGEN), refreshing the display and recomputing geometry.")
def regen(all_viewports: bool = True) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.active_doc()
        com.retry(lambda: doc.Regen(1 if all_viewports else 0))
        return {"regenerated": True}

    return com.run_com(work, timeout=180)


@tool(description="Remove unused layers, blocks, linetypes and styles (PURGE) and optionally run AUDIT to fix errors. Reports what was removed.")
def purge(
    kinds: list[str] | None = None,
    audit_and_fix: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    def counts(doc: Any) -> dict[str, int]:
        return {
            "layers": int(com.quiet(lambda: doc.Layers.Count, 0) or 0),
            "blocks": int(com.quiet(lambda: doc.Blocks.Count, 0) or 0),
            "linetypes": int(com.quiet(lambda: doc.Linetypes.Count, 0) or 0),
            "text_styles": int(com.quiet(lambda: doc.TextStyles.Count, 0) or 0),
            "dim_styles": int(com.quiet(lambda: doc.DimStyles.Count, 0) or 0),
        }

    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60)
    before = com.run_com(lambda: counts(doc), timeout=60)

    if audit_and_fix:
        lisp.run_command("_.AUDIT", "_Y", doc=doc, timeout=600)
    # PURGE twice: removing a block can orphan a layer it referenced
    for _ in range(2):
        lisp.run_command("_.-PURGE", "_All", "*", "_N", doc=doc, timeout=300)

    after = com.run_com(lambda: counts(doc), timeout=60)
    removed = {k: before[k] - after[k] for k in before if before[k] != after[k]}
    return {
        "before": before,
        "after": after,
        "removed": removed or "nothing unused was found",
        "audited": bool(audit_and_fix),
        "requested": kinds or "all",
    }


@tool(description=(
    "Undo or redo. action: undo (the last `steps` operations), redo, mark (set "
    "an undo mark), or back (undo everything since the last mark). Each tool "
    "call is at least one undo step, so mark before a multi-step change and "
    "back reverts all of it if the result is wrong."
))
def undo(
    action: str = "undo",
    steps: int = 1,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    n = max(1, int(steps))
    if verb == "undo":
        lisp.run_command("_.UNDO", n, doc=doc, timeout=300)
        return {"undone": n}
    if verb == "redo":
        lisp.run_command("_.MREDO", n, doc=doc, timeout=300)
        return {"redone": n}
    if verb == "mark":
        lisp.run_command("_.UNDO", "_Mark", doc=doc, timeout=60)
        return {"mark": "set"}
    if verb == "back":
        marks = lisp.evaluate(lisp.raw('(getvar "UNDOMARKS")'), doc=doc, timeout=60)
        if not marks:
            raise AcadError(
                "there is no undo mark to go back to - set one first with "
                "action='mark' (going back without a mark would undo everything)"
            )
        lisp.run_command("_.UNDO", "_Back", doc=doc, timeout=300)
        return {"undone": "everything since the last mark", "marks_left": int(marks) - 1}
    raise AcadError("action must be undo, redo, mark or back")


@tool(description=(
    "Named views: list, save the current view under a name, restore one, or "
    "delete one. A saved view remembers where the camera was, so 'go back to "
    "the roof view' is one call."
))
def view(
    action: str = "list",
    name: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60)

    def names() -> list[str]:
        return com.run_com(
            lambda: [str(doc.Views.Item(i).Name) for i in range(int(doc.Views.Count))],
            timeout=60,
        )

    if verb == "list":
        return {"views": names()}
    if not name:
        raise AcadError(f"{verb} needs the view name")
    if verb == "save":
        exists = str(name).lower() in {n.lower() for n in names()}
        args: list[Any] = ["_.-VIEW", "_Save", str(name)]
        if exists:
            args.append("_Yes")            # "View already exists. Replace it?"
        lisp.run_command(*args, doc=doc, timeout=60)
        return {"saved": name, "replaced": exists}
    if verb == "restore":
        lisp.run_command("_.-VIEW", "_Restore", str(name), doc=doc, timeout=60)
        return {"restored": name}
    if verb == "delete":
        lisp.run_command("_.-VIEW", "_Delete", str(name), doc=doc, timeout=60)
        return {"deleted": name}
    raise AcadError("action must be list, save, restore or delete")


@tool(description=(
    "The user coordinate system. action: world (back to WCS), origin (move the "
    "origin, optionally rotate by angle degrees about Z), three_point (origin, a "
    "point on +X, a point on +Y), object (align to an entity), save, restore, "
    "list or current."
))
def ucs(
    action: str = "current",
    origin: list[float] | None = None,
    x_point: list[float] | None = None,
    y_point: list[float] | None = None,
    angle: float = 0.0,
    handle: str | None = None,
    name: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower().replace("-", "_")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60)

    def current() -> dict[str, Any]:
        return com.run_com(
            lambda: {
                "name": str(com.quiet(lambda: doc.GetVariable("UCSNAME"), "") or "")
                or "(unnamed)",
                "origin": com.unwrap(doc.GetVariable("UCSORG")),
                "x_axis": com.unwrap(doc.GetVariable("UCSXDIR")),
                "y_axis": com.unwrap(doc.GetVariable("UCSYDIR")),
                "is_world": int(com.quiet(lambda: doc.GetVariable("WORLDUCS"), 1) or 0) == 1,
            },
            timeout=60,
        )

    if verb == "current":
        return current()
    if verb == "list":
        saved = com.run_com(
            lambda: [
                str(doc.UserCoordinateSystems.Item(i).Name)
                for i in range(int(doc.UserCoordinateSystems.Count))
            ],
            timeout=60,
        )
        return {"saved": saved, **current()}
    if verb == "world":
        lisp.run_command("_.UCS", "_World", doc=doc, timeout=60)
    elif verb == "origin":
        if not origin:
            raise AcadError("origin needs the new origin point")
        lisp.run_command("_.UCS", origin, doc=doc, timeout=60)
        if float(angle):
            lisp.run_command("_.UCS", "_Z", float(angle), doc=doc, timeout=60)
    elif verb in ("three_point", "3point"):
        if not (origin and x_point and y_point):
            raise AcadError("three_point needs origin, x_point and y_point")
        lisp.run_command("_.UCS", "_3", origin, x_point, y_point, doc=doc, timeout=60)
    elif verb == "object":
        if not handle:
            raise AcadError("object needs the handle of the entity to align to")
        lisp.run_command("_.UCS", "_OBject", lisp.entity(str(handle)), doc=doc, timeout=60)
    elif verb == "save":
        if not name:
            raise AcadError("save needs a name")
        existing = com.run_com(
            lambda: [
                str(doc.UserCoordinateSystems.Item(i).Name).lower()
                for i in range(int(doc.UserCoordinateSystems.Count))
            ],
            timeout=60,
        )
        args: list[Any] = ["_.UCS", "_Save", str(name)]
        if str(name).lower() in existing:
            args.append("_Yes")            # "already exists. Replace it?"
        lisp.run_command(*args, doc=doc, timeout=60)
    elif verb == "restore":
        if not name:
            raise AcadError("restore needs a name")
        lisp.run_command("_.UCS", "_Restore", str(name), doc=doc, timeout=60)
    else:
        raise AcadError(
            "action must be current, list, world, origin, three_point, object, save or restore"
        )
    return {"action": verb, **current()}
