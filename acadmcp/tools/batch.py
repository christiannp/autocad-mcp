"""Running the same work across a folder full of drawings."""

from __future__ import annotations

import fnmatch
import os
import time
from typing import Any

from .. import com, lisp
from ..errors import AcadError
from ..registry import tool
from .raw import _arg


def _decode(raw: bytes | None) -> str:
    """accoreconsole writes UTF-16LE; fall back to the ANSI code page."""
    if not raw:
        return ""
    if b"\x00" in raw[:200]:
        try:
            return raw.decode("utf-16-le", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    for encoding in ("utf-8", "mbcs", "latin-1"):
        try:
            return raw.decode(encoding, errors="replace")
        except Exception:  # noqa: BLE001
            continue
    return repr(raw[:200])


def _gather(
    folder: str | None,
    files: list[str] | None,
    pattern: str,
    recursive: bool,
) -> list[str]:
    found: list[str] = []
    for f in files or []:
        full = os.path.abspath(os.path.expanduser(str(f)))
        if not os.path.isfile(full):
            raise AcadError(f"There is no file at {full}")
        found.append(full)
    if folder:
        root = os.path.abspath(os.path.expanduser(str(folder)))
        if not os.path.isdir(root):
            raise AcadError(f"There is no folder at {root}")
        if recursive:
            for base, _dirs, names in os.walk(root):
                for name in names:
                    if fnmatch.fnmatch(name.lower(), pattern.lower()):
                        found.append(os.path.join(base, name))
        else:
            for name in sorted(os.listdir(root)):
                full = os.path.join(root, name)
                if os.path.isfile(full) and fnmatch.fnmatch(name.lower(), pattern.lower()):
                    found.append(full)
    # ignore AutoCAD's own backups and lock leftovers
    return sorted(
        {f for f in found if not os.path.basename(f).lower().startswith(("~$", "backup_"))}
    )


@tool(readonly=True, description="List the drawings a batch run would touch, without opening anything. Always worth doing first.")
def batch_preview(
    folder: str | None = None,
    files: list[str] | None = None,
    pattern: str = "*.dwg",
    recursive: bool = False,
) -> dict[str, Any]:
    found = _gather(folder, files, pattern, recursive)
    return {
        "count": len(found),
        "files": [
            {
                "path": f,
                "name": os.path.basename(f),
                "size_kb": round(os.path.getsize(f) / 1024, 1),
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(f))),
            }
            for f in found[:200]
        ],
        "truncated": len(found) > 200,
    }


@tool(undo_group=False, description=(
    "Open every matching drawing in a folder, run the same steps on each, then "
    "save and close it. Steps are the same shape as cad_script: "
    "{\"command\": \"_.-PURGE\", \"args\": [...]} or {\"lisp\": \"...\"}. "
    "Set output_folder to write copies and leave the originals untouched. "
    "Run batch_preview first, and try one file before running the lot."
))
def batch_process(
    steps: list[dict[str, Any]],
    folder: str | None = None,
    files: list[str] | None = None,
    pattern: str = "*.dwg",
    recursive: bool = False,
    output_folder: str | None = None,
    save_format: str | None = None,
    save: bool = True,
    limit: int | None = None,
    stop_on_error: bool = False,
    step_timeout: float = 180,
) -> dict[str, Any]:
    if not steps:
        raise AcadError("no steps given - what should be done to each drawing?")
    found = _gather(folder, files, pattern, recursive)
    if not found:
        raise AcadError("No drawings matched.")
    if limit:
        found = found[: int(limit)]

    out_dir = None
    if output_folder:
        out_dir = os.path.abspath(os.path.expanduser(str(output_folder)))
        os.makedirs(out_dir, exist_ok=True)

    from .session import SAVE_FORMATS

    fmt = None
    if save_format:
        key = str(save_format).strip().lower()
        if key not in SAVE_FORMATS:
            raise AcadError(
                f"unknown save_format {save_format!r}; choose from "
                + ", ".join(sorted(SAVE_FORMATS))
            )
        fmt = SAVE_FORMATS[key]

    def build(step: dict[str, Any]) -> Any:
        if "lisp" in step:
            return lisp.raw(str(step["lisp"]))
        if "command" in step:
            parts: list[Any] = [str(step["command"])]
            if not parts[0].startswith(("_", ".", "-")):
                parts[0] = "_." + parts[0].lstrip("_.")
            for a in step.get("args") or []:
                parts.append(_arg(a))
            return lisp.command(*parts)
        raise AcadError("each step needs either 'command' or 'lisp'")

    bodies = [build(s) for s in steps]

    results: list[dict[str, Any]] = []
    started = time.time()

    for path in found:
        entry: dict[str, Any] = {"file": os.path.basename(path), "path": path}
        doc = None
        try:
            doc = com.run_com(
                lambda p=path: com.retry(
                    lambda: com.app().Documents.Open(p, False),
                    timeout=300,
                    context=f"opening {os.path.basename(p)}",
                ),
                timeout=360,
            )
            lisp.forget_library()

            done = []
            for index, body in enumerate(bodies):
                lisp.evaluate(body, doc=doc, timeout=step_timeout)
                done.append(index + 1)
            entry["steps_done"] = len(done)

            if save:
                if out_dir:
                    target = os.path.join(out_dir, os.path.basename(path))
                    if fmt is not None:
                        com.run_com(
                            lambda d=doc, t=target: com.retry(
                                lambda: d.SaveAs(t, fmt), timeout=300
                            ),
                            timeout=360,
                        )
                    else:
                        com.run_com(
                            lambda d=doc, t=target: com.retry(
                                lambda: d.SaveAs(t), timeout=300
                            ),
                            timeout=360,
                        )
                    entry["written"] = target
                elif fmt is not None:
                    com.run_com(
                        lambda d=doc, p=path: com.retry(lambda: d.SaveAs(p, fmt), timeout=300),
                        timeout=360,
                    )
                    entry["written"] = path
                else:
                    com.run_com(lambda d=doc: com.retry(lambda: d.Save(), timeout=300),
                                timeout=360)
                    entry["written"] = path
            entry["ok"] = True
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = str(exc)[:300]
        finally:
            if doc is not None:
                com.run_com(
                    lambda d=doc: com.quiet(lambda: d.Close(False)), timeout=180
                )
                lisp.forget_library()
                # closing a drawing keeps AutoCAD busy for a moment; wait so the
                # next file (or the next tool call) does not hit a rejected call
                com.run_com(lambda: com.ensure_responsive(), timeout=90)
        results.append(entry)
        if stop_on_error and not entry.get("ok"):
            break

    ok = sum(1 for r in results if r.get("ok"))
    return {
        "processed": len(results),
        "succeeded": ok,
        "failed": len(results) - ok,
        "seconds": round(time.time() - started, 1),
        "output_folder": out_dir,
        "results": results,
    }


