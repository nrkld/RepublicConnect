"""Гибридный цикл (Фаза 3): provider -> snap -> один set_pos.

Владелец курсора здесь единственный: все движения идут через cursor.set_pos.
Источник — любой провайдер (Gaze/Mouse/Auto). Цели — magnetcursor.TargetCache
при наличии uiautomation, иначе пусто (цикл работает как чистый gaze-курсор).
Оверлей — magnetcursor.Overlay при наличии, иначе заглушка.

Клик подмигиванием — в СНАПНУТОЙ точке (выигрыш точности бесплатно).
Dwell-клик — в Фазе 4 (ClickRouter).
"""
import math
import time
from pathlib import Path

from . import win_cursor as _wc
from . import profiles as _prof
from .config import get_preset
from .snap_core import MagnetSnap
from .clicks import ClickRouter
from .providers import AsyncGaze, AutoProvider, MouseProvider

VK_F9 = 0x78
VK_F12 = 0x7B


class _NullTargets:
    """Заглушка кэша целей: магнит тихо выключен, курсор едет как есть."""

    def __init__(self, interval=0.5, strict=None):
        self.interval = interval
        self.strict = bool(strict) if strict is not None else False
        self.last_ms = 0.0
        self.last_count = 0
        self.last_is_browser = False
        self.last_weblinks = 0
        self.last_fg = 0

    def start(self):
        pass

    def stop(self):
        pass

    def request_refresh(self):
        pass

    def clear(self):
        pass

    def get(self):
        return []


class _NullOverlay:
    def start(self):
        pass

    def stop(self):
        pass

    def set_target(self, key):
        pass

    def set_state(self, on):
        pass

    def set_count(self, n):
        pass

    def poll_action(self):
        return None


def _ensure_repo_dir(repo_dir, package):
    """Добавить корень соседнего репо на sys.path (ищем repo_dir/package/__init__.py вверх)."""
    try:
        import sys
        for p in Path(__file__).resolve().parents:
            if (p / repo_dir / package / "__init__.py").exists():
                root = str(p / repo_dir)
                if root not in sys.path:
                    sys.path.insert(0, root)
                # сам корень тоже (на случай плоской раскладки)
                if str(p) not in sys.path:
                    sys.path.insert(0, str(p))
                return True
    except Exception:
        pass
    return False


def load_targets(interval=0.5, strict=None):
    """(cache, foreground_hwnd_fn): настоящее UIA или заглушки."""
    try:
        _ensure_repo_dir("magnetcursor", "magnetcursor")
        from magnetcursor.targets import TargetCache, foreground_hwnd
        return TargetCache(interval=interval, strict=strict), foreground_hwnd
    except Exception:
        return _NullTargets(interval=interval, strict=strict), lambda: 0


def load_overlay():
    """Оверлей magnetcursor или заглушка (как service.main)."""
    try:
        _ensure_repo_dir("magnetcursor", "magnetcursor")
        from magnetcursor.overlay import Overlay, NullOverlay
        try:
            ov = Overlay()
            ov.start()
            return ov
        except Exception:
            return NullOverlay()
    except Exception:
        return _NullOverlay()


def pick_compute_device():
    """Явный выбор дискретной GPU: первая не-интегрированная cuda-карта.
    -> ("cuda:N"|"cpu", имя устройства). Встроенные (Intel/Radeon/UHD) пропускаем."""
    try:
        import torch
        n = torch.cuda.device_count()
        if n <= 0:
            return "cpu", "cuda-устройств нет"
        names = []
        for i in range(n):
            try:
                names.append(torch.cuda.get_device_name(i))
            except Exception:
                names.append(f"cuda:{i}")

        def _integrated(nm):
            nm = nm.lower()
            return any(k in nm for k in ("intel", "uhd", "iris", "radeon",
                                         "vega", "apple", "integrated"))
        order = sorted(range(n), key=lambda i: (_integrated(names[i]), i))
        return f"cuda:{order[0]}", names[order[0]]
    except Exception as e:
        return "cpu", f"torch/cuda недоступны ({e})"


def needs_calibration(tracker="unigaze", home=None):
    """Нужна ли калибровка: нет профиля или он от другого экрана/трекера.
    -> причина строкой или None (профиль годится). home — для тестов."""
    if _prof.resolve_gaze_npz(home=home) is None:
        return "нет профиля"
    try:
        import json
        W, H = _wc.screen_size()
        m = _prof.resolve_gaze_meta(home=home)
        if m is None:
            return "нет метаданных"
        meta = json.loads(m.read_text(encoding="utf-8"))
    except Exception as e:
        return f"битые метаданные ({e})"
    if not isinstance(meta, dict):
        return "битые метаданные (не словарь)"
    if meta.get("screen_w") != W or meta.get("screen_h") != H:
        return (f"профиль {meta.get('screen_w')}x{meta.get('screen_h')}, "
                f"экран {W}x{H}")
    if meta.get("tracker", "facemesh") != tracker:
        return f"профиль от {meta.get('tracker')}, нужен {tracker}"
    return None


