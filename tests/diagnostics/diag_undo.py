"""Do empty StartUndoMark/EndUndoMark pairs pollute the undo stack?"""
from __future__ import annotations
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from acadmcp import com, lisp
from acadmcp.server import load_tools
load_tools()
from acadmcp.tools.session import doc_new, doc_close
from acadmcp.tools.draw import draw_circle

def exists(h):
    return com.run_com(lambda: com.quiet(lambda: com.active_doc().HandleToObject(h)) is not None)

def raw(text, wait=1.2):
    lisp.send_raw(text)
    time.sleep(wait)

def mark_start(): com.run_com(lambda: com.active_doc().StartUndoMark())
def mark_end(): com.run_com(lambda: com.active_doc().EndUndoMark())

doc_new()
print("--- N: group per tool call, then three empty groups, then UNDO 1")
mark_start(); a = draw_circle([0, 0], radius=10)["handle"]; mark_end()
mark_start(); b = draw_circle([100, 0], radius=10)["handle"]; mark_end()
for _ in range(3):
    mark_start(); com.run_com(lambda: int(com.active_doc().ModelSpace.Count)); mark_end()
raw("_.UNDO 1 ")
print("   a kept =", exists(a), " b gone =", not exists(b), "(True/True means empty groups are skipped)")
raw("_.UNDO 1 ")
print("   a gone =", not exists(a))
raw("_.MREDO 2 ")
print("   a back =", exists(a), " b back =", exists(b))

print("--- O: group containing a LISP-run command plus COM edits, undo 1 twice")
mark_start(); c = draw_circle([200, 0], radius=10)["handle"]; lisp.run_command("_.LINE", [0, 0], [50, 50], ""); mark_end()
mark_start(); d = draw_circle([300, 0], radius=10)["handle"]; mark_end()
raw("_.UNDO 1 ")
print("   c kept =", exists(c), " d gone =", not exists(d))
raw("_.UNDO 1 ")
n = com.run_com(lambda: int(com.active_doc().ModelSpace.Count))
print("   c gone =", not exists(c), " modelspace count =", n, "(expect 2: a and b)")

print("--- P: nested marks (a tool calling a tool)")
mark_start(); mark_start(); e = draw_circle([400, 0], radius=10)["handle"]; mark_end(); f = draw_circle([500, 0], radius=10)["handle"]; mark_end()
raw("_.UNDO 1 ")
print("   e gone =", not exists(e), " f gone =", not exists(f), "(both True = nesting is fine)")
doc_close(save=False)
