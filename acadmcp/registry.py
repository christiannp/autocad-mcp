"""The MCP server object and the decorator every tool module uses."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, TypeVar

from mcp.server.mcpserver import MCPServer

from .errors import AcadError, Busy

F = TypeVar("F", bound=Callable[..., Any])

INSTRUCTIONS = """\
Drives a running AutoCAD on this PC. Two engines work together:

* COM creates and edits entities as objects.
* AutoLISP runs real AutoCAD commands, so anything that exists only on the
  command line (TRIM, FILLET, ARRAY, HATCH by internal point, PURGE, Express
  Tools) is available too. `cad_command` and `cad_lisp` are the escape hatches
  for anything without a dedicated tool - if it can be done by hand in AutoCAD,
  it can be done through them.

Conventions:
* Entities are identified by their drawing **handle** (a short hex string like
  "2F1"). Handles survive saving and reopening; they are what every tool
  returns and accepts.
* Points are [x, y] or [x, y, z] in the drawing's own units.
* Angles are in **degrees** everywhere in this API (AutoCAD stores radians).
* `space` selects model or paper space; "auto" follows what is on screen.
* Nothing is saved unless you call doc_save. Prefer reading the drawing
  (entity_list, drawing_info) before changing it.
"""

mcp: MCPServer = MCPServer(
    name="autocad",
    title="AutoCAD",
    version="0.1.0",
    instructions=INSTRUCTIONS,
)


def _clean(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _begin_undo_group(drawing: Any) -> Any:
    """Open an undo group on the drawing a tool is about to change.

    AutoCAD lumps every COM edit made between two commands into one undo
    step, so without this "undo the last thing" after five COM-based tool
    calls would undo all five. StartUndoMark/EndUndoMark around each call
    makes one tool call one undo step - verified against AutoCAD 2025,
    nesting included. Returns the document the group was opened on, or None.
    """
    from . import com

    def work() -> Any:
        doc = com.find_doc(drawing) if drawing else com.active_doc()
        doc.StartUndoMark()
        return doc

    try:
        return com.run_com(work, timeout=20)
    except Exception:  # noqa: BLE001 - no drawing, or AutoCAD busy: no group
        return None


def _end_undo_group(doc: Any) -> None:
    from . import com

    try:
        com.run_com(lambda: doc.EndUndoMark(), timeout=20)
    except Exception:  # noqa: BLE001
        pass


def tool(
    *dargs: Any,
    readonly: bool = False,
    undo_group: bool | None = None,
    **dkwargs: Any,
) -> Callable[[F], F]:
    """Register a tool, turning internal failures into readable messages.

    ``readonly=True`` marks a tool that only inspects the drawing. Those are
    safe to run again, so if AutoCAD happens to be busy for a moment (it often
    is right after a command finishes) we wake it and retry once instead of
    failing. Tools that change the drawing are never retried automatically.

    ``undo_group`` wraps the call in its own undo step (default for every tool
    that is not readonly). Pass False for tools that never change the drawing
    (plotting, screenshots, opening files) - an empty group would still cost
    the user a press of Ctrl+Z.
    """
    grouped = (not readonly) if undo_group is None else bool(undo_group)

    def decorate(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            raise TypeError("AutoCAD tools are synchronous")

        def call(*args: Any, **kwargs: Any) -> Any:
            doc = _begin_undo_group(kwargs.get("drawing")) if grouped else None
            try:
                return fn(*args, **kwargs)
            finally:
                if doc is not None:
                    _end_undo_group(doc)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return call(*args, **kwargs)
            except Busy:
                if not readonly:
                    raise
            except AcadError as exc:
                raise ValueError(_clean(exc)) from None
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"{fn.__name__} failed: {_clean(exc)}") from None

            from . import com

            com.ensure_responsive()
            try:
                return call(*args, **kwargs)
            except AcadError as exc:
                raise ValueError(_clean(exc)) from None
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"{fn.__name__} failed: {_clean(exc)}") from None

        mcp.tool(*dargs, **dkwargs)(wrapper)
        return fn  # keep the undecorated function importable for tests

    return decorate
