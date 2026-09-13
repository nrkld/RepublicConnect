"""Сбор интерактивных целей через Windows UI Automation (кнопки, ссылки, ярлыки).

Стратегия скорости: опрашиваем только активное окно + ярлыки рабочего стола,
дерево кэшируем в фоновом потоке (2 Гц). Цикл курсора кэш только читает.
Без uiautomation / вне Windows — пустой список (магнит просто выключен).
"""
import threading
import time

try:
    import ctypes
    _u32 = ctypes.windll.user32

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def _desktop_hwnd():
        try:
            return _u32.FindWindowW("Progman", None)
        except Exception:
            return 0

    def _fg_hwnd():
        try:
            return _u32.GetForegroundWindow()
        except Exception:
            return 0

    def _root_of(hwnd):
        try:
            return _u32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT
        except Exception:
            return hwnd

    def _visible_root(x, y):
        """Корень окна, реально видимого в точке (наш оверлей пропускаем)."""
        from .overlay import OVERLAY_HWNDS
        try:
            hwnd = _u32.WindowFromPoint(_POINT(int(x), int(y)))
            guard = 0
            while hwnd in OVERLAY_HWNDS and guard < 8:
                hwnd = _u32.GetWindow(hwnd, 2)  # GW_HWNDNEXT — окно под нами
                guard += 1
            return _root_of(hwnd)
        except Exception:
            return 0
except Exception:
    def _desktop_hwnd():
        return 0

    def _fg_hwnd():
        return 0

    def _root_of(hwnd):
        return hwnd

    def _visible_root(x, y):
        return 0

try:
    import uiautomation as auto
    _HAS_UIA = True
except Exception:
    auto = None
    _HAS_UIA = False

from . import config as C
from .snap import Target

WANT_TYPES = None  # заполняется лениво, т.к. auto может отсутствовать
STRICT_TYPES = None


def _strict_want():
    """Только настоящие контролы: кнопки, ссылки, меню, табы, чекбоксы."""
    global STRICT_TYPES
    if STRICT_TYPES is None:
        STRICT_TYPES = {
            auto.ControlType.ButtonControl,
            auto.ControlType.HyperlinkControl,
            auto.ControlType.MenuItemControl,
            auto.ControlType.TabItemControl,
            auto.ControlType.CheckBoxControl,
            auto.ControlType.RadioButtonControl,
            auto.ControlType.SplitButtonControl,
        }
    return STRICT_TYPES


def _accept(ctype, action_fn, desktop=False, strict=False):
    """Принимать ли элемент как цель. action_fn() лениво проверяет паттерны."""
    if auto is None:
        return False
    if ctype in _strict_want():
        return True
    if strict:
        # ярлыки рабочего стола — ListItem, их оставляем
        return bool(desktop) and ctype == auto.ControlType.ListItemControl
    if ctype in _want():
        return True
    if ctype in _invoke_extra():
        try:
            return bool(action_fn())
        except Exception:
            return False
    return False


def _default_strict():
    return bool(getattr(C, "MAGNET_STRICT", False))
MIN_SIZE = 8
MAX_DEPTH = 10        # обычные приложения: дерево мелкое
BROWSER_DEPTH = 26    # веб-страницы: ссылки лежат на глубине 23-24 (замер)
BROWSER_CLASSES = ("Chrome_WidgetWin_", "MozillaWindowClass", "ApplicationFrameWindow")
HYPERLINK_KIND = "50005"


def _want():
    global WANT_TYPES
    if WANT_TYPES is None:
        WANT_TYPES = {
            auto.ControlType.ButtonControl,
            auto.ControlType.HyperlinkControl,
            auto.ControlType.MenuItemControl,
            auto.ControlType.TabItemControl,
            auto.ControlType.CheckBoxControl,
            auto.ControlType.RadioButtonControl,
            auto.ControlType.ListItemControl,
            auto.ControlType.TreeItemControl,
            auto.ControlType.SplitButtonControl,
        }
    return WANT_TYPES


def _is_browser(root):
    try:
        cls = root.ClassName or ""
        return cls.startswith(BROWSER_CLASSES)
    except Exception:
        return False


def _fg_root_control(fg_root, fg):
    try:
        if fg_root:
            c = auto.ControlFromHandle(fg_root)
            if c is not None:
                return c
    except Exception:
        pass
    return fg


# Типы, которые кликабельны не всегда: берём только если есть «действующий»
# паттерн — Invoke / Toggle / ExpandCollapse / SelectionItem / ссылка MSAA.
# (картинки-ссылки, карточки видео, чекбоксы-кастом, пункты списков —
# всё, что показывает «руку»).
INVOKE_EXTRA = None

# ID UIA-паттернов: Invoke 10000, ExpandCollapse 10005, Toggle 10015,
# SelectionItem 10010. LegacyIAccessible роль ссылки = 30.
_ACTION_PATTERNS = (10000, 10015, 10005, 10010)


def _invoke_extra():
    global INVOKE_EXTRA
    if INVOKE_EXTRA is None:
        INVOKE_EXTRA = {
            auto.ControlType.ImageControl,
            auto.ControlType.CustomControl,
            auto.ControlType.DataItemControl,
            auto.ControlType.TextControl,
        }
    return INVOKE_EXTRA


