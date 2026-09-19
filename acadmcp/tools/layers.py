"""Layers, linetypes, text styles and dimension styles."""

from __future__ import annotations

import fnmatch
from typing import Any

from .. import com, lisp, util
from ..errors import AcadError, NotFound
from ..registry import tool


def _layer_row(layer: Any, current: str = "") -> dict[str, Any]:
    q = com.quiet
    name = str(layer.Name)
    row: dict[str, Any] = {
        "name": name,
        "color": q(lambda: int(layer.Color)),
        "linetype": q(lambda: str(layer.Linetype)),
        "lineweight": q(lambda: int(layer.Lineweight)),
        "on": bool(q(lambda: layer.LayerOn, True)),
        "frozen": bool(q(lambda: layer.Freeze, False)),
        "locked": bool(q(lambda: layer.Lock, False)),
        "plot": bool(q(lambda: layer.Plottable, True)),
    }
    desc = q(lambda: str(layer.Description))
    if desc:
        row["description"] = desc
    trans = q(lambda: layer.Transparency)
    if trans:
        row["transparency"] = int(trans)
    if name == current:
        row["current"] = True
    return row


@tool(readonly=True, description="List the layers in a drawing, optionally filtered by a wildcard pattern such as 'A-*'.")
def layer_list(
    pattern: str | None = None,
    in_use_only: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        current = str(com.quiet(lambda: doc.ActiveLayer.Name, ""))
        rows = []
        for i in range(int(doc.Layers.Count)):
            layer = doc.Layers.Item(i)
            name = str(layer.Name)
            if pattern and not fnmatch.fnmatch(name.lower(), str(pattern).lower()):
                continue
            rows.append(_layer_row(layer, current))
        return {"count": len(rows), "current": current, "layers": rows}

    result = com.run_com(work, timeout=120)

    if in_use_only:
        used = lisp.evaluate(
            lisp.raw(
                '(progn (setq amq-ss (ssget "_X") amq-i 0 amq-out nil)'
                " (if amq-ss (repeat (sslength amq-ss)"
                " (setq amq-out (cons (cdr (assoc 8 (entget (ssname amq-ss amq-i))))"
                " amq-out) amq-i (1+ amq-i)))) (reverse amq-out))"
            ),
            timeout=300,
        ) or []
        names = {str(u).lower() for u in used}
        result["layers"] = [r for r in result["layers"] if r["name"].lower() in names]
        result["count"] = len(result["layers"])
        result["filter"] = "layers that have objects on them"
    return result


@tool(description=(
    "Create a layer or change its settings. Anything left out is unchanged. "
    "Colour takes an index 1-255 or a name like 'red'; lineweight is in mm."
))
def layer_set(
    name: str,
    color: Any = None,
    true_color: str | None = None,
    linetype: str | None = None,
    lineweight: Any = None,
    transparency: int | None = None,
    description: str | None = None,
    plot: bool | None = None,
    make_current: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not str(name).strip():
        raise AcadError("a layer needs a name")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        existed = True
        try:
            layer = util.find_layer(doc, name)
        except NotFound:
            existed = False
            layer = util.ensure_layer(doc, name)

        if linetype is not None:
            _load_linetype(doc, str(linetype))
            layer.Linetype = str(linetype)
        if color is not None:
            layer.Color = util.colour_value(color)
        if true_color is not None:
            r, g, b = util.true_colour(true_color)
            tc = com.app().GetInterfaceObject("AutoCAD.AcCmColor.25")
            tc.SetRGB(r, g, b)
            layer.TrueColor = tc
        if lineweight is not None:
            layer.Lineweight = util.lineweight_value(lineweight)
        if transparency is not None:
            layer.Transparency = int(transparency)
        if description is not None:
            layer.Description = str(description)
        if plot is not None:
            layer.Plottable = bool(plot)
        if make_current:
            if com.quiet(lambda: layer.Freeze):
                layer.Freeze = False
            doc.ActiveLayer = layer

        current = str(com.quiet(lambda: doc.ActiveLayer.Name, ""))
        return {"created": not existed, "layer": _layer_row(layer, current)}

    return com.run_com(work, timeout=120)


def _load_linetype(doc: Any, name: str) -> None:
    if str(name).lower() in ("bylayer", "byblock", "continuous"):
        return
    for i in range(int(doc.Linetypes.Count)):
        if str(doc.Linetypes.Item(i).Name).lower() == str(name).lower():
            return
    for source in ("acadiso.lin", "acad.lin"):
        try:
            com.retry(lambda s=source: doc.Linetypes.Load(str(name), s), timeout=60)
            return
        except Exception:  # noqa: BLE001
            continue
    raise AcadError(
        f"Linetype {name!r} is not in this drawing and was not found in "
        "acadiso.lin or acad.lin."
    )


@tool(description="Turn layers on/off, freeze/thaw, lock/unlock, or isolate them so everything else is hidden.")
def layer_state(
    names: list[str] | None = None,
    pattern: str | None = None,
    on: bool | None = None,
    frozen: bool | None = None,
    locked: bool | None = None,
    isolate: bool = False,
    unisolate: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    if unisolate:
        lisp.run_command("_.LAYULK" if False else "_.LAYUNISO", timeout=120)
        return {"unisolated": True}

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        current = str(com.quiet(lambda: doc.ActiveLayer.Name, ""))
        targets: list[Any] = []
        wanted = {str(n).lower() for n in (names or [])}
        for i in range(int(doc.Layers.Count)):
            layer = doc.Layers.Item(i)
            lname = str(layer.Name)
            if wanted and lname.lower() in wanted:
                targets.append(layer)
            elif pattern and fnmatch.fnmatch(lname.lower(), str(pattern).lower()):
                targets.append(layer)
        if not targets:
            raise NotFound("No layers matched.")

        if isolate:
            keep = {str(t.Name).lower() for t in targets}
            changed = 0
            for i in range(int(doc.Layers.Count)):
                layer = doc.Layers.Item(i)
                lname = str(layer.Name)
                if lname.lower() in keep or lname == current:
                    continue
                if com.quiet(lambda l=layer: setattr(l, "LayerOn", False)) is None:
                    changed += 1
            return {"isolated": sorted(keep), "hidden": changed}

        done = []
        for layer in targets:
            lname = str(layer.Name)
            if on is not None:
                layer.LayerOn = bool(on)
            if frozen is not None:
                if lname == current and frozen:
                    continue  # AutoCAD will not freeze the current layer
                layer.Freeze = bool(frozen)
            if locked is not None:
                layer.Lock = bool(locked)
            done.append(_layer_row(layer, current))
        return {"changed": len(done), "layers": done}

    return com.run_com(work, timeout=180)


@tool(description="Delete layers. A layer that still has objects on it, or is current, cannot be deleted - move or erase those objects first, or use layer_merge.")
def layer_delete(names: list[str], drawing: str | None = None) -> dict[str, Any]:
    if not names:
        raise AcadError("no layer names given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        gone, kept = [], []
        for n in names:
            try:
                util.find_layer(doc, n).Delete()
                gone.append(str(n))
            except Exception as exc:  # noqa: BLE001
                kept.append({"layer": str(n), "reason": com.unwrap(str(exc))[:160]})
        out: dict[str, Any] = {"deleted": gone}
        if kept:
            out["could_not_delete"] = kept
        return out

    return com.run_com(work, timeout=180)


@tool(description="Rename a layer.")
def layer_rename(old_name: str, new_name: str, drawing: str | None = None) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        layer = util.find_layer(doc, old_name)
        layer.Name = str(new_name)
        return {"renamed": {"from": old_name, "to": str(new_name)}}

    return com.run_com(work, timeout=90)


@tool(description="Move everything from one or more layers onto a target layer and delete the sources (LAYMRG).")
def layer_merge(sources: list[str], target: str, drawing: str | None = None) -> dict[str, Any]:
    if not sources:
        raise AcadError("no source layers given")

    # Validate first: LAYMRG asks an interactive question if a name is unknown,
    # which would leave AutoCAD sitting at a prompt.
    def check() -> None:
        doc = com.find_doc(drawing)
        for name in list(sources) + [target]:
            util.find_layer(doc, name)

    com.run_com(check, timeout=90)

    args: list[Any] = ["_.-LAYMRG"]
    for s in sources:
        args += ["_N", str(s)]
    args += ["", "_N", str(target), "_Y"]
    lisp.evaluate(lisp.command(*args), timeout=600)
    return {"merged": list(sources), "into": target}


@tool(description="List the linetypes in the drawing, or load one from acadiso.lin / acad.lin (e.g. DASHED, CENTER, HIDDEN).")
def linetype(
    load: list[str] | None = None,
    source_file: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        loaded = []
        for name in load or []:
            if source_file:
                com.retry(lambda n=name: doc.Linetypes.Load(str(n), str(source_file)), timeout=60)
            else:
                _load_linetype(doc, str(name))
            loaded.append(str(name))
        rows = []
        for i in range(int(doc.Linetypes.Count)):
            lt = doc.Linetypes.Item(i)
            rows.append(
                {
                    "name": str(lt.Name),
                    "description": str(com.quiet(lambda: lt.Description, "") or ""),
                }
            )
        out: dict[str, Any] = {"count": len(rows), "linetypes": rows}
        if loaded:
            out["loaded"] = loaded
        return out

    return com.run_com(work, timeout=180)


@tool(description="List, create or modify text styles, and set the current one. font is a file name such as 'arial.ttf' or a .shx name.")
def text_style(
    name: str | None = None,
    font: str | None = None,
    height: float | None = None,
    width_factor: float | None = None,
    oblique_angle: float | None = None,
    make_current: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if name:
            style = com.retry(lambda: doc.TextStyles.Add(str(name)))
            if font:
                text = str(font)
                if text.lower().endswith((".ttf", ".ttc", ".otf")):
                    com.quiet(lambda: style.SetFont(text.rsplit(".", 1)[0], False, False, 0, 0))
                com.quiet(lambda: setattr(style, "fontFile", text))
            if height is not None:
                style.Height = float(height)
            if width_factor is not None:
                style.Width = float(width_factor)
            if oblique_angle is not None:
                style.ObliqueAngle = util.degrees_to_radians(oblique_angle)
            if make_current:
                doc.ActiveTextStyle = style
        rows = []
        for i in range(int(doc.TextStyles.Count)):
            s = doc.TextStyles.Item(i)
            rows.append(
                {
                    "name": str(s.Name),
                    "font": str(com.quiet(lambda: s.fontFile, "") or ""),
                    "height": com.quiet(lambda: round(float(s.Height), 4)),
                    "width_factor": com.quiet(lambda: round(float(s.Width), 4)),
                }
            )
        return {
            "current": str(com.quiet(lambda: doc.ActiveTextStyle.Name, "")),
            "count": len(rows),
            "styles": rows,
        }

    return com.run_com(work, timeout=180)


@tool(description=(
    "List dimension styles, set the current one, or create/update one from "
    "DIM system variables (e.g. {\"DIMTXT\": 2.5, \"DIMASZ\": 2.5, \"DIMSCALE\": 100})."
))
def dim_style(
    name: str | None = None,
    variables: dict[str, Any] | None = None,
    make_current: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        created = False
        if name:
            existing = {
                str(doc.DimStyles.Item(i).Name).lower(): doc.DimStyles.Item(i)
                for i in range(int(doc.DimStyles.Count))
            }
            style = existing.get(str(name).lower())
            if style is None:
                style = com.retry(lambda: doc.DimStyles.Add(str(name)))
                created = True
            if variables:
                for var, value in variables.items():
                    com.retry(
                        lambda v=str(var).upper(), x=value: doc.SetVariable(v, x),
                        context=f"setting {var}",
                    )
                # capture the current DIM* settings into the style
                com.retry(lambda: style.CopyFrom(doc))
            if make_current:
                doc.ActiveDimStyle = style
        rows = [
            {"name": str(doc.DimStyles.Item(i).Name)}
            for i in range(int(doc.DimStyles.Count))
        ]
        return {
            "created": created,
            "current": str(com.quiet(lambda: doc.ActiveDimStyle.Name, "")),
            "count": len(rows),
            "styles": rows,
        }

    return com.run_com(work, timeout=180)
