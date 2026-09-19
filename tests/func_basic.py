"""Functional test: drive the real tools against a real drawing."""

from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import winui  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402

winui.press_escape(2)
load_tools()

from acadmcp.tools.draw import (  # noqa: E402
    draw_arc, draw_circle, draw_construction_line, draw_ellipse, draw_hatch,
    draw_line, draw_point, draw_polyline, draw_rectangle, draw_spline,
)
from acadmcp.tools.modify import (  # noqa: E402
    entity_array, entity_break, entity_chamfer, entity_copy, entity_delete,
    entity_explode, entity_fillet, entity_join, entity_mirror, entity_move,
    entity_offset, entity_overkill, entity_properties, entity_rotate,
    entity_scale, entity_trim, match_properties,
)
from acadmcp.tools.raw import cad_command, cad_lisp, cad_script  # noqa: E402
from acadmcp.tools.select import (  # noqa: E402
    entity_info, entity_select, entity_summary, measure,
)
from acadmcp.tools.session import (  # noqa: E402
    acad_status, doc_new, purge, regen, sysvar, zoom,
)

passed = failed = 0


def run(name, fn):
    global passed, failed
    t0 = time.time()
    try:
        value = fn()
        passed += 1
        text = repr(value)
        print(f"[ok]   {time.time()-t0:6.2f}s {name}\n         {text[:220]}", flush=True)
        return value
    except Exception as exc:  # noqa: BLE001
        failed += 1
        print(f"[FAIL] {time.time()-t0:6.2f}s {name}\n         {type(exc).__name__}: {exc}",
              flush=True)
        if "--tb" in sys.argv:
            traceback.print_exc()
        return None


print("=== session ===", flush=True)
run("acad_status", acad_status)
run("doc_new", doc_new)
run("sysvar set INSUNITS=4 (mm)", lambda: sysvar(settings={"INSUNITS": 4}))

print("\n=== draw ===", flush=True)
rect = run("draw_rectangle", lambda: draw_rectangle([0, 0], [4000, 3000], layer="ROOF", color="cyan"))
circ = run("draw_circle", lambda: draw_circle([2000, 1500], radius=400, layer="OBSTRUCTION", color=1))
line = run("draw_line", lambda: draw_line([0, 0], [4000, 3000], layer="AXIS", linetype="Continuous"))
poly = run("draw_polyline", lambda: draw_polyline(
    [[5000, 0], [9000, 0], [9000, 2000], [7000, 3000], [5000, 2000]], closed=True, layer="ROOF"))
arc = run("draw_arc centre/angles", lambda: draw_arc(center=[2000, 1500], radius=1200,
                                                     start_angle=0, end_angle=90, layer="AXIS"))
arc3 = run("draw_arc 3-point", lambda: draw_arc(through=[[10000, 0], [10500, 800], [11000, 0]]))
ell = run("draw_ellipse", lambda: draw_ellipse([12000, 1000], [800, 0], 0.5))
spl = run("draw_spline", lambda: draw_spline([[13000, 0], [13500, 900], [14000, 100], [14500, 800]]))
pts = run("draw_point", lambda: draw_point([[100, 100], [200, 200]], layer="MARK"))
xl = run("draw_construction_line", lambda: draw_construction_line([0, 0], angle=45))

hatch_b = run("draw_hatch by boundary", lambda: draw_hatch(
    boundary_handles=[poly["handle"]], pattern="ANSI31", scale=50, layer="HATCH"))
# NB: pick a point that is not ON a boundary - [500,500] sits exactly on the
# 45-degree construction line drawn above, and AutoCAD then finds no region.
hatch_p = run("draw_hatch by internal point", lambda: draw_hatch(
    internal_points=[[3500, 200]], pattern="SOLID", layer="HATCH", color=8))

print("\n=== select / inspect / measure ===", flush=True)
run("zoom extents", lambda: zoom("extents"))
all_roof = run("entity_select layer=ROOF", lambda: entity_select(layer="ROOF"))
run("entity_select type=CIRCLE", lambda: entity_select(type="CIRCLE", include_details=True))
run("entity_select wildcard layer", lambda: entity_select(layer="*O*"))
run("entity_select window", lambda: entity_select(window=[[-100, -100], [4100, 3100]]))
run("entity_summary by type", lambda: entity_summary("type"))
run("entity_summary by layer", lambda: entity_summary("layer"))
run("entity_info", lambda: entity_info([rect["handle"], circ["handle"]], bounding_box=True))
run("measure two points", lambda: measure(point1=[0, 0], point2=[3000, 4000]))
run("measure entities", lambda: measure(handles=[rect["handle"], poly["handle"]]))

