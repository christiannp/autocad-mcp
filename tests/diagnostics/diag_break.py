"""Find the BREAK argument sequence AutoCAD 2025 actually accepts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, lisp, winui  # noqa: E402

winui.press_escape(4)
com.run_com(lambda: com.ensure_responsive(), timeout=90)


def say(*a):
    print(*a, flush=True)


def fresh(x: float) -> str:
    def work():
        doc = com.active_doc(create_if_none=True)
        line = doc.ModelSpace.AddLine(com.pt([x, 0, 0]), com.pt([x + 1000, 0, 0]))
        return str(line.Handle)

    return com.run_com(work, timeout=60)


def length(handle: str):
    def work():
        doc = com.active_doc()
        try:
            return round(float(com.by_handle(doc, handle).Length), 2)
        except Exception:  # noqa: BLE001
            return "gone"

    return com.run_com(work, timeout=60)


def trial(label: str, make_expr, x: float):
    h = fresh(x)
    before = length(h)
    try:
        lisp.evaluate(lisp.raw(make_expr(h, x)), timeout=12)
        after = length(h)
        say(f"  {label:44s} {before} -> {after}  {'BROKEN' if after != before else 'unchanged'}")
    except Exception as exc:  # noqa: BLE001
        say(f"  {label:44s} {type(exc).__name__}: {str(exc)[:70]}")
        lisp.cancel()


say("== BREAK variants (line 1000 long, remove 300..700) ==")

trial(
    "ent, _F, p1, p2",
    lambda h, x: '(command "_.BREAK" %s "_F" %s %s)'
    % (lisp.entity(h), lisp.lpoint([x + 300, 0]), lisp.lpoint([x + 700, 0])),
    40000,
)

trial(
    "ent, _F, _non p1, _non p2",
    lambda h, x: '(command "_.BREAK" %s "_F" "_non" %s "_non" %s)'
    % (lisp.entity(h), lisp.lpoint([x + 300, 0]), lisp.lpoint([x + 700, 0])),
    42000,
)

trial(
    "(list ent pickpoint), p2",
    lambda h, x: '(command "_.BREAK" (list %s %s) %s)'
    % (lisp.entity(h), lisp.lpoint([x + 300, 0]), lisp.lpoint([x + 700, 0])),
    44000,
)

trial(
    "(list ent pickpoint), _F, p1, p2",
    lambda h, x: '(command "_.BREAK" (list %s %s) "_F" %s %s)'
    % (lisp.entity(h), lisp.lpoint([x + 300, 0]), lisp.lpoint([x + 300, 0]),
       lisp.lpoint([x + 700, 0])),
    46000,
)

trial(
    "vl-cmdf ent _F p1 p2",
    lambda h, x: '(vl-cmdf "_.BREAK" %s "_F" %s %s)'
    % (lisp.entity(h), lisp.lpoint([x + 300, 0]), lisp.lpoint([x + 700, 0])),
    48000,
)

say("\n== break at a single point (BREAK @) ==")
trial(
    "(list ent p), _F, p, @",
    lambda h, x: '(command "_.BREAK" (list %s %s) "_F" %s "@")'
    % (lisp.entity(h), lisp.lpoint([x + 500, 0]), lisp.lpoint([x + 500, 0])),
    50000,
)

say("\ndone")
