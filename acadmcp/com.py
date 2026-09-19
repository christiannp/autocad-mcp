"""COM plumbing: a single-apartment worker thread that owns the AutoCAD object.

Everything that touches AutoCAD goes through :func:`run_com`.  All COM calls
therefore happen on one thread, in one STA, which sidesteps the cross-apartment
marshalling problems you get when an async MCP server runs tools on a pool.
"""

from __future__ import annotations

import concurrent.futures
import os
import queue
import threading
import time
from typing import Any, Callable, Iterable, Sequence, TypeVar

import pythoncom
import pywintypes
import win32com.client
from win32com.client import VARIANT

from .errors import (
    RETRYABLE,
    AcadError,
    Busy,
    NoDocument,
    NotConnected,
    NotFound,
    hresult,
    wrap,
)

T = TypeVar("T")

PROGID = "AutoCAD.Application"

# How long to keep retrying a "callee rejected the call" before giving up.
BUSY_TIMEOUT = float(os.environ.get("ACADMCP_BUSY_TIMEOUT", "60"))
BUSY_INTERVAL = 0.2

# How long a single queued COM job may take, end to end.
JOB_TIMEOUT = float(os.environ.get("ACADMCP_JOB_TIMEOUT", "300"))

_local = threading.local()


# ---------------------------------------------------------------------------
# worker thread
# ---------------------------------------------------------------------------


class _ComWorker:
    def __init__(self) -> None:
        self._q: "queue.Queue[tuple[concurrent.futures.Future, Callable[[], Any]] | None]" = queue.Queue()
        self._ready = threading.Event()
        self._app: Any = None
        self._thread = threading.Thread(target=self._loop, name="acad-com", daemon=True)
        self._thread.start()
        self._ready.wait(10)

    # -- thread body --------------------------------------------------------
    def _loop(self) -> None:
        pythoncom.CoInitialize()
        _local.is_worker = True
        self._ready.set()
        try:
            while True:
                item = self._q.get()
                if item is None:
                    break
                fut, fn = item
                if not fut.set_running_or_notify_cancel():
                    continue
                try:
                    fut.set_result(fn())
                except BaseException as exc:  # noqa: BLE001 - relayed to caller
                    fut.set_exception(exc)
        finally:
            pythoncom.CoUninitialize()

    # -- submission ---------------------------------------------------------
    def submit(self, fn: Callable[[], T], timeout: float | None = None) -> T:
        if getattr(_local, "is_worker", False):
            return fn()
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self._q.put((fut, fn))
        limit = timeout if timeout is not None else JOB_TIMEOUT
        try:
            return fut.result(limit)
        except concurrent.futures.TimeoutError:
            pass

        # The worker is blocked *inside* a COM call - SendCommand does not
        # return while AutoCAD sits at a prompt - so no amount of retrying on
        # that thread can help. This thread is still free, so press Esc in the
        # UI to release it, then give the call a moment to come back.
        try:
            from . import winui

            pressed = winui.press_escape(4)
        except Exception:  # noqa: BLE001
            pressed = False
        try:
            return fut.result(25)
        except concurrent.futures.TimeoutError as exc:
            raise Busy(
                "AutoCAD did not finish the operation in time and is still not "
                "responding"
                + (" (Esc was sent)" if pressed else "")
                + ". Look at AutoCAD: there is probably a dialog open, or a "
                "command waiting for input. Clear it, then run acad_cancel."
            ) from exc

    # -- connection (worker thread only) ------------------------------------
    def app(self, autostart: bool = True) -> Any:
        if self._app is not None and self._alive(self._app):
            return self._app
        self._app = self._connect(autostart)
        return self._app

    @staticmethod
    def _alive(app: Any) -> bool:
        try:
            _ = app.Version
            return True
        except Exception:
            return False

    def _connect(self, autostart: bool) -> Any:
        try:
            return win32com.client.GetActiveObject(PROGID)
        except pythoncom.com_error:
            pass
        if not autostart:
            raise NotConnected(
                "AutoCAD is not running. Start AutoCAD and try again, or call "
                "acad_connect with autostart=true."
            )
        try:
            app = win32com.client.Dispatch(PROGID)
        except pythoncom.com_error as exc:
            raise NotConnected(
                "Could not start AutoCAD over COM: " + str(exc)
            ) from exc
        try:
            app.Visible = True
        except Exception:
            pass
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                _ = app.Version
                return app
            except pythoncom.com_error as exc:
                if hresult(exc) in RETRYABLE:
                    time.sleep(1.0)
                    continue
                raise
        raise NotConnected("AutoCAD started but never became responsive.")

    def reset(self) -> None:
        self._app = None


_worker: _ComWorker | None = None
_worker_lock = threading.Lock()


def worker() -> _ComWorker:
    global _worker
    if _worker is None:
        with _worker_lock:
            if _worker is None:
                _worker = _ComWorker()
    return _worker


def run_com(fn: Callable[[], T], timeout: float | None = None) -> T:
    """Run ``fn`` on the COM thread and return its result."""
    try:
        return worker().submit(fn, timeout)
    except AcadError:
        raise
    except pywintypes.com_error as exc:
        raise wrap(exc) from exc


