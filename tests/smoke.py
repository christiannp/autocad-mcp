"""Live smoke test: COM connection + AutoLISP round-trip against real AutoCAD."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, lisp, winui  # noqa: E402

winui.press_escape(3)  # start from a clean command prompt

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def check(name: str, fn):
    t0 = time.time()
    try:
        value = fn()
        detail = repr(value)[:160]
        status = PASS
    except Exception as exc:  # noqa: BLE001
        value = None
        detail = f"{type(exc).__name__}: {exc}"[:400]
        status = FAIL
    dt = time.time() - t0
    results.append((status, name, detail))
    mark = "[ok]  " if status == PASS else "[FAIL]"
    print(f"{mark} {dt:6.2f}s  {name}\n            {detail}", flush=True)
    return value


# 1. connection -------------------------------------------------------------
check("connect / version", lambda: com.run_com(lambda: com.app().Version))
check("visible", lambda: com.run_com(lambda: bool(com.app().Visible)))
check("document count", lambda: com.run_com(lambda: int(com.app().Documents.Count)))

# 2. a document to work in --------------------------------------------------
def _ensure_doc():
    def work():
        a = com.app()
        if a.Documents.Count == 0:
            a.Documents.Add()
        return a.ActiveDocument.Name
    return com.run_com(work)


check("active document", _ensure_doc)

# 3. COM draw ---------------------------------------------------------------
def _com_line():
    def work():
        doc = com.active_doc()
        ln = doc.ModelSpace.AddLine(com.pt((0, 0, 0)), com.pt((300, 400, 0)))
        return {"handle": com.handle_of(ln), "length": round(float(ln.Length), 6)}
    return com.run_com(work)


check("COM AddLine", _com_line)


def _com_polyline():
    def work():
        doc = com.active_doc()
        pl = doc.ModelSpace.AddLightWeightPolyline(
            com.flat2d([(0, 0), (1000, 0), (1000, 600), (0, 600)])
        )
        pl.Closed = True
        return {"handle": com.handle_of(pl), "area": round(float(pl.Area), 3)}
    return com.run_com(work)


poly = check("COM AddLightWeightPolyline (closed, area)", _com_polyline)

# 4. LISP bridge ------------------------------------------------------------
check("LISP arithmetic", lambda: lisp.evaluate("(+ 1 2)"))
check("LISP list + reals", lambda: lisp.evaluate("(list 1 2.5 \"three\" T nil)"))
check("LISP point precision", lambda: lisp.evaluate("(list 1234.56789012 -0.5)"))
check("LISP getvar", lambda: lisp.evaluate('(getvar "DWGNAME")'))
check("LISP unicode in", lambda: lisp.evaluate(lisp.lstr("屋頂 roof 屋上")))
check("LISP unicode out", lambda: lisp.evaluate('(strcat "layer-" (chr 20013))'))
check("LISP dotted pair", lambda: lisp.evaluate('(cons 8 "0")'))
check("LISP entget assoc list", lambda: lisp.evaluate('(entget (entlast))'))

# 5. LISP driving a real command -------------------------------------------
def _lisp_circle():
    return lisp.evaluate(
        lisp.progn(
            lisp.command("_.CIRCLE", (2000, 300), 150),
            lisp.raw('(acadmcp:hnd (entlast))'),
        )
    )


circle_handle = check("LISP (command CIRCLE) -> handle", _lisp_circle)

# 6. selection set round trip ----------------------------------------------
check(
    "LISP ssget all -> handles",
    lambda: lisp.evaluate('(acadmcp:handles (ssget "_X"))'),
)

if poly and circle_handle:
    check(
        "LISP pickset from handles -> MOVE",
        lambda: lisp.evaluate(
            lisp.progn(
                lisp.command("_.MOVE", lisp.ss_from([circle_handle]), "", (0, 0), (0, 50)),
                lisp.raw('(cdr (assoc 10 (entget (handent ' + lisp.lstr(circle_handle) + '))))'),
            )
        ),
    )

# 7. error propagation ------------------------------------------------------
def _err():
    try:
        lisp.evaluate("(/ 1 0)")
    except Exception as exc:  # noqa: BLE001
        return f"caught: {exc}"
    return "NO ERROR RAISED - bad"


check("LISP error is reported", _err)

# 8. a command that does not exist in COM at all ---------------------------
check(
    "LISP FILLET (COM cannot do this)",
    lambda: lisp.evaluate(
        lisp.progn(
            lisp.command("_.RECTANG", (3000, 0), (3800, 600)),
            lisp.command("_.FILLET", "_R", 100),
            lisp.raw('(command "_.FILLET" "_P" (entlast))'),
            lisp.raw("(acadmcp:hnd (entlast))"),
        )
    ),
)

# ---------------------------------------------------------------------------
width = max(len(n) for _, n, _ in results) + 2
print()
for status, name, detail in results:
    mark = "[ok]  " if status == PASS else "[FAIL]"
    print(f"{mark} {name.ljust(width)} {detail}")
failed = sum(1 for s, _, _ in results if s == FAIL)
print(f"\n{len(results) - failed}/{len(results)} passed")
sys.exit(1 if failed else 0)
