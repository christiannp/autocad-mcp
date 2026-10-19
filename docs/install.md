# Install

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
