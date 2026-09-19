"""Paper space: layouts, page setups, viewports, plotting and export."""

from __future__ import annotations

import os
import time
from typing import Any

from .. import com, lisp, util
from ..errors import AcadError, NotFound
from ..registry import tool

PDF_DEVICE = "DWG To PDF.pc3"

PLOT_TYPE = {
    "display": 0, "extents": 1, "limits": 2, "view": 3, "window": 4, "layout": 5,
}


def _find_layout(doc: Any, name: str) -> Any:
    target = str(name).lower()

    def scan() -> Any:
        for i in range(int(doc.Layouts.Count)):
            layout = doc.Layouts.Item(i)
            if str(layout.Name).lower() == target:
                return layout
        return None

    # Creating or deleting a layout leaves AutoCAD busy for a moment, so this
    # lookup has to ride that out rather than fail.
    found = com.retry(scan, timeout=30, attr_is_busy=True, context="finding the layout")
    if found is None:
        raise NotFound(f"There is no layout called {name!r} in {doc.Name}.")
    return found


def _layout_row(layout: Any, active: str = "") -> dict[str, Any]:
    q = com.quiet
    name = str(layout.Name)
    row: dict[str, Any] = {
        "name": name,
        "tab_order": q(lambda: int(layout.TabOrder)),
        "device": q(lambda: str(layout.ConfigName)),
        "paper_size": q(lambda: str(layout.CanonicalMediaName)),
        "plot_style_table": q(lambda: str(layout.StyleSheet)),
        "landscape": bool(q(lambda: int(layout.PlotRotation), 0) in (1, 3)),
    }
    if name == active:
        row["active"] = True
    return row


@tool(readonly=True, description="List the layouts (paper space tabs) in a drawing with their page setups.")
def layout_list(drawing: str | None = None) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        active = str(com.quiet(lambda: doc.ActiveLayout.Name, ""))
        rows = [
            _layout_row(doc.Layouts.Item(i), active)
            for i in range(int(doc.Layouts.Count))
        ]
        rows.sort(key=lambda r: (r.get("tab_order") or 0))
        return {"count": len(rows), "active": active, "layouts": rows}

    return com.run_com(work, timeout=120)


