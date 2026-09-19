"""Shared helpers: describing entities, applying common properties, coercion."""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

from . import com
from .errors import AcadError, NotFound

# AutoCAD reports DXF-ish names over LISP and AcDb* class names over COM.
# Normalise to the DXF name, which is what people (and ssget filters) use.
CLASS_TO_DXF = {
    "AcDbLine": "LINE",
    "AcDbPolyline": "LWPOLYLINE",
    "AcDb2dPolyline": "POLYLINE",
    "AcDb3dPolyline": "POLYLINE",
    "AcDbCircle": "CIRCLE",
    "AcDbArc": "ARC",
    "AcDbEllipse": "ELLIPSE",
    "AcDbSpline": "SPLINE",
    "AcDbPoint": "POINT",
    "AcDbText": "TEXT",
    "AcDbMText": "MTEXT",
    "AcDbBlockReference": "INSERT",
    "AcDbMInsertBlock": "INSERT",
    "AcDbAttribute": "ATTRIB",
    "AcDbAttributeDefinition": "ATTDEF",
    "AcDbHatch": "HATCH",
    "AcDbSolid": "SOLID",
    "AcDbRegion": "REGION",
    "AcDb3dSolid": "3DSOLID",
    "AcDbRasterImage": "IMAGE",
    "AcDbWipeout": "WIPEOUT",
    "AcDbLeader": "LEADER",
    "AcDbMLeader": "MULTILEADER",
    "AcDbMline": "MLINE",
    "AcDbTable": "ACAD_TABLE",
    "AcDbViewport": "VIEWPORT",
    "AcDbRotatedDimension": "DIMENSION",
    "AcDbAlignedDimension": "DIMENSION",
    "AcDbRadialDimension": "DIMENSION",
    "AcDbDiametricDimension": "DIMENSION",
    "AcDb3PointAngularDimension": "DIMENSION",
    "AcDb2LineAngularDimension": "DIMENSION",
    "AcDbOrdinateDimension": "DIMENSION",
    "AcDbArcDimension": "DIMENSION",
    "AcDbXline": "XLINE",
    "AcDbRay": "RAY",
    "AcDbBlockTableRecord": "BLOCK",
}

LINEWEIGHTS = {
    "bylayer": -1, "byblock": -2, "default": -3,
    "0": 0, "0.05": 5, "0.09": 9, "0.13": 13, "0.15": 15, "0.18": 18,
    "0.20": 20, "0.25": 25, "0.30": 30, "0.35": 35, "0.40": 40, "0.50": 50,
    "0.53": 53, "0.60": 60, "0.70": 70, "0.80": 80, "0.90": 90, "1.00": 100,
    "1.06": 106, "1.20": 120, "1.40": 140, "1.58": 158, "2.00": 200, "2.11": 211,
}

ACI = {
    "byblock": 0, "red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5,
    "magenta": 6, "white": 7, "black": 7, "grey": 8, "gray": 8, "bylayer": 256,
}


def dxf_type(entity: Any) -> str:
    name = str(com.quiet(lambda: entity.ObjectName, "") or "")
    return CLASS_TO_DXF.get(name, name.replace("AcDb", "").upper() or "UNKNOWN")


def round_pt(p: Any, nd: int = 6) -> list[float]:
    return [round(float(v), nd) for v in com.unwrap(p)]


def colour_value(colour: Any) -> int:
    """Accept 1-255, an ACI name, 'bylayer'/'byblock', or '#rrggbb' (-> nearest ACI)."""
    if colour is None:
        raise AcadError("no colour given")
    if isinstance(colour, bool):
        raise AcadError("colour must be a number or a name")
    if isinstance(colour, int):
        if 0 <= colour <= 256:
            return colour
        raise AcadError("an AutoCAD Color Index must be 0-256")
    text = str(colour).strip().lower()
    if text.isdigit():
        return colour_value(int(text))
    if text in ACI:
        return ACI[text]
    raise AcadError(
        f"unknown colour {colour!r}; use 1-255, an index name like 'red', "
        "'bylayer' or 'byblock' (for RGB use the true_color argument)"
    )


def true_colour(rgb: str | Sequence[int]) -> tuple[int, int, int]:
    if isinstance(rgb, str):
        text = rgb.strip().lstrip("#")
        if len(text) != 6:
            raise AcadError("an RGB colour looks like '#4C9AFF'")
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    vals = [int(v) for v in rgb]
    if len(vals) != 3 or not all(0 <= v <= 255 for v in vals):
        raise AcadError("an RGB colour needs three values 0-255")
    return vals[0], vals[1], vals[2]


