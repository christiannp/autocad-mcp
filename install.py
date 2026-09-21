"""Register the AutoCAD MCP server with the Claude desktop app.

Two ways, because the first one has proved fragile:

    python install.py --mcpb     # build dist\\autocad-mcp.mcpb, then double-click it
    python install.py            # write mcpServers.autocad into claude_desktop_config.json
    python install.py --remove   # take the config entry out again

The desktop app rewrites claude_desktop_config.json for its own settings and
has been seen to drop the whole ``mcpServers`` key while doing so (twice on one
machine). An extension bundle (.mcpb) is registered through the app's own
installer and survives those rewrites, so that is the recommended route:
build it once, double-click it, approve the install. The bundle is a thin
launcher pointing at this clone's venv and code, so ``git pull`` updates the
server without reinstalling.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "autocad"
CONFIG = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "run_server.py"
DIST = ROOT / "dist"

ENV = {
    "PYTHONUTF8": "1",
    # how long one AutoLISP job may take before Esc is sent
    "ACADMCP_LISP_TIMEOUT": "120",
}


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


def check_files() -> None:
    for path in (PYTHON, LAUNCHER):
        if not path.exists():
            raise SystemExit(f"missing {path} - run the install steps in README.md first")


def tool_list() -> list[dict[str, str]]:
    """The registered tools, for the manifest (the app shows them before install)."""
    sys.path.insert(0, str(ROOT))
    try:
        import asyncio

        from acadmcp.registry import mcp
        from acadmcp.server import load_tools

        load_tools()
        tools = asyncio.run(mcp.list_tools())
        return [
            {"name": t.name, "description": (t.description or "").split(". ")[0][:200]}
            for t in sorted(tools, key=lambda x: x.name)
        ]
    except Exception as exc:  # noqa: BLE001 - the manifest is fine without them
        print(f"(could not list tools for the manifest: {exc})")
        return []


def build_mcpb() -> Path:
    """Build a thin extension bundle that launches this clone's server."""
    check_files()
    DIST.mkdir(exist_ok=True)
    bundle = DIST / "autocad-mcp.mcpb"

    shim = (
        '"""Launcher written by install.py - starts the AutoCAD MCP server from its clone."""\n'
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from acadmcp.server import main\n"
        "main()\n"
    )
    manifest = {
        "manifest_version": "0.3",
        "name": "autocad-mcp",
        "display_name": "AutoCAD",
        "version": "0.2.0",
        "description": "Drive the AutoCAD running on this PC: draw, edit, annotate, plot, extract data, and look at the result.",
        "long_description": (
            "Lets Claude work in the AutoCAD open on this computer through COM and "
            "AutoLISP - every command the UI can reach, plus dedicated tools for "
            "drawing, editing, annotation, layers, blocks, sheets, plotting, data "
            "extraction, batch processing, and pictures of the drawing so results "
            "can be checked visually. Installed from the local clone at "
            f"{ROOT}."
        ),
        "author": {"name": "autocad-mcp"},
        "repository": {"type": "git", "url": "https://github.com/christiannp/autocad-mcp"},
        "server": {
            "type": "python",
            "entry_point": "run_server.py",
            "mcp_config": {
                "command": str(PYTHON),
                "args": ["-X", "utf8", "${__dirname}/run_server.py"],
                "env": dict(ENV),
            },
        },
        "tools": tool_list(),
        "keywords": ["autocad", "cad", "drafting", "dwg", "architecture", "solar"],
        "compatibility": {"platforms": ["win32"]},
    }
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("run_server.py", shim)
        readme = ROOT / "README.md"
        if readme.exists():
            zf.write(readme, "README.md")
    print(f"built {bundle}")
    print(
        "\nDouble-click it (or use Settings > Extensions > Advanced > Install "
        "Extension in the Claude desktop app) and approve the install. The "
        "server starts from this folder, so 'git pull' is all an update needs."
    )
    return bundle


def main() -> None:
    if "--mcpb" in sys.argv:
        build_mcpb()
        return

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

    check_files()
    servers[NAME] = {
        "command": str(PYTHON),
        "args": ["-X", "utf8", str(LAUNCHER)],
        "env": dict(ENV),
    }
    save(config)
    print(f"registered '{NAME}':")
    print(json.dumps(servers[NAME], indent=2))
    print(
        "\nRestart the Claude desktop app to pick it up. If the entry disappears "
        "again later, build the extension bundle instead: python install.py --mcpb"
    )


if __name__ == "__main__":
    main()
