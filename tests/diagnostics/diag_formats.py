"""Which AcSaveAsType numbers does this AutoCAD accept, and what do they produce?"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from acadmcp import com, winui  # noqa: E402

winui.press_escape(2)
com.run_com(lambda: com.ensure_responsive(), timeout=60)

OUT = Path(r"C:\Users\Wanda\Documents\AI Companion\autocad-mcp\testout\fmt2")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    b"AC1015": "DWG 2000", b"AC1018": "DWG 2004", b"AC1021": "DWG 2007",
    b"AC1024": "DWG 2010", b"AC1027": "DWG 2013", b"AC1032": "DWG 2018",
}


def kind(path: Path) -> str:
    with open(path, "rb") as fh:
        magic = fh.read(6)
    if magic in HEADERS:
        return HEADERS[magic]
    head = magic.decode("latin1", "replace")
    if head.strip().startswith("0") or head.startswith("AutoCAD"):
        return "DXF"
    return repr(head)


def main() -> None:
    doc = com.run_com(lambda: com.app().Documents.Add(), timeout=120)
    com.run_com(lambda: doc.ModelSpace.AddCircle(com.pt([0, 0, 0]), 10.0), timeout=60)

    print("value  ext    result", flush=True)
    for value in range(1, 72):
        for ext in (".dwg", ".dxf"):
            target = OUT / f"v{value}{ext}"
            target.unlink(missing_ok=True)
            try:
                com.run_com(
                    lambda v=value, t=str(target): com.retry(
                        lambda: doc.SaveAs(t, v), timeout=20
                    ),
                    timeout=40,
                )
            except Exception:  # noqa: BLE001
                continue
            if target.exists() and target.stat().st_size:
                print(f"{value:5d}  {ext}   {kind(target)}", flush=True)
                break

    com.run_com(lambda: com.quiet(lambda: doc.Close(False)), timeout=60)


main()
print("done", flush=True)
