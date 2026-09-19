"""Last-resort recovery: press Esc in AutoCAD for real.

When AutoCAD is sitting at a command prompt waiting for input, *every* COM call
returns RPC_E_CALL_REJECTED - including the ones you would use to cancel.  The
only way out from outside the process is a genuine keystroke, so this module
focuses the AutoCAD window and sends Escape through SendInput.

It steals focus for a fraction of a second, so it is only used when the COM
channel is already wedged.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

SW_RESTORE = 9
VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


def _acad_hwnd() -> int | None:
    """Top-level, visible window belonging to an acad.exe process."""
    found: list[int] = []
    pids = _acad_pids()
    if not pids:
        return None

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):  # noqa: ANN001
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 10:  # the main frame has a long caption
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "AutoCAD" in buf.value:
                    found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def _acad_pids() -> set[int]:
    import subprocess

    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq acad.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        ).stdout
    except Exception:
        return set()
    pids: set[int] = set()
    for line in out.splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _send_escape() -> None:
    inputs = (_INPUT * 2)()
    for i, flags in enumerate((0, KEYEVENTF_KEYUP)):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i].u.ki = _KEYBDINPUT(VK_ESCAPE, 0, flags, 0, None)
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(_INPUT))


def press_escape(times: int = 3, focus: bool = True) -> bool:
    """Focus AutoCAD and press Esc. Returns False if no window was found."""
    hwnd = _acad_hwnd()
    if not hwnd:
        return False
    if focus:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
    for _ in range(max(1, times)):
        _send_escape()
        time.sleep(0.25)
    time.sleep(0.5)
    return True
