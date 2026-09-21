"""Visual check: zoom/screenshot/render on the extended test drawing."""
from __future__ import annotations
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from acadmcp.server import load_tools
load_tools()
from acadmcp.tools.session import doc_open, doc_close, zoom
from acadmcp.tools.select import entity_select, entity_info
from acadmcp.tools.vision import render, screenshot
from acadmcp.tools.layout import layout_manage

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "testout" / "vis"; OUT.mkdir(parents=True, exist_ok=True)
try: doc_close(drawing="ext-test.dwg", save=False)
except Exception: pass
doc_open(str(ROOT / "testout" / "ext" / "ext-test.dwg"))
layout_manage("activate", name="Model")
polys = entity_select(type="LWPOLYLINE", layer="A-ROOF")["handles"]
info = entity_info(polys)["entities"]
roof = max((e for e in info if e.get("area")), key=lambda e: e["area"])["handle"]
print("roof", roof)
print("zoom", zoom(mode="objects", handles=[roof]))
for name, fn in [
    ("shot-roof", lambda: screenshot(handles=[roof], path=str(OUT / "shot-roof.png"))),
    ("shot-extents", lambda: screenshot(path=str(OUT / "shot-extents.png"))),
    ("render-roof", lambda: render(handles=[roof], path=str(OUT / "render-roof.png"))),
    ("render-extents", lambda: render(path=str(OUT / "render-extents.png"))),
    ("render-sheet", lambda: render(layout="SHEET", path=str(OUT / "render-sheet.png"))),
]:
    r = fn(); print(name, r[1][:300])
doc_close(save=False)
