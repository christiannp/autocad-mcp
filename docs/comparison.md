# Compared with Autodesk's official MCP server

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
