"""Verify the Express Tools (and anything else still unknown) safely.

No keyboard automation. Each command is sent through COM from a *throwaway
subprocess*: if the command parks AutoCAD, SendCommand blocks that subprocess
only, and the parent kills it and carries on. Prompts are read from AutoCAD's
log file, which is just a file on disk and stays readable even while the
application is busy.

The only keystroke ever sent is Esc, and only to clear a parked command - and
even that refuses to fire unless AutoCAD is genuinely the frontmost window.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acadmcp import com, winui  # noqa: E402

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / "build" / "verify_express.json"
SEND_TIMEOUT = 6.0
SETTLE = 0.5

SENDER = r"""
import sys
sys.path.insert(0, r"{root}")
from acadmcp import com
name = sys.argv[1]
def work():
    doc = com.active_doc()
    doc.SendCommand(name + "\n")
    return True
com.run_com(work, timeout=30)
"""


def prepare() -> Path:
    def work():
        doc = com.active_doc(create_if_none=True)
        for var, value in (("FILEDIA", 0), ("ATTDIA", 0), ("ATTREQ", 0),
                           ("EXPERT", 5), ("CMDECHO", 1)):
            com.quiet(lambda v=var, x=value: doc.SetVariable(v, x))
        doc.SetVariable("LOGFILEMODE", 0)
        doc.SetVariable("LOGFILEMODE", 1)
        return str(doc.GetVariable("LOGFILENAME"))

    return Path(com.run_com(work, timeout=120))


def restore() -> None:
    def work():
        doc = com.active_doc()
        for var, value in (("LOGFILEMODE", 0), ("FILEDIA", 1), ("ATTDIA", 1),
                           ("ATTREQ", 1), ("EXPERT", 0)):
            com.quiet(lambda v=var, x=value: doc.SetVariable(v, x))
        return True

    com.quiet(lambda: com.run_com(work, timeout=120))


def main() -> None:
    targets = json.loads((ROOT / "build" / "express_targets.json").read_text())
    results: dict[str, dict] = {}
    if OUT.exists():
        try:
            results = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results = {}
    todo = [c for c in targets if c not in results]
    print(f"{len(todo)} to verify ({len(results)} already done)", flush=True)

    sender = ROOT / "build" / "_send_one.py"
    sender.write_text(SENDER.format(root=str(ROOT)), encoding="utf-8")

    log = prepare()
    print(f"log: {log}", flush=True)
    parked = 0

    for index, name in enumerate(todo, start=1):
        before = log.stat().st_size if log.exists() else 0
        blocked = False
        proc = subprocess.Popen(
            [str(PYTHON), "-X", "utf8", str(sender), name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, creationflags=0x08000000,
        )
        try:
            proc.wait(timeout=SEND_TIMEOUT)
        except subprocess.TimeoutExpired:
            blocked = True
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        time.sleep(SETTLE)

        chunk = ""
        if log.exists():
            with open(log, "rb") as fh:
                fh.seek(before)
                chunk = fh.read().decode("mbcs", errors="replace")
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        lines = [l for l in lines if l not in ("Command:",)]

        unknown = any("Unknown command" in l for l in lines)
        results[name] = {
            "exists_ui": bool(lines) and not unknown,
            "output": lines[:10],
            "parked": blocked,
        }
        if blocked:
            parked += 1
            winui.press_escape(3)          # guarded: only fires if AutoCAD is frontmost
            time.sleep(0.4)

        if index % 5 == 0 or blocked:
            OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False),
                           encoding="utf-8")
            print(f"  {index}/{len(todo)} {name}"
                  + ("  [parked, Esc sent]" if blocked else ""), flush=True)

    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    restore()

    exists = sum(1 for v in results.values() if v.get("exists_ui"))
    with_prompts = sum(1 for v in results.values() if v.get("output"))
    print(f"\ndone: {len(results)} tried, {exists} confirmed present, "
          f"{with_prompts} produced output, {parked} parked and were cleared")
    print(f"written to {OUT}")


main()
