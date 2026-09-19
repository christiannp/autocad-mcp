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


VK_RETURN = 0x0D
KEYEVENTF_UNICODE = 0x0004


def _send_unicode(ch: str) -> None:
    inputs = (_INPUT * 2)()
    for i, flags in enumerate((KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i].u.ki = _KEYBDINPUT(0, ord(ch), flags, 0, None)
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(_INPUT))


def _send_vk(vk: int) -> None:
    inputs = (_INPUT * 2)()
    for i, flags in enumerate((0, KEYEVENTF_KEYUP)):
        inputs[i].type = INPUT_KEYBOARD
        inputs[i].u.ki = _KEYBDINPUT(vk, 0, flags, 0, None)
    user32.SendInput(2, ctypes.byref(inputs), ctypes.sizeof(_INPUT))


def foreground_is_autocad() -> bool:
    """Is AutoCAD the window that will receive keystrokes right now?

    This check is not optional. Sending input without it once typed a list of
    AutoCAD command names into the user's chat window, because focus had moved
    and the code carried on regardless. Every keystroke this module sends is
    now gated on this returning True.
    """
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value in _acad_pids()


def focus_autocad(verify: bool = True) -> bool:
    hwnd = _acad_hwnd()
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    return foreground_is_autocad() if verify else True


def type_line(text: str, enter: bool = True, focus: bool = True) -> bool:
    """Type text at AutoCAD's command line, but only if AutoCAD has focus.

    Returns False without sending anything when AutoCAD is not frontmost -
    never type blind.
    """
    if focus:
        focus_autocad()
    if not foreground_is_autocad():
        return False
    for ch in str(text):
        if not foreground_is_autocad():
            return False
        _send_unicode(ch)
        time.sleep(0.004)
    if enter and foreground_is_autocad():
        _send_vk(VK_RETURN)
    return True


def visible_dialogs() -> list[str]:
    """Titles of any modal dialogs AutoCAD currently has open."""
    titles: list[str] = []
    pids = _acad_pids()
    if not pids:
        return titles

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):  # noqa: ANN001
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls, 64)
            if cls.value == "#32770":
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                titles.append(buf.value or "(untitled dialog)")
        return True

    user32.EnumWindows(cb, 0)
    return titles


def press_escape(times: int = 3, focus: bool = True) -> bool:
    """Focus AutoCAD and press Esc. Returns False if no window was found."""
    hwnd = _acad_hwnd()
    if not hwnd:
        return False
    if focus:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.4)
    if not foreground_is_autocad():
        # Esc is harmless anywhere, but sending input to someone else's window
        # is not something this should ever do on purpose.
        return False
    for _ in range(max(1, times)):
        _send_escape()
        time.sleep(0.25)
    time.sleep(0.5)
    return True