def build_gaze_provider(tracker="unigaze", camera=0, no_wink=False, recalibrate=False):
    """Настоящий GazeProvider из eyeconnect (камера + калибровка/профиль).

    recalibrate=True -> fullscreen-калибровка (126 равноудалённых точек на весь
    экран, края/углы включены) при каждом старте; отмена (Esc) или провал ->
    откат на сохранённый профиль. Профиля нет вообще -> RuntimeError с подсказкой.
    Возвращает (provider, close).
    """
    _ensure_repo_dir("EyeConnect-Ramazan", "eyeconnect")
    from eyeconnect import config as C  # noqa
    from eyeconnect.gaze.capture import Camera
    from eyeconnect.main import make_tracker
    from eyeconnect.gaze.filter import GazeFilter
    from eyeconnect.gaze.regressor import load_mapper

    W, H = _wc.screen_size()
    print(f"Экран: {W}x{H}")
    device, gpu_name = pick_compute_device()
    print(f"GPU-анализ: {gpu_name} [{device}]")
    if device.startswith("cuda"):
        try:
            import os
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", device.split(":")[1])
        except Exception:
            pass
    cam = Camera(camera)
    tr = make_tracker(tracker)
    if not no_wink:
        from eyeconnect.gaze.wink import WinkTracker
        tr = WinkTracker(inner=tr)  # левое=ЛКМ, правое=ПКМ
    try:  # прогрев детектора живыми кадрами: ленивые аллокации/CUDA — сейчас, а не в цикле
        for _ in range(3):
            f = cam.read()
            if f is None:
                break
            try:
                tr.process(f)
            except Exception:
                break
        print("Прогрев детектора: OK")
    except Exception:
        pass
    filt = GazeFilter()
    reg = None
    if recalibrate:
        from eyeconnect.ui.cursor import fullscreen_calibrate
        avg_s = 1.0 if tracker in ("l2cs", "unigaze") else None
        print("Калибровка: 126 точек на весь экран (~4 мин). "
              "Сядь 60см, смотри на красную точку. ПРОБЕЛ — начать, Esc — отмена.")
        try:
            reg, W, H = fullscreen_calibrate(cam, tr, filt, tracker, avg_s,
                                             grid=("auto", 126), dwell_s=None, wait=True)
        except RuntimeError as e:
            print(f"Калибровка не удалась ({e}) — пробую сохранённый профиль")
            reg = None
    if reg is None:
        prof_npz = _prof.resolve_gaze_npz()
        if prof_npz is None:
            raise RuntimeError(
                "Нет профиля gaze.npz — сначала калибровка:\n"
                "  python -m eyeconnect.main --mode calibrate  (из EyeConnect-Ramazan/)")
    try:
        import json
        meta_p = _prof.resolve_gaze_meta()
        if meta_p is not None:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            if meta.get("screen_w") != W or meta.get("screen_h") != H:
                print(f"Профиль от экрана {meta.get('screen_w')}x{meta.get('screen_h')}, "
                      f"сейчас {W}x{H} — точность упадёт, перекалибруйте.")
            if meta.get("tracker", "facemesh") != tracker:
                print(f"Профиль от трекера {meta.get('tracker')}, сейчас {tracker} — "
                      f"маппинг не совпадёт, перекалибруйте.")
    except Exception:
        pass
    from .providers import GazeProvider
    if reg is None:
        reg = load_mapper(prof_npz)

    def close():
        try:
            tr.close()
        except Exception:
            pass
        try:
            cam.release()
        except Exception:
            pass

    return GazeProvider(cam, tr, GazeFilter(), reg, W, H), close


def build_provider(source="auto", tracker="unigaze", camera=0, no_wink=False,
                   recalibrate=False):
    """(provider, close) под source: mouse|gaze|auto."""
    if source == "mouse":
        return MouseProvider(), lambda: None
    gaze, close_gaze = build_gaze_provider(tracker, camera, no_wink, recalibrate)
    ag = AsyncGaze(gaze)
    print("Прогрев потока инференса (первые кадры медленные, ~1 мин)...")
    ag.start(warmup_polls=3)
    print("Поток инференса готов.")

    def close():
        try:
            ag.stop()
        except Exception:
            pass
        try:
            close_gaze()
        except Exception:
            pass

    if source == "gaze":
        return ag, close
    return AutoProvider(ag, MouseProvider()), close


