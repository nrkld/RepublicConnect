"""Полноэкранный курсор взгляда: калибровка на весь экран + крестик за взглядом.

Плюс опционально двигает настоящий системный курсор Windows (ctypes),
чтобы было видно точку взгляда поверх любых окон после выхода (Esc сворачивает).
"""
import ctypes
import json
import time
import cv2
import numpy as np

from .. import config as C
from ..gaze.regressor import GazeRegressor, load_mapper
from ..gaze.normalize import is_saccade
from .calibration import grid_points


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


def screen_size():
    if _wc is not None:
        try:
            return _wc.screen_size()
        except Exception:
            pass
    # Windows
    try:
        u = ctypes.windll.user32  # type: ignore[attr-defined]
        return int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
    except Exception:
        pass
    # Linux: xrandr без GUI-зависимостей
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
        r.withdraw()
        w, h = int(r.winfo_screenwidth()), int(r.winfo_screenheight())
        r.destroy()
        return w, h
    except Exception:
        return 1920, 1080


def meta_path():
    return C.PROFILE_DIR / "gaze_meta.json"


def save_profile(reg, W, H, tracker="facemesh"):
    """Единая точка сохранения профиля + meta (экран + трекер + маппер). Фиксит конфликт 1280x720 vs fullscreen."""
    C.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    reg.save(C.PROFILE_DIR / "gaze.npz")
    meta_path().write_text(json.dumps({"screen_w": int(W), "screen_h": int(H),
                                        "tracker": tracker,
                                        "mapper": getattr(reg, "kind", "poly")}), encoding="utf-8")


