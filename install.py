"""Register (or unregister) the AutoCAD MCP server with the Claude desktop app.

Keeps a timestamped backup of the config and leaves every other setting alone.

    python install.py            # add / update
    python install.py --remove   # take it out again
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "autocad"
CONFIG = Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "run_server.py"


def load() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{CONFIG} is not valid JSON ({exc}); fix it first.")


def save(data: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG.exists():
        backup = CONFIG.with_suffix(f".json.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copyfile(CONFIG, backup)
        print(f"backed up existing config to {backup.name}")
    CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    remove = "--remove" in sys.argv
    config = load()
    servers = config.setdefault("mcpServers", {})

    if remove:
        if servers.pop(NAME, None) is None:
            print(f"{NAME} was not registered; nothing to do")
            return
        save(config)
        print(f"removed {NAME}; restart the Claude desktop app")
        return

    for path in (PYTHON, LAUNCHER):
        if not path.exists():
            raise SystemExit(f"missing {path} - run the install steps in README.md first")

    servers[NAME] = {
        "command": str(PYTHON),
        "args": ["-X", "utf8", str(LAUNCHER)],
        "env": {
            "PYTHONUTF8": "1",
            # how long one AutoLISP job may take before Esc is sent
            "ACADMCP_LISP_TIMEOUT": "120",
        },
    }
    save(config)
    print(f"registered '{NAME}':")
    print(json.dumps(servers[NAME], indent=2))
    print("\nRestart the Claude desktop app to pick it up.")


if __name__ == "__main__":
    main()