print("\n=== modify ===", flush=True)
copies = run("entity_copy", lambda: entity_copy([circ["handle"]], to_points=[[1000, 0], [2000, 0]]))
run("entity_move", lambda: entity_move([circ["handle"]], displacement=[0, 100]))
run("entity_rotate", lambda: entity_rotate([poly["handle"]], [7000, 1500], 15))
run("entity_scale", lambda: entity_scale([ell["handle"]], [12000, 1000], 1.5))
mir = run("entity_mirror", lambda: entity_mirror([spl["handle"]], [13000, 0], [13000, 1000]))
off = run("entity_offset", lambda: entity_offset([rect["handle"]], -200))
arr = run("entity_array rectangular", lambda: entity_array(
    [pts["created"][0]], kind="rectangular", rows=2, columns=3, row_spacing=300, column_spacing=300))
arr2 = run("entity_array polar", lambda: entity_array(
    [copies["created"][0]], kind="polar", count=6, center=[2000, 1500]))
run("entity_properties read", lambda: entity_properties([rect["handle"]]))
run("entity_properties set", lambda: entity_properties([line["handle"]], layer="AXIS",
                                                       color="green", lineweight=0.30))
run("match_properties", lambda: match_properties(rect["handle"], [line["handle"]]))

l1 = run("line for fillet A", lambda: draw_line([20000, 0], [21000, 0]))
l2 = run("line for fillet B", lambda: draw_line([21000, 0], [21000, 1000]))
run("entity_fillet", lambda: entity_fillet(l1["handle"], l2["handle"], radius=200))

c1 = run("line for chamfer A", lambda: draw_line([23000, 0], [24000, 0]))
c2 = run("line for chamfer B", lambda: draw_line([24000, 0], [24000, 1000]))
run("entity_chamfer", lambda: entity_chamfer(c1["handle"], c2["handle"], 150, 150))

t1 = run("line to trim", lambda: draw_line([26000, 500], [28000, 500]))
t2 = run("cutting edge", lambda: draw_line([27000, 0], [27000, 1000]))
run("entity_trim", lambda: entity_trim([t1["handle"]], [t2["handle"]]))

e1 = run("line to extend", lambda: draw_line([30000, 500], [30500, 500]))
e2 = run("boundary", lambda: draw_line([31000, 0], [31000, 1000]))
run("entity_extend", lambda: entity_trim and __import__(
    "acadmcp.tools.modify", fromlist=["entity_extend"]).entity_extend(
    [e1["handle"]], [e2["handle"]]))

j1 = run("segment 1", lambda: draw_line([33000, 0], [34000, 0]))
j2 = run("segment 2", lambda: draw_line([34000, 0], [35000, 0]))
run("entity_join", lambda: entity_join([j1["handle"], j2["handle"]]))

br = run("line to break", lambda: draw_line([37000, 0], [38000, 0]))
run("entity_break", lambda: entity_break(br["handle"], [37300, 0], [37700, 0]))

ex = run("rect to explode", lambda: draw_rectangle([40000, 0], [41000, 1000]))
run("entity_explode", lambda: entity_explode([ex["handle"]]))

print("\n=== escape hatches ===", flush=True)
run("cad_command DONUT", lambda: cad_command("_.DONUT", [100, 200, [45000, 500], ""]))
# REVCLOUD finishes on the second corner - a trailing "" would be a stray
# Enter that re-runs the command and leaves AutoCAD waiting.
run("cad_command REVCLOUD", lambda: cad_command(
    "_.REVCLOUD", ["_A", 200, 400, "_R", [47000, 0], [48000, 1000]], timeout=40))
run("cad_lisp getvar", lambda: cad_lisp('(getvar "CLAYER")'))
run("cad_lisp entity count", lambda: cad_lisp('(sslength (ssget "_X"))'))
run("cad_script", lambda: cad_script([
    {"command": "_.CIRCLE", "args": [[50000, 500], 300]},
    {"lisp": '(setvar "CLAYER" "0")'},
    {"command": "_.TEXT", "args": [[50000, 1200], 200, 0, "scripted"]},
]))

print("\n=== cleanup checks ===", flush=True)
run("entity_overkill", lambda: entity_overkill())
run("regen", regen)
run("purge", purge)
run("entity_delete", lambda: entity_delete([xl["handle"]]))
run("final status", acad_status)

print(f"\n{passed} passed, {failed} failed", flush=True)
sys.exit(1 if failed else 0)
