"""Bisect the job file: which part parks AutoCAD?"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402

LIB = Path(__file__).resolve().parent.parent / "lisp" / "acadmcp.lsp"


def say(*a):
    print(*a, flush=True)


def main() -> None:
    winui.press_escape(4)
    say("responsive after Esc:", com.run_com(lambda: com.ensure_responsive(), timeout=60))

    def work():
        doc = com.active_doc(create_if_none=True)
        temp = Path(str(doc.GetVariable("TEMPPREFIX")).rstrip("\\/"))
        say("temp:", temp)

        def send(text, settle=1.0, label=""):
            try:
                com.retry(lambda: doc.SendCommand(text), timeout=15)
            except Exception as exc:  # noqa: BLE001
                say(f"   [{label}] SendCommand raised: {exc}")
                winui.press_escape()
                return
            time.sleep(settle)
            try:
                if int(com.retry(lambda: doc.GetVariable("CMDACTIVE"), timeout=8, attr_is_busy=True)):
                    say(f"   [{label}] PARKED (CMDACTIVE) - Esc")
                    winui.press_escape()
            except Exception:
                say(f"   [{label}] PARKED (COM rejected) - Esc")
                winui.press_escape()
                com.ensure_responsive()

        def i1():
            try:
                return int(com.retry(lambda: doc.GetVariable("USERI1"), timeout=10, attr_is_busy=True))
            except Exception:
                return -1

        def setr(v=0):
            try:
                com.retry(lambda: doc.SetVariable("USERI1", v), timeout=10)
            except Exception:
                pass

        # --- 1. does load still work with a trivial file? ----------------
        f = temp / "acadmcp_t1.lsp"
        f.write_text('(setvar "USERI1" 501)(princ)\n', encoding="ascii")
        setr(); send('(load "%s") ' % f.as_posix(), label="1")
        say("1. trivial load                 ->", i1(), "(501 = ok)")

        # --- 2. writing files, by extension ------------------------------
        for ext in (".txt", ".json", ".flag", ".tmp"):
            p = temp / ("acadmcp_ext_test" + ext)
            p.unlink(missing_ok=True)
            setr()
            send('(progn (setq zf (open "%s" "w")) (setvar "USERI1" (if zf 1 0)) '
                 '(if zf (progn (princ "x" zf) (close zf)))) ' % p.as_posix(),
                 settle=0.8, label="2" + ext)
            say(f"2. open w {ext:6s}                -> handle={i1()} exists={p.exists()}")

        # --- 3. load the real library ------------------------------------
        lib = temp / "acadmcp_lib_test.lsp"
        lib.write_text(LIB.read_text(encoding="utf-8"), encoding="ascii", errors="replace")
        setr()
        send('(load "%s") ' % lib.as_posix(), settle=2.0, label="3")
        setr()
        send('(setvar "USERI1" (if acadmcp:version 601 602)) ', label="3b")
        say("3. library loads                ->", i1(), "(601 = yes, 602 = no, -1 = parked)")

        # --- 4. if not, bisect the library -------------------------------
        if i1() != 601:
            text = LIB.read_text(encoding="utf-8")
            # split on top level blank-line-separated defuns
            blocks, cur = [], []
            depth = 0
            for line in text.splitlines():
                cur.append(line)
                depth += line.count("(") - line.count(")")
                if depth == 0 and any(c.strip() for c in cur):
                    blocks.append("\n".join(cur))
                    cur = []
            say(f"4. library has {len(blocks)} top-level forms; loading one at a time")
            for idx, block in enumerate(blocks):
                head = block.strip().splitlines()[0][:60] if block.strip() else "(blank)"
                if not block.strip() or block.strip().startswith(";"):
                    continue
                part = temp / f"acadmcp_part_{idx}.lsp"
                part.write_text(block + '\n(setvar "USERI1" 700)\n(princ)\n',
                                encoding="ascii", errors="replace")
                setr()
                send('(load "%s") ' % part.as_posix(), settle=0.8, label=f"4.{idx}")
                ok = i1() == 700
                say(f"   [{idx:2d}] {'ok  ' if ok else 'FAIL'} {head}")

    com.run_com(work, timeout=280)


main()
say("done")
