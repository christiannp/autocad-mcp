"""Letting Claude see the drawing.

Two ways, because they fail differently:

* ``screenshot`` grabs the AutoCAD window - what the user sees, ribbon and
  all. It is pure Win32, so it works even while a dialog has COM frozen.
* ``render`` plots the drawing to a PNG through AutoCAD's own raster plotter.
  Clean, exact, no UI in the picture, and independent of what is on screen
  (the window can be minimised or covered).

Both hand the picture straight back as an image the model can look at, and
optionally keep a PNG on disk too.
"""

from __future__ import annotations

import io
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image

from .. import capture, com, util, winui
from ..errors import AcadError, NotFound
from ..registry import tool
from .layout import PLOT_TYPE, _find_layout

PNG_DEVICE = "PublishToWeb PNG.pc3"
DEFAULT_MAX_WIDTH = 1600


def _default_path(stem: str) -> str:
    return os.path.join(os.environ.get("TEMP", "."), f"{stem}_{datetime.now():%H%M%S}.png")


def _shrink(image: Any, max_width: int) -> Any:
    limit = max(200, int(max_width or DEFAULT_MAX_WIDTH))
    longest = max(image.width, image.height)
    if longest <= limit:
        return image
    factor = limit / float(longest)
    from PIL import Image as PILImage

    return image.resize(
        (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
        PILImage.LANCZOS,
    )


def _finish(image: Any, path: str | None, details: dict[str, Any]) -> list[Image | str]:
    """Encode the picture for the model and, if asked, keep it on disk."""
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    if path:
        target = Path(os.path.abspath(os.path.expanduser(str(path))))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        details["file"] = str(target)
    details["width"], details["height"] = image.width, image.height
    details["bytes"] = len(data)
    return [Image(data=data, format="png"), json.dumps(details)]


def _zoom(handles: list[str] | None, window: list[list[float]] | None, extents: bool) -> str:
    """Best-effort view change before a screenshot; never fails the capture."""
    from .session import zoom

    try:
        if handles:
            zoom(mode="objects", handles=[str(h) for h in handles])
            return "zoomed to the given objects"
        if window:
            if len(window) != 2:
                raise AcadError("window needs two corner points")
            zoom(mode="window", corner1=window[0], corner2=window[1])
            return "zoomed to window"
        if extents:
            zoom(mode="extents")
            return "zoomed to extents"
        return "view left as it was"
    except Exception as exc:  # noqa: BLE001 - the picture is still worth taking
        return f"zoom skipped ({str(exc)[:120]})"


@tool(undo_group=False, description=(
    "Look at the AutoCAD window: returns a picture of the drawing canvas as the "
    "user sees it, so an edit can be checked visually. Zooms to extents first "
    "unless handles (zoom to those objects) or window corners are given, or "
    "zoom_extents is false. Works even when a dialog is open. For a clean, exact "
    "picture without the UI use render instead."
))
def screenshot(
    zoom_extents: bool = True,
    handles: list[str] | None = None,
    window: list[list[float]] | None = None,
    crop_to_canvas: bool = True,
    max_width: int = DEFAULT_MAX_WIDTH,
    path: str | None = None,
    drawing: str | None = None,
) -> list[Image | str]:
    details: dict[str, Any] = {}
    dialogs = winui.visible_dialogs()
    if dialogs:
        details["dialogs_open"] = dialogs
        details["view"] = "zoom skipped - a dialog is open"
    else:
        details["view"] = _zoom(handles, window, zoom_extents)
        time.sleep(0.25)  # let the redraw land before grabbing
    image, meta = capture.grab(crop=bool(crop_to_canvas))
    details.update(meta)
    image = _shrink(image, max_width)
    return _finish(image, path, details)


_PIXELS = re.compile(r"\(?\s*([\d.]+)\s*[_ ]?x[_ ]?\s*([\d.]+)\s*[_ ]?Pixels", re.I)


def _pick_media(names: list[str], width: int, height: int) -> tuple[str, int, int]:
    """Choose the raster paper size with the most pixels.

    The PNG plotter's sizes are listed as '(width x height Pixels)' and the
    canvas is always exactly that size - PlotRotation does not turn it - so
    orientation cannot be chosen. The largest canvas wins regardless: the
    drawing is plotted to fit, the blank margin is trimmed afterwards, and the
    result is shrunk to the requested size. A landscape drawing on a portrait
    1280x1600 canvas still gets 1280 px of width, more than any landscape sheet
    the plotter offers.
    """
    # the plotter goes up to 16K (15360 x 8640); anything past about twice the
    # requested size only costs time, so cap the long side there
    cap = max(2 * max(int(width), int(height)), 1600)
    best: tuple[int, str, int, int] | None = None
    for name in names:
        m = _PIXELS.search(str(name))
        if not m:
            continue
        w, h = int(float(m.group(1))), int(float(m.group(2)))
        area = w * h
        fits = max(w, h) <= cap
        score = area if fits else -area
        if best is None or score > best[0]:
            best = (score, str(name), w, h)
    if best is None:
        raise AcadError(
            f"{PNG_DEVICE} lists no pixel paper sizes; check the plotter configuration"
        )
    _, name, w, h = best
    return name, w, h


def _trim(image: Any, margin: int = 24) -> Any:
    """Cut away the blank border a plot-to-fit leaves around the drawing."""
    from PIL import ImageChops

    rgb = image.convert("RGB")
    background = rgb.getpixel((0, 0))
    from PIL import Image as PILImage

    diff = ImageChops.difference(rgb, PILImage.new("RGB", rgb.size, background))
    box = diff.getbbox()
    if not box:
        return image
    left = max(0, box[0] - margin)
    top = max(0, box[1] - margin)
    right = min(rgb.width, box[2] + margin)
    bottom = min(rgb.height, box[3] + margin)
    if right - left < 50 or bottom - top < 50:
        return image
    return image.crop((left, top, right, bottom))


_SAVED_PROPS = (
    "ConfigName", "CanonicalMediaName", "PlotType", "PlotRotation", "CenterPlot",
    "StyleSheet", "PlotWithPlotStyles", "PlotWithLineweights", "UseStandardScale",
    "StandardScale", "PlotHidden", "ScaleLineweights", "PlotViewportBorders",
)


@tool(undo_group=False, description=(
    "Render the drawing to a clean picture through AutoCAD's own plotter and "
    "return it - exact geometry, no ribbon or palettes, independent of what is "
    "on screen. area: extents (default), window (give window corners), objects "
    "(give handles) or layout (give the layout name). Up to 1600 px wide. "
    "plot_style can name a .ctb such as monochrome.ctb."
))
def render(
    area: str = "extents",
    window: list[list[float]] | None = None,
    handles: list[str] | None = None,
    layout: str | None = None,
    width: int = 1600,
    height: int = 1200,
    plot_style: str | None = None,
    lineweights: bool = False,
    padding: float = 0.05,
    path: str | None = None,
    drawing: str | None = None,
    timeout: float = 180,
) -> list[Image | str]:
    key = str(area).strip().lower()
    if handles:
        key = "objects"
    elif window:
        key = "window"
    elif layout:
        key = "layout"
    if key not in ("extents", "window", "objects", "layout"):
        raise AcadError("area must be extents, window, objects or layout")
    target = os.path.abspath(os.path.expanduser(str(path))) if path else _default_path("acad_render")
    if not target.lower().endswith(".png"):
        target += ".png"
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if key == "layout":
            page = _find_layout(doc, str(layout))
            if str(page.Name).lower() == "model":
                raise AcadError("to render model space use area='extents' or a window")
        else:
            page = _find_layout(doc, "Model")

        corners: tuple[list[float], list[float]] | None = None
        if key == "window":
            if not window or len(window) != 2:
                raise AcadError("window needs exactly two corner points")
            corners = ([float(v) for v in window[0][:2]], [float(v) for v in window[1][:2]])
        elif key == "objects":
            box = util.union_bbox(com.by_handles(doc, [str(h) for h in handles or []]))
            if not box:
                raise NotFound("none of those handles has a bounding box")
            corners = (box["min"][:2], box["max"][:2])
        if corners:
            (x1, y1), (x2, y2) = corners
            lo = [min(x1, x2), min(y1, y2)]
            hi = [max(x1, x2), max(y1, y2)]
            pad = max(hi[0] - lo[0], hi[1] - lo[1]) * float(padding)
            if pad <= 0:
                pad = 1.0
            corners = ([lo[0] - pad, lo[1] - pad], [hi[0] + pad, hi[1] + pad])

        saved: dict[str, Any] = {}
        for name in _SAVED_PROPS:
            saved[name] = com.quiet(lambda n=name: getattr(page, n))
        custom = com.quiet(lambda: page.GetCustomScale())
        before_bg = com.quiet(lambda: int(doc.GetVariable("BACKGROUNDPLOT")), 2)
        com.quiet(lambda: doc.SetVariable("BACKGROUNDPLOT", 0))
        details: dict[str, Any] = {"area": key, "layout": str(page.Name)}
        try:
            page.ConfigName = PNG_DEVICE
            com.quiet(lambda: page.RefreshPlotDeviceInfo())
            names = list(com.unwrap(com.retry(lambda: page.GetCanonicalMediaNames())) or [])
            media, out_w, out_h = _pick_media(names, int(width), int(height))
            page.CanonicalMediaName = media
            page.PlotRotation = 0
            if corners:
                com.retry(lambda: page.SetWindowToPlot(com.pt2(corners[0]), com.pt2(corners[1])))
                page.PlotType = PLOT_TYPE["window"]
                details["window"] = [corners[0], corners[1]]
            else:
                # for a layout too: "extents" of the sheet, scaled to fit the
                # canvas. PlotType layout plots at 1:1 and comes out tiny.
                page.PlotType = PLOT_TYPE["extents"]
            page.UseStandardScale = True
            page.StandardScale = 0            # scale to fit
            page.CenterPlot = True
            page.PlotHidden = False
            page.PlotWithLineweights = bool(lineweights)
            if plot_style:
                page.PlotWithPlotStyles = True
                page.StyleSheet = str(plot_style)
            else:
                page.PlotWithPlotStyles = False
            com.quiet(lambda: page.RefreshPlotDeviceInfo())
            plotter = doc.Plot
            com.retry(lambda: plotter.SetLayoutsToPlot(com.strings([str(page.Name)])))
            ok = com.retry(
                lambda: plotter.PlotToFile(target, PNG_DEVICE), timeout=120, context="rendering"
            )
            details.update({"paper": media, "canvas": [out_w, out_h], "accepted": bool(ok)})
        finally:
            for name in reversed(_SAVED_PROPS):
                value = saved.get(name)
                if value is not None:
                    com.quiet(lambda n=name, v=value: setattr(page, n, v))
            if custom and not saved.get("UseStandardScale"):
                com.quiet(lambda: page.SetCustomScale(float(custom[0]), float(custom[1])))
            com.quiet(lambda: doc.SetVariable("BACKGROUNDPLOT", before_bg))
        return details

    details = com.run_com(work, timeout=timeout)

    deadline = time.time() + min(float(timeout), 120)
    while time.time() < deadline:
        if os.path.isfile(target) and os.path.getsize(target) > 0:
            break
        time.sleep(0.3)
    else:
        raise AcadError(
            "AutoCAD accepted the render but no PNG appeared. Check that "
            f"'{PNG_DEVICE}' is installed (plot_devices) and the folder is writable."
        )
    time.sleep(0.2)
    from PIL import Image as PILImage

    with PILImage.open(target) as im:
        image = im.convert("RGB")
    if not path:
        com.quiet(lambda: os.remove(target))
    image = _trim(image)
    image = _shrink(image, max(int(width), int(height)))
    return _finish(image, path, details)
