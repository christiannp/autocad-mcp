"""Editing existing geometry."""

from __future__ import annotations

import math
from typing import Any

import win32com.client

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


def _curve_direction(ent: Any) -> tuple[list[float], list[float]] | None:
    """(start point, unit direction) of an open curve, or None."""
    kind = util.dxf_type(ent)
    try:
        if kind == "LINE":
            a, b = util.round_pt(ent.StartPoint), util.round_pt(ent.EndPoint)
        elif kind in ("LWPOLYLINE", "POLYLINE"):
            coords = com.unwrap(ent.Coordinates)
            step = 2 if kind == "LWPOLYLINE" else 3
            a, b = list(coords[0:2]), list(coords[step:step + 2])
        elif kind in ("ARC", "SPLINE", "ELLIPSE"):
            a = util.round_pt(ent.StartPoint)
            b = util.round_pt(ent.EndPoint)
            if kind == "ARC":
                # tangent at the start, counter-clockwise
                ang = float(ent.StartAngle) + math.pi / 2
                b = [a[0] + math.cos(ang), a[1] + math.sin(ang)]
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dy)
    if n == 0:
        return None
    return [a[0], a[1]], [dx / n, dy / n]


@tool(description=(
    "Offset curves by a distance. side chooses where the copy goes: inside or "
    "outside for closed shapes (a roof outline offset inside by the setback), "
    "left or right of the curve's direction for open ones, or give a through "
    "point. Without side, a positive distance offsets one way and a negative "
    "one the other."
))
def entity_offset(
    handles: list[str],
    distance: float = 0.0,
    side: str | None = None,
    through: list[float] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    want = str(side).strip().lower() if side else None
    if want and want not in ("inside", "outside", "left", "right"):
        raise AcadError("side must be inside, outside, left or right")
    if through is None and float(distance) == 0:
        raise AcadError("the offset distance cannot be zero (or give a through point)")

    if through is not None:
        made_all: list[str] = []
        for h in handles:
            _, made = lisp.capture(
                lisp.command("_.OFFSET", "_Through", lisp.entity(str(h)), through, ""),
                timeout=120,
            )
            made_all.extend(made)
        return {"created": made_all, "count": len(made_all), "through": through}

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        made: list[str] = []
        failed: list[dict[str, str]] = []
        sides: list[str] = []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            closed = bool(com.quiet(lambda: ent.Closed, False)) or util.dxf_type(ent) in ("CIRCLE", "ELLIPSE")
            if want in ("inside", "outside") and not closed:
                failed.append({"handle": str(h), "reason": "not a closed shape; use left/right"})
                continue
            if want in ("left", "right") and closed:
                failed.append({"handle": str(h), "reason": "a closed shape; use inside/outside"})
                continue

            def offset(d: float) -> list[Any]:
                return list(com.unwrap(com.retry(lambda: ent.Offset(float(d)))) or [])

            try:
                d = abs(float(distance)) if want else float(distance)
                objs = offset(d)
                if want and objs:
                    wrong = False
                    if want in ("inside", "outside"):
                        a0 = float(com.quiet(lambda: ent.Area, 0.0) or 0.0)
                        a1 = float(com.quiet(lambda: objs[0].Area, 0.0) or 0.0)
                        wrong = (a1 > a0) if want == "inside" else (a1 < a0)
                    else:
                        base = _curve_direction(ent)
                        other = _curve_direction(objs[0])
                        if base and other:
                            (ax, ay), (dx, dy) = base
                            (bx, by), _ = other
                            cross = dx * (by - ay) - dy * (bx - ax)
                            wrong = (cross < 0) if want == "left" else (cross > 0)
                    if wrong:
                        for o in objs:
                            com.quiet(lambda o=o: o.Delete())
                        objs = offset(-d)
                for o in objs:
                    made.append(str(o.Handle))
                if want:
                    sides.append(want)
            except Exception as exc:  # noqa: BLE001
                failed.append({"handle": str(h), "reason": str(exc)})
        out: dict[str, Any] = {"created": made, "count": len(made), "distance": distance}
        if want:
            out["side"] = want
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


def _ss_crossing(corner1: list[float], corner2: list[float], only: list[str] | None) -> lisp.Raw:
    """A crossing-window pickset, optionally reduced to the given handles.

    STRETCH honours the window that built a pickset, which is what lets it
    stretch the objects the window cuts and move the ones it encloses.
    """
    ss = f'(ssget "_C" {lisp.lpoint(corner1)} {lisp.lpoint(corner2)})'
    if not only:
        return lisp.raw(ss)
    keep = " ".join(lisp.lstr(str(h)) for h in only)
    return lisp.raw(
        f"(progn (setq amx-ss {ss} amx-keep (list {keep}) amx-i 0) "
        "(if amx-ss (progn (setq amx-drop nil) "
        "(repeat (sslength amx-ss) (setq amx-e (ssname amx-ss amx-i)) "
        "(if (not (member (acadmcp:hnd amx-e) amx-keep)) (setq amx-drop (cons amx-e amx-drop))) "
        "(setq amx-i (1+ amx-i))) "
        "(foreach amx-e amx-drop (ssdel amx-e amx-ss)))) "
        "(if (and amx-ss (> (sslength amx-ss) 0)) amx-ss nil))"
    )


@tool(description=(
    "Stretch: move the vertices that fall inside a crossing window while the "
    "rest of each object stays put (the STRETCH command). crossing is two "
    "corner points; objects fully inside simply move. Give a displacement, or "
    "from_point and to_point. handles limits which objects may be affected."
))
def entity_stretch(
    crossing: list[list[float]],
    displacement: list[float] | None = None,
    from_point: list[float] | None = None,
    to_point: list[float] | None = None,
    handles: list[str] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not crossing or len(crossing) != 2:
        raise AcadError("crossing needs exactly two corner points")
    if displacement is not None:
        base, dest = [0.0, 0.0, 0.0], [float(v) for v in displacement] + ([0.0] if len(displacement) == 2 else [])
    elif from_point is not None and to_point is not None:
        base, dest = from_point, to_point
    else:
        raise AcadError("give a displacement, or both from_point and to_point")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    # a crossing window only finds what is on screen, exactly like picking it
    com.run_com(lambda: com.quiet(lambda: com.app().ZoomExtents()), timeout=60)
    count = lisp.evaluate(
        lisp.raw(
            f"(progn (setq amx-sel {_ss_crossing(crossing[0], crossing[1], handles)}) "
            f"(if amx-sel (progn {lisp.command('_.STRETCH', lisp.raw('amx-sel'), '', base, dest)} "
            "(sslength amx-sel)) 0))"
        ),
        doc=doc,
        timeout=300,
    )
    return {"stretched": int(count or 0), "crossing": crossing, "moved_by": dest if displacement else [to_point, from_point]}


@tool(description=(
    "Align objects by matching source points to destination points (the ALIGN "
    "command): one pair moves, two pairs move and rotate (and optionally "
    "scale), three pairs align in 3D."
))
def entity_align(
    handles: list[str],
    source_points: list[list[float]],
    destination_points: list[list[float]],
    scale: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")
    n = len(source_points)
    if n not in (1, 2, 3) or len(destination_points) != n:
        raise AcadError("give 1, 2 or 3 source points and the same number of destination points")
    args: list[Any] = ["_.ALIGN", lisp.ss_from(handles), ""]
    for s_pt, d_pt in zip(source_points, destination_points):
        args += [s_pt, d_pt]
    if n == 1:
        args.append("")                     # no second source point
    elif n == 2:
        args.append("")                     # no third source point
        args.append("_Yes" if scale else "_No")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    lisp.evaluate(lisp.command(*args), doc=doc, timeout=300)
    return {"aligned": len(handles), "pairs": n, "scaled": bool(scale and n == 2)}


def _end_point(ent: Any, which: str) -> list[float]:
    kind = util.dxf_type(ent)
    if kind in ("LWPOLYLINE", "POLYLINE"):
        coords = com.unwrap(ent.Coordinates)
        step = 2 if kind == "LWPOLYLINE" else 3
        pts = [list(coords[i:i + 2]) for i in range(0, len(coords), step)]
        p = pts[-1] if which == "end" else pts[0]
        return [float(p[0]), float(p[1])]
    p = util.round_pt(ent.EndPoint if which == "end" else ent.StartPoint)
    return p[:2]


@tool(description=(
    "Lengthen or shorten open curves (the LENGTHEN command) at one end: by a "
    "delta (negative shortens), to a total length, or by a percentage. end is "
    "'end' or 'start' of the curve."
))
def entity_lengthen(
    handles: list[str],
    delta: float | None = None,
    total: float | None = None,
    percent: float | None = None,
    end: str = "end",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")
    which = str(end).strip().lower()
    if which not in ("end", "start"):
        raise AcadError("end must be 'end' or 'start'")
    if delta is not None:
        mode: list[Any] = ["_DElta", float(delta)]
    elif total is not None:
        mode = ["_Total", float(total)]
    elif percent is not None:
        mode = ["_Percent", float(percent)]
    else:
        raise AcadError("give delta, total or percent")

    def picks() -> list[tuple[str, list[float]]]:
        doc = com.find_doc(drawing)
        return [(str(h), _end_point(com.by_handle(doc, str(h)), which)) for h in handles]

    targets = com.run_com(picks, timeout=120)
    args: list[Any] = ["_.LENGTHEN", *mode]
    for h, p in targets:
        args.append(lisp.raw(f"(list {lisp.entity(h)} {lisp.lpoint(p)})"))
    args.append("")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    lisp.evaluate(lisp.command(*args), doc=doc, timeout=300)

    def lengths() -> dict[str, float | None]:
        d = com.find_doc(drawing)
        return {
            str(h): com.quiet(lambda h=h: round(float(com.by_handle(d, str(h)).Length), 6))
            for h in handles
        }

    return {"changed": len(handles), "mode": mode[0].lstrip("_"), "lengths": com.run_com(lengths, timeout=120)}


PEDIT_OPTIONS = {
    "fit": "_Fit", "spline": "_Spline", "decurve": "_Decurve",
}


@tool(description=(
    "Edit a polyline. action: close, open, width (constant width), add_vertex "
    "(index, point - inserts before that index), move_vertex (index, point), "
    "delete_vertex (index), reverse, join (merge lines/arcs/polylines in "
    "handles into one polyline, within fuzz), to_polyline (convert lines and "
    "arcs), fit, spline, decurve, linetype_generation (on/off), or info."
))
def polyline_edit(
    handle: str | None = None,
    action: str = "info",
    index: int | None = None,
    point: list[float] | None = None,
    width: float | None = None,
    handles: list[str] | None = None,
    fuzz: float = 0.0,
    on: bool | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()

    if verb in ("join", "to_polyline"):
        subjects = [str(h) for h in (handles or ([handle] if handle else []))]
        if not subjects:
            raise AcadError(f"{verb} needs handles")
        doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
        if verb == "to_polyline":
            body = lisp.command("_.PEDIT", "_Multiple", lisp.ss_from(subjects), "", "")
        else:
            body = lisp.command(
                "_.PEDIT", "_Multiple", lisp.ss_from(subjects), "", "_Join", float(fuzz), ""
            )
        _, created = lisp.capture(lisp.pushed({"PEDITACCEPT": 1}, body), doc=doc, timeout=300)
        survivors = lisp.evaluate(
            lisp.raw(
                "(vl-remove nil (mapcar '(lambda (h) (if (handent h) h)) "
                + "(list " + " ".join(lisp.lstr(h) for h in subjects) + ")))"
            ),
            doc=doc,
            timeout=60,
        ) or []
        return {"action": verb, "created": created, "remaining": survivors}

    if not handle:
        raise AcadError("give the polyline's handle")

    if verb == "reverse":
        doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
        lisp.evaluate(lisp.command("_.REVERSE", lisp.entity(str(handle)), ""), doc=doc, timeout=120)
        return {"action": "reverse", "handle": handle}
    if verb in PEDIT_OPTIONS:
        doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
        lisp.evaluate(
            lisp.pushed(
                {"PEDITACCEPT": 1},
                lisp.command("_.PEDIT", lisp.entity(str(handle)), PEDIT_OPTIONS[verb], ""),
            ),
            doc=doc,
            timeout=120,
        )
        return {"action": verb, "handle": handle}
    if verb == "linetype_generation":
        if on is None:
            raise AcadError("linetype_generation needs on=true or false")
        doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
        lisp.evaluate(
            lisp.pushed(
                {"PEDITACCEPT": 1},
                lisp.command("_.PEDIT", lisp.entity(str(handle)), "_Ltype", "_ON" if on else "_OFF", ""),
            ),
            doc=doc,
            timeout=120,
        )
        return {"action": verb, "handle": handle, "on": bool(on)}

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        ent = com.by_handle(doc, str(handle))
        kind = util.dxf_type(ent)
        if kind not in ("LWPOLYLINE", "POLYLINE"):
            raise AcadError(f"{handle} is a {kind}, not a polyline (use to_polyline first)")
        if verb == "info":
            info = util.describe(ent)
            info["vertices"] = len(info.get("points", []))
            info["constant_width"] = com.quiet(lambda: round(float(ent.ConstantWidth), 6))
            return info
        if verb == "close":
            ent.Closed = True
        elif verb == "open":
            ent.Closed = False
        elif verb == "width":
            if width is None:
                raise AcadError("width needs the width value")
            ent.ConstantWidth = float(width)
        elif verb in ("add_vertex", "move_vertex", "delete_vertex"):
            if kind != "LWPOLYLINE":
                raise AcadError("vertex editing works on lightweight polylines; convert it first")
            if index is None:
                raise AcadError(f"{verb} needs the vertex index (0-based)")
            coords = list(com.unwrap(ent.Coordinates))
            pts = [coords[i:i + 2] for i in range(0, len(coords), 2)]
            bulges = [float(com.quiet(lambda i=i: ent.GetBulge(i), 0.0) or 0.0) for i in range(len(pts))]
            i = int(index)
            if verb == "delete_vertex":
                if not 0 <= i < len(pts):
                    raise AcadError(f"index {i} is out of range (0-{len(pts) - 1})")
                if len(pts) <= 2:
                    raise AcadError("a polyline needs at least two vertices")
                del pts[i]
                del bulges[i]
            else:
                if point is None:
                    raise AcadError(f"{verb} needs the point")
                p = [float(point[0]), float(point[1])]
                if verb == "move_vertex":
                    if not 0 <= i < len(pts):
                        raise AcadError(f"index {i} is out of range (0-{len(pts) - 1})")
                    pts[i] = p
                else:
                    i = max(0, min(i, len(pts)))
                    pts.insert(i, p)
                    bulges.insert(i, 0.0)
            flat = [float(v) for p in pts for v in p]
            ent.Coordinates = com.doubles(flat)
            for j, b in enumerate(bulges):
                if b:
                    com.quiet(lambda j=j, b=b: ent.SetBulge(j, b))
        else:
            raise AcadError(
                "action must be info, close, open, width, add_vertex, move_vertex, "
                "delete_vertex, reverse, join, to_polyline, fit, spline, decurve or "
                "linetype_generation"
            )
        com.quiet(lambda: ent.Update())
        out = util.describe(ent)
        out["action"] = verb
        return out

    return com.run_com(work, timeout=180)


@tool(description=(
    "Place points or blocks along a curve: divide it into a number of equal "
    "segments (DIVIDE) or step along it by a length (MEASURE). With a block "
    "name, one insert goes at each division. point_style sets PDMODE so plain "
    "points are visible (3 = X, 34 = circle with cross)."
))
def entity_divide(
    handle: str,
    segments: int | None = None,
    length: float | None = None,
    block: str | None = None,
    align_block: bool = True,
    point_style: int | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    if segments is None and length is None:
        raise AcadError("give segments (DIVIDE) or length (MEASURE)")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    if point_style is not None:
        lisp.evaluate(lisp.raw(f'(setvar "PDMODE" {int(point_style)})'), doc=doc, timeout=60)
    ent = lisp.entity(str(handle))
    if segments is not None:
        if int(segments) < 2:
            raise AcadError("segments must be at least 2")
        if block:
            body = lisp.command("_.DIVIDE", ent, "_Block", str(block), "_Yes" if align_block else "_No", int(segments))
        else:
            body = lisp.command("_.DIVIDE", ent, int(segments))
    else:
        if float(length) <= 0:
            raise AcadError("length must be positive")
        if block:
            body = lisp.command("_.MEASURE", ent, "_Block", str(block), "_Yes" if align_block else "_No", float(length))
        else:
            body = lisp.command("_.MEASURE", ent, float(length))
    _, created = lisp.capture(body, doc=doc, timeout=300)
    return {
        "created": created,
        "count": len(created),
        "mode": "divide" if segments is not None else "measure",
        "placed": block or "points",
    }


@tool(description=(
    "Display order: send entities to the back or front, or above/below a "
    "reference entity (DRAWORDER). action hatches_to_back sends every hatch "
    "behind everything else; text_to_front brings text, dimensions and leaders "
    "forward."
))
def draw_order(
    action: str = "back",
    handles: list[str] | None = None,
    reference: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    if verb == "hatches_to_back":
        lisp.run_command("_.HATCHTOBACK", doc=doc, timeout=300)
        return {"action": verb}
    if verb == "text_to_front":
        lisp.run_command("_.TEXTTOFRONT", "_All", doc=doc, timeout=300)
        return {"action": verb}
    if not handles:
        raise AcadError("give the handles to reorder")
    if verb in ("front", "back"):
        args: list[Any] = ["_.DRAWORDER", lisp.ss_from(handles), "", "_Front" if verb == "front" else "_Back"]
    elif verb in ("above", "below"):
        if not reference:
            raise AcadError(f"{verb} needs a reference handle")
        args = [
            "_.DRAWORDER", lisp.ss_from(handles), "",
            "_Above" if verb == "above" else "_Under",
            lisp.entity(str(reference)), "",
        ]
    else:
        raise AcadError("action must be front, back, above, below, hatches_to_back or text_to_front")
    lisp.evaluate(lisp.command(*args), doc=doc, timeout=300)
    return {"action": verb, "count": len(handles)}


@tool(description=(
    "Move entities between model space and paper space through a layout "
    "viewport (what CHSPACE does), keeping their apparent position and size "
    "on the sheet. The layout must have a viewport; give its handle to choose "
    "which one (the newest is used otherwise)."
))
def entity_change_space(
    handles: list[str],
    to: str = "paper",
    layout: str | None = None,
    viewport: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    """Done with COM rather than the CHSPACE command, which will not take a
    selection set from a script in this release (it sits at Select objects
    until Esc). Copy into the other space, then scale and move through the
    viewport's transform - the same maths CHSPACE applies."""
    if not handles:
        raise AcadError("no handles given")
    target = str(to).strip().lower()
    if target not in ("paper", "model"):
        raise AcadError("to must be 'paper' or 'model'")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if layout:
            from .layout import _find_layout

            doc.ActiveLayout = _find_layout(doc, str(layout))
        page = doc.ActiveLayout
        if str(page.Name).lower() == "model":
            raise AcadError("switch to a paper-space layout first (layout_manage activate)")
        block = page.Block
        vps = [block.Item(i) for i in range(int(block.Count)) if util.dxf_type(block.Item(i)) == "VIEWPORT"]
        if viewport:
            vp = com.by_handle(doc, str(viewport))
        elif len(vps) >= 2:
            vp = vps[-1]            # the first VIEWPORT is the sheet itself
        else:
            raise AcadError("this layout has no viewport to move objects through (viewport_create)")
        scale = float(vp.CustomScale)
        if scale <= 0:
            raise AcadError("the viewport has no usable scale")
        twist = float(com.quiet(lambda: vp.TwistAngle, 0.0) or 0.0)
        if abs(twist) > 1e-9:
            raise AcadError("the viewport view is twisted; this only handles untwisted views")
        # a paper-space viewport has no ViewCenter: Target is the model point
        # shown at its centre (for an untwisted top view)
        vcenter = util.round_pt(vp.Target)
        pcenter = util.round_pt(vp.Center)          # where that is on the sheet
        ents = com.by_handles(doc, [str(h) for h in handles])
        owner = doc.PaperSpace if target == "paper" else doc.ModelSpace
        # CopyObjects has an [in,out] IDPairs argument, so pywin32 hands back
        # (objects, idpairs); take the objects whichever shape comes back
        raw = com.unwrap(com.retry(lambda: doc.CopyObjects(com.objects(ents), owner))) or []
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        # the copies come back as bare IDispatch pointers; wrap them
        made = [
            win32com.client.Dispatch(o)
            for o in raw
            if not isinstance(o, (list, int, float, str))
        ]
        for obj in made:
            if target == "paper":
                obj.ScaleEntity(com.pt(vcenter), scale)
                obj.Move(com.pt(vcenter), com.pt(pcenter))
            else:
                obj.ScaleEntity(com.pt(pcenter), 1.0 / scale)
                obj.Move(com.pt(pcenter), com.pt(vcenter))
        for e in ents:
            com.quiet(lambda e=e: e.Delete())
        return {
            "moved": len(made),
            "created": [str(o.Handle) for o in made],
            "to": target,
            "layout": str(page.Name),
            "viewport": str(vp.Handle),
            "scale": f"1:{round(1.0 / scale, 4):g}",
        }

    return com.run_com(work, timeout=300)
