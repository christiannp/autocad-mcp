"""Read AutoCAD's own command log (LOGFILEMODE) to see what a parked command was asking.

Swap the calls below for any command whose prompt chain is in doubt."""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from acadmcp import lisp, com
from acadmcp.server import load_tools
load_tools()
from acadmcp.tools.session import doc_new, sysvar
from acadmcp.tools.raw import cad_command
from acadmcp.tools.layout import layout_manage, viewport_create
from acadmcp.tools.annotate import draw_text

def timed(label, fn):
    t0 = time.time()
    try:
        v = fn(); print(f"=== {label}: {time.time()-t0:5.1f}s ok {repr(v)[:120]}", flush=True)
    except Exception as e:
        print(f"=== {label}: {time.time()-t0:5.1f}s {type(e).__name__}: {str(e)[:200]}", flush=True)

doc_new()
sysvar(settings={"LOGFILEMODE": 1})
time.sleep(0.5)
path = str(com.run_com(lambda: com.active_doc().GetVariable("LOGFILENAME")))
print("log:", path, flush=True)
timed("rect keyword", lambda: cad_command("_.REVCLOUD", ["_Rectangular", [0, 0], [5000, 3000]], timeout=8))
timed("polygonal keyword", lambda: cad_command("_.REVCLOUD", ["_Polygonal", [0, 10000], [5000, 10000], [2500, 13000], ""], timeout=8))
timed("arc 2 values then rect", lambda: cad_command("_.REVCLOUD", ["_Arc", 300, 300, "_Rectangular", [0, 20000], [5000, 23000]], timeout=8))
timed("style then rect", lambda: cad_command("_.REVCLOUD", ["_Style", "_Calligraphy", "_Rectangular", [0, 30000], [5000, 33000]], timeout=8))

layout_manage("create", name="S3"); layout_manage("activate", name="S3")
vp = viewport_create([200, 150], 350, 250, layout="S3", scale_1_to=200)
note = draw_text("NOTE", [15000, 5000], height=500, space="model")
def prep():
    doc = com.active_doc(); doc.MSpace = True; doc.ActivePViewport = com.by_handle(doc, vp["handle"])
    return int(doc.GetVariable("CVPORT"))
print("CVPORT:", com.run_com(prep), flush=True)
timed("chspace ss enter", lambda: cad_command("_.CHSPACE", ["<selection>", ""], select_handles=[note["handle"]], timeout=8))
note2 = draw_text("NOTE2", [15000, 6000], height=500, space="model")
com.run_com(prep)
timed("chspace ss only", lambda: cad_command("_.CHSPACE", ["<selection>"], select_handles=[note2["handle"]], timeout=8))
sysvar(settings={"LOGFILEMODE": 0})
time.sleep(0.5)
for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-60:]:
    print("   |", ln[:200], flush=True)