def fullscreen_calibrate(cam, tracker, filt, tracker_name="facemesh", avg_s=None,
                         grid=None, dwell_s=None, wait=True, margin=None):
    """Калибровка serpentine на весь экран (126 равноудалённых точек). Возвращает (reg, W, H)."""
    from ..gaze.normalize import robust_mean, is_saccade
    from .calibration import grid_points, wait_for_start
    W, H = screen_size()
    nspec = ("auto", C.CALIB_POINTS)
    mgn = float(margin) if margin is not None else C.CALIB_MARGIN
    pts = grid_points(W, H, n=nspec, margin=mgn, serpentine=True)
    dwell = float(dwell_s) if dwell_s else C.CALIBDWELL_S
    avg_window = float(avg_s) if avg_s else float(C.CALIB_AVG_S)
    win = "EyeConnect: smotri na krasnuyu tochku"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    if wait:
        total = len(pts) * (dwell + 0.3)
        try:
            wait_for_start(win, [f"Tochek: {len(pts)}, ~{total:.0f} sek.",
                                 "Syad 60sm, smotri na krasnuyu tochku.",
                                 "PROBEL/klik — nachat, Esc — otmena."], w=W, h=H)
        except KeyboardInterrupt:
            cv2.destroyWindow(win)
            raise RuntimeError("Kalibrovka ne nachata.")
    feats, screens = [], []
    try:
        for i, (sx, sy) in enumerate(pts):
            filt.reset()
            t_start = time.time()
            t_settle = t_start + C.CALIB_SETTLE_S
            t_end = t_start + dwell
            t_avg = t_end - avg_window
            buf = []
            prev = None
            n_total, n_ok, n_cut = 0, 0, 0
            while time.time() < t_end:
                f = cam.read()
                if f is None:
                    continue
                feat, conf, _ = tracker.process(f)
                n_total += 1
                now = time.time()
                if feat is not None and conf >= C.MP_MIN_CONF:
                    if prev is not None and is_saccade(prev, feat):
                        n_cut += 1
                        filt.reset()
                        prev = None
                        continue
                    prev = feat
                    n_ok += 1
                    sm = filt.update(feat)
                    if now >= t_avg and now >= t_settle:
                        buf.append(np.asarray(sm, dtype=float))
                else:
                    filt.reset()
                    prev = None
                canvas = np.zeros((H, W, 3), np.uint8)
                if now < t_settle:
                    cv2.circle(canvas, (int(sx), int(sy)), 18, (0, 165, 255), 3)
                else:
                    # маленькая точка (r=12): точнее фиксация взгляда
                    cv2.circle(canvas, (int(sx), int(sy)), 12, (0, 0, 255), -1)
                    cv2.circle(canvas, (int(sx), int(sy)), 18, (255, 255, 255), 2)
                remain = max(0.0, t_end - now)
                cv2.putText(canvas, f"{i+1}/{len(pts)} smotri {remain:.1f}s det {n_ok}/{max(1,n_total)} cut {n_cut}",
                            (60, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
                cv2.imshow(win, canvas)
                if cv2.waitKey(1) & 0xFF == 27:
                    raise KeyboardInterrupt
            if buf:
                det_rate = n_ok / max(1, n_total)
                if det_rate < 0.3:
                    print(f"Tochka {i+1}: malo detekciy ({det_rate:.0%}) — propushena")
                    continue
                m, s, nin, ntot = robust_mean(buf)
                feats.append(m)
                screens.append((sx, sy))
            else:
                print(f"Tochka {i+1}: lico teryalos — propushena")
    except KeyboardInterrupt:
        print("Kalibrovka prervana (Esc)")
    finally:
        cv2.destroyWindow(win)
    need = max(4, len(pts) // 4)
    if len(feats) < need:
        raise RuntimeError(f"Malo tochek ({len(feats)}/{len(pts)}, nuzhno {need}): lico teryalos. Syad blizhe (60sm) i povtori.")
    reg = GazeRegressor().fit(np.array(feats), np.array(screens))
    save_profile(reg, W, H, tracker_name)
    print(f"Kalibrovka OK: {len(feats)}/{len(pts)} tochek, ekran {W}x{H}")
    return reg, W, H


def load_or_calibrate(cam, tracker, filt, force=False, tracker_name="facemesh", avg_s=None,
                      grid=None, dwell_s=None, wait=True, margin=None):
    prof = C.PROFILE_DIR / "gaze.npz"
    W, H = screen_size()
    if not force and prof.exists() and meta_path().exists():
        try:
            meta = json.loads(meta_path().read_text(encoding="utf-8"))
            if meta.get("screen_w") == W and meta.get("screen_h") == H and \
                    meta.get("tracker", "facemesh") == tracker_name:
                return load_mapper(prof), W, H
            print(f"Profil ustarel ({meta} -> {W}x{H}/{tracker_name}), perekalibrovka")
        except Exception as e:
            print(f"Profil bityy ({e}), perekalibrivka")
    return fullscreen_calibrate(cam, tracker, filt, tracker_name, avg_s,
                                grid=grid, dwell_s=dwell_s, wait=wait, margin=margin)


def set_sys_cursor(x, y):
    if _wc is not None:
        try:
            return bool(_wc.set_pos(x, y))
        except Exception:
            pass
    try:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def do_click(x, y, button="left"):
    """Клик: Windows — mouse_event, Linux — без зависимостей молча True/False."""
    if _wc is not None:
        try:
            return bool(_wc.do_click(x, y, button=button))
        except Exception:
            pass
    try:
        u = ctypes.windll.user32  # type: ignore[attr-defined]
        u.SetCursorPos(int(x), int(y))
        if button == "right":
            u.mouse_event(0x0008, 0, 0, 0, 0)  # RIGHTDOWN
            u.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTUP
        else:
            u.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
            u.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
        return True
    except Exception:
        return False


def run_cursor(cam, tracker, filt, reg, W, H, syscursor=True, click=False, click_dwell_ms=1200,
               overlay=True, jump_px=500, wink=True):
    """Курсор взглядом.
    overlay=True — старое полноэкранное чёрное окно с крестиком.
    overlay=False — курсор-мышь поверх обычных окон: двигает системный курсор,
      показывает только маленькое окно камеры-статуса (не мешает работать).
    jump_px — если предсказание прыгнуло дальше (моргание/потеря), кадр
      пропускаем: системный курсор не дёргается.
    wink — подмигивания из dbg['wink']: left=ЛКМ, right=ПКМ (авто-dwell-клик
      для этого не нужен; click=... оставлен как опция).
    """
    win = "EyeConnect vzglyad (Q/Esc - vyhod)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    if overlay:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    else:
        cv2.resizeWindow(win, 640, 400)
    mode = " + dwell-click" if click else ""
    print(f"Kursor sledit za vzglyadom{mode}. Q/Esc — vyhod.")
    img = np.zeros((H, W, 3), np.uint8) if overlay else None  # переиспользуем буфер — не аллоцируем каждый кадр
    sm_x, sm_y = W / 2, H / 2  # сглаженный системный курсор
    has_pos = False  # первое предсказание — без jump-гейта (истории нет)
    jump_streak = 0
    prev_ff = None  # прошлая фича для гейта морганий (фильтр битым кадром не кормим)
    wink_msg, wink_until = "", 0.0  # последний ручной клик для статус-окна
    alpha = 0.45
    dwell_need = max(0.4, click_dwell_ms / 1000.0)
    dwell_radius = 45
    anchor = None
    anchor_t0 = 0.0
    try:
        while True:
            f = cam.read()
            if f is None:
                if cv2.waitKey(30) & 0xFF in (ord("q"), ord("Q"), 27):
                    break
                continue
            feat, conf, dbg = tracker.process(f)
            if overlay:
                img.fill(0)
            try:
                conf_v = float(conf)
            except Exception:
                conf_v = float("-inf")
            if feat is None or not conf_v >= C.MP_LOST_CONF:
                filt.reset()
                anchor = None
                prev_ff = None
                has_pos = False
                jump_streak = 0
                if overlay:
                    cv2.putText(img, "Lico ne naydeno — syad pered kameroy",
                                (60, H // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 165, 255), 3)
                else:
                    cv2.putText(f, "NO FACE", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            else:
                # гейт морганий на фичах: резкий скачок pitch/yaw (>~14°) —
                # кадр пропускаем целиком (фильтр не травим, курсор стоит).
                # Опору обновляем: следующий steady-кадр сразу проходит.
                if prev_ff is not None and is_saccade(prev_ff, feat):
                    prev_ff = np.asarray(feat, dtype=float)
                    if not overlay:
                        cv2.putText(f, "blink?", (10, 30),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                        cv2.imshow(win, f)
                        if cv2.waitKey(30) & 0xFF in (ord("q"), ord("Q"), 27):
                            break
                    else:
                        cv2.imshow(win, img)
                        if cv2.waitKey(30) & 0xFF in (ord("q"), ord("Q"), 27):
                            break
                    continue
                prev_ff = np.asarray(feat, dtype=float)
                sm = filt.update(feat)
                gx, gy = reg.predict(sm)
                gx = float(np.clip(gx, 0, W - 1))
                gy = float(np.clip(gy, 0, H - 1))
                if not (np.isfinite(gx) and np.isfinite(gy)):
                    cv2.imshow(win, img if overlay else f)
                    if cv2.waitKey(30) & 0xFF in (ord("q"), ord("Q"), 27):
                        break
                    continue
                # анти-моргание: прыжок дальше jump_px за кадр — не двигаем курсор
                if has_pos:
                    jump = ((gx - sm_x) ** 2 + (gy - sm_y) ** 2) ** 0.5
                    if jump > jump_px:
                        jump_streak += 1
                        if jump_streak >= 3:
                            jump_streak = 0
                            sm_x, sm_y = gx, gy
                        else:
                            if not overlay:
                                cv2.putText(f, "blink?", (10, 30),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                            cv2.imshow(win, img if overlay else f)
                            if cv2.waitKey(30) & 0xFF in (ord("q"), ord("Q"), 27):
                                break
                            continue
                    else:
                        jump_streak = 0
                has_pos = True
                # EMA для системного курсора — убрать дрожь
                sm_x = alpha * gx + (1 - alpha) * sm_x
                sm_y = alpha * gy + (1 - alpha) * sm_y
                if syscursor:
                    set_sys_cursor(sm_x, sm_y)
                # ручные клики подмигиванием (из WinkTracker)
                wink_ev = dbg.get("wink") if wink else None
                if wink_ev in ("left", "right"):
                    ok = do_click(sm_x, sm_y, button=wink_ev)
                    wink_msg = ("LEFT CLICK!" if wink_ev == "left" else "RIGHT CLICK!") \
                        if ok else "click N/A"
                    wink_until = time.time() + 1.0
                if time.time() < wink_until and not overlay:
                    cv2.putText(f, wink_msg, (10, 90),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                if overlay:
                    # крестик + кольца на весь экран
                    x, y = int(gx), int(gy)
                    cv2.drawMarker(img, (x, y), (0, 255, 0), cv2.MARKER_CROSS, 48, 3)
                    cv2.circle(img, (x, y), 26, (0, 255, 0), 3)
                    cv2.circle(img, (x, y), 6, (0, 0, 255), -1)
                    cv2.putText(img, f"x={x} y={y} fps={cam.fps:.0f}",
                                (60, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
                    if time.time() < wink_until:
                        cv2.putText(img, wink_msg, (60, 130),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
                else:
                    # мышь поверх окон: в маленьком окне только статус
                    cv2.putText(f, f"x={int(gx)} y={int(gy)} fps={cam.fps:.0f}",
                                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                if click:
                    now = time.time()
                    if anchor is None or ((gx - anchor[0]) ** 2 + (gy - anchor[1]) ** 2) ** 0.5 > dwell_radius:
                        anchor = (gx, gy)
                        anchor_t0 = now
                    prog = min(1.0, (now - anchor_t0) / dwell_need)
                    if overlay:
                        cv2.ellipse(img, (x, y), (40, 40), 0, 0, int(360 * prog), (0, 255, 255), 4)
                        cv2.putText(img, f"click {prog:.0%}",
                                    (x + 50, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
                    else:
                        bar = int(200 * prog)
                        cv2.rectangle(f, (10, 40), (10 + bar, 60), (0, 255, 255), -1)
                        cv2.putText(f, f"click {prog:.0%}", (220, 58),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    if prog >= 1.0:
                        ok = do_click(gx, gy)
                        if overlay:
                            cv2.putText(img, "CLICK!" if ok else "click N/A (Linux)",
                                        (x + 50, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                        else:
                            cv2.putText(f, "CLICK!", (10, 90),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                        anchor = None  # анти-даблклик: нужна новая фиксация
            cv2.imshow(win, img if overlay else f)
            k = cv2.waitKey(30) & 0xFF
            if k in (ord("q"), ord("Q"), 27):
                break
    finally:
        cv2.destroyWindow(win)