def lineweight_value(lw: Any) -> int:
    if isinstance(lw, (int, float)) and not isinstance(lw, bool):
        value = int(lw)
        if value in LINEWEIGHTS.values() or value in (-1, -2, -3):
            return value
        # allow 0.30 style numbers
        key = f"{float(lw):.2f}"
        if key in LINEWEIGHTS:
            return LINEWEIGHTS[key]
        raise AcadError(f"{lw} is not an AutoCAD lineweight")
    text = str(lw).strip().lower()
    if text in LINEWEIGHTS:
        return LINEWEIGHTS[text]
    try:
        return LINEWEIGHTS[f"{float(text):.2f}"]
    except Exception as exc:  # noqa: BLE001
        raise AcadError(
            f"unknown lineweight {lw!r}; use mm like 0.30, or 'bylayer'/'byblock'/'default'"
        ) from exc


def apply_props(
    entity: Any,
    *,
    layer: str | None = None,
    colour: Any = None,
    true_color: Any = None,
    linetype: str | None = None,
    linetype_scale: float | None = None,
    lineweight: Any = None,
    transparency: Any = None,
) -> None:
    """Set the properties every entity shares. Silently skips what is None."""
    if layer is not None:
        entity.Layer = str(layer)
    if colour is not None:
        entity.Color = colour_value(colour)
    if true_color is not None:
        r, g, b = true_colour(true_color)
        tc = com.app().GetInterfaceObject("AutoCAD.AcCmColor.25")
        tc.SetRGB(r, g, b)
        entity.TrueColor = tc
    if linetype is not None:
        entity.Linetype = str(linetype)
    if linetype_scale is not None:
        entity.LinetypeScale = float(linetype_scale)
    if lineweight is not None:
        entity.Lineweight = lineweight_value(lineweight)
    if transparency is not None:
        text = str(transparency).strip().lower()
        entity.EntityTransparency = (
            text if text in ("bylayer", "byblock") else str(int(float(text)))
        )


def describe(entity: Any, geometry: bool = True) -> dict[str, Any]:
    """A compact, readable summary of one entity."""
    info: dict[str, Any] = {
        "handle": str(com.quiet(lambda: entity.Handle, "")),
        "type": dxf_type(entity),
        "layer": str(com.quiet(lambda: entity.Layer, "")),
    }
    colour = com.quiet(lambda: int(entity.Color))
    if colour is not None:
        info["color"] = colour
    lt = com.quiet(lambda: str(entity.Linetype))
    if lt and lt.lower() != "bylayer":
        info["linetype"] = lt
    if not geometry:
        return info

    kind = info["type"]
    q = com.quiet
    if kind == "LINE":
        info["start"] = round_pt(entity.StartPoint)
        info["end"] = round_pt(entity.EndPoint)
        info["length"] = round(float(entity.Length), 6)
    elif kind in ("CIRCLE",):
        info["center"] = round_pt(entity.Center)
        info["radius"] = round(float(entity.Radius), 6)
        info["area"] = round(float(entity.Area), 6)
    elif kind == "ARC":
        info["center"] = round_pt(entity.Center)
        info["radius"] = round(float(entity.Radius), 6)
        info["start_angle"] = round(math.degrees(float(entity.StartAngle)), 6)
        info["end_angle"] = round(math.degrees(float(entity.EndAngle)), 6)
        info["length"] = q(lambda: round(float(entity.ArcLength), 6))
    elif kind in ("LWPOLYLINE", "POLYLINE"):
        coords = com.unwrap(q(lambda: entity.Coordinates, []) or [])
        step = 2 if kind == "LWPOLYLINE" else 3
        info["points"] = [
            [round(float(v), 6) for v in coords[i : i + step]]
            for i in range(0, len(coords), step)
        ]
        info["closed"] = bool(q(lambda: entity.Closed, False))
        info["length"] = q(lambda: round(float(entity.Length), 6))
        if info["closed"]:
            info["area"] = q(lambda: round(float(entity.Area), 6))
    elif kind == "TEXT":
        info["text"] = str(q(lambda: entity.TextString, ""))
        info["position"] = round_pt(entity.InsertionPoint)
        info["height"] = q(lambda: round(float(entity.Height), 6))
        info["rotation"] = q(lambda: round(math.degrees(float(entity.Rotation)), 6))
        info["style"] = q(lambda: str(entity.StyleName))
    elif kind == "MTEXT":
        info["text"] = str(q(lambda: entity.TextString, ""))
        info["position"] = round_pt(entity.InsertionPoint)
        info["height"] = q(lambda: round(float(entity.Height), 6))
        info["width"] = q(lambda: round(float(entity.Width), 6))
        info["style"] = q(lambda: str(entity.StyleName))
    elif kind == "INSERT":
        info["block"] = str(q(lambda: entity.Name, ""))
        info["position"] = round_pt(entity.InsertionPoint)
        info["scale"] = [
            q(lambda: round(float(entity.XScaleFactor), 6)),
            q(lambda: round(float(entity.YScaleFactor), 6)),
            q(lambda: round(float(entity.ZScaleFactor), 6)),
        ]
        info["rotation"] = q(lambda: round(math.degrees(float(entity.Rotation)), 6))
        attrs = q(lambda: entity.GetAttributes())
        if attrs:
            info["attributes"] = {
                str(a.TagString): str(a.TextString) for a in com.unwrap(attrs)
            }
    elif kind == "HATCH":
        info["pattern"] = str(q(lambda: entity.PatternName, ""))
        info["area"] = q(lambda: round(float(entity.Area), 6))
        info["loops"] = q(lambda: int(entity.NumberOfLoops))
    elif kind == "ELLIPSE":
        info["center"] = round_pt(entity.Center)
        info["major_axis"] = round_pt(q(lambda: entity.MajorAxis, [0, 0, 0]))
        info["radius_ratio"] = q(lambda: round(float(entity.RadiusRatio), 6))
    elif kind == "POINT":
        info["position"] = round_pt(entity.Coordinates)
    elif kind == "DIMENSION":
        info["measurement"] = q(lambda: round(float(entity.Measurement), 6))
        info["text_override"] = q(lambda: str(entity.TextOverride))
        info["style"] = q(lambda: str(entity.StyleName))
    elif kind == "SPLINE":
        info["closed"] = bool(q(lambda: entity.Closed, False))
        info["control_points"] = q(lambda: int(entity.NumberOfControlPoints))
    elif kind == "VIEWPORT":
        info["center"] = round_pt(entity.Center)
        info["width"] = q(lambda: round(float(entity.Width), 6))
        info["height"] = q(lambda: round(float(entity.Height), 6))
        info["scale"] = q(lambda: round(float(entity.CustomScale), 8))
        info["on"] = bool(q(lambda: entity.ViewportOn, False))

    return {k: v for k, v in info.items() if v is not None}


