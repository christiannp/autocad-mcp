"""Pick the transport: can we (load) a job file from AutoCAD's own temp folder?"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402


def say(*a):
    print(*a, flush=True)


def main() -> None:
    com.run_com(lambda: com.ensure_responsive(), timeout=60)

    def work():
        doc = com.active_doc(create_if_none=True)
        temp = Path(str(doc.GetVariable("TEMPPREFIX")))
        say("AutoCAD temp:", temp)

        def send(text, settle=0.9):
            try:
                com.retry(lambda: doc.SendCommand(text), timeout=15)
            except Exception as exc:  # noqa: BLE001
                say("   raised:", exc)
                return
            time.sleep(settle)
            try:
                if int(doc.GetVariable("CMDACTIVE")):
                    winui.press_escape()
                    say("   (Esc)")
            except Exception:
                winui.press_escape()

        def i1():
            return int(doc.GetVariable("USERI1"))

        def trial(label, path: Path, code='(setvar "USERI1" 777)(princ)\n'):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(code, encoding="ascii")
            doc.SetVariable("USERI1", 0)
            send('(load "%s") ' % path.as_posix())
            ok = i1() == 777
            say(f"   load from {label:22s} -> {'OK' if ok else 'BLOCKED'}")
            return ok

        say("\n== 1. (load) by location, SECURELOAD =", doc.GetVariable("SECURELOAD"), "==")
        ok_temp = trial("AutoCAD temp", temp / "acadmcp_job.lsp")
        ok_docs = trial("Documents", Path("C:/Users/Wanda/Documents/acadmcp_job.lsp"))
        ok_proj = trial("project lisp folder",
                        Path(__file__).resolve().parent.parent / "lisp" / "probe_job.lsp")

        if not (ok_temp or ok_docs or ok_proj):
            say("\n== 2. add trusted paths and retry ==")
            before = str(doc.GetVariable("TRUSTEDPATHS") or "")
            paths = [p for p in before.split(";") if p.strip()]
            for extra in (str(temp).rstrip("\\"),
                          str(Path(__file__).resolve().parent.parent / "lisp")):
                if extra not in paths:
                    paths.append(extra)
            doc.SetVariable("TRUSTEDPATHS", ";".join(paths))
            say("   TRUSTEDPATHS =", doc.GetVariable("TRUSTEDPATHS"))
            ok_temp = trial("AutoCAD temp (trusted)", temp / "acadmcp_job.lsp")
            ok_proj = trial("project lisp (trusted)",
                            Path(__file__).resolve().parent.parent / "lisp" / "probe_job.lsp")

        say("\n== 3. long code via accumulate-then-eval (no file needed) ==")
        # build a long expression in 700 char slices, then (eval (read s))
        body = ('(progn (setq zz 0) ' + " ".join("(setq zz (+ zz %d))" % i for i in range(1, 121))
                + ' (setvar "USERI1" zz)) ')
        say("   expression length =", len(body))
        send('(setq acadmcp:src "") ', settle=0.3)
        for i in range(0, len(body), 600):
            piece = body[i:i + 600].replace("\\", "\\\\").replace('"', '\\"')
            send('(setq acadmcp:src (strcat acadmcp:src "%s")) ' % piece, settle=0.3)
        doc.SetVariable("USERI1", 0)
        send('(eval (read acadmcp:src)) ', settle=1.0)
        say(f"   result USERI1 = {i1()} (want {sum(range(1, 121))})")

        say("\n== 4. writing the result file from LISP into AutoCAD temp ==")
        out = temp / "acadmcp_result.json"
        out.unlink(missing_ok=True)
        send('(progn (setq f (open "%s" "w")) (princ "{\\"ok\\":true,\\"result\\":[1,2,3]}" f) '
             '(close f) (princ)) ' % out.as_posix())
        say("   exists:", out.exists(), "content:",
            out.read_text() if out.exists() else None)

        say("\n== 5. unicode through the file channel ==")
        out2 = temp / "acadmcp_uni.json"
        out2.unlink(missing_ok=True)
        send('(progn (setq f (open "%s" "w")) (princ (strcat "[" (chr 34) '
             '(chr 23627) (chr 38914) (chr 34) "]") f) (close f) (princ)) ' % out2.as_posix())
        if out2.exists():
            raw = out2.read_bytes()
            say("   bytes:", raw[:40])
            for enc in ("utf-8", "cp950", "mbcs"):
                try:
                    say(f"   as {enc}: {raw.decode(enc)!r}")
                except Exception as exc:  # noqa: BLE001
                    say(f"   as {enc}: {exc}")

    com.run_com(work, timeout=280)


main()
say("done")
