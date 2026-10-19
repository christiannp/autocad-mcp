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

## Compared with Autodesk's official MCP server

Autodesk ships its own
[AutoCAD and Civil 3D MCP Server](https://help.autodesk.com/view/ADSKMCP/ENU/?guid=ADSKMCP_AutoCADCivil3DMcp_autodesk_autocad_civil_3d_mcp_html).
As of October 2026:

| | **This server** | **Autodesk official** |
|---|---|---|
| AI client | Claude Desktop, Cowork, any MCP client | Autodesk Assistant only |
| AutoCAD version | 2025, verified live | 2027 (ships with it) |
| Status | 121 tools, test suites green | Public beta (Tech Preview), maintained by Autodesk |
| Setup | `install.py`, plus MSIX config gotchas | Nothing, built in |
| Query & stats | `drawing_info`, `entity_select`, `measure` | ✅ Cleaner: schema discovery + query + aggregate |
| Template compliance check | ❌ No dedicated tool | ✅ `checkAutoCADObjects` |
| Draw new geometry | ✅ ~15 draw tools | ❌ |
| Modify geometry | ✅ ~27 modify tools | ❌ (Civil 3D only) |
| Layers | ✅ Full | ⚠️ Partial since Sep 2026 |
| Blocks, attributes, dims, tables | ✅ Create & edit (tables from Excel too) | Read only |
| Layouts, plot, PDF | ✅ | ❌ |
| Batch across many files | ✅ `batch_process`, `batch_headless` | ❌ Active drawing only |
| Export to Excel | ✅ `data_extract` → .xlsx | Not documented |
| AI sees the drawing | ✅ `screenshot` / `render` return images | Zooms and selects on screen |
| Raw command / LISP | ✅ Powerful, but risky | ❌ Safer by design |
| Undo | ✅ One undo step per tool call | n/a |
| Solar PV tools | ⏳ Planned | ❌ |

This server was built for an architect who lays out solar PV on large
buildings, working in AutoCAD 2025 on Windows through her own Claude. Most of
her time goes into drawing from tables and specs, making the same edits
across many drawings, and pulling data out for reports. Autodesk's server
only covers the last of those: it cannot draw or edit geometry in plain
AutoCAD, works on one open drawing at a time, needs AutoCAD 2027 and talks
only to Autodesk Assistant. This server covers all three today, with
solar-specific tools to follow; Autodesk's remains useful as a read-only
checker (block counts, template compliance) if she moves to 2027.

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
| [Tests](docs/testing.md) | The live test suites and the diagnostic scripts |
| [Handover](HANDOVER.md) | Current state, open items, and rules for working on the dev machine |
