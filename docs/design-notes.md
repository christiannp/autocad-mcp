# Design notes (the non-obvious bits)

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
