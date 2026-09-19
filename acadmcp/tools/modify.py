"""Editing existing geometry."""

from __future__ import annotations

import math
from typing import Any

from .. import com, lisp, util
from ..errors import AcadError
from ..registry import tool


def _each(handles: list[str], drawing: str | None, fn, timeout: float = 180):
    if not handles:
        raise AcadError("no handles given")

    def work():
        doc = com.find_doc(drawing)
        results = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            results.append(fn(doc, ent))
        return results

    return com.run_com(work, timeout=timeout)


@tool(description="Move entities by a displacement, or from one point to another.")
def entity_move(
    handles: list[str],
    displacement: list[float] | None = None,
    from_point: list[float] | None = None,
    to_point: list[float] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if displacement is not None:
        base = [0.0, 0.0, 0.0]
        target = [float(v) for v in displacement]
        if len(target) == 2:
            target.append(0.0)
    elif from_point is not None and to_point is not None:
        base, target = from_point, to_point
    else:
        raise AcadError("give a displacement, or both from_point and to_point")

    _each(handles, drawing, lambda doc, e: e.Move(com.pt(base), com.pt(target)))
    return {"moved": len(handles), "handles": handles}


@tool(description="Copy entities. Give one or more destination points; each produces a copy offset from from_point.")
def entity_copy(
    handles: list[str],
    to_points: list[list[float]],
    from_point: list[float] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")
    if not to_points:
        raise AcadError("give at least one destination point")
    base = from_point or [0.0, 0.0, 0.0]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        made: list[str] = []
        for h in handles:
            source = com.by_handle(doc, str(h))
            for dest in to_points:
                copy = com.retry(lambda s=source: s.Copy())
                copy.Move(com.pt(base), com.pt(dest))
                made.append(str(copy.Handle))
        return {"created": made, "count": len(made)}

    return com.run_com(work, timeout=300)


@tool(description="Rotate entities about a base point. The angle is in degrees, counter-clockwise.")
def entity_rotate(
    handles: list[str],
    base_point: list[float],
    angle: float,
    drawing: str | None = None,
) -> dict[str, Any]:
    rad = math.radians(float(angle))
    _each(handles, drawing, lambda doc, e: e.Rotate(com.pt(base_point), rad))
    return {"rotated": len(handles), "angle": angle, "handles": handles}


@tool(description="Scale entities about a base point by a factor.")
def entity_scale(
    handles: list[str],
    base_point: list[float],
    factor: float,
    drawing: str | None = None,
) -> dict[str, Any]:
    if float(factor) == 0:
        raise AcadError("the scale factor cannot be zero")
    _each(handles, drawing, lambda doc, e: e.ScaleEntity(com.pt(base_point), float(factor)))
    return {"scaled": len(handles), "factor": factor, "handles": handles}


@tool(description="Mirror entities across the line through two points. Set keep_original=false to erase the source.")
def entity_mirror(
    handles: list[str],
    point1: list[float],
    point2: list[float],
    keep_original: bool = True,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        made = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            mirrored = com.retry(lambda e=ent: e.Mirror(com.pt(point1), com.pt(point2)))
            made.append(str(mirrored.Handle))
            if not keep_original:
                com.quiet(lambda e=ent: e.Delete())
        return {"created": made, "count": len(made), "original_kept": bool(keep_original)}

    return com.run_com(work, timeout=300)


@tool(description="Offset curves by a distance. A positive distance offsets one way, a negative one the other; try the sign you want and check the result.")
def entity_offset(
    handles: list[str],
    distance: float,
    drawing: str | None = None,
) -> dict[str, Any]:
    if float(distance) == 0:
        raise AcadError("the offset distance cannot be zero")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        made: list[str] = []
        failed: list[dict[str, str]] = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            try:
                result = com.retry(lambda e=ent: e.Offset(float(distance)))
                for obj in com.unwrap(result) or []:
                    made.append(str(obj.Handle))
            except Exception as exc:  # noqa: BLE001
                failed.append({"handle": str(h), "reason": str(exc)})
        out: dict[str, Any] = {"created": made, "count": len(made), "distance": distance}
        if failed:
            out["could_not_offset"] = failed
        return out

    return com.run_com(work, timeout=300)


@tool(description="Array entities in a rectangular grid or around a centre point.")
def entity_array(
    handles: list[str],
    kind: str = "rectangular",
    rows: int = 1,
    columns: int = 1,
    levels: int = 1,
    row_spacing: float = 0.0,
    column_spacing: float = 0.0,
    level_spacing: float = 0.0,
    count: int = 4,
    center: list[float] | None = None,
    fill_angle: float = 360.0,
    drawing: str | None = None,
) -> dict[str, Any]:
    key = str(kind).lower()
    if not handles:
        raise AcadError("no handles given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        made: list[str] = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            if key.startswith("rect"):
                if int(rows) * int(columns) * int(levels) < 2:
                    raise AcadError("a rectangular array needs at least two positions")
                result = com.retry(
                    lambda e=ent: e.ArrayRectangular(
                        int(rows), int(columns), int(levels),
                        float(row_spacing), float(column_spacing), float(level_spacing),
                    )
                )
            elif key.startswith("pol"):
                if not center:
                    raise AcadError("a polar array needs a centre point")
                if int(count) < 2:
                    raise AcadError("a polar array needs at least two items")
                result = com.retry(
                    lambda e=ent: e.ArrayPolar(
                        int(count), math.radians(float(fill_angle)), com.pt(center)
                    )
                )
            else:
                raise AcadError("kind must be 'rectangular' or 'polar'")
            for obj in com.unwrap(result) or []:
                made.append(str(obj.Handle))
        return {"created": made, "count": len(made), "kind": key}

    return com.run_com(work, timeout=600)


@tool(description="Erase entities from the drawing.")
def entity_delete(handles: list[str], drawing: str | None = None) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        gone, missing = [], []
        for h in handles:
            try:
                com.by_handle(doc, str(h)).Delete()
                gone.append(str(h))
            except Exception:  # noqa: BLE001
                missing.append(str(h))
        out: dict[str, Any] = {"deleted": len(gone), "handles": gone}
        if missing:
            out["not_found"] = missing
        return out

    return com.run_com(work, timeout=300)


@tool(description="Read or change the common properties of entities: layer, colour, linetype, lineweight, transparency, linetype scale. Omit the values to just read them.")
def entity_properties(
    handles: list[str],
    layer: str | None = None,
    color: Any = None,
    true_color: str | None = None,
    linetype: str | None = None,
    lineweight: Any = None,
    linetype_scale: float | None = None,
    transparency: Any = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")
    changing = any(
        v is not None
        for v in (layer, color, true_color, linetype, lineweight, linetype_scale, transparency)
    )

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if layer:
            util.ensure_layer(doc, layer)
        rows = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            if changing:
                util.apply_props(
                    ent,
                    layer=layer,
                    colour=color,
                    true_color=true_color,
                    linetype=linetype,
                    linetype_scale=linetype_scale,
                    lineweight=lineweight,
                    transparency=transparency,
                )
            rows.append(
                {
                    "handle": str(ent.Handle),
                    "type": util.dxf_type(ent),
                    "layer": str(com.quiet(lambda e=ent: e.Layer, "")),
                    "color": com.quiet(lambda e=ent: int(e.Color)),
                    "linetype": com.quiet(lambda e=ent: str(e.Linetype)),
                    "lineweight": com.quiet(lambda e=ent: int(e.Lineweight)),
                    "linetype_scale": com.quiet(lambda e=ent: round(float(e.LinetypeScale), 6)),
                    "transparency": com.quiet(lambda e=ent: str(e.EntityTransparency)),
                }
            )
        return {"changed": changing, "entities": rows, "count": len(rows)}

    return com.run_com(work, timeout=300)


@tool(description="Copy properties from one entity onto others, like the MATCHPROP command.")
def match_properties(
    source: str,
    targets: list[str],
    drawing: str | None = None,
) -> dict[str, Any]:
    if not targets:
        raise AcadError("no target handles given")
    lisp.evaluate(
        lisp.command(
            "_.MATCHPROP",
            lisp.entity(str(source)),
            lisp.ss_from([str(t) for t in targets]),
            "",
        ),
        timeout=180,
    )
    return {"source": source, "matched": len(targets)}


def _trim_or_extend(name: str, edges: list[str], targets: list[str]) -> None:
    """TRIM/EXTEND in Standard mode.

    AutoCAD 2021+ defaults these commands to Quick mode, which asks for no
    cutting edges at all - so force TRIMEXTENDMODE=1 for the call and put it
    back. Exactly two Enters: one after the edges, one after the targets. A
    third would land at the Command prompt and re-run the command, leaving
    AutoCAD waiting for input.
    """
    lisp.evaluate(
        lisp.raw(
            '(progn (setq amx-tem (getvar "TRIMEXTENDMODE")) (setvar "TRIMEXTENDMODE" 1) '
            + str(lisp.command(name, lisp.ss_from(edges), "", lisp.ss_from(targets), ""))
            + ' (setvar "TRIMEXTENDMODE" amx-tem) (setq amx-tem nil))'
        ),
        timeout=300,
    )


@tool(description="Trim entities back to cutting edges. Give the entities to trim and the edges to trim them at.")
def entity_trim(
    handles: list[str],
    cutting_edges: list[str],
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles or not cutting_edges:
        raise AcadError("give both the entities to trim and the cutting edges")
    _trim_or_extend("_.TRIM", cutting_edges, handles)
    return {"trimmed": len(handles), "against": len(cutting_edges)}


@tool(description="Extend entities to meet boundary edges.")
def entity_extend(
    handles: list[str],
    boundaries: list[str],
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles or not boundaries:
        raise AcadError("give both the entities to extend and the boundary edges")
    _trim_or_extend("_.EXTEND", boundaries, handles)
    return {"extended": len(handles), "to": len(boundaries)}


@tool(description="Fillet two entities with a radius (0 makes a sharp corner), or fillet all vertices of a polyline.")
def entity_fillet(
    handle1: str,
    handle2: str | None = None,
    radius: float = 0.0,
    polyline: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    steps: list[Any] = [lisp.command("_.FILLET", "_R", float(radius))]
    if polyline or handle2 is None:
        steps.append(lisp.command("_.FILLET", "_P", lisp.entity(str(handle1))))
    else:
        steps.append(
            lisp.command(
                "_.FILLET", lisp.entity(str(handle1)), lisp.entity(str(handle2))
            )
        )
    payload = lisp.evaluate(
        lisp.raw("(acadmcp:capture '(lambda () %s))" % lisp.progn(*steps)), timeout=180
    )
    created = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
    return {"radius": radius, "created": created, "whole_polyline": bool(polyline or handle2 is None)}


@tool(description="Chamfer two entities with two setback distances.")
def entity_chamfer(
    handle1: str,
    handle2: str | None = None,
    distance1: float = 0.0,
    distance2: float | None = None,
    polyline: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    d1 = float(distance1)
    d2 = float(distance2 if distance2 is not None else distance1)
    steps: list[Any] = [lisp.command("_.CHAMFER", "_D", d1, d2)]
    if polyline or handle2 is None:
        steps.append(lisp.command("_.CHAMFER", "_P", lisp.entity(str(handle1))))
    else:
        steps.append(
            lisp.command("_.CHAMFER", lisp.entity(str(handle1)), lisp.entity(str(handle2)))
        )
    payload = lisp.evaluate(
        lisp.raw("(acadmcp:capture '(lambda () %s))" % lisp.progn(*steps)), timeout=180
    )
    created = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
    return {"distances": [d1, d2], "created": created}


@tool(description="Join collinear or contiguous entities into one, like the JOIN command.")
def entity_join(handles: list[str], drawing: str | None = None) -> dict[str, Any]:
    if len(handles) < 2:
        raise AcadError("joining needs at least two entities")
    payload = lisp.evaluate(
        lisp.raw(
            "(acadmcp:capture '(lambda () %s))"
            % lisp.command("_.JOIN", lisp.ss_from(handles), "")
        ),
        timeout=300,
    )
    created = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
    return {"joined": len(handles), "created": created}


@tool(description="Explode blocks, polylines, dimensions or hatches into their parts. Returns the handles of the pieces.")
def entity_explode(handles: list[str], drawing: str | None = None) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        pieces: list[str] = []
        failed: list[dict[str, str]] = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            try:
                for obj in com.unwrap(com.retry(lambda e=ent: e.Explode())) or []:
                    pieces.append(str(obj.Handle))
                com.quiet(lambda e=ent: e.Delete())
            except Exception as exc:  # noqa: BLE001
                failed.append({"handle": str(h), "reason": str(exc)})
        out: dict[str, Any] = {"created": pieces, "count": len(pieces)}
        if failed:
            out["could_not_explode"] = failed
        return out

    return com.run_com(work, timeout=600)


@tool(description=(
    "Break an entity at one point, or remove the piece between two points. "
    "Lines and arcs are split geometrically; other curves go through the BREAK "
    "command."
))
def entity_break(
    handle: str,
    point1: list[float],
    point2: list[float] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    """Split a curve.

    The BREAK *command* is driven by picked points and behaves unpredictably
    when it is fed coordinates from a script - it can silently do nothing, or
    sit waiting for input, which freezes COM. For the two shapes that account
    for nearly every break (lines and arcs) the result is computed directly
    instead, which is exact and cannot hang. Anything else falls back to the
    command with a short leash.
    """
    p1 = [float(v) for v in point1[:2]]
    p2 = [float(v) for v in (point2 or point1)[:2]]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        ent = com.by_handle(doc, str(handle))
        kind = util.dxf_type(ent)
        # put the pieces back where the original lived (model or paper space)
        space = com.quiet(lambda: ent.Owner) or doc.ModelSpace

        if kind == "LINE":
            start = util.round_pt(ent.StartPoint)
            end = util.round_pt(ent.EndPoint)
            dx, dy = end[0] - start[0], end[1] - start[1]
            span = math.hypot(dx, dy)
            if span == 0:
                raise AcadError("that line has zero length")

            def along(p: list[float]) -> float:
                """Distance along the line of the closest point to p (0..1)."""
                t = ((p[0] - start[0]) * dx + (p[1] - start[1]) * dy) / (span * span)
                return min(1.0, max(0.0, t))

            def at(t: float) -> list[float]:
                return [start[0] + dx * t, start[1] + dy * t, start[2]]

            t1, t2 = sorted((along(p1), along(p2)))
            if t1 <= 0 and t2 >= 1:
                raise AcadError(
                    "those points remove the whole line - use entity_delete instead"
                )
            made: list[str] = []
            target = space
            if t1 > 0:
                first = com.retry(lambda: target.AddLine(com.pt(at(0.0)), com.pt(at(t1))))
                first.Layer = ent.Layer
                first.Color = ent.Color
                first.Linetype = ent.Linetype
                made.append(str(first.Handle))
            if t2 < 1:
                last = com.retry(lambda: target.AddLine(com.pt(at(t2)), com.pt(at(1.0))))
                last.Layer = ent.Layer
                last.Color = ent.Color
                last.Linetype = ent.Linetype
                made.append(str(last.Handle))
            com.retry(lambda: ent.Delete())
            return {
                "broken": handle,
                "created": made,
                "pieces": len(made),
                "gap": t2 > t1,
                "method": "geometric split",
            }

        if kind == "ARC":
            centre = util.round_pt(ent.Center)

            def angle_of(p: list[float]) -> float:
                return math.degrees(
                    math.atan2(p[1] - centre[1], p[0] - centre[0])
                ) % 360

            a_start = math.degrees(float(ent.StartAngle)) % 360
            a_end = math.degrees(float(ent.EndAngle)) % 360
            b1, b2 = angle_of(p1), angle_of(p2)

            def sweep(frm: float, to: float) -> float:
                return (to - frm) % 360

            if sweep(a_start, b1) > sweep(a_start, b2):
                b1, b2 = b2, b1
            radius = float(ent.Radius)
            owner = space
            made = []
            for frm, to in ((a_start, b1), (b2, a_end)):
                if round(sweep(frm, to), 9) == 0:
                    continue
                arc = com.retry(
                    lambda f=frm, t=to: owner.AddArc(
                        com.pt(centre), radius, math.radians(f), math.radians(t)
                    )
                )
                arc.Layer = ent.Layer
                arc.Color = ent.Color
                made.append(str(arc.Handle))
            com.retry(lambda: ent.Delete())
            return {
                "broken": handle,
                "created": made,
                "pieces": len(made),
                "method": "geometric split",
            }

        return {"fallback": kind}

    result = com.run_com(work, timeout=180)
    if "fallback" not in result:
        return result

    # Anything else: let AutoCAD do it, but do not let it hang the session.
    payload = lisp.evaluate(
        lisp.raw(
            "(acadmcp:capture '(lambda () %s))"
            % lisp.command(
                "_.BREAK",
                lisp.raw(f"(list {lisp.entity(str(handle))} {lisp.lpoint(p1)})"),
                "_F", p1, p2,
            )
        ),
        timeout=25,
    )
    created = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
    return {
        "broken": handle,
        "created": created,
        "type": result["fallback"],
        "method": "BREAK command",
    }


@tool(description="Delete duplicate and overlapping geometry (the OVERKILL command).")
def entity_overkill(
    handles: list[str] | None = None,
    tolerance: float = 0.000001,
    drawing: str | None = None,
) -> dict[str, Any]:
    selection = lisp.ss_from(handles) if handles else lisp.raw('(ssget "_X")')
    # -OVERKILL: select, Enter, then options, then Done. "_D" ends the command,
    # so nothing may follow it - a stray Enter would re-run it and park AutoCAD.
    before = lisp.evaluate(lisp.raw('(sslength (ssget "_X"))'), timeout=60)
    args: list[Any] = ["_.-OVERKILL", selection, ""]
    if tolerance and abs(float(tolerance) - 0.000001) > 1e-12:
        # the keyword is "tOlerance", so the letter is O - "_T" is not an
        # option and AutoCAD would keep re-asking, which parks the command
        args += ["_O", float(tolerance)]
    args.append("")            # Enter accepts the default <Done>
    lisp.evaluate(lisp.command(*args), timeout=300)
    after = lisp.evaluate(lisp.raw('(sslength (ssget "_X"))'), timeout=60)
    return {
        "scope": f"{len(handles)} objects" if handles else "whole drawing",
        "tolerance": tolerance,
        "entities_before": before,
        "entities_after": after,
        "removed": (before - after) if isinstance(before, int) and isinstance(after, int) else None,
    }
