"""Детектор промахов магнита: смотрит форму курсора системы.

Если курсор стал «рукой» (IDC_HAND — признак кликабельности), а у магнита
рядом нет цели — записываем промах (приложение + точка). Так находим всё,
что магнит пока не видит.
Запуск: python -m magnetcursor.handcheck. Поводи по кликабельному,
F12 — отчёт.
"""
import ctypes
import time
from collections import Counter

from .service import RELEASE_RADIUS, VK_F12, _set_dpi_aware, get_pos, pressed
from .targets import TargetCache

IDC_HAND = 32649


class _CursorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint),
                ("hCursor", ctypes.c_void_p), ("pt", ctypes.c_long * 2)]


def cursor_is_hand():
    try:
        u32 = ctypes.windll.user32
        ci = _CursorInfo()
        ci.cbSize = ctypes.sizeof(_CursorInfo)
        if not u32.GetCursorInfo(ctypes.byref(ci)):
            return False
        if not ci.hCursor:
            return False
        hand = u32.LoadCursorW(None, IDC_HAND)
        return ci.hCursor == hand
    except Exception:
        return False


def fg_name():
    try:
        import uiautomation as auto
        w = auto.GetForegroundControl()
        return f"{w.ClassName}|{(w.Name or '')[:40]}"
    except Exception:
        return "?"


def _report_path():
    from . import config as C
    return C.PROFILE_DIR / "handcheck_report.txt"


def _near_target(targets, x, y, radius):
    r2 = radius ** 2
    return any(max(t.left - x, 0, x - t.right) ** 2
               + max(t.top - y, 0, y - t.bottom) ** 2 <= r2 for t in targets)


def _write_report(misses):
    try:
        _report_path().parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    lines = [time.strftime("Handcheck otchyot %Y-%m-%d %H:%M:%S"), ""]
    if not misses:
        lines.append("promahov net — vsyo, chto dayot ruku, magnit vidit")
    else:
        for (app, gx, gy), n in misses.most_common(30):
            lines.append(f"{n}x {app} @~({gx},{gy})")
    _report_path().write_text("\n".join(lines), encoding="utf-8")
    return _report_path()


def main():
    _set_dpi_aware()
    cache = TargetCache(interval=0.5)
    cache.start()
    misses = Counter()
    last_report = 0.0
    print("Handcheck: vodi po klikabelnomu, F12 — otchyot.")
    try:
        while True:
            if pressed(VK_F12):
                break
            time.sleep(0.05)
            if not cursor_is_hand():
                continue
            x, y = get_pos()
            near = _near_target(cache.get(), x, y, RELEASE_RADIUS)
            if not near:
                key = (fg_name(), x // 100 * 100, y // 100 * 100)
                misses[key] += 1
                if time.time() - last_report > 2.0:
                    last_report = time.time()
                    print(f"promah: {key[0]} @~({key[1]},{key[2]})")
    finally:
        cache.stop()
    print("=== IT OG PROM AHOV ===")
    for (app, gx, gy), n in misses.most_common(20):
        print(f"{n}x {app} @~({gx},{gy})")
    if not misses:
        print("promahov net — vsyo, chto dayot ruku, magnit vidit")
    path = _write_report(misses)
    print(f"otchyot sohranyon: {path}")


if __name__ == "__main__":
    main()
