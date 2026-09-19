"""Load every tool module and print the registered tool surface."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp.registry import mcp  # noqa: E402
from acadmcp.server import load_tools  # noqa: E402

print("modules loaded:", ", ".join(load_tools()))
tools = asyncio.run(mcp.list_tools())
print("TOTAL TOOLS:", len(tools))
print()
for t in sorted(tools, key=lambda x: x.name):
    desc = (t.description or "").replace("\n", " ")
    schema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
    params = list(schema.get("properties", {}))
    print(f"  {t.name:22s} ({len(params):2d} args)  {desc[:88]}")
