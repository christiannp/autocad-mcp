"""Screenshot the AutoCAD window so the model can look at the drawing."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path

from .errors import AcadError
from .winui import _acad_hwnd

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
SW_RESTORE = 9


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


def _client_rect(hwnd: int) -> tuple[int, int]:
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def grab_window(path: str | Path, focus: bool = False) -> dict:
    """Save a PNG of the AutoCAD window.

    Tries PrintWindow first, which does not disturb the user. If that yields a
    blank image (AutoCAD draws its viewport with the GPU, which PrintWindow can
    miss) it brings the window forward and grabs the screen instead.
    """
    try:
        from PIL import Image, ImageGrab
    except ImportError as exc:  # pragma: no cover
        raise AcadError("Pillow is not installed, so screenshots are unavailable") from exc

    hwnd = _acad_hwnd()
    if not hwnd:
        raise AcadError("Could not find the AutoCAD window - is AutoCAD running?")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    width, height = _client_rect(hwnd)
    if width < 10 or height < 10:
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)
        width, height = _client_rect(hwnd)

    image = None
    if width > 10 and height > 10:
        src = user32.GetDC(hwnd)
        dst = gdi32.CreateCompatibleDC(src)
        bitmap = gdi32.CreateCompatibleBitmap(src, width, height)
        gdi32.SelectObject(dst, bitmap)
        ok = user32.PrintWindow(hwnd, dst, PW_RENDERFULLCONTENT)
        if not ok:
            gdi32.BitBlt(dst, 0, 0, width, height, src, 0, 0, SRCCOPY)

        header = BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.bmiHeader.biWidth = width
        header.bmiHeader.biHeight = -height      # top-down
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(dst, bitmap, 0, height, buffer, ctypes.byref(header), 0)

        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dst)
        user32.ReleaseDC(hwnd, src)

        image = Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
        colours = image.getcolors(maxcolors=4)
        if colours and len(colours) <= 1:
            image = None          # blank - PrintWindow did not capture the canvas

    if image is None:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.6)
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        image = ImageGrab.grab(
            bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True
        )
        method = "screen grab (window brought to front)"
    else:
        method = "PrintWindow (did not disturb the screen)"

    image.save(target, "PNG", optimize=True)
    return {
        "file": str(target),
        "width": image.width,
        "height": image.height,
        "method": method,
    }
