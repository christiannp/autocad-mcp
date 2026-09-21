"""Functional test for the extended tool set: vision, interaction, modify, draw,
annotation, layers, blocks. Run against a freshly started AutoCAD."""

from __future__ import annotations

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
    annotation_scale, dimension_chain, dimension_edit, draw_mleader, draw_table,
    draw_text, table_edit, table_from_spreadsheet, table_read, text_combine,
)
from acadmcp.tools.blocks import (  # noqa: E402
    attribute_sync, block_define, block_dynamic, block_insert, pdf_import, underlay,
)
from acadmcp.tools.draw import (  # noqa: E402
    boundary, draw_circle, draw_line, draw_polygon, draw_polyline, draw_rectangle,
    draw_revcloud, draw_wipeout, region,
)
from acadmcp.tools.layers import layer_set, layer_state, layer_states, standards_import  # noqa: E402
from acadmcp.tools.layout import layout_manage, plot, viewport_create  # noqa: E402
from acadmcp.tools.modify import (  # noqa: E402
    draw_order, entity_align, entity_change_space, entity_divide, entity_lengthen,
    entity_offset, entity_stretch, polyline_edit,
)
from acadmcp.tools.query import data_extract  # noqa: E402
from acadmcp.tools.select import (  # noqa: E402
    entity_info, group, selection_current, selection_highlight, user_pick,
)
from acadmcp.tools.session import doc_close, doc_new, doc_save, sysvar, ucs, undo, view  # noqa: E402
from acadmcp.tools.vision import render, screenshot  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "testout" / "ext"
if OUT.exists():
    shutil.rmtree(OUT, ignore_errors=True)
OUT.mkdir(parents=True, exist_ok=True)

passed = failed = 0
INTERACTIVE = "--interactive" in sys.argv


def run(name, fn):
    global passed, failed
    t0 = time.time()
    try:
        value = fn()
        passed += 1
        shown = value
        if isinstance(value, list) and value and hasattr(value[0], "to_image_content"):
            shown = f"<image> {value[1]}"
        print(f"[ok]   {time.time()-t0:6.2f}s {name}\n         {repr(shown)[:230]}", flush=True)
        return value
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"[FAIL] {time.time()-t0:6.2f}s {name}\n         {type(exc).__name__}: {exc}",
              flush=True)
        if "--tb" in sys.argv:
            traceback.print_exc()
        return None


def h(value):
    """handle of a created entity"""
    if isinstance(value, dict):
        if "handle" in value:
            return value["handle"]
        if value.get("created"):
            c = value["created"][0]
            return c["handle"] if isinstance(c, dict) else c
    return None


run("doc_new", doc_new)
run("units mm", lambda: sysvar(settings={"INSUNITS": 4, "LTSCALE": 50, "PDMODE": 3, "PDSIZE": 200}))
run("layer A-ROOF", lambda: layer_set("A-ROOF", color="cyan", make_current=True))

print("\n=== geometry ===", flush=True)
roof = run("roof outline", lambda: draw_polyline([[0, 0], [30000, 0], [30000, 18000], [12000, 18000], [12000, 10000], [0, 10000]], closed=True))
obst = run("obstruction", lambda: draw_circle([20000, 8000], radius=1500, layer="A-OBST"))
line = run("line", lambda: draw_line([0, -3000], [30000, -3000]))
poly = run("polygon", lambda: draw_polygon([40000, 5000], 6, 3000))

print("\n=== undo ===", flush=True)
run("undo mark", lambda: undo("mark"))
tmp = run("temp circle", lambda: draw_circle([50000, 50000], radius=100))
run("undo back", lambda: undo("back"))
run("temp circle gone", lambda: (_ for _ in ()).throw(AssertionError("still there")) if entity_info([h(tmp)]).get("count", 0) else "gone")
run("undo 1 (undoes nothing harmful)", lambda: undo("undo", steps=1))
run("redo 1", lambda: undo("redo", steps=1))

