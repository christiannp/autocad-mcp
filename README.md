# AutoCAD MCP

Lets Claude drive the AutoCAD running on this PC — draw, edit, annotate,
dimension, lay out sheets, plot, extract data, batch-process folders of
drawings — and **look at the result**, because a drawing has to be checked by
eye, not just by entity count.

The design goal was simple: **if it can be done by hand in AutoCAD, it can be
done through this server.** 121 tools, plus a verified registry of every
command the AutoCAD UI can reach.

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

Windows only. This drives AutoCAD through COM, so it needs the real desktop
AutoCAD installed on the same machine. Built and tested against
**AutoCAD 2025 (25.0s)** with Python 3.14.

```powershell
cd <wherever you cloned this>
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp[cli]" pywin32 ezdxf openpyxl pillow
.\.venv\Scripts\python.exe install.py
```

`install.py` registers the server with the Claude desktop app by adding an
`mcpServers.autocad` entry to `%APPDATA%\Claude\claude_desktop_config.json`,
pointing at this clone's venv and `run_server.py`. It backs the file up first and
leaves every other setting alone. `install.py --remove` undoes it.

**Quit the Claude desktop app before running `install.py`**, then start it
again. The app keeps the config in memory and saves it back over the file for
its own settings, so an entry written while it is open can vanish hours later
— seen twice on one machine. Written while it was closed, the entry was read
at startup and kept.

If Claude is installed as an MSIX package (it lives under `C:\Program Files\WindowsApps\Claude_…`), its `%APPDATA%\Claude` is
really `%LOCALAPPDATA%\Packages\Claude_<id>\LocalCache\Roaming\Claude`. Run
`install.py` from a normal terminal with `APPDATA` pointed there:

```powershell
$env:APPDATA = "$env:LOCALAPPDATA\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming"
.\.venv\Scripts\python.exe install.py
```

AutoCAD must be running. If it is not, the first call starts it.

> **If the config entry still disappears** (check with the same `APPDATA` as
> above on an MSIX install):
>
> ```powershell
> (Get-Content "$env:APPDATA\Claude\claude_desktop_config.json" -Raw |
>   ConvertFrom-Json).mcpServers
> ```
>
> Empty output means it was wiped. The durable fix is to install the server as
> a **desktop extension**, which the app registers through its own installer:
>
> ```powershell
> .\.venv\Scripts\python.exe install.py --mcpb
> ```
>
> builds `dist\autocad-mcp.mcpb`. Install it from Settings > Extensions >
> Advanced settings > Install Extension and approve (double-clicking works
> only where `.mcpb` is associated with Claude). The bundle is only a
> launcher pointing at this clone, so `git pull` updates the server with no
> reinstall. Use one route or the other, not both.
>
> Either route reaches Cowork sessions linked to the PC as well as the
> desktop chat.

---

## Setting it up on another machine

Three things do not travel with the repo.

**1. The venv** — not committed. Re-create it with the install steps above.

**2. The command registry.** `docs/commands.json` was generated from one
specific machine's AutoCAD: its CUIX files, its version, its installed Express
Tools, its ribbon customisation. It works as-is on a stock AutoCAD 2025, but on
a different version or a customised UI, regenerate it:

```powershell
.\.venv\Scripts\python.exe build\build_inventory.py        # read the CUIX files
.\.venv\Scripts\python.exe build\extract_descriptions.py   # pull Autodesk's help strings
.\.venv\Scripts\python.exe build\probe_commands.py         # run each command headless
.\.venv\Scripts\python.exe build\build_registry.py         # write docs/commands.json
```

`probe_commands.py` takes a while. It runs in headless `accoreconsole`, not in
the AutoCAD you have open, so it will not disturb anything on screen, and it is
resumable if interrupted.

**3. The registration** — per-machine. Run `install.py` there.

Nothing in the repo hardcodes a user folder, so a clone anywhere works.

---

## The tools

