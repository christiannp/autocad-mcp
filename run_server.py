"""Launcher for the AutoCAD MCP server.

Claude starts the server with an absolute path to this file, so it must not
depend on the working directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acadmcp.server import main  # noqa: E402

if __name__ == "__main__":
    main()
