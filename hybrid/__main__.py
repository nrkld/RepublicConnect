"""Точка входа гибрида (Фаза 1): диагностика без камеры и UIA.

  python -m hybrid --check    пресеты + snap самопроверка + win_cursor + профили
  python -m hybrid --migrate  скопировать legacy-профиль в ~/.eyeconnect_hybrid
  python -m hybrid --probe    живое окружение: мышь + eyeconnect/камера (если есть)
  python -m hybrid --source auto        гибридный цикл (взгляд+мышь+магнит)
  python -m hybrid --source gaze --no-magnet  чистый gaze-курсор
Запуск из корня Ramazan/ (чтобы `import hybrid` находился).
"""
import argparse

from . import __version__
from .config import get_preset
from . import win_cursor as wc
from . import profiles as prof
from .snap_core import Target, MagnetSnap


def cmd_check():
    print(f"hybrid {__version__} win={wc.IS_WIN}")
    for src in ("mouse", "gaze"):
        p = get_preset(src)
        print(f"preset {src}: capture={p['capture']} release={p['release']} "
              f"flick={p['flick']} cooldown={p['cooldown']} away={p['away_frames']}")
    # snap-самопроверка: захват центра + промах + гистерезис
    m = MagnetSnap(120, 180)
    t = Target.from_rect(100, 100, 200, 140, name="OK")
    sx, sy, got, snapped = m.update(90, 110, [t])
    assert snapped and got is t and (sx, sy) == (150.0, 120.0), (sx, sy, snapped)
    m.reset()
    sx, sy, got, snapped = m.update(900, 700, [t])
    assert not snapped and got is None and (sx, sy) == (900, 700)
    print("snap: OK (capture+miss)")
    # win_cursor: только чтение (без SetCursorPos/кликов — без побочек)
    wc.ensure_dpi_aware()
    x, y = wc.get_pos()
    assert isinstance(x, int) and isinstance(y, int), (x, y)
    assert wc.pressed(0x7B) in (True, False)
    w, h = wc.screen_size()
    assert w > 0 and h > 0, (w, h)
    print(f"win_cursor: OK (pos={x},{y} screen={w}x{h})")
    # профили: только resolve (ничего не создаём)
    print(f"gaze_npz: {prof.resolve_gaze_npz()}")
    print(f"gaze_meta: {prof.resolve_gaze_meta()}")
    print(f"hybrid_dir: {prof.hybrid_dir()}")
    print("HYBRID CHECK OK")
    return 0


def cmd_migrate():
    done = prof.migrate_legacy()
    if done:
        for name, dst in done.items():
            print(f"copied {name} -> {dst}")
    else:
        print("migrate: нечего копировать (legacy пуст или гибрид уже заполнен)")
    return 0


def cmd_probe():
    """Живое окружение: мышь всегда, eyeconnect/камера — если установлены."""
    from .providers import MouseProvider
    s = MouseProvider().poll()
    print(f"mouse: ({s.x:.0f},{s.y:.0f}) valid={s.valid}")
    try:
        from pathlib import Path
        import sys
        root = Path(__file__).resolve().parents[1]
        cand = root / "EyeConnect-Ramazan"
        if str(cand) not in sys.path:
            sys.path.insert(0, str(cand))
        from eyeconnect import config as C
        prof = C.PROFILE_DIR / "gaze.npz"
        print(f"eyeconnect: OK, профиль {prof} exists={prof.exists()}")
    except Exception as e:
        print(f"eyeconnect: недоступен ({e})")
        return 0
    try:
        from eyeconnect.gaze.capture import Camera
        cam = Camera(0)
        n = sum(1 for _ in range(5) if cam.read() is not None)
        print(f"camera: {n}/5 кадров")
        cam.release()
    except Exception as e:
        print(f"camera: недоступна ({e})")
    try:
        from eyeconnect.gaze.facemesh import FaceTracker  # только импорт, без модели
        print(f"tracker: {FaceTracker.__name__} импортируется")
    except Exception as e:
        print(f"tracker: недоступен ({e})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="hybrid", description="Hybrid cursor-core")
    ap.add_argument("--check", action="store_true", help="самопроверка без камеры/UIA")
    ap.add_argument("--migrate", action="store_true", help="скопировать legacy-профиль в гибрид")
    ap.add_argument("--probe", action="store_true", help="живое окружение: мышь + камера")
    ap.add_argument("--source", choices=["mouse", "gaze", "auto"], default=None,
                    help="запустить гибридный цикл с этим источником")
    ap.add_argument("--no-magnet", action="store_true", help="цикл без снапа (чистый курсор)")
    ap.add_argument("--no-wink-click", action="store_true", help="без кликов подмигиванием")
    ap.add_argument("--seconds", type=float, default=None, help="остановиться через N сек")
    ap.add_argument("--tracker", choices=["unigaze", "l2cs", "facemesh"], default="unigaze")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--recalib", action="store_true",
                    help="принудительная калибровка (~126 точек, ~4 мин)")
    ap.add_argument("--no-calib", action="store_true",
                    help="не калибровать даже без профиля (упадёт с подсказкой)")
    ap.add_argument("--fps", type=float, default=120.0, help="частота цикла, Гц")
    ap.add_argument("--no-dwell", action="store_true", help="без dwell-кликов")
    ap.add_argument("--dwell-s", type=float, default=1.2, help="фиксация для dwell-клика, сек")
    ap.add_argument("--strict", dest="strict", action="store_true",
                    help="магнит только по кнопкам/ссылкам/меню")
    ap.add_argument("--no-strict", dest="strict", action="store_false",
                    help="магнит по всему кликабельному (как раньше)")
    ap.set_defaults(strict=None)
    args = ap.parse_args(argv)
    if args.source:
        return cmd_run(args)
    if args.migrate:
        return cmd_migrate()
    if args.probe:
        return cmd_probe()
    return cmd_check()


def cmd_run(args):
    """Живой гибридный цикл: provider -> snap -> системный курсор. F12 — выход."""
    from . import engine
    recal = args.recalib
    if not recal and not args.no_calib and args.source != "mouse":
        reason = engine.needs_calibration(args.tracker)
        if reason == "нет профиля":
            print("Профиля нет — запускаю калибровку.")
            recal = True
        elif reason is not None:
            print(f"ВНИМАНИЕ: {reason} — продолжаю на старом "
                  "(--recalib для перекалибровки).")
    provider, close = engine.build_provider(args.source, tracker=args.tracker,
                                             camera=args.camera,
                                             no_wink=args.no_wink_click,
                                             recalibrate=recal)
    try:
        engine.run_loop(provider, source=args.source,
                        magnet=not args.no_magnet,
                        wink_click=not args.no_wink_click,
                        strict=args.strict,
                        dwell_click=not args.no_dwell,
                        dwell_s=args.dwell_s,
                        interval=1.0 / max(1.0, args.fps),
                        max_seconds=args.seconds)
    finally:
        try:
            close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
