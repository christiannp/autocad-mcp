"""Is AutoLISP evaluating at all, or is it only the file write that fails?"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com  # noqa: E402

TMP = Path(os.path.expandvars("%LOCALAPPDATA%/acadmcp/probe"))
TMP.mkdir(parents=True, exist_ok=True)


def say(*a):
    print(*a, flush=True)


def main() -> None:
    def work():
        doc = com.active_doc(create_if_none=True)

        def send(text, label, settle=1.5):
            try:
                com.retry(lambda: doc.SendCommand(text), timeout=20)
                time.sleep(settle)
                return True
            except Exception as exc:  # noqa: BLE001
                say(f"   {label} RAISED: {exc}")
                return False

        # 1. does LISP run at all?  set a user system variable from LISP
        doc.SetVariable("USERI1", 0)
        send('(setvar "USERI1" 42) ', "1")
        say("1. LISP setvar USERI1     ->", doc.GetVariable("USERI1"), "(want 42)")

        # 2. LISP driving a command
        n0 = int(doc.ModelSpace.Count)
        send('(command "_.CIRCLE" (list 6000.0 6000.0 0.0) 100.0) ', "2")
        say(f"2. LISP (command CIRCLE)  -> {n0} -> {int(doc.ModelSpace.Count)}")

        # 3. is (open ... "w") allowed?
        doc.SetVariable("USERI1", 0)
        probe = (TMP / "w.txt").as_posix()
        Path(probe).unlink(missing_ok=True)
        send(
            '(progn (setq zf (open "%s" "w")) (setvar "USERI1" (if zf 7 9))) ' % probe,
            "3",
        )
        say("3. (open w) returned      ->", doc.GetVariable("USERI1"), "(7 = ok, 9 = nil, 0 = LISP never ran)")
        send('(progn (if zf (progn (princ "X" zf) (close zf))) (setvar "USERI1" 5)) ', "3b")
        say("3b. after close           ->", doc.GetVariable("USERI1"), "file exists:", Path(probe).exists())

        # 4. string sysvar round trip (how much can we get back without files?)
        doc.SetVariable("USERS1", "")
        send('(setvar "USERS1" (strcat "v=" (getvar "ACADVER"))) ', "4")
        say("4. USERS1                 ->", repr(doc.GetVariable("USERS1")))

        # 5. how long may the string be?
        for n in (200, 500, 1000, 2000, 4000):
            doc.SetVariable("USERI1", 0)
            pad = "(setq q 1)" * ((n - 40) // 10)
            ok = send('(progn %s (setvar "USERI1" %d)) ' % (pad, n), f"5[{n}]", settle=1.0)
            got = doc.GetVariable("USERI1")
            say(f"5. len~{len(pad) + 40:5d} -> USERI1={got} {'OK' if got == n else 'LOST'}")
            if got != n:
                break

        # 6. vl functions available?
        doc.SetVariable("USERI1", 0)
        send('(progn (vl-load-com) (setvar "USERI1" (if (vl-catch-all-error-p (vl-catch-all-apply (function /) (list 1 0))) 3 4))) ', "6")
        say("6. vl-catch-all-apply     ->", doc.GetVariable("USERI1"), "(3 = vl works)")

    com.run_com(work, timeout=240)


main()
say("done")
