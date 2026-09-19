"""Just OVERKILL and purge, quickly."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import winui  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402

winui.press_escape(3)
load_tools()

from acadmcp.tools.draw import draw_line  # noqa: E402
from acadmcp.tools.modify import entity_overkill  # noqa: E402
from acadmcp.tools.session import doc_new, purge, regen  # noqa: E402


def run(name, fn):
    t0 = time.time()
    try:
        print(f"[ok]   {time.time()-t0:6.2f}s {name}: {repr(fn())[:200]}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] {time.time()-t0:6.2f}s {name}: {type(exc).__name__}: {exc}", flush=True)


run("doc_new", doc_new)
# three identical lines on top of each other: OVERKILL should leave one
for _ in range(3):
    draw_line([0, 0], [1000, 0])
draw_line([0, 500], [1000, 500])
run("overkill default", lambda: entity_overkill())
run("overkill with tolerance", lambda: entity_overkill(tolerance=0.5))
run("regen", regen)
run("purge", purge)
print("done", flush=True)
