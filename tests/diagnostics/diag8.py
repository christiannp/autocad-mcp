"""Which SendCommand terminator does NOT leave a stray Enter behind?

A bare LISP expression auto-executes as soon as its parens balance, so whatever
we append afterwards lands at the command prompt as an extra Enter - which
repeats the previous command.  If that command prompts for input, AutoCAD parks
and every later COM call is rejected.  Find the form that is safe.
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
    winui.press_escape(4)
    com.run_com(lambda: com.ensure_responsive(), timeout=60)

    def work():
        doc = com.active_doc(create_if_none=True)
        temp = Path(str(doc.GetVariable("TEMPPREFIX")).rstrip("\\/"))

        probe = temp / "acadmcp_term.lsp"
        flag = temp / "acadmcp_term.ok"

        def prime():
            """Make the previous command a parking one: CIRCLE."""
            doc.SendCommand('(command "_.CIRCLE" (list 9000.0 9000.0 0.0) 5.0) ')
            time.sleep(1.2)
            winui.press_escape(2)
            com.ensure_responsive()

        def attempt(label: str, text: str):
            flag.unlink(missing_ok=True)
            probe.write_text(
                '(setq zf (open "%s" "w"))(princ "1" zf)(close zf)(princ)\n'
                % flag.as_posix(),
                encoding="ascii",
            )
            prime()
            try:
                doc.SendCommand(text)
            except Exception as exc:  # noqa: BLE001
                say(f"{label:34s} SendCommand raised: {exc}")
                winui.press_escape(3)
                com.ensure_responsive()
                return
            end = time.time() + 5
            while time.time() < end and not flag.exists():
                time.sleep(0.05)
            ran = flag.exists()
            try:
                active = int(doc.GetVariable("CMDACTIVE"))
                prompt = str(doc.GetVariable("LASTPROMPT"))[:48]
                busy = False
            except Exception:
                active, prompt, busy = -1, "<rejected>", True
            say(f"{label:34s} ran={ran!s:5s} CMDACTIVE={active} busy={busy!s:5s} {prompt!r}")
            if busy or active:
                winui.press_escape(3)
                com.ensure_responsive()

        p = probe.as_posix()
        attempt("A newline terminator", '(load "%s")\n' % p)
        attempt("B space terminator", '(load "%s") ' % p)
        attempt("C no terminator", '(load "%s")' % p)
        attempt("D newline then cancel", '(load "%s")\n\x03' % p)
        attempt("E cancel, expr, newline", '\x03\x03(load "%s")\n' % p)
        attempt("F expr then ESC char", '(load "%s")\x1b' % p)

        # G: the command approach - define a command, then call it by name
        say("\n-- G: define c:AMRUN and call it as a command --")
        fixed = temp / "acadmcp_current.lsp"
        fixed.write_text(
            '(setq zf (open "%s" "w"))(princ "1" zf)(close zf)(princ)\n' % flag.as_posix(),
            encoding="ascii",
        )
        defn = '(defun c:AMRUN () (load "%s") (princ)) ' % fixed.as_posix()
        winui.press_escape(2)
        doc.SendCommand(defn)
        time.sleep(1.0)
        winui.press_escape(2)
        com.ensure_responsive()
        flag.unlink(missing_ok=True)
        prime()
        doc.SendCommand("AMRUN\n")
        end = time.time() + 5
        while time.time() < end and not flag.exists():
            time.sleep(0.05)
        try:
            active = int(doc.GetVariable("CMDACTIVE"))
            prompt = str(doc.GetVariable("LASTPROMPT"))[:48]
            busy = False
        except Exception:
            active, prompt, busy = -1, "<rejected>", True
        say(f"{'G command by name':34s} ran={flag.exists()!s:5s} CMDACTIVE={active} "
            f"busy={busy!s:5s} {prompt!r}")
        if busy or active:
            winui.press_escape(3)
            com.ensure_responsive()

    com.run_com(work, timeout=280)


main()
say("done")
