# AutoCAD MCP

Lets Claude drive the AutoCAD running on this PC — draw, edit, annotate,
dimension, lay out sheets, plot, extract data, batch-process folders of
drawings — and **look at the result**, because a drawing has to be checked by
eye, not just by entity count.

The design goal was simple: **if it can be done by hand in AutoCAD, it can be
done through this server.** 121 tools, plus a verified registry of every
command the AutoCAD UI can reach.

- **Draws and edits**, not just reads: geometry, blocks, dimensions, tables, layouts, plots and PDFs
- **Sees the drawing**: `screenshot` and `render` hand Claude an image to check
- **One undo step per tool call**
- **Batch** the same recipe across a folder of drawings
- **99.8% of AutoCAD's UI commands** in a verified registry; anything without a tool is one `cad_command` away

Built for an architect laying out solar PV on large buildings.
[How it compares with Autodesk's official MCP server](docs/comparison.md).

## Quick start

Windows, with desktop AutoCAD installed (built and tested against AutoCAD 2025
and Python 3.14). **Quit the Claude desktop app first**, then:

```powershell
cd <wherever you cloned this>
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp[cli]" pywin32 ezdxf openpyxl pillow
.\.venv\Scripts\python.exe install.py
```

Start Claude again. If Claude is the MSIX build, or the config entry
disappears, see [Install](docs/install.md).

## Documentation

| | |
|---|---|
| [Install](docs/install.md) | Registration, MSIX installs, the `.mcpb` desktop extension, setting it up on another machine |
| [Tools](docs/tools.md) | How it works, every tool by group, seeing the drawing, undo, tips, troubleshooting |
| [Command registry](docs/command-registry.md) | The 918-command registry, `command_search` / `command_help`, how it was built |
| [Design notes](docs/design-notes.md) | AutoCAD 2025 behaviours found the hard way; read before changing the bridge |
| [Comparison](docs/comparison.md) | Feature by feature against Autodesk's official AutoCAD MCP server |
| [Tests](docs/testing.md) | The live test suites and the diagnostic scripts |
| [Handover](HANDOVER.md) | Current state, open items, and rules for working on the dev machine |
