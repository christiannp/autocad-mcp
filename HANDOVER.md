# Handover

State of this project as of **2026-09-25**, for whoever picks it up next —
a new Claude session, or the machine this gets handed to.

The README is the manual: what the tools are, how to install, what AutoCAD
does that surprised us. This file is only the things the README cannot tell
you — where it actually stands right now, what is blocking, and what it is
like to work on this machine.

---

## The one thing that is broken right now

**The server is not registered with the Claude desktop app.** Nothing is
wrong with the code; there is simply no live registration.

```powershell
(Get-Content "$env:APPDATA\Claude\claude_desktop_config.json" -Raw |
  ConvertFrom-Json).mcpServers
```

Empty. The desktop app has now wiped that key **twice** — it rewrites the
file for its own settings and drops what it does not recognise.

The fix is already built and sitting there unused:

```
dist\autocad-mcp.mcpb
```

`install.py --mcpb` produced it. It is a thin launcher pointing at this
clone's venv, so `git pull` updates the server without reinstalling, and it
registers through the app's own installer, which survives the rewrites.

**It has never been installed.** `%APPDATA%\Claude\Claude Extensions\` holds
only Desktop Commander. Installing it means the user double-clicking the file
and approving — not something to do on their behalf.

So: first action next session is to ask the user to double-click that bundle,
restart the app, and confirm the `autocad` tools appear. Until then the server
runs only when a test script launches it directly.

---

## Where it stands

**121 tools** over COM + AutoLISP, across `session, raw, commands, draw,
modify, select, layers, blocks, annotate, layout, query, vision, batch`.

**Command registry:** 918 UI commands, 473 verified by running them, 443
documented from AutoCAD's own help strings, 2 unknown (`SCRIPT`, `VLISP`) —
**99.8% covered**, all reachable through `cad_command`. 171 now point at a
dedicated tool, 181 carry extracted option keywords.

**Published:** https://github.com/christiannp/autocad-mcp — public, `main`
at `43a09b4`, working tree clean, local and remote in sync.

Commit history:

```
43a09b4  Verified against live AutoCAD: undo per call, Esc without focus, ...
1756386  Extended tool set: vision, selection, editing, annotation, UCS/views/undo
09ff1a6  Make the repo portable and fix the layout_list flake
d0a3a82  Verified command registry: 99.8 percent of the AutoCAD UI
0f2f875  AutoCAD MCP server: 85 tools over COM + AutoLISP
```

**Test status:** per commit `43a09b4` — func_ext 126/126, func_full 59/59,
func_basic 65/65, smoke 19/19, func_registry 20/20, func_batch, unicode round
trip, stdio handshake at 121 tools, rendered PNGs checked by eye. That was a
different session's run; it has not been re-verified since, and AutoCAD is not
currently running.

---

## Open items

**1. Install the .mcpb** — see above. Blocks everything else being useful.

**2. No LICENSE file.** The repo is public but "all rights reserved" by
default, which means nobody can legally use it, including the person it is
being handed to. Needs a choice from the owner.

**3. The solar tool group was the original point and does not exist yet.**
It is waiting on real inputs from the architect who will use this: module
spec, setback standard, layer naming, title block, and a sample roof DWG.
Nothing is tuned to her standards. The assumed defaults from the older plan
(module 1134 x 1722 mm, 20 mm gaps, 1000 mm setback, portrait, mm) are **not**
baked in anywhere and should not be assumed.

Her real drawings have deliberately never been opened — the owner wanted to
ask her first. That still stands.

**4. `AttributeError: <unknown>.<Collection>` is patched case by case, not
generally.** Late binding can hand back a document whose next property read
fails, because AutoCAD is still digesting the previous call. `layout_list`
and `doc_new` now ride it out with `com.retry(attr_is_busy=True)`. Plenty of
other places still read `doc.Layers`, `doc.Blocks`, `doc.TextStyles` bare —
`grep` for `doc\.\(Layers\|Blocks\|TextStyles\|DimStyles\|Linetypes\)` to see
them.

The obvious fix is to make `com.find_doc` / `com.active_doc` return only a
document they have proved readable. **This was tried on 2026-09-21 and
reverted** — it touches the path every single tool calls, and it produced new
failures (`viewport_create`) rather than fewer. It is worth doing properly,
with the suites green before and after, at the start of a session rather than
the end. Do not attempt it as a quick fix.

**5. 443 commands are documented but their prompt chains were never
captured.** Dialog-driven commands and Express Tools. They are reachable and
described; if one misbehaves in real use, capture its chain by hand with the
subprocess prober (`build/verify_express.py` is the safe pattern).

---

## Working on this machine — read before you touch anything

This is the owner's daily-driver PC, not a build box. It runs ComfyUI,
Enscape, AutoCAD and other Python workloads at the same time.

**Kill by PID. Never by process name.** On 2026-09-20 a
`Get-Process python | Stop-Process -Force`, run to clear one stuck test,
killed the owner's ComfyUI backend mid-job. Always list first, pick the PID,
kill that.

**Never send synthetic keystrokes without checking the foreground window.**
On the same day a UI prober using `SendInput` with `focus=False` typed a
stream of AutoCAD command names into the owner's chat window. Esc is now
posted with `WM_KEYDOWN`/`WM_KEYUP` to AutoCAD's own windows, which needs no
focus at all — use that. `winui.foreground_is_autocad()` guards what is left.

**Start from a freshly launched AutoCAD when running the suites.** After a
few consecutive runs — around 19 scratch drawings and several hundred seconds
of CPU — AutoCAD stops answering COM entirely while still pumping window
messages and burning CPU, with no dialog on screen. Only a restart clears it.
Do not mistake this for a code bug; it cost an hour once.

**COM's first call is slow when AutoCAD sits on the Start tab with nothing
open** — up to a couple of minutes. That is not a hang. Do not kill it.

**Close scratch drawings and leave AutoCAD clean** when you finish.

**The device bridge times out at 60s per call.** Long suites need
`start_process` plus repeated `read_process_output`, or output redirected to a
file you poll. Detached `Start-Job` / `Start-Process` did not survive; the
foreground-plus-polling pattern is what works.

**Run `build/scrub_paths.py` before committing any regenerated JSON.**
AutoCAD echoes default filenames into its prompts, so a Windows username ends
up inside the captured probe data. The script is idempotent.

---

## Handing it to a different machine

The README's "Setting it up on another machine" section is the procedure.
Three things do not travel with the repo:

- **The venv** — not committed, rebuild it.
- **The command registry** — `docs/commands.json` was generated from *this*
  machine's CUIX files. Fine on a stock AutoCAD 2025; regenerate with the four
  `build/` scripts if the version or the ribbon customisation differs.
- **The registration** — per machine, and use the `.mcpb` route.

Paths everywhere are derived from `%LOCALAPPDATA%` / `%APPDATA%`, with
`ACADMCP_ACAD_RELEASE` / `_VERSION` / `_LANG` overrides, so a clone runs
anywhere. No Windows username is committed anywhere in the repo.

One caveat worth passing on: the published registry carries roughly 1,870 of
Autodesk's own help strings and the captured prompt text, lifted from an
installed AutoCAD. That was a deliberate choice by the owner when publishing
public. Low risk, not zero — a stripped variant is straightforward if it ever
needs to change.

---

## If you are a new session picking this up

Read in this order: this file, then the README's "Design notes" and "Things
worth knowing" — they hold roughly twenty AutoCAD behaviours that each cost
real time to discover, and re-discovering them is the main way to waste a
session here.

Then confirm the ground truth rather than trusting this file, which goes
stale:

```powershell
cd "C:\Users\Wanda\Documents\AI Companion\autocad-mcp"
git log --oneline -5
git status -sb
(Get-Content "$env:APPDATA\Claude\claude_desktop_config.json" -Raw |
  ConvertFrom-Json).mcpServers
Get-ChildItem "$env:APPDATA\Claude\Claude Extensions"
```

Then ask the owner what they want next, rather than assuming it is the next
item on the open list.
