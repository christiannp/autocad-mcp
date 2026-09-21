"""Batch processing, with full error text."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402

winui.press_escape(2)
load_tools()

from acadmcp.tools.batch import batch_headless, batch_preview, batch_process  # noqa: E402
from acadmcp.tools.draw import draw_circle, draw_rectangle  # noqa: E402
from acadmcp.tools.layers import layer_set  # noqa: E402
from acadmcp.tools.session import doc_close, doc_list, doc_new, doc_save  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "testout" / "batchtest"
shutil.rmtree(OUT, ignore_errors=True)
(OUT / "in").mkdir(parents=True, exist_ok=True)


def show(label, value):
    print(f"--- {label}\n{json.dumps(value, indent=2, default=str)[:2200]}\n", flush=True)


# close everything so we start from a clean slate
def close_all():
    com.run_com(lambda: com.ensure_responsive(), timeout=90)

    def work():
        app = com.app()
        while com.doc_count():
            com.quiet(lambda: app.Documents.Item(0).Close(False))
        return com.doc_count()

    return com.run_com(work, timeout=300)


print("closed everything, docs left:", close_all(), flush=True)

for name in ("plan-a", "plan-b", "plan-c"):
    doc_new()
    layer_set("A-ROOF", color="cyan")
    draw_rectangle([0, 0], [8000, 5000], layer="A-ROOF")
    draw_circle([4000, 2500], radius=600, layer="A-ROOF")
    layer_set("UNUSED-LAYER", color=1)     # something for PURGE to remove
    show(f"saved {name}", doc_save(path=str(OUT / "in" / f"{name}.dwg")))
    doc_close(save=False)

show("preview", batch_preview(folder=str(OUT / "in")))

show(
    "batch_process (add a note + purge, write copies)",
    batch_process(
        steps=[
            {"command": "_.-PURGE", "args": ["_All", "*", "_N"]},
            {"lisp": '(acadmcp:hnd (entmakex (list (cons 0 "TEXT") '
                     '(cons 10 (list 0.0 5400.0 0.0)) (cons 40 300.0) '
                     '(cons 1 "checked by MCP"))))'},
        ],
        folder=str(OUT / "in"),
        output_folder=str(OUT / "out"),
    ),
)

show("docs still open", doc_list())

show(
    "batch_headless (accoreconsole)",
    batch_headless(
        script_lines=["_.-PURGE", "_All", "*", "_N", "(princ (strcat \"n=\" (itoa (sslength (ssget \"_X\")))))"],
        folder=str(OUT / "out"),
        save=True,
        limit=2,
    ),
)

print("files:", flush=True)
for f in sorted(OUT.rglob("*.dwg")):
    print(f"   {f.relative_to(OUT)}  {f.stat().st_size:,}", flush=True)
