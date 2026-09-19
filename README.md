# AutoCAD MCP

Lets Claude drive the AutoCAD running on this PC — draw, edit, annotate,
dimension, lay out sheets, plot, extract data, and batch-process folders of
drawings.

The design goal was simple: **if it can be done by hand in AutoCAD, it can be
done through this server.**

---

## How it works

Two engines, used together:

| Engine | Used for | Why |
|---|---|---|
| **COM** (ActiveX) | creating and editing entities as objects | fast, precise, gives every object a stable handle |
| **AutoLISP** | real AutoCAD commands | TRIM, FILLET, ARRAY, HATCH-by-point, PURGE, OVERKILL, LAYMRG and Express Tools **do not exist** in the COM API |

On top of both sits a set of escape hatches — `cad_command`, `cad_lisp`,
`cad_script`, `cad_send` — so anything without a dedicated tool is still one
call away.

Entities are identified by their **drawing handle** (a short hex string like
`2F1`). Handles survive saving and reopening, so they are what every tool
accepts and returns. Angles are in **degrees** everywhere, points are
`[x, y]` or `[x, y, z]` in the drawing's own units.

---

## Install

Already done on this machine, but for the record:

```powershell
cd "C:\Users\Wanda\Documents\AI Companion\autocad-mcp"
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp[cli]" pywin32 ezdxf openpyxl pillow
```

Registered with Claude in `%APPDATA%\Claude\claude_desktop_config.json`:

```json
"mcpServers": {
  "autocad": {
    "command": "C:\\Users\\Wanda\\Documents\\AI Companion\\autocad-mcp\\.venv\\Scripts\\python.exe",
    "args": ["-X", "utf8", "C:\\Users\\Wanda\\Documents\\AI Companion\\autocad-mcp\\run_server.py"]
  }
}
```

AutoCAD must be running. If it is not, the first call starts it.

---

## The tools

**Session** `acad_status` `acad_cancel` `doc_list` `doc_new` `doc_open`
`doc_save` `doc_close` `doc_activate` `sysvar` `zoom` `regen` `purge`

**Escape hatches** `cad_command` `cad_lisp` `cad_script` `cad_send`

**Command reference** `command_search` `command_help`

**Draw** `draw_line` `draw_polyline` `draw_rectangle` `draw_circle` `draw_arc`
`draw_ellipse` `draw_spline` `draw_point` `draw_hatch` `draw_construction_line`

**Modify** `entity_move` `entity_copy` `entity_rotate` `entity_scale`
`entity_mirror` `entity_offset` `entity_array` `entity_delete` `entity_trim`
`entity_extend` `entity_fillet` `entity_chamfer` `entity_join` `entity_explode`
`entity_break` `entity_overkill` `entity_properties` `match_properties`

**Find & measure** `entity_select` `entity_info` `entity_summary` `measure`

**Layers & styles** `layer_list` `layer_set` `layer_state` `layer_delete`
`layer_rename` `layer_merge` `linetype` `text_style` `dim_style`

**Blocks & xrefs** `block_list` `block_define` `block_insert`
`block_attributes` `block_edit` `block_export` `xref`

**Annotation** `draw_text` `draw_mtext` `draw_dimension` `draw_leader`
`draw_table` `text_edit` `text_find_replace`

**Sheets & output** `layout_list` `layout_manage` `page_setup` `plot_devices`
`viewport_create` `viewport_manage` `plot` `export`

**Data & vision** `drawing_info` `data_extract` `screenshot`

**Batch** `batch_preview` `batch_process` `batch_headless`

---

## Command coverage

Every command the AutoCAD interface can reach is in `docs/commands.json`,
built by reading this machine's own CUIX files and then running the commands.

| | |
|---|---|
| Commands the UI exposes | **918** |
| Verified by running them, prompts captured | **473** |
| Documented from AutoCAD's own UI definition | **443** |
| Neither | **2** |
| **Covered** | **99.8%** |
| Reachable through `cad_command` | all of them |

