# Tests

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

One-off diagnostic scripts written while working out how AutoCAD behaves live
in `tests/diagnostics/`; [its README](../tests/diagnostics/README.md) lists the
question each one answered.
