"""Finding things in a drawing, and inspecting what you found."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import com, lisp, util
from ..errors import AcadError
from ..registry import tool

# DXF group codes used for selection filters
CODE = {
    "type": 0,
    "text": 1,
    "block": 2,
    "linetype": 6,
    "layer": 8,
    "color": 62,
    "layout": 410,
}


def _filter_pairs(
    type: str | None,
    layer: str | None,
    color: Any,
    block: str | None,
    text: str | None,
    linetype: str | None,
    space: str | None,
    layout: str | None,
    dxf: dict[str, Any] | None,
) -> list[tuple[int, Any]]:
    pairs: list[tuple[int, Any]] = []
    if type:
        pairs.append((0, str(type).upper()))
    if layer:
        pairs.append((8, str(layer)))
    if color is not None:
        pairs.append((62, util.colour_value(color)))
    if block:
        pairs.append((2, str(block)))
    if text:
        pairs.append((1, str(text)))
    if linetype:
        pairs.append((6, str(linetype)))
    if layout:
        pairs.append((410, str(layout)))
    elif space:
        key = str(space).lower()
        if key in ("model", "modelspace", "ms"):
            pairs.append((410, "Model"))
        elif key in ("paper", "paperspace", "ps"):
            pairs.append((410, "~Model"))   # anything that is not model space
    for k, v in (dxf or {}).items():
        try:
            pairs.append((int(k), v))
        except (TypeError, ValueError) as exc:
            raise AcadError(f"{k!r} is not a DXF group code number") from exc
    return pairs


def _filter_lisp(pairs: list[tuple[int, Any]]) -> str:
    if not pairs:
        return "nil"
    items = " ".join(f"(cons {code} {lisp.lval(value)})" for code, value in pairs)
    return f"(list {items})"


@tool(readonly=True, description=(
    "Find entities and return their handles. Filters combine with AND and accept "
    "AutoCAD wildcards (* and ?), e.g. layer='A-ROOF*'. Restrict to an area with "
    "window/crossing corners, or pass nothing to search the whole drawing. "
    "type takes DXF names: LINE, LWPOLYLINE, CIRCLE, ARC, TEXT, MTEXT, INSERT, "
    "HATCH, DIMENSION."
))
def entity_select(
    type: str | None = None,
    layer: str | None = None,
    color: Any = None,
    block: str | None = None,
    text: str | None = None,
    linetype: str | None = None,
    space: str | None = None,
    layout: str | None = None,
    window: list[list[float]] | None = None,
    crossing: list[list[float]] | None = None,
    fence: list[list[float]] | None = None,
    polygon: list[list[float]] | None = None,
    dxf_filter: dict[str, Any] | None = None,
    include_details: bool = False,
    limit: int = 500,
    drawing: str | None = None,
) -> dict[str, Any]:
    pairs = _filter_pairs(type, layer, color, block, text, linetype, space, layout, dxf_filter)
    flt = _filter_lisp(pairs)

    if window:
        if len(window) != 2:
            raise AcadError("window needs exactly two corner points")
        mode = f'(ssget "_W" {lisp.lpoint(window[0])} {lisp.lpoint(window[1])} {flt})'
    elif crossing:
        if len(crossing) != 2:
            raise AcadError("crossing needs exactly two corner points")
        mode = f'(ssget "_C" {lisp.lpoint(crossing[0])} {lisp.lpoint(crossing[1])} {flt})'
    elif fence:
        pts = " ".join(lisp.lpoint(p) for p in fence)
        mode = f'(ssget "_F" (list {pts}) {flt})'
    elif polygon:
        pts = " ".join(lisp.lpoint(p) for p in polygon)
        mode = f'(ssget "_CP" (list {pts}) {flt})'
    else:
        mode = f'(ssget "_X" {flt})'

    handles = lisp.evaluate(lisp.raw(f"(acadmcp:handles {mode})"), timeout=180) or []
    handles = [str(h) for h in handles if h]
    total = len(handles)
    shown = handles[: max(0, int(limit))]

    result: dict[str, Any] = {
        "count": total,
        "handles": shown,
        "filters": {
            k: v
            for k, v in {
                "type": type, "layer": layer, "color": color, "block": block,
                "text": text, "linetype": linetype, "space": space, "layout": layout,
            }.items()
            if v is not None
        },
    }
    if total > len(shown):
        result["truncated"] = f"showing the first {len(shown)} of {total}"

    if shown:
        def summarise() -> dict[str, Any]:
            doc = com.find_doc(drawing)
            kinds = Counter()
            layers = Counter()
            details = []
            for h in shown:
                try:
                    ent = com.by_handle(doc, h)
                except Exception:  # noqa: BLE001
                    continue
                kinds[util.dxf_type(ent)] += 1
                layers[str(com.quiet(lambda: ent.Layer, ""))] += 1
                if include_details:
                    details.append(util.describe(ent))
            out: dict[str, Any] = {
                "by_type": dict(kinds.most_common()),
                "by_layer": dict(layers.most_common(20)),
            }
            if include_details:
                out["entities"] = details
            return out

        result.update(com.run_com(summarise, timeout=180))

    return result


@tool(readonly=True, description="Look up full details of specific entities by handle: type, layer, geometry, text, block attributes.")
def entity_info(
    handles: list[str],
    geometry: bool = True,
    bounding_box: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        found, missing = [], []
        for h in handles:
            try:
                ent = com.by_handle(doc, str(h))
            except Exception:  # noqa: BLE001
                missing.append(str(h))
                continue
            info = util.describe(ent, geometry=geometry)
            if bounding_box:
                info["bounds"] = util.bbox(ent)
            found.append(info)
        out: dict[str, Any] = {"entities": found, "count": len(found)}
        if missing:
            out["not_found"] = missing
        return out

    return com.run_com(work, timeout=180)


@tool(readonly=True, description="Count what a drawing contains, grouped by entity type, layer or block name. A quick way to understand an unfamiliar drawing.")
def entity_summary(
    group_by: str = "type",
    space: str | None = None,
    layer: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    key = str(group_by).lower()
    if key not in ("type", "layer", "block"):
        raise AcadError("group_by must be 'type', 'layer' or 'block'")

    pairs = _filter_pairs(
        "INSERT" if key == "block" else None, layer, None, None, None, None,
        space, None, None,
    )
    flt = _filter_lisp(pairs)
    code = {"type": 0, "layer": 8, "block": 2}[key]
    # variables are prefixed: AutoLISP is dynamically scoped, so plain names
    # like `out` would clobber the bridge's own locals while this runs.
    expr = (
        f'(progn (setq amq-ss (ssget "_X" {flt}) amq-i 0 amq-out nil)'
        " (if amq-ss (repeat (sslength amq-ss)"
        f" (setq amq-out (cons (cdr (assoc {code} (entget (ssname amq-ss amq-i))))"
        " amq-out) amq-i (1+ amq-i))))"
        " (reverse amq-out))"
    )

    values = lisp.evaluate(lisp.raw(expr), timeout=300) or []
    counts = Counter(str(v) for v in values if v)
    return {
        "grouped_by": key,
        "total": sum(counts.values()),
        "distinct": len(counts),
        "counts": dict(counts.most_common()),
    }


@tool(readonly=True, description="Measure things: distance between two points, or the combined area, length and bounding box of the given entities.")
def measure(
    handles: list[str] | None = None,
    point1: list[float] | None = None,
    point2: list[float] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {}

    if point1 and point2:
        dx = float(point2[0]) - float(point1[0])
        dy = float(point2[1]) - float(point1[1])
        dz = (float(point2[2]) if len(point2) > 2 else 0.0) - (
            float(point1[2]) if len(point1) > 2 else 0.0
        )
        import math

        out["distance"] = round(math.hypot(math.hypot(dx, dy), dz), 8)
        out["delta"] = [round(dx, 8), round(dy, 8), round(dz, 8)]
        out["angle_degrees"] = round(math.degrees(math.atan2(dy, dx)) % 360, 6)

    if handles:
        def work() -> dict[str, Any]:
            doc = com.find_doc(drawing)
            ents = [com.by_handle(doc, str(h)) for h in handles]
            total_area = 0.0
            total_length = 0.0
            per: list[dict[str, Any]] = []
            for ent in ents:
                area = com.quiet(lambda e=ent: float(e.Area))
                length = com.quiet(lambda e=ent: float(e.Length))
                if length is None:
                    length = com.quiet(lambda e=ent: float(e.ArcLength))
                if area:
                    total_area += area
                if length:
                    total_length += length
                per.append(
                    {
                        "handle": str(ent.Handle),
                        "type": util.dxf_type(ent),
                        "area": round(area, 6) if area is not None else None,
                        "length": round(length, 6) if length is not None else None,
                    }
                )
            return {
                "entities": per,
                "total_area": round(total_area, 6),
                "total_length": round(total_length, 6),
                "bounds": util.union_bbox(ents),
            }

        out.update(com.run_com(work, timeout=180))

    if not out:
        raise AcadError("give two points, some handles, or both")
    return out