**Session** `acad_status` `acad_cancel` `doc_list` `doc_new` `doc_open`
`doc_save` `doc_close` `doc_activate` `sysvar` `zoom` `regen` `purge` `undo`
`view` `ucs`

**Seeing the drawing** `screenshot` `render` — both return the picture to
Claude directly (see below)

**Working with the person at the screen** `selection_current`
`selection_highlight` `user_pick`

**Escape hatches** `cad_command` `cad_lisp` `cad_script` `cad_send`

**Command reference** `command_search` `command_help`

**Draw** `draw_line` `draw_polyline` `draw_rectangle` `draw_polygon`
`draw_circle` `draw_arc` `draw_ellipse` `draw_spline` `draw_point` `draw_hatch`
`draw_construction_line` `draw_revcloud` `draw_wipeout` `region` `boundary`

**Modify** `entity_move` `entity_copy` `entity_rotate` `entity_scale`
`entity_mirror` `entity_offset` `entity_array` `entity_delete` `entity_trim`
`entity_extend` `entity_fillet` `entity_chamfer` `entity_join` `entity_explode`
`entity_break` `entity_overkill` `entity_stretch` `entity_align`
`entity_lengthen` `polyline_edit` `entity_divide` `draw_order`
`entity_change_space` `entity_properties` `match_properties` `group`

**Find & measure** `entity_select` `entity_info` `entity_summary` `measure`

**Layers & styles** `layer_list` `layer_set` `layer_state` `layer_states`
`layer_delete` `layer_rename` `layer_merge` `linetype` `text_style` `dim_style`
`standards_import` `annotation_scale`

**Blocks, xrefs & underlays** `block_list` `block_define` `block_insert`
`block_attributes` `block_dynamic` `attribute_sync` `block_edit` `block_export`
`xref` `underlay` `pdf_import`

**Annotation** `draw_text` `draw_mtext` `draw_dimension` `dimension_chain`
`dimension_edit` `draw_leader` `draw_mleader` `draw_table` `table_read`
`table_edit` `table_from_spreadsheet` `text_edit` `text_find_replace`
`text_combine`

**Sheets & output** `layout_list` `layout_manage` `page_setup` `plot_devices`
`viewport_create` `viewport_manage` `plot` `export`

**Data** `drawing_info` `data_extract`

**Batch** `batch_preview` `batch_process` `batch_headless`

### Seeing the drawing

Two tools hand a picture straight back to Claude as an image, so an edit can
be checked by looking at it rather than by trusting a handle list:

* **`screenshot`** grabs the AutoCAD window as the user sees it, cropped to the
  drawing canvas and shrunk to 1600 px, after zooming to extents, to the given
  objects, or to a window. It is pure Win32 — it still works while a modal
  dialog has COM frozen, and it does not need the window to be in front.
* **`render`** plots the drawing to a PNG through AutoCAD's own raster plotter
  (`PublishToWeb PNG.pc3`) — exact geometry, no ribbon or palettes, independent
  of what is on screen, optionally through a plot style such as
  `monochrome.ctb`. Extents, a window, a set of objects, or a whole layout.

Either can also keep the PNG on disk with `path`.

### Undo

Every tool call that changes the drawing is wrapped in its own undo group, so
`undo` (and Ctrl+Z at the keyboard) steps back **one tool call at a time** —
without this, AutoCAD lumps every COM edit made between two commands into a
single step. `undo` also sets marks and goes back to them: mark before a
multi-step change, look, and `back` reverts all of it if it is wrong. `redo`
only works straight after an undo; any other change in between clears it,
exactly as in AutoCAD itself.

### Working with the person at the screen

She can click things in AutoCAD and say "move these": `selection_current`
returns what is highlighted. `selection_highlight` does the reverse — grips the
objects Claude means, so she can see them before saying yes. `user_pick` asks
her for objects, a point, a distance, a word or a number on AutoCAD's command
line and waits (with a timeout) for the answer.

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
prompt text rather than guessed. **171 commands** point at a dedicated tool
that is easier than driving them through `cad_command`.

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