Of the verified set, **181 carry their option keywords**, extracted from the
prompt text rather than guessed.

Ask the registry before driving an unfamiliar command:

```
command_search("duplicate")   -> OVERKILL, "Cleans up overlapping geometry..."
command_help("TRIM")          -> prompts, options {mOde: O}, default, its tool
command_help("-LAYER")        -> 21 options incl. TRansparency: TR, stAte: A
```

`cad_command` consults it too, so a readable option name works:
`cad_command("-OVERKILL", [..., "tolerance", 0.5])` sends `_O` by itself.

### How the registry was built

1. **Inventory** — every macro in `acad.cuix` and the other CUIX files, plus
   `acad.pgp` aliases, plus the hyphen twin of every command. AutoCAD states
   the command behind each button in a `<CLICommand>` element, which is more
   reliable than parsing macro syntax; missing it initially cost 245 commands,
   including REVCLOUD, whose macro reads `^C^C_^Rrevcloud`.
2. **Probe** — 1,854 candidates run through `accoreconsole`, in batches, on one
   script line. A pending command swallows the *next* line of a `.scr`, so a
   line-per-command script dies at the first prompt; a single `foreach` keeps
   control inside LISP. `(command "X")` starts a command and returns, and a
   bare `(command)` cancels it, so the sweep never gets stuck.
3. **Options** — parsed from the real prompt text. `[Ignore/tOlerance/Done]`
   means the keyword is the capital letters: `tOlerance` is `O`, not `T`.
4. **Descriptions** — the `<HelpString>` AutoCAD shows in its own status bar.

`build/` holds the scripts; re-run them after an AutoCAD update.

## Things worth knowing

**Nothing is saved unless you ask.** Every edit is live in the open drawing;
`doc_save` writes it to disk. Closing discards changes by default.

**Start with `drawing_info`** on a drawing you do not know. One call gives
entity counts by type and layer, every layer with its settings, blocks, xrefs,
layouts, units and extents.

**`entity_select` speaks AutoCAD wildcards.** `layer="A-ROOF*"` matches the
family; `type="INSERT"` plus `block="PV-*"` finds panel placements.

**`screenshot` lets Claude look at the drawing** — useful for checking a layout
before plotting, or confirming an edit landed where it should.

**`data_extract` replaces the Data Extraction wizard.** Point it at a block and
it writes one row per insert, one column per attribute, straight to .xlsx.

**Batch: preview, then one, then all.** `batch_preview` lists what would be
touched. Run `batch_process` with `limit=1` to check the recipe on a single
file. Use `output_folder` to write copies and leave the originals alone.
`batch_headless` uses accoreconsole — no window, much faster, commands only.

---

## Design notes (the non-obvious bits)

These were all found the hard way against AutoCAD 2025, and each one would
otherwise be a recurring mystery.

**`SECURELOAD` blocks loading LISP files.** With the default `SECURELOAD=1`,
`(load "...")` throws a modal *"Security - Unsigned Executable File"* dialog,
which freezes the whole application — every COM call then fails with
`RPC_E_CALL_REJECTED` and only a real click clears it. So this server **never
loads a file**: LISP source is streamed into the command line in <500 byte
slices and evaluated with `(eval (read ...))`. No prompt, and no changes to
the user's security settings.

**Long `SendCommand` strings wedge AutoCAD.** Roughly 2.4 kB was enough to park
it at a prompt. Everything is capped at 700 characters and sliced.

**AutoLISP is dynamically scoped.** The caller's expression runs inside the
bridge's own variable bindings, so a plain `(setq out ...)` in a tool's LISP
would overwrite the bridge's `out` — and the bridge would then try to open a
list as a filename. Every local in `lisp/acadmcp.lsp` is prefixed `amx-`, and
generated LISP uses `amq-` names.

