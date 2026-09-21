"""Probe every AutoCAD command headlessly and record its real prompt chain.

Runs accoreconsole in batches. Each batch is a single .scr line holding a LISP
foreach that, for every command: prints a marker, starts the command, cancels
whatever it left pending, and prints a closing marker. Nothing can hang the UI
because there is no UI, and a batch that dies is bisected down to the command
that killed it.

Output: build/probe_headless.json
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = os.environ.get("ACADMCP_ACAD_RELEASE", "AutoCAD 2025")
ACCORE = Path(r"C:\Program Files\Autodesk") / RELEASE / "accoreconsole.exe"
SCRATCH = Path(os.environ["LOCALAPPDATA"]) / "Temp" / "acadmcp_probe" / "scratch.dwg"
OUT = ROOT / "build" / "probe_headless.json"

BATCH = 40
TIMEOUT = 150

UNKNOWN = re.compile(r'Unknown command\s+"([^"]+)"', re.I)


def decode(raw: bytes) -> str:
    if b"\x00" in raw[:200]:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("mbcs", errors="replace")


# Everything must be on ONE script line. accoreconsole executes the first line
# and a pending command would swallow the next one, so the setvars and the
# sweep live inside a single expression.
PREAMBLE = (
    '(progn (setvar "FILEDIA" 0) (setvar "EXPERT" 5) (setvar "ATTDIA" 0)'
    ' (setvar "ATTREQ" 0) (setvar "CMDECHO" 1) '
)


def build_script(commands: list[str]) -> str:
    names = " ".join('"%s"' % n.replace('"', "") for n in commands)
    return PREAMBLE + (
        # the markers end with ";" so they can be matched unambiguously - the
        # command echo follows immediately and starts with "_", which is a
        # word character, so a \b boundary would not work
        "(foreach c (list %s)"
        ' (princ (strcat "\\n@@" "@B:" c ";"))'
        " (setq r (vl-catch-all-apply '(lambda () (command (strcat \"_.\" c))) nil))"
        " (if (vl-catch-all-error-p r)"
        '   (princ (strcat "\\n@@" "@X:" (vl-catch-all-error-message r))))'
        " (vl-catch-all-apply '(lambda () (command)) nil)"
        " (vl-catch-all-apply '(lambda () (command)) nil)"
        ' (princ (strcat "\\n@@" "@E:" c ";")))' % names
    ) + ' (princ (strcat "\\n@@" "@ALLDONE")) (princ))\n'


def run_batch(commands: list[str]) -> tuple[str, bool]:
    """Run one batch, capturing output to a FILE rather than a pipe.

    capture_output=True hands the child an inherited pipe; accoreconsole spawns
    helpers that keep that pipe open, so killing it on timeout still leaves
    communicate() waiting forever. Writing to a file avoids the whole problem
    and lets us read whatever was produced before the kill.
    """
    tmp = Path(tempfile.gettempdir())
    script = tmp / "acadmcp_probe_batch.scr"
    outfile = tmp / "acadmcp_probe_batch.out"
    script.write_text(build_script(commands), encoding="ascii", errors="replace")
    outfile.unlink(missing_ok=True)

    completed = True
    with open(outfile, "wb") as sink:
        proc = subprocess.Popen(
            [str(ACCORE), "/i", str(SCRATCH), "/s", str(script)],
            stdout=sink, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        try:
            proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            completed = False
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True, creationflags=0x08000000,
                )
    try:
        return decode(outfile.read_bytes()), completed
    except OSError:
        return "", completed


def parse(text: str, commands: list[str]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for name in commands:
        m = re.search(
            r"@@@B:%s;(.*?)@@@E:%s;" % (re.escape(name), re.escape(name)),
            text, re.S,
        )
        if not m:
            continue
        body = m.group(1)
        lines = [l.strip() for l in body.splitlines() if l.strip()]
        # drop the command echo itself and the trailing "Command:" prompts
        cleaned = []
        for line in lines:
            if line in ("Command:", f"_.{name}"):
                continue
            if line.startswith(f"_.{name}"):
                rest = line[len(f"_.{name}"):].strip()
                if rest:
                    cleaned.append(rest)
                continue
            cleaned.append(line)
        unknown = bool(UNKNOWN.search(body))
        entry: dict = {
            "exists_headless": not unknown,
            "output": cleaned,
        }
        err = re.search(r"@@@X:(.*)", body)
        if err:
            entry["lisp_error"] = err.group(1).strip()
        found[name] = entry
    return found


def sweep(commands: list[str]) -> dict[str, dict]:
    """Walk the list, resuming past anything that kills the headless session.

    A few commands end accoreconsole outright (they quit, or wait on something
    that never comes). Bisecting for them costs a process launch per command;
    instead, whatever the run produced is kept, the first command with no
    result is recorded as the culprit, and the sweep resumes after it.
    """
    # resume: keep whatever a previous run already established
    results: dict[str, dict] = {}
    if OUT.exists():
        try:
            results = json.loads(OUT.read_text(encoding="utf-8"))
            print(f"  resuming - {len(results)} commands already probed", flush=True)
        except json.JSONDecodeError:
            results = {}

    remaining = [c for c in commands if c not in results]
    total = len(commands)
    killers = 0
    since_save = 0

    while remaining:
        batch = remaining[:BATCH]
        text, completed = run_batch(batch)
        parsed = parse(text, batch) if text else {}
        results.update(parsed)

        if len(parsed) == len(batch):
            remaining = remaining[len(batch):]
        else:
            idx = next(i for i, c in enumerate(batch) if c not in parsed)
            culprit = batch[idx]
            results[culprit] = {
                "exists_headless": None,
                "output": [],
                "note": "ended the headless session"
                if completed else "hung until the batch timed out",
            }
            killers += 1
            remaining = remaining[idx + 1:]

        since_save += 1
        if since_save >= 3:
            OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False),
                           encoding="utf-8")
            since_save = 0
        done = len(results)
        print(f"  {done}/{total}  ({killers} session-enders so far)", flush=True)
    return results


def main() -> None:
    src = ROOT / "build" / "inventory.json"
    if not src.exists():
        sys.exit("run build_inventory.py first")
    commands = json.loads(src.read_text(encoding="utf-8"))["commands"]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only:
        commands = [c for c in commands if c.startswith(only.upper())]
    print(f"probing {len(commands)} commands in batches of {BATCH}", flush=True)

    start = time.time()
    results = sweep(commands)
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")

    known = sum(1 for v in results.values() if v.get("exists_headless"))
    unknown = sum(1 for v in results.values() if v.get("exists_headless") is False)
    silent = sum(1 for v in results.values() if v.get("exists_headless") is None)
    print(
        f"\ndone in {time.time()-start:.0f}s: "
        f"{known} known headless, {unknown} unknown headless, {silent} no output"
    )
    print(f"written to {OUT}")


main()
