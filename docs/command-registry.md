# Command registry

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

## How the registry was built

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

`build/` holds the scripts; re-run them after an AutoCAD update — the steps are
in [Setting it up on another machine](install.md#setting-it-up-on-another-machine).