def run_loop(provider, source="auto", magnet=True, wink_click=True, strict=None,
             dwell_click=True, dwell_s=1.2, dwell_radius=45.0,
             targets=None, overlay=None, cursor=None,
             capture=None, release=None, flick=None, cooldown=None,
             away_frames=None, interval=1 / 120, max_iters=None,
             max_seconds=None, time_fn=None, sleep_fn=None, on_frame=None):
    """Главный цикл. cursor/targets/overlay инжектятся (тесты подсовывают фейки)."""
    cur = cursor if cursor is not None else _wc
    tfn = time_fn or time.time
    sfn = sleep_fn or time.sleep
    preset = get_preset("mouse" if source == "mouse" else "gaze")
    cap = capture if capture is not None else preset["capture"]
    rel = release if release is not None else preset["release"]
    flk = flick if flick is not None else preset["flick"]
    awy = away_frames if away_frames is not None else preset["away_frames"]
    cool = cooldown if cooldown is not None else preset["cooldown"]
    snap = MagnetSnap(cap, rel, flk, awy)
    router = ClickRouter(dwell_s, dwell_radius, dwell_on=dwell_click,
                         wink_on=wink_click, time_fn=tfn)

    own_cache = targets is None
    cache, fg_fn = ((targets, lambda: 0) if targets is not None
                     else load_targets(strict=strict))
    if targets is not None and not isinstance(targets, list):
        try:
            if not hasattr(targets, "last_fg"):
                cache.last_fg = 0
        except Exception:
            pass
    ov = overlay if overlay is not None else load_overlay()

    def note(x, y):
        fn = getattr(provider, "note_output", None)
        if callable(fn):
            try:
                fn(x, y)
            except Exception:
                pass

    def _fire(sample, snapped, out):
        """Решение роутера + физический клик (координаты — снапнутая точка)."""
        ev = router.update(sample, snapped, out[0], out[1])
        if ev is None or not getattr(cur, "IS_WIN", True):
            return
        do_click = getattr(cur, "do_click", None)
        if not callable(do_click):
            return
        ok = do_click(ev.x, ev.y, button="right" if ev.kind == "right" else "left")
        label = {"right": "RIGHT CLICK!", "left": "LEFT CLICK!",
                 "dwell": "DWELL CLICK!"}.get(ev.kind, "CLICK!")
        print(label if ok else "click N/A")

    def crash_log(ex):
        try:
            import traceback
            try:
                _prof.ensure_hybrid_dir()
            except Exception:
                pass
            lp = _prof.crash_log_path()
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

    try:
        try:
            cache.start()
        except Exception:
            pass
        try:
            ov.set_state(True)
        except Exception:
            pass
        try:
            fn = getattr(cur, "ensure_dpi_aware", None)
            if callable(fn):
                fn()
        except Exception:
            pass
        on = True
        last_key = 0.0
        shown = None
        hinted_browser = False
        next_hint_check = 0.0
        next_count_push = 0.0
        try:
            last_out = cur.get_pos()
        except Exception:
            last_out = (0.0, 0.0)
        cooldown_until = 0.0
        iters = 0
        t_start = tfn()
        deadline = None if max_seconds is None else t_start + max_seconds
        print(f"Hybrid ON (source={source} magnet={'on' if magnet else 'off'}; "
              f"F9 toggle, F12 quit). capture={cap} release={rel}")
        while True:
            if max_iters is not None and iters >= max_iters:
                break
            if deadline is not None and tfn() >= deadline:
                break
            iters += 1
            try:
                now = tfn()
                if cur.pressed(VK_F12):
                    break
                try:
                    action = ov.poll_action()
                except Exception:
                    action = None
                if action == "quit":
                    break
                if ((cur.pressed(VK_F9) or action == "toggle") and now - last_key > 0.4):
                    on = not on
                    snap.reset()
                    router.reset()
                    try:
                        ov.set_target(None)
                        ov.set_state(on)
                    except Exception:
                        pass
                    shown = None
                    print("Magnet", "ON" if on else "OFF")
                    last_key = now
                    last_out = cur.get_pos()
                if not on:
                    last_out = cur.get_pos()
                    note(*last_out)
                    router.note_invalid()
                    sfn(interval)
                    continue
                sample = provider.poll()
                if not sample.valid:
                    ax, ay = cur.get_pos()
                    note(ax, ay)
                    router.note_invalid()
                    sfn(interval)
                    continue
                ix, iy = sample.x, sample.y
                try:
                    fg = fg_fn()
                except Exception:
                    fg = 0
                if fg and fg != getattr(cache, "last_fg", 0):
                    snap.reset()
                    try:
                        cache.clear()
                        cache.request_refresh()
                        ov.set_target(None)
                    except Exception:
                        pass
                    shown = None
                    try:
                        last_out = cur.get_pos()
                    except Exception:
                        last_out = (ix, iy)
                if now >= next_count_push:
                    next_count_push = now + 1.0
                    try:
                        ov.set_count(getattr(cache, "last_count", 0))
                    except Exception:
                        pass
                if now >= next_hint_check:
                    next_hint_check = now + 5.0
                    if (not hinted_browser and getattr(cache, "last_is_browser", False)
                            and getattr(cache, "last_weblinks", 0) <= 1):
                        hinted_browser = True
                        print("BROWSER: страница не видна (нет ссылок). "
                              "Chrome/Edge — с флагом --force-renderer-accessibility, "
                              "Firefox работает сразу.")
                tgts = []
                if magnet and on:
                    try:
                        tgts = list(cache) if isinstance(cache, list) else list(cache.get())
                    except Exception:
                        tgts = []
                if now < cooldown_until:
                    # пауза после вырывания — не трогаем; якорь = факт (как last_set)
                    ax, ay = cur.get_pos()
                    last_out = (ax, ay)
                    note(*last_out)
                else:
                    if sample.src == "mouse":
                        ax, ay = cur.get_pos()
                        user_moved = math.hypot(ax - last_out[0], ay - last_out[1])
                        if (snap.current is not None
                                and snap.note_movement(ax, ay, user_moved)):
                            snap.reset()
                            cooldown_until = now + cool
                            try:
                                ov.set_target(None)
                            except Exception:
                                pass
                            shown = None
                            print("отпустил — вырвались, пауза")
                            last_out = (ax, ay)
                            note(*last_out)
                        else:
                            sx, sy, t, snapped = snap.update(ax, ay, tgts)
                            out = (sx, sy) if snapped else (ax, ay)
                            if math.hypot(out[0] - last_out[0], out[1] - last_out[1]) > 1:
                                cur.set_pos(out[0], out[1])
                            last_out = out
                            note(*last_out)
                            key = (t.left, t.top, t.right, t.bottom) if t else None
                            if key != shown:
                                shown = key
                                try:
                                    ov.set_target(key)
                                except Exception:
                                    pass
                                if t:
                                    print(f"snap: {t.name[:40]} ({int(out[0])},{int(out[1])})")
                            _fire(sample, snapped, out)
                    else:  # gaze: курсор ведём мы, всегда ставим
                        sx, sy, t, snapped = snap.update(ix, iy, tgts)
                        out = (sx, sy) if snapped else (ix, iy)
                        if math.hypot(out[0] - last_out[0], out[1] - last_out[1]) > 1:
                            cur.set_pos(out[0], out[1])
                        last_out = out
                        note(*last_out)
                        key = (t.left, t.top, t.right, t.bottom) if t else None
                        if key != shown:
                            shown = key
                            try:
                                ov.set_target(key)
                            except Exception:
                                pass
                            if t:
                                print(f"snap: {t.name[:40]} ({int(out[0])},{int(out[1])})")
                        _fire(sample, snapped, out)
                if on_frame is not None:
                    try:
                        on_frame(sample, last_out)
                    except Exception:
                        pass
                sfn(interval)
            except Exception as ex:
                crash_log(ex)
                snap.reset()
                sfn(0.2)
    finally:
        for fin in (getattr(ov, "stop", None),
                    cache.stop if own_cache else None):
            try:
                if callable(fin):
                    fin()
            except Exception:
                pass
        try:
            print("targets_last:", getattr(cache, "last_count", 0),
                  f"{getattr(cache, 'last_ms', 0.0):.0f}ms")
        except Exception:
            pass
        try:
            el = max(tfn() - t_start, 1e-6)
            print(f"цикл: {iters} кадров, {iters / el:.1f} Гц")
            st = getattr(provider, "stats", None)
            if callable(st):
                d = st() or {}
                if d.get("polls"):
                    print(f"gaze-инференс: {d['polls']} кадров, "
                          f"{d.get('hz', 0.0):.1f} Гц, "
                          f"кадр {d.get('last_ms', 0.0):.0f}мс, "
                          f"ошибок {d.get('errors', 0)}, поток жив={d.get('alive')}")
        except Exception:
            pass
        print("Выход.")
