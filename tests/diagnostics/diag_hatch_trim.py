"""Nail down two things: how to pass a hatch boundary over COM, and the
prompt sequence TRIM/EXTEND actually use in AutoCAD 2025 (Quick mode)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pythoncom  # noqa: E402
from win32com.client import VARIANT  # noqa: E402

from acadmcp import com, lisp, winui  # noqa: E402

winui.press_escape(3)
com.run_com(lambda: com.ensure_responsive(), timeout=60)


def say(*a):
    print(*a, flush=True)


def make_square(x, y, size=1000):
    def work():
        doc = com.active_doc()
        pts = [[x, y], [x + size, y], [x + size, y + size], [x, y + size]]
        pl = doc.ModelSpace.AddLightWeightPolyline(com.flat2d(pts))
        pl.Closed = True
        return str(pl.Handle)

    return com.run_com(work)


say("== A. AppendOuterLoop marshalling ==")
h = make_square(0, 0)


def try_variant(label, build):
    def work():
        doc = com.active_doc()
        hatch = doc.ModelSpace.AddHatch(1, "SOLID", True, 0)
        obj = com.by_handle(doc, h)
        try:
            hatch.AppendOuterLoop(build([obj]))
            hatch.Evaluate()
            return f"OK area={float(hatch.Area):.1f}"
        except Exception as exc:  # noqa: BLE001
            com.quiet(lambda: hatch.Delete())
            return f"FAIL {exc}"[:150]

    say(f"  {label:34s} {com.run_com(work)}")


try_variant("plain python list", lambda objs: objs)
try_variant("tuple", lambda objs: tuple(objs))
try_variant("VT_ARRAY|VT_VARIANT", lambda objs: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_VARIANT, objs))
try_variant("VT_ARRAY|VT_DISPATCH (wrappers)",
            lambda objs: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH, objs))
try_variant("VT_ARRAY|VT_DISPATCH (_oleobj_)",
            lambda objs: VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH,
                                 [o._oleobj_ for o in objs]))
try_variant("single object, not array", lambda objs: objs[0])

say("\n== B. -HATCH by selected objects (command fallback) ==")
h2 = make_square(3000, 0)
payload = lisp.evaluate(
    lisp.raw("(acadmcp:capture '(lambda () %s))"
             % lisp.command("_.-HATCH", "_P", "SOLID", "_S", lisp.ss_from([h2]), "", "")),
    timeout=60,
)
say("  -HATCH _S ->", payload)

say("\n== C. -HATCH by internal point ==")
h3 = make_square(6000, 0)
com.run_com(lambda: com.quiet(lambda: com.app().ZoomExtents()))
time.sleep(0.5)
for label, steps in [
    ("P/SOLID then point", ["_.-HATCH", "_P", "SOLID", [6500, 500], ""]),
    ("P/_S then point", ["_.-HATCH", "_P", "_S", [6500, 500], ""]),
    ("ANSI31 with scale/angle", ["_.-HATCH", "_P", "ANSI31", 50, 0, [6500, 500], ""]),
]:
    try:
        r = lisp.evaluate(
            lisp.raw("(acadmcp:capture '(lambda () %s))" % lisp.command(*steps)),
            timeout=60,
        )
        say(f"  {label:26s} -> {r}")
    except Exception as exc:  # noqa: BLE001
        say(f"  {label:26s} -> ERROR {exc}"[:170])
    lisp.cancel()

say("\n== D. TRIMEXTENDMODE and TRIM prompts ==")
say("  TRIMEXTENDMODE =", com.run_com(lambda: com.active_doc().GetVariable("TRIMEXTENDMODE")))


def trim_trial(label, expr, timeout=25):
    try:
        r = lisp.evaluate(lisp.raw(expr), timeout=timeout)
        say(f"  {label:34s} -> {r}")
    except Exception as exc:  # noqa: BLE001
        say(f"  {label:34s} -> {type(exc).__name__}: {str(exc)[:90]}")
    lisp.cancel()


def fresh_pair(x):
    def work():
        doc = com.active_doc()
        a = doc.ModelSpace.AddLine(com.pt([x, 500]), com.pt([x + 2000, 500]))
        b = doc.ModelSpace.AddLine(com.pt([x + 1000, 0]), com.pt([x + 1000, 1000]))
        return str(a.Handle), str(b.Handle)

    return com.run_com(work)


t1, c1 = fresh_pair(10000)
trim_trial(
    "standard mode, 2 enters",
    '(progn (setq amt-old (getvar "TRIMEXTENDMODE")) (setvar "TRIMEXTENDMODE" 1)'
    f' (command "_.TRIM" {lisp.ss_from([c1])} "" {lisp.ss_from([t1])} "")'
    ' (setvar "TRIMEXTENDMODE" amt-old) (cdr (assoc 11 (entget (handent "%s")))))' % t1,
)

t2, c2 = fresh_pair(14000)
trim_trial(
    "quick mode, direct select",
    f'(progn (command "_.TRIM" {lisp.ss_from([t2])} "") "done")',
)

t3, c3 = fresh_pair(18000)
trim_trial(
    "standard via _MODE option",
    f'(progn (command "_.TRIM" "_MODE" "_Standard" {lisp.ss_from([c3])} ""'
    f' {lisp.ss_from([t3])} "") "done")',
)

say("\ndone")