def bbox(entity: Any) -> dict[str, Any] | None:
    try:
        lo, hi = entity.GetBoundingBox()
    except Exception:  # noqa: BLE001
        return None
    lo, hi = com.unwrap(lo), com.unwrap(hi)
    return {
        "min": [round(float(v), 6) for v in lo],
        "max": [round(float(v), 6) for v in hi],
        "size": [round(float(hi[i]) - float(lo[i]), 6) for i in range(3)],
    }


def union_bbox(entities: Iterable[Any]) -> dict[str, Any] | None:
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    found = False
    for e in entities:
        box = bbox(e)
        if not box:
            continue
        found = True
        for i in range(3):
            lo[i] = min(lo[i], box["min"][i])
            hi[i] = max(hi[i], box["max"][i])
    if not found:
        return None
    return {
        "min": [round(v, 6) for v in lo],
        "max": [round(v, 6) for v in hi],
        "size": [round(hi[i] - lo[i], 6) for i in range(3)],
    }


def ensure_layer(doc: Any, name: str) -> Any:
    """Return the layer, creating it if needed (AutoCAD's Add is idempotent)."""
    return com.retry(lambda: doc.Layers.Add(str(name)), context=f"layer {name!r}")


def find_layer(doc: Any, name: str) -> Any:
    target = str(name).lower()

    def scan() -> Any:
        for i in range(int(doc.Layers.Count)):
            layer = doc.Layers.Item(i)
            if str(layer.Name).lower() == target:
                return layer
        return None

    found = com.retry(scan, timeout=30, attr_is_busy=True, context="finding the layer")
    if found is None:
        raise NotFound(f"There is no layer called {name!r} in {doc.Name}.")
    return found


def degrees_to_radians(deg: float | None) -> float:
    return math.radians(float(deg or 0.0))


def new_entities_since(doc: Any, previous: set[str], space: Any) -> list[str]:
    """Handles present in `space` that were not in `previous`."""
    out: list[str] = []
    for i in range(int(space.Count)):
        h = str(space.Item(i).Handle)
        if h not in previous:
            out.append(h)
    return out


def space_handles(space: Any) -> set[str]:
    return {str(space.Item(i).Handle) for i in range(int(space.Count))}
