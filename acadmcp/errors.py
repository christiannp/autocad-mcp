"""Error types and COM error translation for the AutoCAD MCP server."""

from __future__ import annotations

import pywintypes


class AcadError(RuntimeError):
    """Any failure talking to, or driving, AutoCAD.

    These are surfaced to the MCP client as readable text rather than
    Python tracebacks, so the message must be self-explanatory.
    """


class NotConnected(AcadError):
    """AutoCAD is not running / not reachable over COM."""


class NoDocument(AcadError):
    """An operation needed an open drawing and there wasn't one."""


class NotFound(AcadError):
    """A handle, layer, block, layout, ... did not resolve."""


class Busy(AcadError):
    """AutoCAD stayed busy (modal dialog or active command) past the timeout."""


class LispError(AcadError):
    """An AutoLISP job reported an error or timed out."""


# --- COM HRESULTs we care about -------------------------------------------

RPC_E_CALL_REJECTED = -2147418111        # 0x80010001 - "Call was rejected by callee"
RPC_E_SERVERCALL_RETRYLATER = -2147417846  # 0x8001010A - "application is busy"
RPC_E_DISCONNECTED = -2147417848         # 0x80010108
CO_E_OBJNOTCONNECTED = -2147220995       # 0x800401FD
MK_E_UNAVAILABLE = -2147221021           # 0x800401E3 - not in running object table

RETRYABLE = {RPC_E_CALL_REJECTED, RPC_E_SERVERCALL_RETRYLATER}
DEAD = {RPC_E_DISCONNECTED, CO_E_OBJNOTCONNECTED}


def hresult(exc: BaseException) -> int | None:
    """Best-effort extraction of the HRESULT from a pywin32 com_error."""
    if not isinstance(exc, pywintypes.com_error):
        return None
    try:
        return int(exc.args[0])
    except Exception:
        return None


def describe(exc: BaseException) -> str:
    """Turn a com_error into something a human (or Claude) can act on."""
    if not isinstance(exc, pywintypes.com_error):
        return str(exc)
    args = list(exc.args) + [None] * (4 - len(exc.args))
    hr, msg, excepinfo, argerr = args[:4]
    detail = ""
    if isinstance(excepinfo, (tuple, list)) and len(excepinfo) >= 3:
        # excepinfo = (wCode, source, description, helpfile, helpctx, scode)
        source = excepinfo[1] or ""
        description = excepinfo[2] or ""
        detail = " - ".join(p for p in (source, description) if p)
    parts = [p for p in (msg, detail) if p]
    text = "; ".join(parts) or "unknown COM failure"
    try:
        return f"{text} (HRESULT 0x{int(hr) & 0xFFFFFFFF:08X})"
    except Exception:
        return text


def wrap(exc: BaseException, context: str = "") -> AcadError:
    """Convert any exception into the right AcadError subclass."""
    if isinstance(exc, AcadError):
        return exc
    hr = hresult(exc)
    text = describe(exc)
    if context:
        text = f"{context}: {text}"
    if hr in RETRYABLE:
        return Busy(
            text
            + "  AutoCAD is busy - it usually means a command is still running or a"
            " dialog is open on screen. Close the dialog or press Esc in AutoCAD."
        )
    if hr in DEAD or hr == MK_E_UNAVAILABLE:
        return NotConnected(text + "  The AutoCAD connection was lost.")
    return AcadError(text)
