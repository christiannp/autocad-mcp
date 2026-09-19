"""Work out exactly why (load) from SendCommand does nothing."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com  # noqa: E402

TMP = Path("C:/Users/Wanda/AppData/Local/acadmcp/probe")
TMP.mkdir(parents=True, exist_ok=True)


def say(*a):
    print(*a, flush=True)


def wait_for(p: Path, seconds: float = 8.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if p.exists():
            return True
        time.sleep(0.05)
    return False


def main() -> None:
    def work():
        doc = com.active_doc(create_if_none=True)
        say("doc:", doc.Name)

        # --- what do the security sysvars say? ---------------------------
        for var in ("SECURELOAD", "TRUSTEDPATHS", "LISPSYS", "ACADLSPASDOC", "CMDECHO"):
            try:
                say(f"  {var} = {doc.GetVariable(var)!r}")
            except Exception as exc:  # noqa: BLE001
                say(f"  {var} = <unreadable: {exc}>")

        # --- A. inline LISP via SendCommand ------------------------------
        p1 = TMP / "probe1.txt"
        p1.unlink(missing_ok=True)
        expr = (
            '(progn (setq f (open "%s" "w")) (princ "INLINE-OK" f) (close f) (princ)) '
            % (p1.as_posix())
        )
        try:
            com.retry(lambda: doc.SendCommand(expr))
            say("A. inline LISP SendCommand ->", "WROTE FILE" if wait_for(p1) else "NOTHING")
        except Exception as exc:  # noqa: BLE001
            say("A. inline LISP SendCommand -> RAISED", exc)

        # --- B. (load) of a tiny lsp file --------------------------------
        p2 = TMP / "probe2.txt"
        p2.unlink(missing_ok=True)
        lsp = TMP / "probe.lsp"
        lsp.write_text(
            '(setq f (open "%s" "w"))(princ "LOAD-OK" f)(close f)(princ)\n' % p2.as_posix(),
            encoding="ascii",
        )
        try:
            com.retry(lambda: doc.SendCommand('(load "%s") ' % lsp.as_posix()))
            say("B. (load) of file       ->", "WROTE FILE" if wait_for(p2) else "NOTHING")
        except Exception as exc:  # noqa: BLE001
            say("B. (load) of file       -> RAISED", exc)

        # --- C. same but with the folder trusted -------------------------
        p3 = TMP / "probe3.txt"
        p3.unlink(missing_ok=True)
        lsp3 = TMP / "probe3.lsp"
        lsp3.write_text(
            '(setq f (open "%s" "w"))(princ "TRUSTED-OK" f)(close f)(princ)\n' % p3.as_posix(),
            encoding="ascii",
        )
        before = ""
        try:
            before = str(doc.GetVariable("TRUSTEDPATHS"))
        except Exception:
            pass
        want = [
            str(TMP),
            str(Path(__file__).resolve().parent.parent / "lisp"),
            str(Path("C:/Users/Wanda/AppData/Local/acadmcp/jobs")),
        ]
        merged = ";".join([p for p in before.split(";") if p.strip()] + want)
        try:
            doc.SetVariable("TRUSTEDPATHS", merged)
            say("C. TRUSTEDPATHS now     =", doc.GetVariable("TRUSTEDPATHS"))
        except Exception as exc:  # noqa: BLE001
            say("C. could not set TRUSTEDPATHS:", exc)
        try:
            com.retry(lambda: doc.SendCommand('(load "%s") ' % lsp3.as_posix()))
            say("C. (load) when trusted  ->", "WROTE FILE" if wait_for(p3) else "NOTHING")
        except Exception as exc:  # noqa: BLE001
            say("C. (load) when trusted  -> RAISED", exc)

        # --- D. does a plain command work at all? ------------------------
        n0 = int(doc.ModelSpace.Count)
        try:
            com.retry(lambda: doc.SendCommand("_.CIRCLE\n5000,5000\n120\n"))
            time.sleep(1.0)
            say(f"D. plain command        -> entities {n0} -> {int(doc.ModelSpace.Count)}")
        except Exception as exc:  # noqa: BLE001
            say("D. plain command        -> RAISED", exc)

        # --- E. how long is a SendCommand allowed to be? -----------------
        p5 = TMP / "probe5.txt"
        p5.unlink(missing_ok=True)
        filler = " ".join(["(setq a%d %d)" % (i, i) for i in range(400)])
        big = (
            "(progn %s (setq f (open \"%s\" \"w\")) (princ \"BIG-OK\" f) (close f) (princ)) "
            % (filler, p5.as_posix())
        )
        say(f"E. long SendCommand len = {len(big)}")
        try:
            com.retry(lambda: doc.SendCommand(big))
            say("E. long SendCommand     ->", "WROTE FILE" if wait_for(p5) else "NOTHING")
        except Exception as exc:  # noqa: BLE001
            say("E. long SendCommand     -> RAISED", exc)

    com.run_com(work, timeout=180)


main()
say("done")