print("\n=== offset with side ===", flush=True)
inner = run("offset inside 1000", lambda: entity_offset([h(roof)], 1000, side="inside"))
outer = run("offset outside 500", lambda: entity_offset([h(roof)], 500, side="outside"))
left = run("offset line left", lambda: entity_offset([h(line)], 400, side="left"))
thr = run("offset through", lambda: entity_offset([h(line)], through=[0, -5000]))
run("check inside area smaller", lambda: (lambda a, b: f"roof {a} > inner {b}" if a > b else (_ for _ in ()).throw(AssertionError(f"{a} vs {b}")))(
    entity_info([h(roof)])["entities"][0]["area"], entity_info(inner["created"])["entities"][0]["area"]))
run("check left is above", lambda: "ok" if entity_info(left["created"])["entities"][0]["start"][1] > -3000 else (_ for _ in ()).throw(AssertionError("wrong side")))

print("\n=== modify ===", flush=True)
sq = run("square to stretch", lambda: draw_rectangle([60000, 0], [64000, 4000]))
run("entity_stretch", lambda: entity_stretch(crossing=[[63000, -1000], [65000, 5000]], displacement=[2000, 0], handles=[h(sq)]))
run("stretched width", lambda: (lambda pts: f"x max {max(p[0] for p in pts)}" if max(p[0] for p in pts) > 65900 else (_ for _ in ()).throw(AssertionError(pts)))(entity_info([h(sq)])["entities"][0]["points"]))
al = run("box to align", lambda: draw_rectangle([70000, 0], [72000, 1000]))
run("entity_align 2 pts", lambda: entity_align([h(al)], [[70000, 0], [72000, 0]], [[80000, 0], [80000, 2000]]))
ln2 = run("line to lengthen", lambda: draw_line([0, -8000], [1000, -8000]))
run("entity_lengthen delta", lambda: entity_lengthen([h(ln2)], delta=500))
run("entity_lengthen total", lambda: entity_lengthen([h(ln2)], total=3000, end="start"))
pl = run("polyline for edit", lambda: draw_polyline([[0, -12000], [5000, -12000], [5000, -9000]]))
run("polyline_edit info", lambda: polyline_edit(h(pl), "info"))
run("polyline_edit add_vertex", lambda: polyline_edit(h(pl), "add_vertex", index=1, point=[2500, -13000]))
run("polyline_edit move_vertex", lambda: polyline_edit(h(pl), "move_vertex", index=0, point=[-500, -12000]))
run("polyline_edit delete_vertex", lambda: polyline_edit(h(pl), "delete_vertex", index=1))
run("polyline_edit close", lambda: polyline_edit(h(pl), "close"))
run("polyline_edit width", lambda: polyline_edit(h(pl), "width", width=50))
run("polyline_edit reverse", lambda: polyline_edit(h(pl), "reverse"))
la = run("line a", lambda: draw_line([0, -20000], [3000, -20000]))
lb = run("line b", lambda: draw_line([3000, -20000], [3000, -17000]))
joined = run("polyline_edit join", lambda: polyline_edit(action="join", handles=[h(la), h(lb)]))
lc = run("line c", lambda: draw_line([10000, -20000], [13000, -20000]))
run("polyline_edit to_polyline", lambda: polyline_edit(action="to_polyline", handles=[h(lc)]))
run("entity_divide points", lambda: entity_divide(h(line), segments=6))
run("entity_divide measure", lambda: entity_divide(h(line), length=7000))
hatch_like = run("rect for draworder", lambda: draw_rectangle([0, 30000], [5000, 35000]))
run("draw_order back", lambda: draw_order("back", handles=[h(hatch_like)]))
run("draw_order above", lambda: draw_order("above", handles=[h(hatch_like)], reference=h(roof)))
run("draw_order hatches_to_back", lambda: draw_order("hatches_to_back"))