def _has_action(el):
    for pid in _ACTION_PATTERNS:
        try:
            el.GetPattern(pid)
            return True
        except Exception:
            continue
    try:  # старая добрая MSAA-ссыллка (SysLink и т.п.)
        if el.GetLegacyIAccessiblePattern().Role == 30:
            return True
    except Exception:
        pass
    return False


def _has_invoke(el):
    return _has_action(el)


def foreground_hwnd():
    """HWND активного окна для трекинга смены фокуса (дешёвый вызов)."""
    return _fg_hwnd()


def _walk(root, out, depth, desktop=False, strict=False):
    try:
        for el, _depth in auto.WalkControl(root, maxDepth=depth):
            try:
                ctype = el.ControlType
                if not _accept(ctype, lambda el=el: _has_invoke(el),
                               desktop=desktop, strict=strict):
                    continue
                if not el.IsEnabled or el.IsOffscreen:
                    continue
                r = el.BoundingRectangle
                if r.width() < MIN_SIZE or r.height() < MIN_SIZE:
                    continue
                out.append(Target.from_rect(
                    float(r.left), float(r.top), float(r.right), float(r.bottom),
                    name=str(el.Name or "")[:60], kind=str(int(el.ControlType))))
            except Exception:
                continue
    except Exception:
        pass


def collect_once(strict=None):
    """Синхронный сбор: активное окно + рабочий стол. Для диагностики.

    Оставляем только то, что реально видно поверх (проверка z-порядка):
    кнопки окон на заднем плане и перекрытые ярлыки отпадают.
    strict=None -> из конфига MAGNET_STRICT.
    Возвращает (targets, is_browser, weblinks, fg_hwnd).
    """
    if strict is None:
        strict = _default_strict()
    if not _HAS_UIA:
        return [], False, 0, 0
    fg_hwnd = _fg_hwnd()
    fg_root = _root_of(fg_hwnd) if fg_hwnd else 0
    desk_hwnd = _desktop_hwnd()
    out = []
    desk = []
    is_browser = False
    try:
        fg = auto.GetForegroundControl()
        is_browser = _is_browser(_fg_root_control(fg_root, fg))
        raw = []
        _walk(fg, raw, BROWSER_DEPTH if is_browser else MAX_DEPTH, strict=strict)
        try:
            fg_now = _fg_hwnd()
        except Exception:
            fg_now = fg_hwnd
        if fg_now != fg_hwnd:
            fg_hwnd = fg_now or fg_hwnd
            raw = []
            is_browser = False
        if fg_root:
            out.extend(t for t in raw if _visible_root(t.cx, t.cy) == fg_root)
        else:
            out.extend(raw)
    except Exception:
        pass
    # ярлыки рабочего стола — только те, что реально видны поверх
    # (не перекрыты активным окном)
    try:
        desk_hwnds = {desk_hwnd} if desk_hwnd else set()
        root = auto.GetRootControl()
        for child in root.GetChildren():
            try:
                if child.ClassName in ("Progman", "WorkerW"):
                    try:
                        desk_hwnds.add(int(child.NativeWindowHandle or 0))
                    except Exception:
                        pass
                    _walk(child, desk, MAX_DEPTH, desktop=True, strict=strict)
            except Exception:
                continue
        desk_hwnds.discard(0)
        if desk_hwnds:
            out.extend(t for t in desk if _visible_root(t.cx, t.cy) in desk_hwnds)
        else:
            out.extend(desk)
    except Exception:
        pass
    weblinks = sum(1 for t in out if t.kind == HYPERLINK_KIND)
    return out, is_browser, weblinks, fg_hwnd


class TargetCache:
    """Фоновое обновление списка целей. Потокобезопасно для чтения."""

    def __init__(self, interval=0.5, strict=None):
        self.interval = interval
        self.strict = _default_strict() if strict is None else bool(strict)
        self._targets = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()  # досрочное обновление (смена фокуса)
        self._thread = None
        self.supported = bool(_HAS_UIA)
        self.last_ms = 0.0
        self.last_count = 0
        self.last_is_browser = False
        self.last_weblinks = 0
        self.last_fg = 0

    def start(self):
        if self._thread is None and _HAS_UIA:
            self._stop.clear()
            self._wake.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def stop(self, timeout=2.0):
        self._stop.set()
        self._wake.set()
        th, self._thread = self._thread, None
        if th is not None and th.is_alive():
            try:
                th.join(timeout=timeout)
            except Exception:
                pass

    def request_refresh(self):
        self._wake.set()

    def clear(self):
        with self._lock:
            self._targets = []
            self.last_count = 0

    def _loop(self):
        # COM требует CoInitialize в каждом потоке — иначе
        # [WinError -2147221008] CoInitialize / cannot load UIAutomationCore.dll
        with auto.UIAutomationInitializerInThread():
            while not self._stop.is_set():
                t0 = time.time()
                try:
                    ts, is_browser, weblinks, fg = collect_once(strict=self.strict)
                except Exception:
                    ts, is_browser, weblinks, fg = [], False, 0, 0
                with self._lock:
                    self._targets = ts
                    self.last_ms = (time.time() - t0) * 1000
                    self.last_count = len(ts)
                    self.last_is_browser = is_browser
                    self.last_weblinks = weblinks
                    self.last_fg = fg
                self._wake.wait(self.interval)
                self._wake.clear()

    def get(self):
        with self._lock:
            return list(self._targets)
