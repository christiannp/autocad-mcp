"""Establish empirically: which AcSaveAsType values work, and how to plot a PDF."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, lisp, winui  # noqa: E402

winui.press_escape(3)
com.run_com(lambda: com.ensure_responsive(), timeout=60)

OUT = Path(__file__).resolve().parents[2] / "testout" / "fmt"
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    b"AC1015": "2000", b"AC1018": "2004", b"AC1021": "2007",
    b"AC1024": "2010", b"AC1027": "2013", b"AC1032": "2018",
}


def say(*a):
    print(*a, flush=True)


def header(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            magic = fh.read(6)
        if magic in HEADERS:
            return "DWG " + HEADERS[magic]
        if magic.startswith(b"  0"):
            return "DXF (ascii)"
        return magic.decode("latin1", "replace")
    except Exception as exc:  # noqa: BLE001
        return f"? {exc}"


def main() -> None:
    def setup():
        doc = com.app().Documents.Add()
        doc.ModelSpace.AddCircle(com.pt([0, 0, 0]), 100.0)
        return doc

    doc = com.run_com(setup, timeout=120)

    say("== AcSaveAsType probe ==")
    works = {}
    for value in list(range(12, 70)):
        target = OUT / f"v{value}.tmp"
        target.unlink(missing_ok=True)
        try:
            com.run_com(lambda v=value, t=str(target): com.retry(
                lambda: doc.SaveAs(t, v), timeout=30), timeout=60)
        except Exception:  # noqa: BLE001
            continue
        if target.exists():
            works[value] = header(target)
    for value, kind in sorted(works.items()):
        say(f"   {value:3d} -> {kind}")

    say("\n== plotting ==")

    def prep():
        d = com.active_doc()
        d.SetVariable("BACKGROUNDPLOT", 0)
        layout = d.ActiveLayout
        layout.ConfigName = "DWG To PDF.pc3"
        layout.RefreshPlotDeviceInfo()
        layout.PlotType = 1        # extents
        layout.UseStandardScale = True
        layout.StandardScale = 0   # fit
        layout.CenterPlot = True
        return str(layout.Name), str(layout.ConfigName)

    say("   layout:", com.run_com(prep, timeout=120))

    def attempt(label, fn, path: Path, wait=40):
        path.unlink(missing_ok=True)
        try:
            com.run_com(fn, timeout=180)
        except Exception as exc:  # noqa: BLE001
            say(f"   {label:38s} raised {str(exc)[:80]}")
            return
        end = time.time() + wait
        while time.time() < end and not (path.exists() and path.stat().st_size):
            time.sleep(0.4)
        ok = path.exists() and path.stat().st_size
        say(f"   {label:38s} {'OK ' + str(path.stat().st_size) + ' bytes' if ok else 'no file'}")

    p1 = OUT / "p1.pdf"
    attempt("Plot.PlotToFile(path) 1 arg",
            lambda: com.active_doc().Plot.PlotToFile(str(p1)), p1)

    p2 = OUT / "p2.pdf"
    attempt("Plot.PlotToFile(path, device)",
            lambda: com.active_doc().Plot.PlotToFile(str(p2), "DWG To PDF.pc3"), p2)

    p3 = OUT / "p3.pdf"

    def with_layouts():
        d = com.active_doc()
        d.Plot.SetLayoutsToPlot(com.strings(["Model"]))
        return d.Plot.PlotToFile(str(p3))

    attempt("SetLayoutsToPlot(VT_BSTR) + PlotToFile", with_layouts, p3)

    p4 = OUT / "p4.pdf"
    try:
        lisp.evaluate(
            lisp.command(
                "_.-PLOT", "_N", "Model", "DWG To PDF.pc3",
                "ISO_full_bleed_A3_(420.00_x_297.00_MM)", "_M", "_L", "_N",
                "_E", "_F", "_C", "_Y", ".", "_N", "_N", "_Y",
            ),
            timeout=180,
        )
        say("   -PLOT command                          sent")
    except Exception as exc:  # noqa: BLE001
        say(f"   -PLOT command                          raised {str(exc)[:110]}")

    com.run_com(lambda: com.quiet(lambda: com.active_doc().Close(False)), timeout=60)

    say("\nfiles produced:")
    for f in sorted(OUT.glob("*")):
        say(f"   {f.name:14s} {f.stat().st_size:,}")


main()
say("done")