@tool(description="Create, copy, rename, delete or switch to a layout.")
def layout_manage(
    action: str = "create",
    name: str | None = None,
    new_name: str | None = None,
    copy_from: str | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    verb = str(action).strip().lower()

    if verb == "copy":
        if not (copy_from and name):
            raise AcadError("copying a layout needs copy_from and name")
        lisp.evaluate(
            lisp.command("_.-LAYOUT", "_Copy", str(copy_from), str(name)), timeout=180
        )
        return {"copied": copy_from, "to": name}

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if verb == "create":
            if not name:
                raise AcadError("a layout needs a name")
            made_with = "COM"
            try:
                com.retry(lambda: doc.Layouts.Add(str(name)), timeout=20)
            except Exception:  # noqa: BLE001
                # Late binding cannot always resolve Layouts.Add. The command
                # line always can, which is the point of having both engines.
                made_with = "-LAYOUT command"
                lisp.evaluate(
                    lisp.command("_.-LAYOUT", "_New", str(name)), doc=doc, timeout=120
                )
            # Add can also hand back an object whose properties are unreadable,
            # so fetch the layout again by name either way.
            layout = _find_layout(doc, str(name))
            return {
                "created": str(layout.Name),
                "tab_order": com.prop(layout, "TabOrder"),
                "via": made_with,
            }
        if not name:
            raise AcadError(f"{verb} needs the layout name")
        layout = _find_layout(doc, name)
        if verb == "rename":
            if not new_name:
                raise AcadError("renaming needs new_name")
            layout.Name = str(new_name)
            return {"renamed": {"from": name, "to": str(new_name)}}
        if verb == "delete":
            com.retry(lambda: layout.Delete())
            return {"deleted": name}
        if verb in ("activate", "current", "switch"):
            doc.ActiveLayout = layout
            return {"active": str(layout.Name)}
        raise AcadError("action must be create, copy, rename, delete or activate")

    return com.run_com(work, timeout=180)


@tool(description=(
    "Set up a layout for plotting: output device, paper size, orientation, plot "
    "style table and scale. Call with no changes to read the current settings."
))
def page_setup(
    layout: str | None = None,
    device: str | None = None,
    paper_size: str | None = None,
    landscape: bool | None = None,
    plot_style_table: str | None = None,
    fit_to_paper: bool | None = None,
    scale_1_to: float | None = None,
    plot_area: str | None = None,
    center_plot: bool | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        page = _find_layout(doc, layout) if layout else doc.ActiveLayout
        if device:
            page.ConfigName = PDF_DEVICE if str(device).lower() == "pdf" else str(device)
        if paper_size:
            page.CanonicalMediaName = str(paper_size)
        if landscape is not None:
            page.PlotRotation = 1 if landscape else 0
        if plot_style_table:
            page.StyleSheet = str(plot_style_table)
        if plot_area:
            key = str(plot_area).lower()
            if key not in PLOT_TYPE:
                raise AcadError("plot_area must be display, extents, limits, view, window or layout")
            page.PlotType = PLOT_TYPE[key]
        if fit_to_paper:
            page.UseStandardScale = True
            page.StandardScale = 0  # acScaleToFit
        elif scale_1_to:
            page.UseStandardScale = False
            page.SetCustomScale(1.0, float(scale_1_to))
        if center_plot is not None:
            page.CenterPlot = bool(center_plot)
        com.quiet(lambda: page.RefreshPlotDeviceInfo())
        row = _layout_row(page)
        row["media_available"] = list(com.unwrap(com.quiet(lambda: page.GetCanonicalMediaNames(), []) or []))[:40]
        return row

    return com.run_com(work, timeout=180)


@tool(readonly=True, description="List the plot devices AutoCAD can print to on this PC.")
def plot_devices(drawing: str | None = None) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        names = list(com.unwrap(com.quiet(lambda: doc.ActiveLayout.GetPlotDeviceNames(), []) or []))
        return {"count": len(names), "devices": names, "pdf_device": PDF_DEVICE}

    return com.run_com(work, timeout=120)


@tool(description="Create a viewport in a paper-space layout and set its scale (e.g. scale_1_to=100 for 1:100).")
def viewport_create(
    center: list[float],
    width: float,
    height: float,
    layout: str | None = None,
    scale_1_to: float | None = None,
    view_center: list[float] | None = None,
    locked: bool = False,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        page = _find_layout(doc, layout) if layout else doc.ActiveLayout
        doc.ActiveLayout = page
        if int(com.quiet(lambda: doc.ActiveSpace, 1)) == 1:
            doc.ActiveSpace = 0  # paper space
        vp = com.retry(
            lambda: doc.PaperSpace.AddPViewport(
                com.pt(center), float(width), float(height)
            ),
            context="creating the viewport",
        )
        vp.Display(True)
        if view_center:
            com.quiet(lambda: setattr(vp, "ViewCenter", com.pt(view_center)))
        if scale_1_to:
            vp.CustomScale = 1.0 / float(scale_1_to)
        if locked:
            vp.DisplayLocked = True
        return {
            "handle": str(vp.Handle),
            "layout": str(page.Name),
            "center": util.round_pt(vp.Center),
            "width": round(float(vp.Width), 4),
            "height": round(float(vp.Height), 4),
            "scale": f"1:{scale_1_to}" if scale_1_to else "not set",
        }

    return com.run_com(work, timeout=180)


@tool(description="List viewports, or change one: its scale, whether it is locked, on/off, and which layers are frozen inside it.")
def viewport_manage(
    handle: str | None = None,
    layout: str | None = None,
    scale_1_to: float | None = None,
    locked: bool | None = None,
    on: bool | None = None,
    freeze_layers: list[str] | None = None,
    thaw_layers: list[str] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        if handle:
            vp = com.by_handle(doc, str(handle))
            if scale_1_to:
                vp.CustomScale = 1.0 / float(scale_1_to)
            if locked is not None:
                vp.DisplayLocked = bool(locked)
            if on is not None:
                vp.Display(bool(on))
            if freeze_layers:
                com.retry(lambda: vp.FreezeLayersInViewport(com.strings(freeze_layers)))
            if thaw_layers:
                com.retry(lambda: vp.ThawLayersInViewport(com.strings(thaw_layers)))
            return {"viewport": util.describe(vp)}

        page = _find_layout(doc, layout) if layout else doc.ActiveLayout
        rows = []
        block = page.Block
        for i in range(int(block.Count)):
            ent = block.Item(i)
            if util.dxf_type(ent) == "VIEWPORT":
                info = util.describe(ent)
                cs = com.quiet(lambda e=ent: float(e.CustomScale))
                if cs:
                    info["scale"] = f"1:{round(1.0 / cs, 4):g}"
                rows.append(info)
        return {"layout": str(page.Name), "count": len(rows), "viewports": rows}

    return com.run_com(work, timeout=180)


@tool(description=(
    "Plot to a PDF file, or to any installed device. By default plots the "
    "active layout; pass layouts to plot several sheets into one PDF."
))
def plot(
    path: str | None = None,
    layouts: list[str] | None = None,
    device: str | None = None,
    model_space_extents: bool = False,
    drawing: str | None = None,
    timeout: float = 600,
) -> dict[str, Any]:
    target = None
    if path:
        target = os.path.abspath(os.path.expanduser(str(path)))
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        if not target.lower().endswith(".pdf") and (device is None or str(device).lower() == "pdf"):
            target += ".pdf"

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        before_bg = com.quiet(lambda: int(doc.GetVariable("BACKGROUNDPLOT")), 2)
        com.quiet(lambda: doc.SetVariable("BACKGROUNDPLOT", 0))  # plot synchronously
        try:
            page = doc.ActiveLayout
            if model_space_extents:
                page.PlotType = PLOT_TYPE["extents"]
                page.UseStandardScale = True
                page.StandardScale = 0
            if target and (device is None or str(device).lower() == "pdf"):
                page.ConfigName = PDF_DEVICE
            elif device:
                page.ConfigName = str(device)
            com.quiet(lambda: page.RefreshPlotDeviceInfo())

            plotter = doc.Plot
            if layouts:
                names = [str(n) for n in layouts]
                for n in names:
                    _find_layout(doc, n)     # validate before plotting
                # must be a VT_BSTR array; VT_VARIANT is rejected outright
                com.retry(lambda: plotter.SetLayoutsToPlot(com.strings(names)))
            if target:
                ok = com.retry(
                    lambda: plotter.PlotToFile(target, page.ConfigName),
                    timeout=120,
                    context="plotting",
                )
            else:
                ok = com.retry(lambda: plotter.PlotToDevice(), timeout=120, context="plotting")
            return {"started": bool(ok), "file": target, "device": str(page.ConfigName)}
        finally:
            com.quiet(lambda: doc.SetVariable("BACKGROUNDPLOT", before_bg))

    result = com.run_com(work, timeout=timeout)

    if result.get("file"):
        deadline = time.time() + min(float(timeout), 300)
        while time.time() < deadline:
            if os.path.isfile(result["file"]) and os.path.getsize(result["file"]) > 0:
                result["size_bytes"] = os.path.getsize(result["file"])
                result["written"] = True
                return result
            time.sleep(0.4)
        result["written"] = False
        result["note"] = (
            "AutoCAD accepted the plot but no file appeared. Check the plot device "
            "and that the path is writable."
        )
    return result


@tool(description="Export the drawing to another format: dxf, pdf, dwf, dwfx, wmf, sat, bmp, or eps.")
def export(
    path: str,
    format: str | None = None,
    handles: list[str] | None = None,
    drawing: str | None = None,
) -> dict[str, Any]:
    target = os.path.abspath(os.path.expanduser(str(path)))
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    ext = (format or os.path.splitext(target)[1].lstrip(".") or "pdf").lower()

    if ext == "pdf":
        return plot(path=target, drawing=drawing)  # type: ignore[return-value]

    if ext == "dxf":
        from .session import doc_save

        return doc_save(path=target, format="dxf2018", drawing=drawing)  # type: ignore[return-value]

    def work() -> dict[str, Any]:
        doc = com.find_doc(drawing)
        stem = os.path.splitext(target)[0]
        if handles:
            sel_name = "ACADMCP_EXPORT"
            com.quiet(lambda: doc.SelectionSets.Item(sel_name).Delete())
            sel = com.retry(lambda: doc.SelectionSets.Add(sel_name))
            sel.AddItems(com.objects(com.by_handles(doc, handles)))
            com.retry(lambda: doc.Export(stem, ext.upper(), sel), timeout=300)
            com.quiet(lambda: sel.Delete())
        else:
            empty = "ACADMCP_EMPTY"
            com.quiet(lambda: doc.SelectionSets.Item(empty).Delete())
            sel = com.retry(lambda: doc.SelectionSets.Add(empty))
            com.retry(lambda: doc.Export(stem, ext.upper(), sel), timeout=300)
            com.quiet(lambda: sel.Delete())
        return {"exported": target, "format": ext}

    result = com.run_com(work, timeout=360)
    if os.path.isfile(target):
        result["size_bytes"] = os.path.getsize(target)
    return result
