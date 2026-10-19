# Tools

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

## Seeing the drawing

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

## Undo

Every tool call that changes the drawing is wrapped in its own undo group, so
`undo` (and Ctrl+Z at the keyboard) steps back **one tool call at a time** —
without this, AutoCAD lumps every COM edit made between two commands into a
single step. `undo` also sets marks and goes back to them: mark before a
multi-step change, look, and `back` reverts all of it if it is wrong. `redo`
only works straight after an undo; any other change in between clears it,
exactly as in AutoCAD itself.

## Working with the person at the screen

She can click things in AutoCAD and say "move these": `selection_current`
returns what is highlighted. `selection_highlight` does the reverse — grips the
objects Claude means, so she can see them before saying yes. `user_pick` asks
her for objects, a point, a distance, a word or a number on AutoCAD's command
line and waits (with a timeout) for the answer.

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

## If something goes wrong

| Symptom | What to do |
|---|---|
| "AutoCAD is busy" | Look at the AutoCAD window for a dialog or a command waiting for input, then run `acad_cancel` |
| Everything times out | A modal dialog is open. Dismiss it on screen; COM is frozen until you do |
| A tool reports a handle is not found | The object was erased, or the handle came from a different drawing |
| Plot produces no file | Check `plot_devices`, and that the folder is writable |

`acad_status` is always safe and says what AutoCAD thinks is going on.