print("\n=== draw ===", flush=True)
rc = run("revcloud rectangle", lambda: draw_revcloud(rectangle=[[0, 40000], [8000, 45000]], arc_length=500))
rc2 = run("revcloud object", lambda: draw_revcloud(handle=h(draw_circle([20000, 42000], radius=2000)), arc_length=400))
wo = run("wipeout points", lambda: draw_wipeout(points=[[30000, 40000], [34000, 40000], [32000, 43000]], frames=1))
r1 = run("region create", lambda: region("create", handles=[h(draw_rectangle([0, 60000], [10000, 68000]))]))
r2 = run("region create 2", lambda: region("create", handles=[h(draw_circle([10000, 64000], radius=2000))]))
run("region subtract", lambda: region("subtract", from_handle=r1["created"][0]["handle"], handles=[r2["created"][0]["handle"]]))
run("region area", lambda: region("area", handles=[r1["created"][0]["handle"]]))
run("region to_polyline", lambda: region("to_polyline", handles=[r1["created"][0]["handle"]]))
run("boundary polyline", lambda: boundary(point=[5000, 5000]))
run("boundary area_only", lambda: boundary(point=[5000, 5000], area_only=True))

print("\n=== annotation ===", flush=True)
ml = run("draw_mleader", lambda: draw_mleader([[20000, 8000], [24000, 12000], [26000, 12000]], "inverter", text_height=300))
ch = run("dimension_chain linear", lambda: dimension_chain([[0, 0], [12000, 0], [30000, 0]], [15000, -6000], kind="horizontal"))
run("dimension_chain baseline", lambda: dimension_chain([[0, 0], [12000, 0], [30000, 0]], [15000, -9000], kind="horizontal", baseline=True, spacing=800))
run("dimension_edit", lambda: dimension_edit(ch["created"][:1], text_override="<> TYP.", text_height=350))
tb = run("draw_table", lambda: draw_table([40000, 30000], [["Item", "Qty"], ["Module", "168"], ["Inverter", "3"]], row_height=400, column_width=2500, title="SCHEDULE"))
run("table_read", lambda: table_read(h(tb)))
run("table_edit", lambda: table_edit(h(tb), cells=[{"row": 2, "col": 1, "value": "170"}], insert_rows={"index": 4, "count": 1}, column_widths={"1": 3000}))
run("table_read after", lambda: table_read(h(tb)))
run("xlsx for table", lambda: data_extract(str(OUT / "sheet.xlsx"), type="LWPOLYLINE"))
run("table_from_spreadsheet", lambda: table_from_spreadsheet(str(OUT / "sheet.xlsx"), [40000, 20000], row_height=300, column_width=2500))
t1 = run("text 1", lambda: draw_text("Line one", [50000, 30000], height=300))
t2 = run("text 2", lambda: draw_text("Line two", [50000, 29500], height=300))
run("text_combine", lambda: text_combine([h(t1), h(t2)]))
run("annotation_scale list", lambda: annotation_scale("list"))
run("annotation_scale add", lambda: annotation_scale("add", scale="1:150", paper_units=1, drawing_units=150))
run("annotation_scale set_current", lambda: annotation_scale("set_current", scale="1:150"))

print("\n=== layers / standards ===", flush=True)
run("layer_states save", lambda: layer_states("save", name="ALL-ON"))
run("layer freeze", lambda: layer_state(names=["A-OBST"], frozen=True))
run("layer_states restore", lambda: layer_states("restore", name="ALL-ON"))
run("layer_states list", lambda: layer_states("list"))
run("layer_states export", lambda: layer_states("export", name="ALL-ON", path=str(OUT / "all-on.las")))
run("layer_states delete", lambda: layer_states("delete", name="ALL-ON"))
std = str(OUT / "standards.dwg")
run("save as standards source", lambda: doc_save(path=std))
run("doc_new for import", doc_new)
run("standards_import", lambda: standards_import(std, layers=["A-*"], text_styles=True, dim_styles=True, blocks=True))
run("close import test", lambda: doc_close(save=False))

print("\n=== blocks ===", flush=True)
mod = run("module geometry", lambda: draw_rectangle([20000, 20000], [21134, 21722]))
run("block_define", lambda: block_define("PV-MODULE", [h(mod)], base_point=[20000, 20000],
                                         attributes=[{"tag": "STRING", "prompt": "String", "default": "S1", "position": [20100, 20200], "height": 150}]))
