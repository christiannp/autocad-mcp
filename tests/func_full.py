"""Functional test for layers, annotation, blocks, layouts, plotting, data and batch."""

from __future__ import annotations

import os
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import winui  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402

winui.press_escape(2)
load_tools()

from acadmcp.tools.annotate import (  # noqa: E402
    draw_dimension, draw_leader, draw_mtext, draw_table, draw_text, text_edit,
    text_find_replace,
)
from acadmcp.tools.batch import batch_preview, batch_process  # noqa: E402
from acadmcp.tools.blocks import (  # noqa: E402
    block_attributes, block_define, block_edit, block_export, block_insert,
    block_list, xref,
)
from acadmcp.tools.draw import draw_circle, draw_line, draw_rectangle  # noqa: E402
from acadmcp.tools.layers import (  # noqa: E402
    dim_style, layer_delete, layer_list, layer_merge, layer_rename, layer_set,
    layer_state, linetype, text_style,
)
from acadmcp.tools.layout import (  # noqa: E402
    export, layout_list, layout_manage, page_setup, plot, plot_devices,
    viewport_create, viewport_manage,
)
from acadmcp.tools.query import data_extract, drawing_info, screenshot  # noqa: E402
from acadmcp.tools.select import entity_select  # noqa: E402
from acadmcp.tools.session import doc_close, doc_new, doc_save, sysvar  # noqa: E402

OUT = Path(r"C:\Users\Wanda\Documents\AI Companion\autocad-mcp\testout")
if OUT.exists():
    shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)

passed = failed = 0


def run(name, fn):
    global passed, failed
    t0 = time.time()
    try:
        value = fn()
        passed += 1
        print(f"[ok]   {time.time()-t0:6.2f}s {name}\n         {repr(value)[:230]}", flush=True)
        return value
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"[FAIL] {time.time()-t0:6.2f}s {name}\n         {type(exc).__name__}: {exc}",
              flush=True)
        if "--tb" in sys.argv:
            traceback.print_exc()
        return None


run("doc_new", doc_new)
run("units mm", lambda: sysvar(settings={"INSUNITS": 4, "LTSCALE": 50}))

print("\n=== layers & styles ===", flush=True)
run("layer_set create", lambda: layer_set("A-ROOF", color="cyan", lineweight=0.30,
                                          description="roof outline", make_current=True))
run("layer_set dashed", lambda: layer_set("A-SETBACK", color=2, linetype="DASHED"))
run("layer_set CJK name", lambda: layer_set("\u5c4b\u9802-\u6a21\u7d44", color=3))
run("layer_list", lambda: layer_list())
run("layer_list pattern", lambda: layer_list(pattern="A-*"))
run("layer_state lock", lambda: layer_state(names=["A-SETBACK"], locked=True))
run("layer_state unlock", lambda: layer_state(names=["A-SETBACK"], locked=False))
run("layer_rename", lambda: layer_rename("A-SETBACK", "A-SETBACK-1M"))
run("layer_set spare", lambda: layer_set("A-SPARE", color=5))
run("layer_merge", lambda: layer_merge(["A-SPARE"], "A-ROOF"))
run("layer_delete", lambda: layer_delete(["A-SETBACK-1M"]))
run("linetype list", lambda: linetype())
run("linetype load CENTER", lambda: linetype(load=["CENTER"]))
run("text_style", lambda: text_style(name="NOTES", font="arial.ttf", height=0))
run("dim_style", lambda: dim_style(name="PV-100",
                                   variables={"DIMTXT": 2.5, "DIMASZ": 2.5, "DIMSCALE": 100},
                                   make_current=True))

print("\n=== geometry to annotate ===", flush=True)
rect = run("rectangle", lambda: draw_rectangle([0, 0], [12000, 8000], layer="A-ROOF"))
circ = run("circle", lambda: draw_circle([6000, 4000], radius=900, layer="A-ROOF"))

print("\n=== annotation ===", flush=True)
run("draw_text", lambda: draw_text("ROOF PLAN", [0, 8600], height=400, layer="A-ROOF"))
run("draw_text CJK", lambda: draw_text("\u5c4b\u9802\u5e73\u9762\u5716", [0, 9200],
                                       height=400, layer="\u5c4b\u9802-\u6a21\u7d44"))
run("draw_text aligned", lambda: draw_text("centred", [6000, -800], height=300,
                                           alignment="middle-center"))
run("draw_mtext", lambda: draw_mtext("Notes:\\P1. All dimensions in mm.\\P2. Verify on site.",
                                     [13000, 8000], width=5000, height=250))
d1 = run("dimension aligned", lambda: draw_dimension("aligned", point1=[0, 0],
                                                     point2=[12000, 0],
                                                     text_position=[6000, -1500]))
run("dimension linear vertical", lambda: draw_dimension("vertical", point1=[0, 0],
                                                        point2=[0, 8000],
                                                        text_position=[-1500, 4000]))