@tool(undo_group=False, description=(
    "Run a batch job headlessly with accoreconsole - no window, much faster for "
    "large folders, but no visual feedback and script commands only (no LISP "
    "that needs the UI). script_lines are typed exactly as at the command line."
))
def batch_headless(
    script_lines: list[str],
    folder: str | None = None,
    files: list[str] | None = None,
    pattern: str = "*.dwg",
    recursive: bool = False,
    save: bool = True,
    limit: int | None = None,
    timeout_per_file: float = 300,
) -> dict[str, Any]:
    import subprocess
    import tempfile

    exe = None
    for base in (
        r"C:\Program Files\Autodesk",
    ):
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base), reverse=True):
            candidate = os.path.join(base, name, "accoreconsole.exe")
            if os.path.isfile(candidate):
                exe = candidate
                break
        if exe:
            break
    if not exe:
        raise AcadError("accoreconsole.exe was not found in the AutoCAD installation.")

    found = _gather(folder, files, pattern, recursive)
    if not found:
        raise AcadError("No drawings matched.")
    if limit:
        found = found[: int(limit)]

    lines = list(script_lines)
    if save:
        lines.append("_.QSAVE")
    body = "\n".join(lines) + "\n"

    script = os.path.join(tempfile.gettempdir(), "acadmcp_batch.scr")
    with open(script, "w", encoding="ascii", errors="replace") as handle:
        handle.write(body)

    results = []
    started = time.time()
    for path in found:
        entry: dict[str, Any] = {"file": os.path.basename(path), "path": path}
        try:
            proc = subprocess.run(
                [exe, "/i", path, "/s", script],
                capture_output=True,
                timeout=float(timeout_per_file),
                creationflags=0x08000000,
            )
            # accoreconsole writes UTF-16; decoding it as text gives NUL bytes
            out_text = _decode(proc.stdout)
            err_text = _decode(proc.stderr)
            entry["ok"] = proc.returncode == 0
            tail = [t.strip() for t in out_text.strip().splitlines() if t.strip()][-4:]
            if tail:
                entry["output"] = " | ".join(tail)[:300]
            if proc.returncode != 0:
                entry["error"] = (err_text or out_text)[-300:]
        except subprocess.TimeoutExpired:
            entry["ok"] = False
            entry["error"] = f"timed out after {timeout_per_file:g}s"
        except Exception as exc:  # noqa: BLE001
            entry["ok"] = False
            entry["error"] = str(exc)[:300]
        results.append(entry)

    ok = sum(1 for r in results if r.get("ok"))
    return {
        "engine": exe,
        "script": body,
        "processed": len(results),
        "succeeded": ok,
        "failed": len(results) - ok,
        "seconds": round(time.time() - started, 1),
        "results": results,
    }