ins = run("block_insert", lambda: block_insert(name="PV-MODULE", positions=[[1000, 1000]], attributes={"STRING": "S1"}))
run("block_dynamic (static block reports dynamic=false)", lambda: block_dynamic(block="PV-MODULE"))
run("attribute_sync", lambda: attribute_sync("PV-MODULE"))
run("group create", lambda: group("create", name="ROOF-SET", handles=[h(roof), h(obst)]))
run("group list", lambda: group("list"))
run("group select", lambda: group("select", name="ROOF-SET"))
run("group delete", lambda: group("delete", name="ROOF-SET"))
run("selection_highlight", lambda: selection_highlight([h(roof)], zoom_to=True))
run("selection_current", lambda: selection_current())
run("selection clear", lambda: selection_highlight(None))

print("\n=== underlays ===", flush=True)
png = run("render for underlay", lambda: render(path=str(OUT / "underlay.png"), width=800, height=600))
img = run("underlay attach image", lambda: underlay("attach", kind="image", path=str(OUT / "underlay.png"), position=[100000, 0], width=20000, fade=50, layer="A-UNDERLAY"))
run("underlay list", lambda: underlay("list"))
run("underlay adjust", lambda: underlay("adjust", handles=[img["handle"]], fade=70, contrast=40))
run("underlay frames 2", lambda: underlay("frames", frames=2))
pdf = run("plot pdf for underlay", lambda: plot(path=str(OUT / "roof.pdf"), model_space_extents=True))
up = run("underlay attach pdf", lambda: underlay("attach", kind="pdf", path=str(OUT / "roof.pdf"), position=[100000, 40000], scale=1))
run("pdf_import file", lambda: pdf_import(str(OUT / "roof.pdf"), position=[100000, 80000], scale=100))
run("underlay detach", lambda: underlay("detach", handles=[img["handle"]]))

print("\n=== views / ucs / space ===", flush=True)
run("view save", lambda: view("save", name="ROOF"))
run("view list", lambda: view("list"))
run("view restore", lambda: view("restore", name="ROOF"))
run("ucs current", lambda: ucs("current"))
run("ucs origin", lambda: ucs("origin", origin=[1000, 1000], angle=15))
run("ucs world", lambda: ucs("world"))
run("layout for chspace", lambda: layout_manage("create", name="SHEET"))
run("activate SHEET", lambda: layout_manage("activate", name="SHEET"))
vp = run("viewport", lambda: viewport_create([200, 150], 350, 250, layout="SHEET", scale_1_to=200))
note = run("note in model", lambda: draw_text("NOTE", [15000, 5000], height=500, space="model"))
run("entity_change_space model->paper", lambda: entity_change_space([h(note)], to="paper", layout="SHEET", viewport=vp["handle"]))
run("back to Model", lambda: layout_manage("activate", name="Model"))

print("\n=== vision ===", flush=True)
run("screenshot canvas", lambda: screenshot(path=str(OUT / "shot-canvas.png")))
run("screenshot objects", lambda: screenshot(handles=[h(roof)], path=str(OUT / "shot-roof.png")))
run("screenshot window uncropped", lambda: screenshot(crop_to_canvas=False, zoom_extents=False, path=str(OUT / "shot-window.png")))
run("render extents", lambda: render(path=str(OUT / "render-extents.png")))
run("render objects mono", lambda: render(handles=[h(roof), h(obst)], plot_style="monochrome.ctb", path=str(OUT / "render-roof.png")))
run("render window", lambda: render(window=[[0, 0], [30000, 18000]], path=str(OUT / "render-window.png"), width=1200, height=900))
run("render layout", lambda: render(layout="SHEET", path=str(OUT / "render-sheet.png")))

if INTERACTIVE:
    print("\n=== interactive (needs a person at AutoCAD) ===", flush=True)
    run("user_pick point", lambda: user_pick("point", prompt="Click anywhere on the roof", timeout=30))
    run("user_pick objects", lambda: user_pick("objects", prompt="Select a few objects then Enter", timeout=30))
    run("user_pick keyword", lambda: user_pick("keyword", options=["Yes", "No"], timeout=30))

run("save", lambda: doc_save(path=str(OUT / "ext-test.dwg")))
print(f"\n{passed} passed, {failed} failed", flush=True)
for f in sorted(OUT.rglob("*")):
    if f.is_file():
        print(f"   {f.relative_to(OUT)}  {f.stat().st_size:,} bytes", flush=True)
sys.exit(1 if failed else 0)