**A blocked COM call cannot be interrupted from the COM thread.**
`SendCommand` does not return while AutoCAD sits at a prompt, so retry loops on
that thread are useless. The worker owns one apartment; when a call overruns,
the *calling* thread sends a real Esc keystroke (`winui.press_escape`) to
release it.

**Late binding sometimes returns unreadable objects.** `Documents.Add`,
`Documents.Open` and `Layouts.Add` can hand back an object whose properties
raise `AttributeError`. Everything re-fetches the result by name instead.

**Hatch boundaries must be `VT_DISPATCH` arrays.** A Python list, a tuple, or a
`VT_VARIANT` array all fail with *"Invalid object array"*.

**TRIM and EXTEND default to Quick mode** in AutoCAD 2021+, which never asks
for cutting edges. Both force `TRIMEXTENDMODE=1` for the call, then restore it,
and send exactly two Enters — a third would land at the Command prompt and
re-run the command.

**Hatching by internal point only sees what is on screen**, so `draw_hatch`
zooms to extents first. Picking a point that lies exactly *on* a boundary finds
no region.

**`AcSaveAsType` values**, verified by saving and reading the version stamp
back: 2018 `64`/dxf `65`, 2013 `60`/`61`, 2010 `48`/`49`, 2007 `36`/`37`,
2004 `24`/`25`, 2000 `12`/`13`, R14 `8`, DXF R12 `1`. The file extension must
match the format or AutoCAD refuses outright.

**`SetLayoutsToPlot` needs a `VT_BSTR` array**, and `BACKGROUNDPLOT` is set to
0 during plotting so the PDF exists by the time the call returns.

**Never send keystrokes without checking what has focus.** An early version of
the command prober typed command names with `SendInput` after focusing AutoCAD
once, then carried on regardless. Focus moved, and it typed a list of AutoCAD
commands into the user's chat window. `winui.type_line` and `press_escape` now
refuse to send anything unless AutoCAD is genuinely the frontmost window, and
the prober was rewritten to use COM from a throwaway subprocess instead - if a
command parks AutoCAD, the subprocess blocks and gets killed, and the session
carries on.

**Some AutoCAD dialogs are not `#32770`.** SuperHatch opens class
`adesk_dlg0000`, so a dialog check that only looks for the standard class will
miss it and wonder why COM has frozen. Posting `WM_CLOSE` clears these without
needing to click.

**Unicode round-trips cleanly.** `\U+XXXX` escapes are decoded by AutoCAD's
file reader but *not* by `(read)`, so non-ASCII text is built with `(chr n)`
instead. Chinese layer names, text and attributes survive
Python → LISP → drawing → COM → Python byte-identical.

---

## If something goes wrong

| Symptom | What to do |
|---|---|
| "AutoCAD is busy" | Look at the AutoCAD window for a dialog or a command waiting for input, then run `acad_cancel` |
| Everything times out | A modal dialog is open. Dismiss it on screen; COM is frozen until you do |
| A tool reports a handle is not found | The object was erased, or the handle came from a different drawing |
| Plot produces no file | Check `plot_devices`, and that the folder is writable |

`acad_status` is always safe and says what AutoCAD thinks is going on.

---

## Tests

```powershell
.\.venv\Scripts\python.exe -X utf8 tests\smoke.py         # COM + LISP bridge
.\.venv\Scripts\python.exe -X utf8 tests\unicode_check.py # CJK round trip
.\.venv\Scripts\python.exe -X utf8 tests\func_basic.py    # draw / modify / select
.\.venv\Scripts\python.exe -X utf8 tests\func_full.py     # layers ... batch
.\.venv\Scripts\python.exe -X utf8 tests\func_batch.py    # folder processing
.\.venv\Scripts\python.exe -X utf8 tests\list_tools.py    # the registered surface
```

They run against the live AutoCAD and create scratch drawings; nothing is
saved over anything of yours.
