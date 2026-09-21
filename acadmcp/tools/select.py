"""Finding things in a drawing, and inspecting what you found."""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import com, lisp, util, winui
from ..errors import AcadError, Busy, LispError, NotFound
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

    if window or crossing or fence or polygon:
        # area selection only sees what is on screen, exactly like picking it
        com.run_com(lambda: com.quiet(lambda: com.app().ZoomExtents()), timeout=60)
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


# ---------------------------------------------------------------------------
# working with the person at the screen
# ---------------------------------------------------------------------------


def _describe_handles(handles: list[str], drawing: str | None, details: bool) -> list[dict[str, Any]]:
    if not handles:
        return []

    def work() -> list[dict[str, Any]]:
        doc = com.find_doc(drawing)
        return [util.describe(com.by_handle(doc, h), geometry=details) for h in handles]

    return com.run_com(work, timeout=180)


@tool(readonly=True, description=(
    "What the user currently has selected (highlighted with grips) in AutoCAD. "
    "Lets them click things on screen and then say 'move these' or 'what are "
    "these?'. Returns the handles; the selection is left as it is."
))
def selection_current(
    include_details: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    handles = lisp.evaluate(lisp.raw("(acadmcp:pickfirst)"), doc=doc, quiet=False, timeout=60) or []
    handles = [str(h) for h in handles if h]
    out: dict[str, Any] = {"count": len(handles), "handles": handles}
    if not handles:
        out["note"] = "nothing is selected in AutoCAD right now"
    else:
        out["entities"] = _describe_handles(handles, drawing, include_details)
    return out


@tool(undo_group=False, description=(
    "Highlight entities in AutoCAD (select them with grips) so the user can "
    "see which objects are meant, or clear the selection with no handles. "
    "Optionally zoom to them first."
))
def selection_highlight(
    handles: list[str] | None = None,
    zoom_to: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    if not handles:
        lisp.evaluate(lisp.raw("(sssetfirst nil nil)"), doc=doc, quiet=False, timeout=60)
        return {"selected": 0, "cleared": True}
    if zoom_to:
        lisp.evaluate(
            lisp.command("_.ZOOM", "_Object", lisp.ss_from(handles), ""), doc=doc, timeout=120
        )
    count = lisp.evaluate(
        lisp.raw(
            f"(progn (setq amx-hs {lisp.ss_from(handles)}) (sssetfirst nil amx-hs) "
            "(if amx-hs (sslength amx-hs) 0))"
        ),
        doc=doc,
        quiet=False,
        timeout=60,
    )
    winui.focus_autocad(verify=False)
    return {"selected": int(count or 0), "handles": handles}


PICK_KINDS = ("objects", "point", "points", "distance", "text", "keyword", "number")


@tool(undo_group=False, description=(
    "Ask the user to pick something in AutoCAD and wait for it: objects (click "
    "or window-select, Enter to finish), point, points (several, Enter to "
    "finish), distance (two clicks or a typed value), text, number, or keyword "
    "(one of `options`). The prompt is shown on AutoCAD's command line and the "
    "window is brought to the front. Waits up to timeout seconds; a cancelled "
    "or timed-out pick returns picked=null rather than failing."
))
def user_pick(
    kind: str = "objects",
    prompt: str | None = None,
    options: list[str] | None = None,
    base_point: list[float] | None = None,
    timeout: float = 120,
    include_details: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    key = str(kind).strip().lower()
    if key not in PICK_KINDS:
        raise AcadError("kind must be one of " + ", ".join(PICK_KINDS))
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    msg = "\n" + (str(prompt).strip() if prompt else {
        "objects": "Select objects (Enter when done):",
        "point": "Pick a point:",
        "points": "Pick points (Enter when done):",
        "distance": "Specify a distance:",
        "text": "Enter text:",
        "keyword": "Choose an option:",
        "number": "Enter a number:",
    }[key]) + " "
    lmsg = lisp.lstr(msg)

    if key == "objects":
        code = f"(progn (prompt {lmsg}) (acadmcp:handles (ssget)))"
    elif key == "point":
        base = f" {lisp.lpoint(base_point)}" if base_point else ""
        code = f"(getpoint{base} {lmsg})"
    elif key == "points":
        code = (
            "(progn (setq amx-pts nil amx-p T) "
            f"(while (setq amx-p (if amx-pts (getpoint (last amx-pts) {lmsg}) (getpoint {lmsg}))) "
            "(setq amx-pts (append amx-pts (list amx-p)))) amx-pts)"
        )
    elif key == "distance":
        base = f" {lisp.lpoint(base_point)}" if base_point else ""
        code = f"(getdist{base} {lmsg})"
    elif key == "text":
        code = f"(getstring T {lmsg})"
    elif key == "number":
        code = f"(getreal {lmsg})"
    else:
        if not options:
            raise AcadError("keyword needs the list of options to offer")
        words = " ".join(str(o).replace(" ", "") for o in options)
        shown = "/".join(str(o) for o in options)
        code = (
            f"(progn (initget {lisp.lstr(words)}) "
            f"(getkword {lisp.lstr(msg.rstrip() + ' [' + shown + ']: ')}))"
        )

    winui.focus_autocad(verify=False)
    try:
        value = lisp.evaluate(lisp.raw(code), doc=doc, quiet=False, timeout=float(timeout))
    except Busy:
        return {"kind": key, "picked": None, "reason": f"no answer within {timeout:g}s"}
    except LispError as exc:
        text = str(exc).lower()
        if "cancel" in text or "quit" in text or "abort" in text:
            return {"kind": key, "picked": None, "reason": "the user pressed Esc"}
        raise

    out: dict[str, Any] = {"kind": key, "picked": value}
    if key == "objects":
        handles = [str(h) for h in (value or []) if h]
        out["picked"] = handles
        out["count"] = len(handles)
        if handles:
            out["entities"] = _describe_handles(handles, drawing, include_details)
    return out


@tool(description=(
    "Named groups (the GROUP command): list them, create one from handles, add "
    "or remove members, delete a group (its members stay), or select one on "
    "screen. Groups let a set of objects be picked together."
))
def group(
    action: str = "list",
    name: str | None = None,
    handles: list[str] | None = None,
    new_name: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()

    def find(doc: Any, wanted: str) -> Any:
        target = str(wanted).lower()
        for i in range(int(doc.Groups.Count)):
            g = doc.Groups.Item(i)
            if str(g.Name).lower() == target:
                return g
        raise NotFound(f"There is no group called {wanted!r}.")

    def members(g: Any) -> list[str]:
        return [str(g.Item(i).Handle) for i in range(int(g.Count))]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if verb == "list":
            rows = []
            for i in range(int(doc.Groups.Count)):
                g = doc.Groups.Item(i)
                rows.append({"name": str(g.Name), "count": int(g.Count), "handles": members(g)})
            return {"count": len(rows), "groups": rows}
        if not name:
            raise AcadError(f"{verb} needs the group name")
        if verb == "create":
            if not handles:
                raise AcadError("create needs the handles to group")
            g = com.retry(lambda: doc.Groups.Add(str(name)), context="creating the group")
            g.AppendItems(com.objects(com.by_handles(doc, [str(h) for h in handles])))
            return {"created": str(g.Name), "count": int(g.Count)}
        g = find(doc, name)
        if verb == "add":
            if not handles:
                raise AcadError("add needs handles")
            g.AppendItems(com.objects(com.by_handles(doc, [str(h) for h in handles])))
            return {"group": str(g.Name), "count": int(g.Count)}
        if verb == "remove":
            if not handles:
                raise AcadError("remove needs handles")
            g.RemoveItems(com.objects(com.by_handles(doc, [str(h) for h in handles])))
            return {"group": str(g.Name), "count": int(g.Count)}
        if verb == "delete":
            n = int(g.Count)
            com.retry(lambda: g.Delete())
            return {"deleted": name, "members_kept": n}
        if verb == "rename":
            if not new_name:
                raise AcadError("rename needs new_name")
            g.Name = str(new_name)
            return {"renamed": {"from": name, "to": str(new_name)}}
        if verb == "select":
            return {"select": members(g)}
        raise AcadError("action must be list, create, add, remove, delete, rename or select")

    result = com.run_com(work, timeout=180)
    if "select" in result:
        return selection_highlight(handles=result["select"], drawing=drawing)
    return result
