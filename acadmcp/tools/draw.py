"""Creating geometry: lines, curves, polylines, points, hatches."""

from __future__ import annotations

import math
from typing import Any, Sequence

from .. import com, lisp, util
from ..errors import AcadError
from ..registry import tool

# AddHatch arguments
PREDEFINED, USER_DEFINED, CUSTOM = 1, 0, 2
HATCH_OBJECT, GRADIENT_OBJECT = 0, 1


def _append_loop(append: Any, objects: list[Any]) -> None:
    """AppendOuterLoop/AppendInnerLoop want a variant array of objects.

    pywin32 marshals the list differently depending on build, so try the plain
    list first (which usually works) and fall back to an explicit variant array.
    """
    if not objects:
        raise AcadError("a hatch loop needs at least one boundary object")
    errors = []
    for attempt in (
        lambda: append(com.objects(objects)),          # VT_DISPATCH array
        lambda: append(objects),
    ):
        try:
            attempt()
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
    raise AcadError(
        "AutoCAD rejected the hatch boundary. It must be closed curves "
        "(a closed polyline, circle, ellipse or region). Details: "
        + errors[0]
    )


def _finish(entity: Any, props: dict[str, Any]) -> dict[str, Any]:
    util.apply_props(entity, **props)
    return util.describe(entity)


def _props(
    layer: str | None,
    color: Any,
    linetype: str | None,
    lineweight: Any,
    transparency: Any = None,
    true_color: Any = None,
) -> dict[str, Any]:
    return {
        "layer": layer,
        "colour": color,
        "linetype": linetype,
        "lineweight": lineweight,
        "transparency": transparency,
        "true_color": true_color,
    }


