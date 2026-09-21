"""Screenshot the AutoCAD window so the model can look at the drawing.

Pure Win32 - no COM - so it still works while a modal dialog has AutoCAD's
COM interface frozen, which is exactly when you most want to see the screen.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time
from pathlib import Path
from typing import Any

from .errors import AcadError
from .winui import _acad_hwnd

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND

PW_CLIENTONLY = 0x00000001
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


def _client_size(hwnd: int) -> tuple[int, int]:
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def canvas_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """The drawing canvas, in client coordinates of the main window.

    AutoCAD does not name its view window in any documented way, so the
    canvas is found by asking which child window sits under the centre of the
    frame - with a drawing open that is always the view. A palette or dialog
    there would be much smaller than the frame, which is the sanity check.
    """
    width, height = _client_size(hwnd)
    if width < 10 or height < 10:
        return None
    centre = wt.POINT(width // 2, height // 2)
    user32.ClientToScreen(hwnd, ctypes.byref(centre))
    child = user32.WindowFromPoint(centre)
    if not child or child == hwnd:
        return None
    rect = wt.RECT()
    user32.GetWindowRect(child, ctypes.byref(rect))
    tl = wt.POINT(rect.left, rect.top)
    br = wt.POINT(rect.right, rect.bottom)
    user32.ScreenToClient(hwnd, ctypes.byref(tl))
    user32.ScreenToClient(hwnd, ctypes.byref(br))
    w, h = br.x - tl.x, br.y - tl.y
    if w < 0.3 * width or h < 0.3 * height:
        return None
    return (max(0, tl.x), max(0, tl.y), min(width, br.x), min(height, br.y))


def _print_window(hwnd: int) -> Any:
    """PrintWindow the client area into a PIL image (None if it came out blank)."""
    from PIL import Image

    width, height = _client_size(hwnd)
    if width < 10 or height < 10:
        return None
    src = user32.GetDC(hwnd)
    dst = gdi32.CreateCompatibleDC(src)
    bitmap = gdi32.CreateCompatibleBitmap(src, width, height)
    gdi32.SelectObject(dst, bitmap)
    ok = user32.PrintWindow(hwnd, dst, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
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

    return Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)


def _is_blank(image: Any) -> bool:
    colours = image.getcolors(maxcolors=4)
    return bool(colours) and len(colours) <= 1


def grab(crop: bool = True) -> tuple[Any, dict[str, Any]]:
    """Capture the AutoCAD window. Returns ``(PIL image, details)``.

    Tries PrintWindow first, which does not disturb the user. If that yields a
    blank image (AutoCAD draws its viewport with the GPU, which PrintWindow can
    miss) it brings the window forward and grabs the screen instead.
    """
    try:
        from PIL import ImageGrab
    except ImportError as exc:  # pragma: no cover
        raise AcadError("Pillow is not installed, so screenshots are unavailable") from exc

    hwnd = _acad_hwnd()
    if not hwnd:
        raise AcadError("Could not find the AutoCAD window - is AutoCAD running?")

    width, height = _client_size(hwnd)
    if width < 10 or height < 10 or user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.4)

    region = canvas_rect(hwnd) if crop else None
    image = _print_window(hwnd)
    if image is not None:
        probe = image.crop(region) if region else image
        if _is_blank(probe):
            image = None

    details: dict[str, Any] = {}
    if image is not None:
        if region:
            image = image.crop(region)
            details["cropped_to"] = "drawing canvas"
        details["method"] = "PrintWindow (did not disturb the screen)"
    else:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.6)
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        bbox = (rect.left, rect.top, rect.right, rect.bottom)
        region = canvas_rect(hwnd) if crop else None
        if region:
            origin = wt.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(origin))
            bbox = (
                origin.x + region[0], origin.y + region[1],
                origin.x + region[2], origin.y + region[3],
            )
            details["cropped_to"] = "drawing canvas"
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        details["method"] = "screen grab (window brought to front)"

    details["width"], details["height"] = image.width, image.height
    return image, details


def grab_window(path: str | Path, focus: bool = False) -> dict:
    """Save a PNG of the AutoCAD window (kept for callers of the old API)."""
    image, details = grab(crop=False)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG", optimize=True)
    details["file"] = str(target)
    return details
