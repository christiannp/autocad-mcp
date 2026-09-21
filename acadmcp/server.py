"""Entry point: import every tool group, then serve over stdio."""

from __future__ import annotations

import importlib
import sys

from .registry import mcp

TOOL_MODULES = [
    "session",
    "raw",
    "commands",
    "draw",
    "modify",
    "select",
    "layers",
    "blocks",
    "annotate",
    "layout",
    "query",
    "vision",
    "batch",
]


def load_tools() -> list[str]:
    loaded = []
    for name in TOOL_MODULES:
        try:
            importlib.import_module(f".tools.{name}", package="acadmcp")
            loaded.append(name)
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.endswith(f"tools.{name}"):
                continue  # not written yet
            raise
    return loaded


def main() -> None:
    load_tools()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    sys.exit(main())
