"""Магнит-курсор без трекинга глаз: вход — обычная мышь, выход — снап к целям.

Управление: F9 — вкл/выкл магнит, F12 — выход.
Запуск: python -m magnetcursor
"""
import ctypes
import math
import sys
import time

_IS_WIN = sys.platform == "win32"

from . import config as C
from .snap import MagnetSnap
from .targets import TargetCache, foreground_hwnd
from .overlay import Overlay, NullOverlay


# Фаза 1 (hybrid cursor-core): канон курсора — hybrid/win_cursor.py.
# Если hybrid найден рядом (корень Ramazan/), делегируем ему,
# иначе работаем локально как раньше (поведение не меняется).
def _load_hybrid_cursor():
    try:
        from hybrid import win_cursor as _wc
        return _wc
    except ImportError:
        pass
    try:
        from pathlib import Path as _Path
        import sys as _sys
        for _p in _Path(__file__).resolve().parents:
            if (_p / "hybrid" / "__init__.py").exists():
                if str(_p) not in _sys.path:
                    _sys.path.insert(0, str(_p))
                break
        from hybrid import win_cursor as _wc
        return _wc
    except Exception:
        return None


_wc = _load_hybrid_cursor()

VK_F9 = 0x78
VK_F12 = 0x7B

CAPTURE_RADIUS = getattr(C, "MAGNET_CAPTURE", 20.0)
RELEASE_RADIUS = getattr(C, "MAGNET_RELEASE", 35.0)
FLICK_PX = getattr(C, "MAGNET_FLICK_PX", 45.0)
COOLDOWN = getattr(C, "MAGNET_COOLDOWN", 0.6)
STRICT = bool(getattr(C, "MAGNET_STRICT", False))


def _set_dpi_aware():
    if _wc is not None:
        try:
            _wc.ensure_dpi_aware()
            return
        except Exception:
            pass
    if not _IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_pos():
    if _wc is not None:
        try:
            return _wc.get_pos()
        except Exception:
            pass
    if not _IS_WIN:
        return 0, 0
    try:
        p = _Point()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        return p.x, p.y
    except Exception:
        return 0, 0


def set_pos(x, y):
    if _wc is not None:
        try:
            _wc.set_pos(x, y)
            return
        except Exception:
            pass
    if not _IS_WIN:
        return
    try:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    except Exception:
        pass


def pressed(vk):
    if _wc is not None:
        try:
            return _wc.pressed(vk)
        except Exception:
            pass
    if not _IS_WIN:
        return False
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False


def _crash_log():
    return C.PROFILE_DIR / "magnet_crash.log"


def main():
    _set_dpi_aware()
    snap = MagnetSnap(CAPTURE_RADIUS, RELEASE_RADIUS, FLICK_PX)
    cache = TargetCache(interval=0.5, strict=STRICT)
    cache.start()
    try:
        ov = Overlay()
        ov.start()
    except Exception:
        ov = NullOverlay()
    on = True
    last_key = 0.0
    f9_down = False
    shown = None
    hinted_browser = False
    next_hint_check = 0.0
    next_count_push = 0.0
    last_set = get_pos()  # куда МЫ поставили курсор (отличие = движение пользователя)
    cooldown_until = 0.0
    print(f"Magnet ON (F9 toggle, F12 quit). capture={CAPTURE_RADIUS} release={RELEASE_RADIUS}")
    ov.set_state(True)
    try:
        while True:
            try:
                now = time.time()
                if pressed(VK_F12):
                    break
                try:
                    action = ov.poll_action()
                except Exception:
                    action = None
                if action == "quit":
                    break
                f9 = bool(pressed(VK_F9))
                if (((f9 and not f9_down) or action == "toggle") and now - last_key > 0.4):
                    on = not on
                    snap.reset()
                    ov.set_target(None)
                    ov.set_state(on)
                    shown = None
                    print("Magnet", "ON" if on else "OFF")
                    last_key = now
                    last_set = get_pos()
                f9_down = f9
                if on:
                    x, y = get_pos()
                    user_moved = math.hypot(x - last_set[0], y - last_set[1])
                    if now >= next_count_push:
                        next_count_push = now + 1.0
                        ov.set_count(cache.last_count)
                    # смена фокуса: старые цели недействительны — сбросить сразу,
                    # а не ждать фонового обновления (иначе липнет к заднему окну)
                    try:
                        fg = foreground_hwnd()
                    except Exception:
                        fg = 0
                    if fg and getattr(cache, "supported", True) and fg != cache.last_fg:
                        snap.reset()
                        cache.clear()
                        cache.request_refresh()
                        ov.set_target(None)
                        shown = None
                        last_set = (x, y)
                    if now >= next_hint_check:
                        next_hint_check = now + 5.0
                        if cache.last_is_browser and cache.last_weblinks <= 1:
                            if not hinted_browser:
                                hinted_browser = True
                                print("BROWSER: stranitsa ne vidna (net ssylok). "
                                      "Zakroy Chrome/Edge i zapusti raz s flagom "
                                      "--force-renderer-accessibility (mozhno dobavit v yarlyk), "
                                      "Firefox rabotaet srazu.")
                        else:
                            hinted_browser = False
                    if now < cooldown_until:
                        last_set = (x, y)  # пауза после вырывания — не трогаем
                    else:
                        if snap.current is not None and snap.note_movement(x, y, user_moved):
                            snap.reset()
                            cooldown_until = now + COOLDOWN
                            ov.set_target(None)
                            shown = None
                            print("otpustil — vyrvalis, pauza")
                            last_set = (x, y)
                        else:
                            sx, sy, t, snapped = snap.update(x, y, cache.get())
                            if snapped and (abs(sx - x) > 1 or abs(sy - y) > 1):
                                set_pos(sx, sy)
                                last_set = (sx, sy)
                            else:
                                last_set = (x, y)
                            key = (int(t.left), int(t.top), int(t.right), int(t.bottom)) if t else None
                            if key != shown:
                                shown = key
                                ov.set_target(key)
                                if t:
                                    print(f"snap: {t.name[:40]} ({int(sx)},{int(sy)})")
                else:
                    last_set = get_pos()
                time.sleep(1 / 60)
            except Exception as ex:
                # одна ошибка кадра не должна убивать сервис — пишем в лог
                try:
                    import traceback
                    try:
                        _crash_log().parent.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                    lp = _crash_log()
                    try:
                        if lp.exists() and lp.stat().st_size > 1000000:
                            lp.write_text("", encoding="utf-8")
                    except Exception:
                        pass
                    with open(lp, "a", encoding="utf-8") as f:
                        f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + repr(ex) + "\n")
                        traceback.print_exc(file=f)
                except Exception:
                    pass
                snap.reset()
                time.sleep(0.2)
    finally:
        ov.stop()
        cache.stop()
        print("targets_last:", cache.last_count, f"{cache.last_ms:.0f}ms")
        print("Vykhod.")


if __name__ == "__main__":
    main()