def reset_connection() -> None:
    worker().reset()


# ---------------------------------------------------------------------------
# retry helper for a busy AutoCAD
# ---------------------------------------------------------------------------


def retry(
    fn: Callable[[], T],
    timeout: float = BUSY_TIMEOUT,
    context: str = "",
    *,
    attr_is_busy: bool = False,
    rescue_after: float | None = None,
) -> T:
    """Call ``fn``, riding out RPC_E_CALL_REJECTED while AutoCAD is busy.

    ``attr_is_busy`` - pywin32's late binding turns a rejected *property* read
    into ``AttributeError`` rather than ``com_error`` (it swallows the HRESULT in
    ``dynamic.__getattr__``).  For properties we know exist, treat that as busy.

    ``rescue_after`` - if AutoCAD is still busy after this many seconds, press
    Esc in the UI once and keep trying.  That is the only way out when AutoCAD
    is parked at a command prompt waiting for input.
    """
    deadline = time.time() + timeout
    rescue_at = (time.time() + rescue_after) if rescue_after else None
    rescued = False
    last: BaseException | None = None
    while True:
        try:
            return fn()
        except AcadError:
            raise
        except (pywintypes.com_error, AttributeError) as exc:
            busy = (
                hresult(exc) in RETRYABLE
                if isinstance(exc, pywintypes.com_error)
                else attr_is_busy
            )
            if not busy or time.time() >= deadline:
                raise wrap(exc, context) from exc
            last = exc
            if rescue_at and not rescued and time.time() >= rescue_at:
                rescued = True
                try:
                    from . import winui

                    winui.press_escape()
                except Exception:  # noqa: BLE001 - recovery is best effort
                    pass
            time.sleep(BUSY_INTERVAL)


# ---------------------------------------------------------------------------
# VARIANT helpers - AutoCAD is fussy about these
# ---------------------------------------------------------------------------

_VT_R8_ARRAY = pythoncom.VT_ARRAY | pythoncom.VT_R8
_VT_I2_ARRAY = pythoncom.VT_ARRAY | pythoncom.VT_I2
_VT_VARIANT_ARRAY = pythoncom.VT_ARRAY | pythoncom.VT_VARIANT
_VT_DISPATCH_ARRAY = pythoncom.VT_ARRAY | pythoncom.VT_DISPATCH


def pt(p: Sequence[float] | None, default_z: float = 0.0) -> VARIANT:
    """A 3D point as AutoCAD wants it (VARIANT array of 3 doubles)."""
    if p is None:
        raise AcadError("a point was required but none was given")
    vals = [float(v) for v in p]
    if len(vals) == 2:
        vals.append(float(default_z))
    if len(vals) != 3:
        raise AcadError(f"a point needs 2 or 3 numbers, got {len(vals)}")
    return VARIANT(_VT_R8_ARRAY, vals)


def pt2(p: Sequence[float]) -> VARIANT:
    """A 2D point (VARIANT array of 2 doubles) - used by LWPOLYLINE."""
    vals = [float(v) for v in p][:2]
    if len(vals) != 2:
        raise AcadError("a 2D point needs 2 numbers")
    return VARIANT(_VT_R8_ARRAY, vals)


def doubles(values: Iterable[float]) -> VARIANT:
    return VARIANT(_VT_R8_ARRAY, [float(v) for v in values])


def flat2d(points: Iterable[Sequence[float]]) -> VARIANT:
    """[[x,y],[x,y],...] -> flat VARIANT array of doubles (for AddLightWeightPolyline)."""
    out: list[float] = []
    n = 0
    for p in points:
        vals = [float(v) for v in p]
        if len(vals) < 2:
            raise AcadError("each polyline point needs at least x and y")
        out.extend(vals[:2])
        n += 1
    if n < 2:
        raise AcadError("a polyline needs at least 2 points")
    return VARIANT(_VT_R8_ARRAY, out)


def flat3d(points: Iterable[Sequence[float]]) -> VARIANT:
    """[[x,y,z],...] -> flat VARIANT array of doubles (3D polyline, spline fit points)."""
    out: list[float] = []
    n = 0
    for p in points:
        vals = [float(v) for v in p]
        if len(vals) == 2:
            vals.append(0.0)
        if len(vals) != 3:
            raise AcadError("each 3D point needs 2 or 3 numbers")
        out.extend(vals)
        n += 1
    if n < 2:
        raise AcadError("need at least 2 points")
    return VARIANT(_VT_R8_ARRAY, out)


def shorts(values: Iterable[int]) -> VARIANT:
    return VARIANT(_VT_I2_ARRAY, [int(v) for v in values])


def objects(items: Sequence[Any]) -> VARIANT:
    """An array of AutoCAD objects (AppendOuterLoop, AppendItems, ...).

    It must be VT_DISPATCH: AutoCAD rejects an array of VT_VARIANT with
    "Invalid object array", and a plain Python list marshals to the same thing.
    """
    return VARIANT(_VT_DISPATCH_ARRAY, list(items))


