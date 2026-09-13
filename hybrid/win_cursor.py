"""Единственный владелец системного курсора (канон Фазы 1).

Собрано из eyeconnect/ui/cursor.py (set_sys_cursor/do_click/screen_size) и
magnetcursor/service.py (get_pos/set_pos/pressed/DPI). Только stdlib + ctypes.
Вне Windows — безопасные заглушки (как targets.py деградирует в []).
"""
import ctypes
import sys

IS_WIN = sys.platform == "win32"


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def ensure_dpi_aware():
    """Per-monitor DPI, иначе координаты UIA и SetCursorPos разъезжаются. Никогда не бросает."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_pos():
    """Текущая позиция курсора. Вне Windows — (0, 0)."""
    if not IS_WIN:
        return 0, 0
    try:
        p = _Point()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y
    except Exception:
        return 0, 0


def set_pos(x, y):
    """Поставить курсор. True если ОС подтвердила (BOOL != 0)."""
    if not IS_WIN:
        return False
    try:
        ok = ctypes.windll.user32.SetCursorPos(int(x), int(y))
        return bool(ok)
    except Exception:
        return False


# Совместимость с eyeconnect (там зовётся set_sys_cursor).
set_sys_cursor = set_pos


def do_click(x, y, button="left"):
    """Клик в точке: двигает курсор + mouse_event. Вне Windows — False."""
    if button not in ("left", "right"):
        raise ValueError(f"unknown button: {button!r}")
    if not IS_WIN:
        return False
    try:
        u = ctypes.windll.user32
        if not set_pos(x, y):
            return False
        if button == "right":
            u.mouse_event(0x0008, 0, 0, 0, 0)
            u.mouse_event(0x0010, 0, 0, 0, 0)
        else:
            u.mouse_event(0x0002, 0, 0, 0, 0)
            u.mouse_event(0x0004, 0, 0, 0, 0)
        return True
    except Exception:
        return False


def pressed(vk):
    """Асинхронное состояние клавиши (VK-код). Вне Windows — False."""
    if not IS_WIN:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def screen_size():
    """Размер экрана: Windows-метрики -> xrandr -> tkinter -> 1920x1080.

    Сначала ensure_dpi_aware, иначе метрики урезаны масштабом ОС
    (1707x1067 вместо настоящих 2560x1600) и калибровка ляжет не туда.
    """
    ensure_dpi_aware()
    try:
        u = ctypes.windll.user32
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        pass
    try:
        import shutil
        import subprocess
        if shutil.which("xrandr"):
            out = subprocess.run(["xrandr"], capture_output=True, text=True, timeout=3).stdout
            import re
            m = re.search(r"current\s+(\d+)\s*x\s*(\d+)", out)
            if m:
                return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    try:
        import tkinter as tk
        r = tk.Tk()
        try:
            r.withdraw()
            w, h = int(r.winfo_screenwidth()), int(r.winfo_screenheight())
        finally:
            try:
                r.destroy()
            except Exception:
                pass
        return w, h
    except Exception:
        return 1920, 1080
