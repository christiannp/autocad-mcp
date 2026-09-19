"""Find a working channel for getting AutoLISP results back into Python.

Candidates:
  A. a file written by LISP           (blocked so far - find out how blocked)
  B. string system variables          (tiny, but always there)
  C. an XRecord in the named object dictionary, read back over COM  <- likely winner
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402


def say(*a):
    print(*a, flush=True)


def main() -> None:
    say("waking AutoCAD:", com.run_com(lambda: com.ensure_responsive(), timeout=60))

    def work():
        doc = com.active_doc(create_if_none=True)

        def send(text, settle=1.0):
            try:
                com.retry(lambda: doc.SendCommand(text), timeout=15)
            except Exception as exc:  # noqa: BLE001
                say("   SendCommand raised:", exc)
                return False
            time.sleep(settle)
            try:
                if int(doc.GetVariable("CMDACTIVE")):
                    winui.press_escape()
                    say("   (had to press Esc)")
            except Exception:
                winui.press_escape()
            return True

        def i1():
            return int(doc.GetVariable("USERI1"))

        def s1():
            return str(doc.GetVariable("USERS1"))

        say("== A. where, if anywhere, can LISP write? ==")
        say("   TEMPPREFIX =", repr(doc.GetVariable("TEMPPREFIX")))
        say("   SECURELOAD =", doc.GetVariable("SECURELOAD"))
        say("   LISPSYS    =", doc.GetVariable("LISPSYS"))

        temp = str(doc.GetVariable("TEMPPREFIX")).replace("\\", "/")
        candidates = {
            "temp dir": temp + "acadmcp_a.txt",
            "documents": "C:/Users/Wanda/Documents/acadmcp_a.txt",
            "appdata": "C:/Users/Wanda/AppData/Local/acadmcp/probe/acadmcp_a.txt",
        }
        for label, path in candidates.items():
            Path(path).unlink(missing_ok=True)
            doc.SetVariable("USERI1", 0)
            send('(progn (setq zf (open "%s" "w")) (setvar "USERI1" (if zf 1 0)) '
                 '(if zf (progn (princ "ok" zf) (close zf)))) ' % path)
            say(f"   open w {label:10s} -> handle={i1()} exists={Path(path).exists()}")

        doc.SetVariable("USERI1", 0)
        send('(setvar "USERI1" (if (open (strcat (getvar "TEMPPREFIX") "nope.txt") "r") 1 0)) ')
        say("   open r missing file ->", i1(), "(0 expected, proves open runs)")
        doc.SetVariable("USERS1", "")
        send('(setvar "USERS1" (if (findfile "acad.lin") "found" "not-found")) ')
        say("   findfile acad.lin   ->", repr(s1()))

        say("\n== B. string system variables ==")
        for n in (100, 200, 250, 400, 600):
            doc.SetVariable("USERS1", "")
            send('(setvar "USERS1" (substr (repeat 8 (setq s (strcat (if s s "") "0123456789"))) 1 %d)) ' % n,
                 settle=0.6)
            got = s1()
            say(f"   USERS1 {n:4d} chars -> got {len(got)}")
            send('(setq s nil) ', settle=0.3)
            if len(got) != n:
                break

        say("\n== C. XRecord in the named object dictionary ==")
        mk = (
            '(progn'
            ' (setq d (namedobjdict))'
            ' (if (dictsearch d "ACADMCP") (dictremove d "ACADMCP"))'
            ' (setq x (entmakex (list (cons 0 "XRECORD") (cons 100 "AcDbXrecord")'
            '   (cons 1 "hello-from-lisp") (cons 1 "second-chunk") (cons 70 7))))'
            ' (dictadd d "ACADMCP" x)'
            ' (setvar "USERI1" (if x 1 0))) '
        )
        doc.SetVariable("USERI1", 0)
        send(mk)
        say("   entmakex xrecord ->", i1())
        try:
            xr = doc.Dictionaries.Item("ACADMCP")
            say("   COM object name  ->", xr.ObjectName)
            data = xr.GetXRecordData()
            say("   GetXRecordData   ->", com.unwrap(data))
        except Exception as exc:  # noqa: BLE001
            say("   COM read FAILED  ->", type(exc).__name__, exc)

        # how much can one xrecord carry?
        say("\n== C2. xrecord capacity ==")
        chunk = "A" * 250
        many = " ".join(['(cons 1 "%s")' % chunk for _ in range(3)])
        big = (
            '(progn (setq d (namedobjdict))'
            ' (if (dictsearch d "ACADMCP2") (dictremove d "ACADMCP2"))'
            ' (setq x (entmakex (list (cons 0 "XRECORD") (cons 100 "AcDbXrecord") %s)))'
            ' (dictadd d "ACADMCP2" x) (setvar "USERI1" (if x 1 0))) ' % many
        )
        say("   command length =", len(big))
        doc.SetVariable("USERI1", 0)
        send(big, settle=1.5)
        say("   made ->", i1())
        try:
            xr2 = doc.Dictionaries.Item("ACADMCP2")
            types, values = xr2.GetXRecordData()
            vals = com.unwrap(values)
            say(f"   read back {len(vals)} items, total {sum(len(str(v)) for v in vals)} chars")
        except Exception as exc:  # noqa: BLE001
            say("   COM read FAILED ->", type(exc).__name__, exc)

        # build a long payload with repeated appends instead of one long command
        say("\n== C3. build payload across several short commands ==")
        doc.SetVariable("USERI1", 0)
        send('(setq acadmcp:buf "") ', settle=0.3)
        for i in range(4):
            send('(setq acadmcp:buf (strcat acadmcp:buf "%s")) ' % ("%d" % i * 200), settle=0.3)
        send('(setvar "USERI1" (strlen acadmcp:buf)) ', settle=0.5)
        say("   accumulated string length ->", i1())

        # write that long string into an xrecord in 250-char chunks, from LISP
        chunker = (
            '(progn (setq d (namedobjdict) lst (list (cons 0 "XRECORD") (cons 100 "AcDbXrecord"))'
            '   i 1 n (strlen acadmcp:buf))'
            ' (while (<= i n) (setq lst (append lst (list (cons 1 (substr acadmcp:buf i 250)))) i (+ i 250)))'
            ' (if (dictsearch d "ACADMCP3") (dictremove d "ACADMCP3"))'
            ' (dictadd d "ACADMCP3" (entmakex lst)) (setvar "USERI1" n)) '
        )
        doc.SetVariable("USERI1", 0)
        send(chunker, settle=1.0)
        say("   chunked into xrecord, n =", i1())
        try:
            xr3 = doc.Dictionaries.Item("ACADMCP3")
            types, values = xr3.GetXRecordData()
            vals = [v for t, v in zip(com.unwrap(types), com.unwrap(values)) if int(t) == 1]
            joined = "".join(str(v) for v in vals)
            say(f"   read back {len(vals)} chunks, {len(joined)} chars, head={joined[:40]!r}")
        except Exception as exc:  # noqa: BLE001
            say("   COM read FAILED ->", type(exc).__name__, exc)

    com.run_com(work, timeout=280)


main()
say("done")