def variants(items: Sequence[Any]) -> VARIANT:
    return VARIANT(_VT_VARIANT_ARRAY, list(items))


def strings(items: Sequence[str]) -> VARIANT:
    """An array of strings (SetLayoutsToPlot, layer names in viewports, ...)."""
    return VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [str(v) for v in items])


def prop(obj: Any, name: str, default: Any = None, timeout: float = 20) -> Any:
    """Read a COM property, riding out a momentarily busy AutoCAD."""
    try:
        return retry(
            lambda: getattr(obj, name),
            timeout=timeout,
            context=f"reading {name}",
            attr_is_busy=True,
        )
    except AcadError:
        return default


def unwrap(value: Any) -> Any:
    """COM arrays come back as tuples; make them plain lists/floats."""
    if isinstance(value, (tuple, list)):
        return [unwrap(v) for v in value]
    if isinstance(value, pywintypes.TimeType):
        return str(value)
    return value


def as_point(value: Any) -> list[float]:
    out = unwrap(value)
    if isinstance(out, list):
        return [round(float(v), 10) for v in out]
    raise AcadError("expected a point")


# ---------------------------------------------------------------------------
# convenience accessors used by every tool module
# ---------------------------------------------------------------------------


def app(autostart: bool = True) -> Any:
    """The AcadApplication. Only valid on the COM thread."""
    return worker().app(autostart)


def docs() -> Any:
    return retry(
        lambda: app().Documents,
        timeout=BUSY_TIMEOUT,
        context="reading the document list",
        attr_is_busy=True,
        rescue_after=6.0,
    )


def doc_count() -> int:
    collection = docs()
    return int(
        retry(
            lambda: collection.Count,
            timeout=30,
            context="counting documents",
            attr_is_busy=True,
        )
    )


def active_doc(create_if_none: bool = False) -> Any:
    a = app()
    if doc_count() == 0:
        if not create_if_none:
            raise NoDocument(
                "No drawing is open in AutoCAD. Open one with doc_open, or create "
                "one with doc_new."
            )
        retry(lambda: a.Documents.Add(), context="creating a drawing")
        # Documents.Add sometimes returns an object late binding cannot read
        # properties from; the new drawing is active, so fetch it that way.
        return retry(
            lambda: a.ActiveDocument,
            timeout=60,
            context="reading the new drawing",
            attr_is_busy=True,
        )
    return retry(
        lambda: a.ActiveDocument,
        timeout=30,
        context="reading the active drawing",
        attr_is_busy=True,
        rescue_after=6.0,
    )


def ensure_responsive(rescue: bool = True) -> bool:
    """True once AutoCAD answers a trivial COM call, pressing Esc if it must."""
    try:
        retry(
            lambda: app().Documents.Count,
            timeout=25,
            context="waking AutoCAD",
            attr_is_busy=True,
            rescue_after=3.0 if rescue else None,
        )
        return True
    except AcadError:
        return False


def find_doc(name_or_path: str | None) -> Any:
    """Locate an open document by name, full path, or return the active one."""
    if not name_or_path:
        return active_doc()
    a = app()
    target = str(name_or_path).replace("/", "\\").lower()
    base = os.path.basename(target)
    for i in range(a.Documents.Count):
        d = a.Documents.Item(i)
        try:
            full = str(d.FullName).replace("/", "\\").lower()
        except Exception:
            full = ""
        if full == target or str(d.Name).lower() in (target, base):
            return d
    raise NotFound(f"No open drawing matches {name_or_path!r}.")


def space(doc: Any, where: str = "auto") -> Any:
    """Return ModelSpace or PaperSpace for the given document."""
    w = (where or "auto").lower()
    if w in ("model", "modelspace", "ms"):
        return doc.ModelSpace
    if w in ("paper", "paperspace", "ps", "layout"):
        return doc.PaperSpace
    if w == "auto":
        # ActiveSpace: 0 = paper space, 1 = model space
        try:
            return doc.ModelSpace if int(doc.ActiveSpace) == 1 else doc.PaperSpace
        except Exception:
            return doc.ModelSpace
    raise AcadError(f"unknown space {where!r}; use 'model', 'paper' or 'auto'")


def handle_of(obj: Any) -> str:
    return str(obj.Handle)


def by_handle(doc: Any, handle: str) -> Any:
    """Resolve a drawing handle (the stable id this server hands out)."""
    h = str(handle).strip().lstrip("<").rstrip(">")
    try:
        return doc.HandleToObject(h)
    except pywintypes.com_error as exc:
        raise NotFound(
            f"No object with handle {handle!r} in {doc.Name}. Handles are per-drawing "
            "and change if the object is erased and recreated."
        ) from exc


def by_handles(doc: Any, handles: Iterable[str]) -> list[Any]:
    return [by_handle(doc, h) for h in handles]


def quiet(fn: Callable[[], T], default: T | None = None) -> T | None:
    try:
        return fn()
    except Exception:
        return default
