"""Does AutoLISP evaluate through SendCommand at all? Safe, incremental probes.

Every probe reports through a system variable rather than a file, so we can tell
"LISP never ran" apart from "LISP ran but could not write".  After each probe we
check CMDACTIVE and bail out the moment AutoCAD is left at a prompt.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402

TMP = Path(os.path.expandvars("%LOCALAPPDATA%/acadmcp/probe"))
TMP.mkdir(parents=True, exist_ok=True)


def say(*a):
    print(*a, flush=True)


class Stuck(Exception):
    pass


def main() -> None:
    def work():
        doc = com.active_doc(create_if_none=True)
        say("doc:", doc.Name, " entities:", int(doc.ModelSpace.Count))

        def probe(label: str, text: str, settle: float = 1.2):
            """Send text, then make sure AutoCAD came back to a clean prompt."""
            try:
                com.retry(lambda: doc.SendCommand(text), timeout=15)
            except Exception as exc:  # noqa: BLE001
                say(f"{label}: SendCommand raised: {type(exc).__name__}: {exc}")
                return False
            time.sleep(settle)
            try:
                active = int(doc.GetVariable("CMDACTIVE"))
            except Exception:
                winui.press_escape()
                raise Stuck(f"{label}: AutoCAD went unresponsive; Esc sent")
            if active:
                winui.press_escape()
                raise Stuck(f"{label}: left CMDACTIVE={active}; Esc sent")
            return True

        def useri1():
            return int(doc.GetVariable("USERI1"))

        # ---- 1. plain LISP, no files -----------------------------------
        doc.SetVariable("USERI1", 0)
        probe("1", '(setvar "USERI1" 42) ')
        got = useri1()
        say(f"1. LISP evaluates?            USERI1={got} -> {'YES' if got == 42 else 'NO'}")
        if got != 42:
            say("   -> AutoLISP is not evaluating through SendCommand. Stopping here.")
            return

        # ---- 2. LISP driving a command ---------------------------------
        n0 = int(doc.ModelSpace.Count)
        probe("2", '(command "_.CIRCLE" (list 7000.0 1000.0 0.0) 150.0) ')
        say(f"2. LISP (command ...)         {n0} -> {int(doc.ModelSpace.Count)} entities")

        # ---- 3. can LISP open a file for writing? ----------------------
        target = (TMP / "w.txt").as_posix()
        Path(target).unlink(missing_ok=True)
        doc.SetVariable("USERI1", 0)
        probe("3", '(progn (setq zf (open "%s" "w")) (setvar "USERI1" (if zf 7 9))) ' % target)
        say(f"3. (open ... \"w\")             USERI1={useri1()}  (7 ok / 9 nil)")
        probe("3b", '(progn (if zf (progn (princ "HELLO" zf) (close zf))) (setvar "USERI1" 5)) ')
        say(f"3b. wrote + closed            exists={Path(target).exists()} "
            f"content={Path(target).read_text() if Path(target).exists() else None!r}")

        # ---- 4. (load) a file ------------------------------------------
        lsp = TMP / "p4.lsp"
        lsp.write_text('(setvar "USERI1" 1234)(princ)\n', encoding="ascii")
        doc.SetVariable("USERI1", 0)
        probe("4", '(load "%s") ' % lsp.as_posix())
        got = useri1()
        say(f"4. (load) untrusted path      USERI1={got} -> {'OK' if got == 1234 else 'BLOCKED (SECURELOAD)'}")

        if got != 1234:
            before = str(doc.GetVariable("TRUSTEDPATHS") or "")
            paths = [p for p in before.split(";") if p.strip()]
            for extra in (str(TMP), str(Path(__file__).resolve().parent.parent / "lisp"),
                          os.path.expandvars(r"%LOCALAPPDATA%\acadmcp\\jobs")):
                if extra not in paths:
                    paths.append(extra)
            doc.SetVariable("TRUSTEDPATHS", ";".join(paths))
            say("   TRUSTEDPATHS =", doc.GetVariable("TRUSTEDPATHS"))
            doc.SetVariable("USERI1", 0)
            probe("4b", '(load "%s") ' % lsp.as_posix())
            got = useri1()
            say(f"4b. (load) once trusted       USERI1={got} -> {'OK' if got == 1234 else 'STILL BLOCKED'}")

        # ---- 5. how long may a SendCommand string be? ------------------
        for n in (250, 600, 1200, 2400):
            doc.SetVariable("USERI1", 0)
            pad = "(setq q 1)" * max(1, (n - 40) // 10)
            try:
                probe(f"5[{n}]", '(progn %s (setvar "USERI1" %d)) ' % (pad, n), settle=1.0)
            except Stuck as exc:
                say(f"5. length {n:5d} -> STUCK ({exc})")
                break
            ok = useri1() == n
            say(f"5. length {len(pad) + 40:5d} -> {'OK' if ok else 'LOST'}")
            if not ok:
                break

        # ---- 6. vl- extensions -----------------------------------------
        doc.SetVariable("USERI1", 0)
        probe("6", '(progn (vl-load-com) (setvar "USERI1" (if (vl-catch-all-error-p '
              '(vl-catch-all-apply (function /) (list 1 0))) 3 4))) ')
        say(f"6. vl-catch-all-apply         USERI1={useri1()} (3 = vl available)")

    try:
        com.run_com(work, timeout=240)
    except Stuck as exc:
        say("STOPPED:", exc)


main()
say("done")