run("dimension radial", lambda: draw_dimension("radial", center=[6000, 4000],
                                               radius_point=[6900, 4000], leader_length=500))
run("dimension angular", lambda: draw_dimension("angular", vertex=[0, 0], point1=[3000, 0],
                                                point2=[0, 3000], text_position=[2000, 2000]))
run("draw_leader", lambda: draw_leader([[6000, 4900], [8000, 6500], [9000, 6500]],
                                       text="obstruction", text_height=300))
run("draw_table", lambda: draw_table([14000, 4000],
                                     data=[["Item", "Qty", "kWp"],
                                           ["PV module", "168", "73.9"],
                                           ["Inverter", "3", "-"]],
                                     title="SCHEDULE", row_height=400, column_width=2000))
run("text_find_replace dry", lambda: text_find_replace("ROOF"))
run("text_find_replace do", lambda: text_find_replace("Verify on site", "Verify on site (TBC)"))

print("\n=== blocks ===", flush=True)
mod = run("module geometry", lambda: draw_rectangle([20000, 0], [21134, 1722], layer="A-ROOF"))
blk = run("block_define", lambda: block_define(
    "PV-MODULE", [mod["handle"]], base_point=[20000, 0],
    attributes=[{"tag": "STRING", "prompt": "String", "default": "S1",
                 "position": [20100, 200], "height": 150},
                {"tag": "IDX", "prompt": "Index", "default": "1",
                 "position": [20100, 500], "height": 150}]))
ins = run("block_insert x3", lambda: block_insert(
    name="PV-MODULE", positions=[[1000, 1000], [2300, 1000], [3600, 1000]],
    attributes={"STRING": "S1", "IDX": "1"}, layer="A-ROOF"))
run("block_list", lambda: block_list())
run("block_attributes read", lambda: block_attributes(block="PV-MODULE"))
run("block_attributes write", lambda: block_attributes(
    handles=[ins["created"][1]["handle"]], set_values={"IDX": "2"}))
run("block_export", lambda: block_export(str(OUT / "pv-module.dwg"), block="PV-MODULE"))
run("xref list", lambda: xref("list"))

print("\n=== layouts, viewports, plotting ===", flush=True)
run("layout_list", lambda: layout_list())
run("layout_manage create", lambda: layout_manage("create", name="PV-SHEET"))
run("layout_manage activate", lambda: layout_manage("activate", name="PV-SHEET"))
run("plot_devices", lambda: plot_devices())
run("page_setup", lambda: page_setup(layout="PV-SHEET", device="pdf",
                                     paper_size="ISO_full_bleed_A3_(420.00_x_297.00_MM)",
                                     landscape=True, plot_area="layout"))
vp = run("viewport_create", lambda: viewport_create([210, 148], 380, 250,
                                                    layout="PV-SHEET", scale_1_to=100))
run("viewport_manage list", lambda: viewport_manage(layout="PV-SHEET"))
if vp:
    run("viewport_manage set", lambda: viewport_manage(handle=vp["handle"], scale_1_to=50,
                                                       locked=True))

print("\n=== save / export / report ===", flush=True)
dwg = str(OUT / "pv-test.dwg")
run("doc_save", lambda: doc_save(path=dwg))
run("plot to PDF", lambda: plot(path=str(OUT / "pv-sheet.pdf"), layouts=["PV-SHEET"]))
run("export dxf", lambda: export(str(OUT / "pv-test.dxf"), format="dxf"))
run("drawing_info", lambda: drawing_info())
run("data_extract xlsx", lambda: data_extract(str(OUT / "modules.xlsx"), block="PV-MODULE"))
run("data_extract csv grouped", lambda: data_extract(str(OUT / "all.csv"),
                                                     group_identical=True))
run("screenshot", lambda: screenshot(str(OUT / "screen.png")))

print("\n=== batch ===", flush=True)
run("make 2nd file", lambda: doc_save(path=str(OUT / "batch" / "a.dwg")))
run("make 3rd file", lambda: doc_save(path=str(OUT / "batch" / "b.dwg")))
run("batch_preview", lambda: batch_preview(folder=str(OUT / "batch")))
run("close current", lambda: doc_close(save=False))
run("batch_process purge+layer", lambda: batch_process(
    steps=[{"command": "_.-PURGE", "args": ["_All", "*", "_N"]},
           {"lisp": '(acadmcp:hnd (entmakex (list (cons 0 "CIRCLE") '
                    '(cons 10 (list 100.0 100.0 0.0)) (cons 40 50.0))))'}],
    folder=str(OUT / "batch"), output_folder=str(OUT / "batch-out")))

print(f"\n{passed} passed, {failed} failed", flush=True)
print("outputs in", OUT, flush=True)
for f in sorted(OUT.rglob("*")):
    if f.is_file():
        print(f"   {f.relative_to(OUT)}  {f.stat().st_size:,} bytes", flush=True)
sys.exit(1 if failed else 0)