@tool(description="Draw a straight line between two points.")
def draw_line(
    start: list[float],
    end: list[float],
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(lambda: target.AddLine(com.pt(start), com.pt(end)))
        return _finish(ent, _props(layer, color, linetype, lineweight))

    return com.run_com(work, timeout=90)


@tool(description="Draw a polyline through a list of points. Set closed=true for a closed shape; bulges make arc segments (bulge = tan of a quarter of the included angle).")
def draw_polyline(
    points: list[list[float]],
    closed: bool = False,
    bulges: list[float] | None = None,
    width: float | None = None,
    elevation: float | None = None,
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not points or len(points) < 2:
        raise AcadError("a polyline needs at least two points")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(lambda: target.AddLightWeightPolyline(com.flat2d(points)))
        if closed:
            ent.Closed = True
        if elevation is not None:
            ent.Elevation = float(elevation)
        if width is not None:
            ent.ConstantWidth = float(width)
        for i, bulge in enumerate(bulges or []):
            if bulge:
                ent.SetBulge(i, float(bulge))
        return _finish(ent, _props(layer, color, linetype, lineweight))

    return com.run_com(work, timeout=120)


@tool(description="Draw a rectangle from two opposite corners.")
def draw_rectangle(
    corner1: list[float],
    corner2: list[float],
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    x1, y1 = float(corner1[0]), float(corner1[1])
    x2, y2 = float(corner2[0]), float(corner2[1])
    if x1 == x2 or y1 == y2:
        raise AcadError("the two corners must differ in both x and y")
    pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(lambda: target.AddLightWeightPolyline(com.flat2d(pts)))
        ent.Closed = True
        out = _finish(ent, _props(layer, color, linetype, lineweight))
        out["width"] = round(abs(x2 - x1), 6)
        out["height"] = round(abs(y2 - y1), 6)
        return out

    return com.run_com(work, timeout=90)


@tool(description="Draw a circle. Give either radius or diameter.")
def draw_circle(
    center: list[float],
    radius: float | None = None,
    diameter: float | None = None,
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if radius is None and diameter is None:
        raise AcadError("give a radius or a diameter")
    r = float(radius) if radius is not None else float(diameter) / 2.0
    if r <= 0:
        raise AcadError("the radius must be greater than zero")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(lambda: target.AddCircle(com.pt(center), r))
        return _finish(ent, _props(layer, color, linetype, lineweight))

    return com.run_com(work, timeout=90)


@tool(description="Draw an arc, either by centre/radius/angles (degrees, counter-clockwise) or through three points.")
def draw_arc(
    center: list[float] | None = None,
    radius: float | None = None,
    start_angle: float | None = None,
    end_angle: float | None = None,
    through: list[list[float]] | None = None,
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if through:
        if len(through) != 3:
            raise AcadError("a three-point arc needs exactly three points")
        payload = lisp.evaluate(
            lisp.raw(
                "(acadmcp:capture '(lambda () %s))"
                % lisp.command("_.ARC", through[0], through[1], through[2])
            )
        )
        handles = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
        if not handles:
            raise AcadError("AutoCAD did not create the arc")
        handle = handles[-1]

        def decorate() -> dict[str, Any]:
            doc = com.find_doc(drawing)
            ent = com.by_handle(doc, handle)
            if layer:
                util.ensure_layer(doc, layer)
            return _finish(ent, _props(layer, color, linetype, lineweight))

        return com.run_com(decorate, timeout=60)

    if center is None or radius is None or start_angle is None or end_angle is None:
        raise AcadError(
            "give centre, radius, start_angle and end_angle - or three points in 'through'"
        )

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(
            lambda: target.AddArc(
                com.pt(center),
                float(radius),
                math.radians(float(start_angle)),
                math.radians(float(end_angle)),
            )
        )
        return _finish(ent, _props(layer, color, linetype, lineweight))

    return com.run_com(work, timeout=90)


@tool(description="Draw an ellipse from its centre, a major-axis vector (from the centre to the end of the long axis) and the minor/major ratio.")
def draw_ellipse(
    center: list[float],
    major_axis: list[float],
    ratio: float = 0.5,
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not 0 < float(ratio) <= 1:
        raise AcadError("the ratio must be greater than 0 and at most 1")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(
            lambda: target.AddEllipse(com.pt(center), com.pt(major_axis), float(ratio))
        )
        return _finish(ent, _props(layer, color, linetype, lineweight))

    return com.run_com(work, timeout=90)


@tool(description="Draw a spline through a list of fit points.")
def draw_spline(
    points: list[list[float]],
    closed: bool = False,
    layer: str | None = None,
    color: Any = None,
    linetype: str | None = None,
    lineweight: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not points or len(points) < 3:
        raise AcadError("a spline needs at least three fit points")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(
            lambda: target.AddSpline(
                com.flat3d(points), com.pt([0, 0, 0]), com.pt([0, 0, 0])
            )
        )
        if closed:
            com.quiet(lambda: setattr(ent, "Closed", True))
        return _finish(ent, _props(layer, color, linetype, lineweight))

    return com.run_com(work, timeout=120)


@tool(description="Place one or more point objects.")
def draw_point(
    positions: list[list[float]],
    layer: str | None = None,
    color: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not positions:
        raise AcadError("no positions given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        made = []
        for p in positions:
            ent = com.retry(lambda p=p: target.AddPoint(com.pt(p)))
            util.apply_props(ent, layer=layer, colour=color)
            made.append(str(ent.Handle))
        return {"created": made, "count": len(made)}

    return com.run_com(work, timeout=180)


@tool(description=(
    "Hatch an area. Either give boundary_handles (closed polylines, circles, "
    "regions) or internal_points inside enclosed areas, exactly like picking a "
    "point with the HATCH command. pattern defaults to SOLID."
))
def draw_hatch(
    boundary_handles: list[str] | None = None,
    internal_points: list[list[float]] | None = None,
    pattern: str = "SOLID",
    scale: float = 1.0,
    angle: float = 0.0,
    associative: bool = True,
    inner_handles: list[str] | None = None,
    layer: str | None = None,
    color: Any = None,
    transparency: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not boundary_handles and not internal_points:
        raise AcadError("give boundary_handles or internal_points")

    name = str(pattern).strip().upper() or "SOLID"

    if internal_points:
        # -HATCH is the only way to hatch by a picked point; COM cannot do it.
        # Boundary detection only sees what is on screen, so make sure the
        # geometry is in view first.
        com.run_com(lambda: com.quiet(lambda: com.app().ZoomExtents()), timeout=60)
        steps: list[Any] = ["_.-HATCH", "_P", name]
        if name != "SOLID":
            steps += [float(scale), float(angle)]
        for p in internal_points:
            steps.append(list(p))
        steps.append("")
        payload = lisp.evaluate(
            lisp.raw("(acadmcp:capture '(lambda () %s))" % lisp.command(*steps)),
            timeout=180,
        )
        handles = payload[1] if isinstance(payload, list) and len(payload) == 2 else []
        if not handles:
            raise AcadError(
                "AutoCAD could not find a closed boundary around those points - "
                "check the area is fully enclosed in the current view"
            )

        def decorate() -> dict[str, Any]:
            doc = com.find_doc(drawing)
            if layer:
                util.ensure_layer(doc, layer)
            out = []
            for h in handles:
                ent = com.by_handle(doc, h)
                util.apply_props(ent, layer=layer, colour=color, transparency=transparency)
                out.append(util.describe(ent))
            return {"created": out, "count": len(out), "method": "internal point"}

        return com.run_com(decorate, timeout=90)

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        kind = USER_DEFINED if name in ("USER", "U") else PREDEFINED
        hatch = com.retry(
            lambda: target.AddHatch(kind, name, bool(associative), HATCH_OBJECT),
            context="creating the hatch",
        )
        outer = com.by_handles(doc, boundary_handles or [])
        _append_loop(hatch.AppendOuterLoop, outer)
        for h in inner_handles or []:
            _append_loop(hatch.AppendInnerLoop, [com.by_handle(doc, h)])
        if name != "SOLID":
            com.quiet(lambda: setattr(hatch, "PatternScale", float(scale)))
            com.quiet(lambda: setattr(hatch, "PatternAngle", math.radians(float(angle))))
        hatch.Evaluate()
        util.apply_props(hatch, layer=layer, colour=color, transparency=transparency)
        return {"created": [util.describe(hatch)], "count": 1, "method": "boundary objects"}

    return com.run_com(work, timeout=180)


@tool(description="Draw a construction line (XLINE, infinite) or a ray (semi-infinite) through a point in a direction.")
def draw_construction_line(
    point: list[float],
    direction: list[float] | None = None,
    angle: float | None = None,
    ray: bool = False,
    layer: str | None = None,
    color: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if direction is None and angle is None:
        raise AcadError("give a direction vector or an angle in degrees")
    if direction is None:
        rad = math.radians(float(angle))
        direction = [math.cos(rad), math.sin(rad), 0.0]
    second = [float(point[0]) + float(direction[0]),
              float(point[1]) + float(direction[1]),
              (float(point[2]) if len(point) > 2 else 0.0) + (float(direction[2]) if len(direction) > 2 else 0.0)]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(
            lambda: target.AddRay(com.pt(point), com.pt(second))
            if ray
            else target.AddXline(com.pt(point), com.pt(second))
        )
        return _finish(ent, _props(layer, color, None, None))

    return com.run_com(work, timeout=90)
