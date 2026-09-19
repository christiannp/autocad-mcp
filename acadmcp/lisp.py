"""The AutoLISP bridge.

COM gives us objects; AutoLISP gives us *commands*.  Plenty of what an architect
does by hand - TRIM, FILLET, HATCH by internal point, ARRAY, OVERKILL, PURGE,
Express Tools - does not exist in the COM API at all.  This module runs
arbitrary LISP inside the live drawing and brings the result back, which is what
makes "if she can do it manually, the server can do it" true rather than a
slogan.

Design notes, all of them learned the hard way against AutoCAD 2025
-------------------------------------------------------------------
* **Never ``(load)`` a file.**  With SECURELOAD=1 (the default) AutoCAD throws a
  modal "Security - Unsigned Executable File" dialog, which blocks the whole
  application: every COM call then fails with RPC_E_CALL_REJECTED and only a
  real mouse click clears it.  Typed LISP is not subject to SECURELOAD, so we
  stream source into a string and ``(eval (read ...))`` it instead.  No dialog,
  no changes to her security settings, nothing to install.
* **Keep SendCommand strings short.**  Around 2.4 kB was enough to park AutoCAD
  at a prompt; we cap at :data:`MAX_SEND` and slice anything longer.
* **Results come back through a file** written by LISP into AutoCAD's own temp
  folder (TEMPPREFIX).  LISP file writes work there; they were observed failing
  in an arbitrary %LOCALAPPDATA% subfolder.  The payload is ASCII-escaped JSON,
  so no code page can corrupt it.
* ``(read)`` parses one expression, so the support library is streamed wrapped
  in a single ``(progn ...)``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import com, winui
from .errors import AcadError, Busy, LispError

LIB_SOURCE = Path(__file__).resolve().parent.parent / "lisp" / "acadmcp.lsp"

DEFAULT_TIMEOUT = float(os.environ.get("ACADMCP_LISP_TIMEOUT", "120"))

#: SendCommand strings much longer than this have been seen to wedge AutoCAD.
MAX_SEND = 700

#: payload per streaming slice, leaving room for the wrapper and escaping
SLICE = 380

#: sentinel meaning "let the user answer this command prompt"
PAUSE = object()

_lock = threading.Lock()
_lib_ready: set[str] = set()   # drawings whose LISP namespace already has the library


def _posix(p: str | Path) -> str:
    return str(p).replace("\\", "/")


# ---------------------------------------------------------------------------
# Python -> AutoLISP literals (always ASCII, so encoding can never bite us)
# ---------------------------------------------------------------------------


def lstr(s: str) -> str:
    """A LISP expression yielding the given string.

    Plain ASCII becomes a literal.  Anything else is built with ``(chr n)``,
    because ``\\U+XXXX`` escapes are handled by AutoCAD's *file/console* reader
    and are **not** decoded by ``(read)`` - and ``(read)`` is how streamed
    source gets parsed, so escapes would survive as literal text.  Control
    characters go through ``(chr n)`` for the same reason.
    """
    text = str(s)
    parts: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            parts.append('"' + "".join(buf) + '"')
            buf.clear()

    for ch in text:
        o = ord(ch)
        if ch == "\\":
            buf.append("\\\\")
        elif ch == '"':
            buf.append('\\"')
        elif 32 <= o <= 126:
            buf.append(ch)
        elif o <= 0xFFFF:
            flush()
            parts.append(f"(chr {o})")
        else:
            raise AcadError(
                f"AutoLISP cannot carry the character U+{o:04X}; remove it or use "
                "a name AutoCAD supports"
            )
    flush()
    if not parts:
        return '""'
    if len(parts) == 1:
        return parts[0]
    return "(strcat " + " ".join(parts) + ")"


def lnum(v: float | int) -> str:
    if isinstance(v, bool):
        return "T" if v else "nil"
    if isinstance(v, int):
        return str(v)
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):
        raise AcadError(f"cannot pass {v!r} to AutoLISP")
    return repr(f)


def lpoint(p: Sequence[float]) -> str:
    vals = [float(x) for x in p]
    if len(vals) == 2:
        vals.append(0.0)
    if len(vals) != 3:
        raise AcadError("a point needs 2 or 3 numbers")
    return "(list " + " ".join(lnum(v) for v in vals) + ")"


class Raw(str):
    """Marker type: already-valid LISP source, inserted verbatim."""


def raw(expr: str) -> Raw:
    return Raw(expr)


def lval(v: Any) -> str:
    """Convert a Python value to an AutoLISP expression."""
    if isinstance(v, Raw):
        return str(v)
    if v is None:
        return "nil"
    if v is PAUSE:
        return "PAUSE"
    if isinstance(v, bool):
        return "T" if v else "nil"
    if isinstance(v, (int, float)):
        return lnum(v)
    if isinstance(v, str):
        return lstr(v)
    if isinstance(v, dict):
        items = " ".join(f"(cons {lstr(str(k))} {lval(val)})" for k, val in v.items())
        return f"(list {items})"
    if isinstance(v, (list, tuple)):
        numeric = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
        if v and numeric and len(v) in (2, 3):
            return lpoint(v)  # type: ignore[arg-type]
        return "(list " + " ".join(lval(x) for x in v) + ")"
    raise AcadError(f"cannot convert {type(v).__name__} to AutoLISP")


def command(*args: Any) -> Raw:
    """Build ``(command ...)``.

    ``command("_.CIRCLE", (0, 0), 50)`` -> ``(command "_.CIRCLE" (list 0.0 0.0 0.0) 50.0)``
    Use ``""`` for an Enter and :data:`PAUSE` to hand control to the user.
    """
    return Raw("(command " + " ".join(lval(a) for a in args) + ")")


def progn(*exprs: Any) -> Raw:
    return Raw("(progn " + " ".join(lval(e) for e in exprs) + ")")


def ss_from(handles: Iterable[str]) -> Raw:
    """A pickset built from drawing handles, usable as a (command ...) argument."""
    items = " ".join(lstr(h) for h in handles)
    return Raw(f"(acadmcp:ss (list {items}))")


def entity(handle: str) -> Raw:
    """The entity name (ename) for a handle, for use inside LISP."""
    return Raw(f"(handent {lstr(handle)})")


# ---------------------------------------------------------------------------
# minifying the support library so it streams in fewer round trips
# ---------------------------------------------------------------------------


def minify(text: str) -> str:
    """Strip LISP comments and redundant whitespace, leaving strings intact."""
    out: list[str] = []
    in_str = esc = in_cmt = False
    for ch in text:
        if in_cmt:
            if ch == "\n":
                in_cmt = False
                if out and out[-1] not in " (":
                    out.append(" ")
            continue
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            continue
        if ch == ";":
            in_cmt = True
            continue
        if ch in " \t\r\n":
            if out and out[-1] not in " (":
                out.append(" ")
            continue
        if ch == ")" and out and out[-1] == " ":
            out.pop()
        out.append(ch)
    return "".join(out).strip()


_lib_cache: str | None = None


def library_source() -> str:
    global _lib_cache
    if _lib_cache is None:
        _lib_cache = "(progn " + minify(LIB_SOURCE.read_text(encoding="utf-8")) + " (princ))"
    return _lib_cache


# ---------------------------------------------------------------------------
# where AutoCAD lets us put files
# ---------------------------------------------------------------------------


def temp_dir(doc: Any) -> Path:
    """AutoCAD's own temp folder - the one place LISP file I/O reliably works."""
    try:
        raw_path = str(com.retry(lambda: doc.GetVariable("TEMPPREFIX"), timeout=20))
    except Exception:  # noqa: BLE001
        raw_path = ""
    raw_path = raw_path.rstrip("\\/") or os.environ.get("TEMP", "C:/Windows/Temp")
    p = Path(raw_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _doc_key(doc: Any) -> str:
    name = str(com.quiet(lambda: doc.Name, "?"))
    path = str(com.quiet(lambda: doc.Path, ""))
    return f"{path}|{name}"


# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------


def _send(doc: Any, text: str) -> None:
    """Post one short chunk of command-line input.

    A balanced LISP expression is submitted by the trailing terminator, so we
    append a single space rather than a newline: a newline behaves as Enter and,
    for input AutoCAD has already consumed, would repeat the previous command.
    """
    if len(text) > MAX_SEND + 120:
        raise AcadError(
            f"internal: refusing to SendCommand {len(text)} characters - "
            "long source must be streamed"
        )
    if not text.endswith(("\n", " ")):
        text += " " if text.rstrip().endswith(")") else "\n"
    com.retry(lambda: doc.SendCommand(text), context="SendCommand", rescue_after=20)


def _stream(doc: Any, source: str) -> None:
    """Build source in a LISP string across several short sends, then eval it."""
    _send(doc, '(setq acadmcp:src "") ')
    for i in range(0, len(source), SLICE):
        piece = source[i : i + SLICE].replace("\\", "\\\\").replace('"', '\\"')
        _send(doc, f'(setq acadmcp:src (strcat acadmcp:src "{piece}")) ')
    _send(doc, "(eval (read acadmcp:src)) ")
    _send(doc, "(setq acadmcp:src nil) ")


def _run_source(doc: Any, source: str) -> None:
    if len(source) <= MAX_SEND:
        _send(doc, source + " ")
    else:
        _stream(doc, source)


def cancel(doc: Any | None = None, force_ui: bool = True) -> bool:
    """Get AutoCAD back to a clean prompt. True if it is responsive afterwards."""

    def work() -> bool:
        try:
            d = doc if doc is not None else com.active_doc()
            com.retry(lambda: d.SendCommand("\x03\x03"), timeout=5)
            time.sleep(0.4)
            if int(com.retry(lambda: d.GetVariable("CMDACTIVE"), timeout=5)) == 0:
                return True
        except Exception:  # noqa: BLE001 - we are already in trouble
            pass
        if force_ui:
            winui.press_escape()
        return com.ensure_responsive()

    return com.run_com(work, timeout=90)


# ---------------------------------------------------------------------------
# running a job
# ---------------------------------------------------------------------------


NOLIB = "ACADMCP-NOLIB"


def _read_result(path: Path) -> Any:
    for _ in range(60):
        try:
            text = path.read_text(encoding="ascii", errors="replace").strip()
        except OSError:
            time.sleep(0.02)
            continue
        if text.endswith("}"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        time.sleep(0.02)
    raise LispError(f"the AutoLISP job wrote an unreadable result file ({path})")


def _job_source(out: Path, body: str, quiet: bool) -> str:
    """Run the job, or report NOLIB if the support library is not loaded yet."""
    out_lit = lstr(_posix(out))
    fail = (
        f'(progn (setq zf (open {out_lit} "w"))'
        f'(princ "{{\\"ok\\":false,\\"error\\":\\"{NOLIB}\\"}}" zf)(close zf)(princ))'
    )
    run = f"(acadmcp:job {out_lit} '(lambda () {body}) {'T' if quiet else 'nil'})"
    return f"(if (null acadmcp:version) {fail} {run})"


def _wait(path: Path, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if path.exists():
            return True
        time.sleep(0.03)
    return False


def _settle(doc: Any, seconds: float = 8.0) -> None:
    """Wait for AutoCAD to finish tidying up after a command.

    The result file appears the moment our LISP writes it, but AutoCAD may
    still be closing the command down for a few hundred milliseconds, during
    which every COM call is rejected. Absorbing that here means the next tool
    call does not fail for no good reason.
    """
    try:
        com.retry(
            lambda: doc.GetVariable("CMDACTIVE"),
            timeout=seconds,
            context="waiting for AutoCAD",
        )
    except Exception:  # noqa: BLE001 - best effort only
        pass


def evaluate(
    expr: Any,
    *,
    doc: Any = None,
    quiet: bool = True,
    timeout: float | None = None,
) -> Any:
    """Evaluate a LISP expression in the drawing and return its value."""
    body = expr if isinstance(expr, str) and not isinstance(expr, Raw) else lval(expr)
    limit = DEFAULT_TIMEOUT if timeout is None else float(timeout)

    def work() -> Any:
        d = doc if doc is not None else com.active_doc()

        # Only switch drawings when we were handed a different one.  Never
        # compare COM wrappers with `is`: late binding returns a fresh Python
        # object each time, so that always mismatches and the needless
        # Activate() blocks and stalls AutoCAD's input queue.
        if doc is not None:
            try:
                active = com.retry(
                    lambda: com.app().ActiveDocument, timeout=10, attr_is_busy=True
                )
                if str(active.Name) != str(d.Name) or str(
                    com.quiet(lambda: active.Path, "")
                ) != str(com.quiet(lambda: d.Path, "")):
                    com.retry(lambda: d.Activate(), timeout=20, context="switching drawing")
                    time.sleep(0.3)
            except Exception:  # noqa: BLE001
                pass

        # A command waiting for input swallows whatever we send next.
        try:
            if int(com.retry(lambda: d.GetVariable("CMDACTIVE"), timeout=10)) != 0:
                cancel(d)
        except Exception:  # noqa: BLE001
            cancel(d)

        tmp = temp_dir(d)
        key = _doc_key(d)

        def attempt(seconds: float) -> Any:
            out = tmp / f"acadmcp_out_{uuid.uuid4().hex[:12]}.json"
            out.unlink(missing_ok=True)
            try:
                _run_source(d, _job_source(out, body, quiet))
                if not _wait(out, seconds):
                    cancel(d)
                    raise Busy(
                        f"AutoLISP did not return within {seconds:g}s. AutoCAD is "
                        "probably waiting for input - check its command line."
                    )
                return _read_result(out)
            finally:
                out.unlink(missing_ok=True)

        with _lock:
            known = key in _lib_ready
        if not known:
            _load_library(d, tmp, key)

        payload = attempt(limit)

        if not payload.get("ok") and payload.get("error") == NOLIB:
            # drawing was closed and reopened, or this is a different namespace
            with _lock:
                _lib_ready.discard(key)
            _load_library(d, tmp, key)
            payload = attempt(limit)

        _settle(d)

        if not payload.get("ok"):
            raise LispError(str(payload.get("error") or "AutoLISP reported an error"))
        return payload.get("result")

    # keep the outer margin small: if a command sequence is wrong AutoCAD parks
    # at a prompt, and the sooner the watchdog presses Esc the better
    return com.run_com(work, timeout=(limit + 30))


def _load_library(doc: Any, tmp: Path, key: str) -> None:
    """Stream the support library into this drawing's LISP namespace."""
    _stream(doc, library_source())
    check = tmp / f"acadmcp_lib_{uuid.uuid4().hex[:8]}.txt"
    check.unlink(missing_ok=True)
    _send(
        doc,
        f'(progn (setq zf (open {lstr(_posix(check))} "w"))'
        '(princ (if acadmcp:version "1" "0") zf)(close zf)(princ)) ',
    )
    try:
        if not _wait(check, 15):
            raise LispError(
                "AutoCAD never answered after the AutoLISP support library was "
                "sent. Check its command line for an error or an open dialog."
            )
        if check.read_text(encoding="ascii", errors="replace").strip() != "1":
            raise LispError(
                "the AutoLISP support library did not define itself; the drawing "
                "may have rejected it"
            )
    finally:
        check.unlink(missing_ok=True)
    with _lock:
        _lib_ready.add(key)


def forget_library(doc: Any | None = None) -> None:
    """Drop the cached "library is loaded" flag (after reopening a drawing)."""
    with _lock:
        if doc is None:
            _lib_ready.clear()
        else:
            _lib_ready.discard(_doc_key(doc))


def run_command(
    *args: Any, doc: Any = None, quiet: bool = True, timeout: float | None = None
) -> Any:
    """Run one AutoCAD command, exactly as if typed."""
    return evaluate(command(*args), doc=doc, quiet=quiet, timeout=timeout)


def send_raw(text: str, doc: Any = None) -> None:
    """Fire a command string at AutoCAD without waiting for a result."""

    def work() -> None:
        d = doc if doc is not None else com.active_doc()
        for i in range(0, len(text), MAX_SEND):
            _send(d, text[i : i + MAX_SEND])

    com.run_com(work)
