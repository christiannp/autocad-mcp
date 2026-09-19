"""Load the library one top-level form at a time and find the one that parks."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402

LIB = Path(__file__).resolve().parent.parent / "lisp" / "acadmcp.lsp"


def say(*a):
    print(*a, flush=True)


def split_forms(text: str) -> list[str]:
    forms, cur, depth = [], [], 0
    in_str = esc = in_cmt = False
    for ch in text:
        cur.append(ch)
        if ch == "\n":
            in_cmt = False
            if depth == 0 and "".join(cur).strip():
                forms.append("".join(cur))
                cur = []
            continue
        if in_cmt:
            continue
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == ";":
            in_cmt = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    if "".join(cur).strip():
        forms.append("".join(cur))
    return [f for f in forms if f.strip() and not f.strip().startswith(";")]


def main() -> None:
    winui.press_escape(4)
    com.run_com(lambda: com.ensure_responsive(), timeout=60)

    def work():
        doc = com.active_doc(create_if_none=True)
        temp = Path(str(doc.GetVariable("TEMPPREFIX")).rstrip("\\/"))
        forms = split_forms(LIB.read_text(encoding="utf-8"))
        say(f"{len(forms)} top-level forms")

        for idx, form in enumerate(forms):
            head = " ".join(form.strip().split())[:64]
            probe = temp / f"acadmcp_f{idx}.lsp"
            flag = temp / f"acadmcp_f{idx}.ok"
            flag.unlink(missing_ok=True)
            probe.write_text(
                form + f'\n(setq zf (open "{flag.as_posix()}" "w"))'
                '(princ "1" zf)(close zf)(princ)\n',
                encoding="ascii",
                errors="replace",
            )
            try:
                com.retry(lambda: doc.SendCommand('(load "%s") ' % probe.as_posix()), timeout=10)
            except Exception as exc:  # noqa: BLE001
                say(f"[{idx:2d}] SEND-FAIL {head}  ({exc})")
                winui.press_escape()
                com.ensure_responsive()
                continue
            end = time.time() + 6
            while time.time() < end and not flag.exists():
                time.sleep(0.05)
            if flag.exists():
                say(f"[{idx:2d}] ok    {head}")
            else:
                say(f"[{idx:2d}] PARKS {head}")
                say("     >>> full form:")
                say(form)
                winui.press_escape(4)
                com.ensure_responsive()

    com.run_com(work, timeout=280)


main()
say("done")
