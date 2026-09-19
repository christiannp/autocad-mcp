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


def tool(*dargs: Any, readonly: bool = False, **dkwargs: Any) -> Callable[[F], F]:
    """Register a tool, turning internal failures into readable messages.

    ``readonly=True`` marks a tool that only inspects the drawing. Those are
    safe to run again, so if AutoCAD happens to be busy for a moment (it often
    is right after a command finishes) we wake it and retry once instead of
    failing. Tools that change the drawing are never retried automatically.
    """

    def decorate(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            raise TypeError("AutoCAD tools are synchronous")

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
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
                return fn(*args, **kwargs)
            except AcadError as exc:
                raise ValueError(_clean(exc)) from None
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"{fn.__name__} failed: {_clean(exc)}") from None

        mcp.tool(*dargs, **dkwargs)(wrapper)
        return fn  # keep the undecorated function importable for tests

    return decorate
