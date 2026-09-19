"""Annotation: text, dimensions, leaders and tables."""

from __future__ import annotations

import math
from typing import Any

from .. import com, lisp, util
from ..errors import AcadError
from ..registry import tool

ALIGNMENT = {
    "left": 0, "center": 1, "centre": 1, "right": 2, "aligned": 3, "middle": 4,
    "fit": 5, "top-left": 6, "top-center": 7, "top-centre": 7, "top-right": 8,
    "middle-left": 9, "middle-center": 10, "middle-centre": 10, "middle-right": 11,
    "bottom-left": 12, "bottom-center": 13, "bottom-centre": 13, "bottom-right": 14,
}

ATTACHMENT = {
    "top-left": 1, "top-center": 2, "top-centre": 2, "top-right": 3,
    "middle-left": 4, "middle-center": 5, "middle-centre": 5, "middle-right": 6,
    "bottom-left": 7, "bottom-center": 8, "bottom-centre": 8, "bottom-right": 9,
}


@tool(description="Place single-line text. alignment can be left, center, right, middle, fit, top-left ... bottom-right.")
def draw_text(
    text: str,
    position: list[float],
    height: float = 2.5,
    rotation: float = 0.0,
    alignment: str | None = None,
    style: str | None = None,
    width_factor: float | None = None,
    layer: str | None = None,
    color: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if float(height) <= 0:
        raise AcadError("text height must be greater than zero")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(
            lambda: target.AddText(str(text), com.pt(position), float(height))
        )
        if rotation:
            ent.Rotation = math.radians(float(rotation))
        if style:
            ent.StyleName = str(style)
        if width_factor is not None:
            ent.ScaleFactor = float(width_factor)
        if alignment:
            key = str(alignment).strip().lower()
            if key not in ALIGNMENT:
                raise AcadError(
                    f"unknown alignment {alignment!r}; try "
                    "left, center, right, middle, top-left, bottom-right ..."
                )
            ent.Alignment = ALIGNMENT[key]
            if ALIGNMENT[key] != 0:
                ent.TextAlignmentPoint = com.pt(position)
        util.apply_props(ent, layer=layer, colour=color)
        return util.describe(ent)

    return com.run_com(work, timeout=120)


@tool(description=(
    "Place paragraph (multiline) text. Use \\P in the text for a line break. "
    "width is the wrap width; 0 means no wrapping."
))
def draw_mtext(
    text: str,
    position: list[float],
    width: float = 0.0,
    height: float = 2.5,
    rotation: float = 0.0,
    attachment: str | None = None,
    style: str | None = None,
    layer: str | None = None,
    color: Any = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        ent = com.retry(
            lambda: target.AddMText(com.pt(position), float(width), str(text))
        )
        ent.Height = float(height)
        if rotation:
            ent.Rotation = math.radians(float(rotation))
        if style:
            ent.StyleName = str(style)
        if attachment:
            key = str(attachment).strip().lower()
            if key not in ATTACHMENT:
                raise AcadError(f"unknown attachment {attachment!r}")
            ent.AttachmentPoint = ATTACHMENT[key]
            ent.InsertionPoint = com.pt(position)
        util.apply_props(ent, layer=layer, colour=color)
        return util.describe(ent)

    return com.run_com(work, timeout=120)


@tool(description="Change the wording of existing text, mtext, attributes or dimension overrides.")
def text_edit(
    handles: list[str],
    new_text: str,
    drawing: str | None = None,
) -> dict[str, Any]:
    if not handles:
        raise AcadError("no handles given")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        done, skipped = [], []
        for h in handles:
            ent = com.by_handle(doc, str(h))
            kind = util.dxf_type(ent)
            if kind in ("TEXT", "MTEXT", "ATTRIB", "ATTDEF"):
                ent.TextString = str(new_text)
                done.append(str(h))
            elif kind == "DIMENSION":
                ent.TextOverride = str(new_text)
                done.append(str(h))
            else:
                skipped.append({"handle": str(h), "type": kind})
        out: dict[str, Any] = {"changed": done, "count": len(done)}
        if skipped:
            out["not_text"] = skipped
        return out

    return com.run_com(work, timeout=300)


@tool(description=(
    "Find and replace wording across a drawing's text, mtext, attributes and "
    "dimension overrides. Leave replace_with empty to only report matches."
))
def text_find_replace(
    find: str,
    replace_with: str | None = None,
    match_case: bool = False,
    layer: str | None = None,
    whole_drawing: bool = True,
    drawing: str | None = None,
) -> dict[str, Any]:
    needle = str(find)
    if not needle:
        raise AcadError("nothing to find")

    filters = '(list (cons 0 "TEXT,MTEXT,ATTDEF,DIMENSION,MULTILEADER")'
    if layer:
        filters += f" (cons 8 {lisp.lstr(str(layer))})"
    filters += ")"

    handles = [
        str(h)
        for h in (lisp.evaluate(lisp.raw(f'(acadmcp:handles (ssget "_X" {filters}))'),
                                timeout=300) or [])
    ]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        hits: list[dict[str, Any]] = []
        changed = 0
        probe = needle if match_case else needle.lower()

        def scan(ent: Any, getter, setter, label: str) -> None:
            nonlocal changed
            current = getter()
            if current is None:
                return
            text = str(current)
            hay = text if match_case else text.lower()
            if probe not in hay:
                return
            entry = {
                "handle": str(ent.Handle),
                "type": util.dxf_type(ent),
                "layer": str(com.quiet(lambda: ent.Layer, "")),
                "text": text[:200],
                "field": label,
            }
            if replace_with is not None:
                if match_case:
                    updated = text.replace(needle, str(replace_with))
                else:
                    out, low, start = [], text.lower(), 0
                    while True:
                        at = low.find(probe, start)
                        if at < 0:
                            out.append(text[start:])
                            break
                        out.append(text[start:at])
                        out.append(str(replace_with))
                        start = at + len(needle)
                    updated = "".join(out)
                setter(updated)
                entry["now"] = updated[:200]
                changed += 1
            hits.append(entry)

        for h in handles:
            try:
                ent = com.by_handle(doc, h)
            except Exception:  # noqa: BLE001
                continue
            kind = util.dxf_type(ent)
            if kind in ("TEXT", "MTEXT", "ATTDEF", "MULTILEADER"):
                scan(ent, lambda e=ent: com.quiet(lambda: e.TextString),
                     lambda v, e=ent: setattr(e, "TextString", v), "text")
            elif kind == "DIMENSION":
                scan(ent, lambda e=ent: com.quiet(lambda: e.TextOverride),
                     lambda v, e=ent: setattr(e, "TextOverride", v), "override")

        # block attributes live on the inserts, not in the ssget above
        att_handles = [
            str(x)
            for x in (
                lisp.evaluate(
                    lisp.raw('(acadmcp:handles (ssget "_X" (list (cons 0 "INSERT"))))'),
                    timeout=300,
                )
                or []
            )
        ]
        for h in att_handles:
            try:
                ref = com.by_handle(doc, h)
            except Exception:  # noqa: BLE001
                continue
            for att in com.unwrap(com.quiet(lambda: ref.GetAttributes(), []) or []):
                scan(att, lambda a=att: com.quiet(lambda: a.TextString),
                     lambda v, a=att: setattr(a, "TextString", v), "attribute")

        return {
            "searched_for": needle,
            "matches": len(hits),
            "replaced": changed if replace_with is not None else None,
            "results": hits[:200],
        }

    result = com.run_com(work, timeout=600)
    return {k: v for k, v in result.items() if v is not None}


@tool(description=(
    "Add a dimension. kind: linear (horizontal/vertical), aligned, angular, "
    "radial, diameter, ordinate or arc. Give the points the kind needs and "
    "text_position for where the dimension line sits."
))
def draw_dimension(
    kind: str = "aligned",
    point1: list[float] | None = None,
    point2: list[float] | None = None,
    text_position: list[float] | None = None,
    vertex: list[float] | None = None,
    center: list[float] | None = None,
    radius_point: list[float] | None = None,
    leader_length: float = 0.0,
    rotation: float = 0.0,
    text_override: str | None = None,
    style: str | None = None,
    layer: str | None = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    key = str(kind).strip().lower()

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)

        if key in ("linear", "rotated", "horizontal", "vertical"):
            if not (point1 and point2 and text_position):
                raise AcadError("a linear dimension needs point1, point2 and text_position")
            angle = float(rotation)
            if key == "horizontal":
                angle = 0.0
            elif key == "vertical":
                angle = 90.0
            ent = com.retry(
                lambda: target.AddDimRotated(
                    com.pt(point1), com.pt(point2), com.pt(text_position),
                    math.radians(angle),
                )
            )
        elif key == "aligned":
            if not (point1 and point2 and text_position):
                raise AcadError("an aligned dimension needs point1, point2 and text_position")
            ent = com.retry(
                lambda: target.AddDimAligned(
                    com.pt(point1), com.pt(point2), com.pt(text_position)
                )
            )
        elif key == "angular":
            if not (vertex and point1 and point2 and text_position):
                raise AcadError(
                    "an angular dimension needs vertex, point1, point2 and text_position"
                )
            ent = com.retry(
                lambda: target.AddDimAngular(
                    com.pt(vertex), com.pt(point1), com.pt(point2), com.pt(text_position)
                )
            )
        elif key in ("radial", "radius"):
            if not (center and radius_point):
                raise AcadError("a radial dimension needs center and radius_point")
            ent = com.retry(
                lambda: target.AddDimRadial(
                    com.pt(center), com.pt(radius_point), float(leader_length)
                )
            )
        elif key in ("diameter", "diametric"):
            if not (point1 and point2):
                raise AcadError(
                    "a diameter dimension needs point1 and point2 on opposite sides "
                    "of the circle"
                )
            ent = com.retry(
                lambda: target.AddDimDiametric(
                    com.pt(point1), com.pt(point2), float(leader_length)
                )
            )
        elif key == "ordinate":
            if not (point1 and text_position):
                raise AcadError("an ordinate dimension needs point1 and text_position")
            ent = com.retry(
                lambda: target.AddDimOrdinate(
                    com.pt(point1), com.pt(text_position), str(rotation) == "0"
                )
            )
        elif key == "arc":
            if not (center and point1 and point2 and text_position):
                raise AcadError(
                    "an arc-length dimension needs center, point1, point2 and text_position"
                )
            ent = com.retry(
                lambda: target.AddDimArc(
                    com.pt(center), com.pt(point1), com.pt(point2), com.pt(text_position)
                )
            )
        else:
            raise AcadError(
                "kind must be linear, aligned, angular, radial, diameter, "
                "ordinate or arc"
            )

        if text_override:
            ent.TextOverride = str(text_override)
        if style:
            ent.StyleName = str(style)
        if layer:
            ent.Layer = str(layer)
        return util.describe(ent)

    return com.run_com(work, timeout=180)


@tool(description="Draw a leader with text at the end. points are the leader vertices, from the arrow to the text.")
def draw_leader(
    points: list[list[float]],
    text: str | None = None,
    text_height: float = 2.5,
    arrow: bool = True,
    layer: str | None = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not points or len(points) < 2:
        raise AcadError("a leader needs at least two points")

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        note = None
        if text:
            tip = points[-1]
            note = com.retry(
                lambda: target.AddMText(com.pt(tip), 0.0, str(text))
            )
            note.Height = float(text_height)
            if layer:
                note.Layer = str(layer)
        ent = com.retry(
            lambda: target.AddLeader(com.flat3d(points), note, 0 if arrow else 1)
        )
        if layer:
            ent.Layer = str(layer)
        out = util.describe(ent)
        if note is not None:
            out["text_handle"] = str(note.Handle)
            out["text"] = str(text)
        return out

    return com.run_com(work, timeout=180)


@tool(description=(
    "Insert a table and fill it with data. data is a list of rows, each a list "
    "of cell values; the first row is treated as the header."
))
def draw_table(
    position: list[float],
    data: list[list[Any]],
    row_height: float = 8.0,
    column_width: float = 40.0,
    title: str | None = None,
    layer: str | None = None,
    space: str = "auto",
    drawing: str | None = None,
) -> dict[str, Any]:
    if not data:
        raise AcadError("no data given")
    columns = max(len(r) for r in data)
    header_rows = 1 if title else 0
    rows = len(data) + 1 + header_rows  # AutoCAD reserves a title row

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        target = com.space(doc, space)
        if layer:
            util.ensure_layer(doc, layer)
        table = com.retry(
            lambda: target.AddTable(
                com.pt(position), int(rows), int(columns),
                float(row_height), float(column_width),
            ),
            context="creating the table",
        )
        if title:
            com.quiet(lambda: table.SetText(0, 0, str(title)))
        offset = 1
        for r, row in enumerate(data):
            for c, value in enumerate(row):
                com.quiet(
                    lambda r=r, c=c, v=value: table.SetText(r + offset, c, str(v))
                )
        if layer:
            table.Layer = str(layer)
        return {
            "handle": str(table.Handle),
            "rows": int(rows),
            "columns": int(columns),
            "filled": sum(len(r) for r in data),
        }

    return com.run_com(work, timeout=300)