**`screenshot` and `render` let Claude look at the drawing** — useful for
checking a layout before plotting, or confirming an edit landed where it
should. Prefer `render` for a clean, exact picture and `screenshot` for "what
is on her screen right now", dialogs included.

**A missing handle stops a command before it starts.** Every command-driven
tool resolves its handles first; one that no longer exists aborts the call
with "no object with handle X" instead of leaving AutoCAD waiting at a prompt.

**When a command does park at a prompt, the error says which one** — the
timeout message quotes AutoCAD's `LASTPROMPT`, so a wrong argument to
`cad_command` is diagnosed from the message, not by looking at the screen.

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

**Esc is posted, not typed.** A parked command is cancelled by posting
`WM_KEYDOWN`/`WM_KEYUP` Escape to AutoCAD's own windows, which needs no focus:
it works while the user is in another application, while the screen is locked,
and when nobody is at the machine — precisely when a synthetic keystroke via
`SendInput` would be refused (and rightly so). A real keystroke follows only if
AutoCAD already is the foreground window.

**One tool call, one undo step.** `StartUndoMark`/`EndUndoMark` around every
drawing-changing tool call. Verified: nesting is fine, a group holding both COM
edits and a LISP-driven command undoes as one, and an *empty* group still
costs an undo step — which is why tools that never change the drawing
(plotting, screenshots, opening files) are excluded from grouping.

**UNDO and REDO are typed, not evaluated.** Any AutoLISP evaluation — even a
read-only `(getvar)` — counts as a new operation and empties the redo stack.
So `undo` sends `_.UNDO n` / `_.MREDO n` straight to the command line and
confirms completion through `CMDACTIVE`; COM reads in between do not disturb
the redo stack, LISP does.

**`ssget` with a window only sees what is on screen**, like hatching by
point. `entity_select` with an area and `entity_stretch` zoom to extents first.

**REVCLOUD cannot be scripted by points.** Its command-line prompt in this
release offers only `[Arc length/Object/Style]` - the rectangular and
polygonal modes are ribbon-only, and freehand follows the mouse, so a point
fed from a script leaves it "guiding crosshairs" until Esc. `draw_revcloud`
draws the outline as a polyline and converts it with the Object option, which
is what the ribbon button does underneath. The Arc option asks for a minimum
*and* a maximum, and the maximum may not exceed three times the minimum.

**CHSPACE will not take a selection set from a script** - it sits at *Select
objects* until Esc. `entity_change_space` does the same job over COM: copy
into the other space, then scale and move through the viewport's transform.

**AutoCAD's own log tells you what a parked command wanted.** With
`LOGFILEMODE=1` every prompt and error goes to `LOGFILENAME`; reading its tail
after a timeout is how the two findings above were made in minutes. The
`tests/diagnostics/diag_prompt_log.py` script does exactly that.

**`layerstate-save` rejects masks it does not know** with "ADS request
error". 511 (every documented property) works; 65535 does not.

**`CenterPlot` is "Invalid input" for a layout plot** — set it only when
plotting model space by extents or window.

**`ActivePViewport` can only be set from floating model space**: `MSpace =
True` first, then the viewport, then CHSPACE. The first VIEWPORT entity in a
layout is the sheet itself; the user's viewports follow it.

**UCS by origin asks for a point on the X axis** after the origin — an Enter
accepts the default, and without it the next command is swallowed as that
point.

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
.\.venv\Scripts\python.exe -X utf8 tests\func_ext.py      # vision, undo, offset sides, stretch ... underlays
.\.venv\Scripts\python.exe -X utf8 tests\func_batch.py    # folder processing
.\.venv\Scripts\python.exe -X utf8 tests\list_tools.py    # the registered surface
```

They run against the live AutoCAD and create scratch drawings; nothing is
saved over anything of yours.
