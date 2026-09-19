"""Verify CJK text survives Python -> LISP -> drawing -> COM -> Python.

Prints ASCII verdicts only, so no console code page can confuse the result.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, lisp, winui  # noqa: E402

winui.press_escape(2)

SAMPLES = {
    "zh-hant": "屋頂太陽能",       # roof solar
    "mixed": "PV-模組 A/1",                     # PV-module A/1
    "punct": 'quote" back\\slash',
    "jp": "屋上",
}

ok = True


def report(name: str, sent: str, got: object) -> None:
    global ok
    same = isinstance(got, str) and got == sent
    ok = ok and same
    print(
        f"[{'ok' if same else 'FAIL'}] {name:10s} "
        f"sent {len(sent)} chars U+{'/U+'.join(f'{ord(c):04X}' for c in sent[:3])}... "
        f"got {type(got).__name__} "
        f"{len(got) if isinstance(got, str) else '-'} chars "
        f"{'identical' if same else repr(got)[:80]}",
        flush=True,
    )


print("-- 1. round trip a string straight through LISP --", flush=True)
for name, text in SAMPLES.items():
    report(name, text, lisp.evaluate(lisp.lstr(text)))

print("\n-- 2. create a layer with a CJK name from LISP, read it back over COM --", flush=True)
layer_name = "屋頂-模組"          # roof-module
lisp.evaluate(
    lisp.raw(
        "(progn (if (not (tblsearch \"LAYER\" %s)) "
        "(entmakex (list (cons 0 \"LAYER\") (cons 100 \"AcDbSymbolTableRecord\") "
        "(cons 100 \"AcDbLayerTableRecord\") (cons 2 %s) (cons 70 0) (cons 62 3)))) "
        "%s)" % (lisp.lstr(layer_name), lisp.lstr(layer_name), lisp.lstr(layer_name))
    )
)


def read_layer() -> str | None:
    def work():
        doc = com.active_doc()
        for i in range(doc.Layers.Count):
            nm = str(doc.Layers.Item(i).Name)
            if nm == layer_name:
                return nm
        return None

    return com.run_com(work)


report("layer", layer_name, read_layer())

print("\n-- 3. CJK text entity: write with LISP, read with COM --", flush=True)
content = "屋頂太陽能板配置圖"   # roof PV layout drawing
handle = lisp.evaluate(
    lisp.progn(
        lisp.command("_.-TEXT", (12000, 0), 200, 0, lisp.raw(lisp.lstr(content))),
        lisp.raw("(acadmcp:hnd (entlast))"),
    )
)


def read_text(h: str) -> str | None:
    def work():
        doc = com.active_doc()
        return str(com.by_handle(doc, h).TextString)

    return com.run_com(work)


report("text", content, read_text(str(handle)))

print("\n-- 4. and back out through LISP again --", flush=True)
report("re-read", content, lisp.evaluate(lisp.raw(f"(cdr (assoc 1 (entget {lisp.entity(str(handle))})))")))

print("\nALL OK" if ok else "\nSOME CHECKS FAILED")
sys.exit(0 if ok else 1)
