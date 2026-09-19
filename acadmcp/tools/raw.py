"""The escape hatches.

Every other tool group is a convenience. These three are the guarantee: if it
can be typed at AutoCAD's command line or written in AutoLISP, it can be done
from here.
"""

from __future__ import annotations

from typing import Any

from .. import com, commands_db, lisp
from ..errors import AcadError
from ..registry import tool

PAUSE_TOKENS = {"\\", "pause", "PAUSE", "<pause>"}


def _arg(value: Any) -> Any:
    """Turn a JSON argument into something (command ...) understands."""
    if value is None:
        return ""                      # a bare Enter
    if isinstance(value, str):
        if value in PAUSE_TOKENS:
            return lisp.PAUSE
        return value
    if isinstance(value, bool):
        return "_Y" if value else "_N"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        nums = [v for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(nums) == len(value) and len(value) in (2, 3):
            return list(value)         # a point
        raise AcadError(
            f"{value!r} is not a valid command argument; use a number, a string, "
            "or a point like [100, 250]"
        )
    raise AcadError(f"cannot pass {type(value).__name__} to an AutoCAD command")


def _unpack(payload: Any) -> tuple[Any, list[str]]:
    if isinstance(payload, list) and len(payload) == 2 and isinstance(payload[1], list):
        return payload[0], [str(h) for h in payload[1] if h]
    return payload, []


@tool(description=(
    "Run any AutoCAD command exactly as if typed, with its arguments in order. "
    "This reaches everything COM cannot: TRIM, EXTEND, FILLET, CHAMFER, ARRAY, "
    "OVERKILL, MATCHPROP, Express Tools, custom commands. Use \"\" for Enter, a "
    "point as [x,y], and prefix names with _. for the English form (e.g. '_.FILLET'). "
    "Returns the handles of any entities the command created. "
    "Note: if the arguments do not match what the command expects, AutoCAD is "
    "left waiting at a prompt - the call times out, Esc is sent automatically, "
    "and acad_cancel clears anything left over. Avoid a trailing \"\" unless the "
    "command really does need a final Enter."
))
def cad_command(
    command: str,
    args: list[Any] | None = None,
    select_handles: list[str] | None = None,
    drawing: str | None = None,
    timeout: float = 120,
    suppress_dialogs: bool = True,
) -> dict[str, Any]:
    name = str(command).strip()
    if not name:
        raise AcadError("no command given")
    if not name.startswith(("_", ".", "-")):
        name = "_." + name.lstrip("_.")

    resolved: list[str] = []
    parts: list[Any] = [name]
    for a in args or []:
        if isinstance(a, str) and a.strip().lower() == "<selection>":
            if not select_handles:
                raise AcadError("<selection> used but no select_handles were given")
            parts.append(lisp.ss_from(select_handles))
            continue
        # Let a readable option name through: "tolerance" becomes "_O",
        # because AutoCAD wants the capital letters of "tOlerance". Getting
        # this wrong leaves the command waiting at a prompt.
        if isinstance(a, str) and a and not a.startswith(("_", "-")) and len(a) > 1:
            keyword = commands_db.option_keyword(name, a)
            if keyword:
                parts.append("_" + keyword)
                resolved.append(f"{a} -> _{keyword}")
                continue
        parts.append(_arg(a))
    if select_handles and not any(isinstance(p, lisp.Raw) for p in parts):
        # conventional place for a selection: straight after the command name
        parts.insert(1, lisp.ss_from(select_handles))
        parts.insert(2, "")

    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    payload = lisp.evaluate(
        lisp.raw(f"(acadmcp:capture '(lambda () {lisp.command(*parts)}))"),
        doc=doc,
        quiet=bool(suppress_dialogs),
        timeout=timeout,
    )
    value, created = _unpack(payload)
    out: dict[str, Any] = {"command": name, "created": created}
    if created:
        out["created_count"] = len(created)
    if value not in (None, ""):
        out["returned"] = value
    if resolved:
        out["option_keywords_resolved"] = resolved
    return out


@tool(description=(
    "Evaluate AutoLISP in the live drawing and return its value. The whole LISP "
    "API is available - entget/entmod/ssget, vla-* through vlax, tblsearch, "
    "(command ...), Express Tools. Handles come back as strings prefixed with #. "
    "Use this for anything the typed tools do not cover."
))
def cad_lisp(
    code: str,
    drawing: str | None = None,
    timeout: float = 120,
    report_created: bool = False,
    suppress_dialogs: bool = True,
) -> dict[str, Any]:
    source = str(code).strip()
    if not source:
        raise AcadError("no LISP code given")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None

    if report_created:
        payload = lisp.evaluate(
            lisp.raw(f"(acadmcp:capture '(lambda () {source}))"),
            doc=doc,
            quiet=bool(suppress_dialogs),
            timeout=timeout,
        )
        value, created = _unpack(payload)
        return {"result": value, "created": created}

    return {
        "result": lisp.evaluate(
            lisp.raw(source), doc=doc, quiet=bool(suppress_dialogs), timeout=timeout
        )
    }


@tool(description=(
    "Run several commands or LISP expressions in order, stopping at the first "
    "failure. Each step is {\"command\": name, \"args\": [...]} or {\"lisp\": code}. "
    "Use this to script a whole edit in one round trip."
))
def cad_script(
    steps: list[dict[str, Any]],
    drawing: str | None = None,
    timeout: float = 300,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    if not steps:
        raise AcadError("no steps given")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None

    results: list[dict[str, Any]] = []
    all_created: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise AcadError(f"step {index + 1} is not an object")
        try:
            if "lisp" in step:
                body = lisp.raw(str(step["lisp"]))
            elif "command" in step:
                parts: list[Any] = [str(step["command"])]
                if not parts[0].startswith(("_", ".", "-")):
                    parts[0] = "_." + parts[0].lstrip("_.")
                sel = step.get("select_handles")
                for a in step.get("args") or []:
                    if isinstance(a, str) and a.strip().lower() == "<selection>":
                        if not sel:
                            raise AcadError(
                                f"step {index + 1} uses <selection> but gives no handles"
                            )
                        parts.append(lisp.ss_from(sel))
                    else:
                        parts.append(_arg(a))
                body = lisp.command(*parts)
            else:
                raise AcadError(f"step {index + 1} needs either 'command' or 'lisp'")

            payload = lisp.evaluate(
                lisp.raw(f"(acadmcp:capture '(lambda () {body}))"),
                doc=doc,
                timeout=timeout,
            )
            value, created = _unpack(payload)
            all_created.extend(created)
            entry: dict[str, Any] = {"step": index + 1, "ok": True}
            if created:
                entry["created"] = created
            if value not in (None, ""):
                entry["returned"] = value
            results.append(entry)
        except Exception as exc:  # noqa: BLE001
            results.append({"step": index + 1, "ok": False, "error": str(exc)})
            if stop_on_error:
                break

    done = sum(1 for r in results if r.get("ok"))
    return {
        "completed": done,
        "of": len(steps),
        "created": all_created,
        "steps": results,
    }


@tool(description=(
    "Type text straight into AutoCAD's command line without waiting for a result. "
    "Last resort for interactive commands that need the user to click in the "
    "drawing; prefer cad_command, which reports what happened."
))
def cad_send(text: str, drawing: str | None = None) -> dict[str, Any]:
    if not str(text):
        raise AcadError("nothing to send")
    doc = com.run_com(lambda: com.find_doc(drawing), timeout=60) if drawing else None
    lisp.send_raw(str(text), doc=doc)
    return {
        "sent": str(text),
        "note": "AutoCAD may now be waiting for input; acad_status will show "
        "command_active, and acad_cancel clears it",
    }
