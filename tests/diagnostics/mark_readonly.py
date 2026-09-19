"""Mark the inspection-only tools readonly=True so a busy AutoCAD retries once."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "acadmcp" / "tools"

READONLY = {
    "session.py": ["acad_status", "doc_list"],
    "select.py": ["entity_select", "entity_info", "entity_summary", "measure"],
    "layers.py": ["layer_list"],
    "blocks.py": ["block_list"],
    "layout.py": ["layout_list", "plot_devices"],
    "query.py": ["drawing_info"],
    "batch.py": ["batch_preview"],
}

for filename, names in READONLY.items():
    path = ROOT / filename
    text = path.read_text(encoding="utf-8")
    changed = 0
    for name in names:
        # find the @tool(...) decorator immediately preceding "def <name>("
        pattern = re.compile(
            r"(@tool\()(?![^\n]*readonly)((?:[^\n]|\n(?!def ))*?\)\s*\ndef " + name + r"\()",
            re.S,
        )
        text, n = pattern.subn(r"\1readonly=True, \2", text, count=1)
        changed += n
        if not n:
            print(f"  !! {filename}: could not mark {name}")
    path.write_text(text, encoding="utf-8")
    print(f"{filename}: marked {changed}/{len(names)}")
