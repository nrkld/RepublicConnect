"""Калибровка 126 равноудалённых точек serpentine: settle + 1.5с фиксация, robust-mean.

Рисерч-приемы: serpentine порядок (меньше длинные саккады, лучше circular/spiral),
delay после смены точки (Hannibal730), медиана+MAD вместо mean, резка саккад,
RANSAC-refit в регрессоре, LOO-валидация, drift-контроль.
"""
import time
import cv2
import numpy as np
from .. import config as C
from ..gaze.normalize import robust_mean, is_saccade


def grid_points(w, h, n=126, margin: float = 0.035, serpentine: bool = True):
    """126 равноудалённых точек (блок центрируется, см. auto_grid).
    Параметр n держим для совместимости тестов (игнорируем малые значения,
    всегда строим плотную сетку CALIB_POINTS)."""
    try:
        total = int(n[1]) if isinstance(n, (tuple, list)) else int(n)
    except Exception:
        total = C.CALIB_POINTS
    if total < 50:
        total = C.CALIB_POINTS
    return auto_grid(w, h, total, margin=margin, serpentine=serpentine)


def auto_grid(w, h, n_total, margin=0.035, serpentine=True):
    """~N точек, все соседние равноудалены: шаг s одинаковый по X и Y.
    Перебираем cols x rows (от n до n+12 точек) и берём вариант с минимальным
    максимальным отступом от рамки — точки достают до самых краёв.
    Шаг s = min(sx, sy), блок центрируем. Возвращает список (x, y)."""
    aspect = w / h
    best = None
    for cols in range(2, 41):
        for rows in range(2, 41):
            total = cols * rows
            if total < n_total or total > n_total + 12:
                continue
            sx = (w * (1 - 2 * margin)) / (cols - 1)
            sy = (h * (1 - 2 * margin)) / (rows - 1)
            s = min(sx, sy)
            xm = (w - s * (cols - 1)) / 2 / w
            ym = (h - s * (rows - 1)) / 2 / h
            cost = (max(xm, ym),
                    abs((cols - 1) / (rows - 1) - aspect) / aspect,
                    total)
            if best is None or cost < best[0]:
                best = (cost, cols, rows)
    _, cols, rows = best
    sx = (w * (1 - 2 * margin)) / (cols - 1)
    sy = (h * (1 - 2 * margin)) / (rows - 1)
    s = min(sx, sy)
    x0 = (w - s * (cols - 1)) / 2
    y0 = (h - s * (rows - 1)) / 2
    pts = []
    for r in range(rows):
        xs = [x0 + c * s for c in range(cols)]
        if serpentine and r % 2:
            xs = xs[::-1]
        for x in xs:
            pts.append((float(x), float(y0 + r * s)))
    return pts


def wait_for_start(win, lines, w=640, h=200):
    """Стартовый экран: ПРОБЕЛ/Enter/клик — начать, Q/Esc — отмена."""
    clicked = {"v": False}

    def on_mouse(e, x, y, f, p):
        if e == cv2.EVENT_LBUTTONDOWN:
            clicked["v"] = True

    try:
        cv2.setMouseCallback(win, on_mouse)
    except Exception:
        pass
    while True:
        canvas = np.zeros((h, w, 3), np.uint8)
        for j, ln in enumerate(lines):
            cv2.putText(canvas, ln, (20, 40 + j * 36),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.imshow(win, canvas)
        k = cv2.waitKey(100) & 0xFF
        if k in (32, 13) or clicked["v"]:
            try:
                cv2.setMouseCallback(win, lambda *a: None)
            except Exception:
                pass
            return True
        if k in (ord("q"), ord("Q"), 27):
            raise KeyboardInterrupt


def run_calibration(cam, tracker, filt, screen_w=1280, screen_h=720, avg_s=None,
                    grid=None, dwell_s=None, wait=True, margin=None, fullscreen=False):
    """Интерактив: смотри на точку. Возвращает (feats, screens).
    Всегда 126 равноудалённых точек serpentine на весь экран.
    Параметры grid/margin оставлены для совместимости и игнорируются."""
    nspec = ("auto", C.CALIB_POINTS)
    dense = True
    mgn = float(margin) if margin is not None else C.CALIB_MARGIN
    pts = grid_points(screen_w, screen_h, n=nspec, margin=mgn, serpentine=True)
    dwell = float(dwell_s) if dwell_s else C.CALIBDWELL_S
    feats, screens = [], []
    avg_window = float(avg_s) if avg_s else float(C.CALIB_AVG_S)
    if dwell <= C.CALIB_SETTLE_S:
        raise ValueError(f"dwell {dwell}с <= settle {C.CALIB_SETTLE_S}с: "
                         f"окно выборки пустое, все точки пропадут")
    bad_streak = 0
    all_samples = []  # (point_idx, feat) для gaze_samples_*.npz
    win = "EyeConnect калибровка (Q - отмена)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    if fullscreen:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    else:
        cv2.resizeWindow(win, screen_w // 2, screen_h // 2)
    if wait:
        total = len(pts) * (dwell + 0.3)
        try:
            wait_for_start(win, [
                f"Точек: {len(pts)}, ~{total:.0f} сек.",
                "Сядь 60см, смотри на красную точку.",
                "ПРОБЕЛ/клик — начать, Q — отмена.",
            ], w=screen_w if fullscreen else screen_w // 2, h=200)
        except KeyboardInterrupt:
            cv2.destroyWindow(win)
            print("Калибровка не начата")
            return np.array(feats), np.array(screens)
    try:
        for i, (sx, sy) in enumerate(pts):
            filt.reset()  # не тянуть хвост от прошлой саккады
            t_start = time.time()
            t_settle = t_start + C.CALIB_SETTLE_S
            t_end = t_start + dwell
            buf = []
            prev = None
            n_total, n_ok, n_cut = 0, 0, 0
            t_avg_start = t_end - avg_window
            while time.time() < t_end:
                f = cam.read()
                if f is None:
                    continue
                try:
                    feat, conf, _ = tracker.process(f)
                    conf_v = float(conf)
                except Exception:
                    feat, conf_v = None, float("-inf")
                n_total += 1
                now = time.time()
                sampling = now >= t_avg_start and now >= t_settle
                if feat is not None and conf_v >= C.MP_MIN_CONF:
                    # резка саккад/морганий до усреднения
                    if prev is not None and is_saccade(prev, feat):
                        n_cut += 1
                        filt.reset()
                        prev = None
                        continue
                    prev = feat
                    n_ok += 1
                    try:
                        sm = filt.update(feat)
                    except Exception:
                        n_cut += 1
                        filt.reset()
                        prev = None
                        continue
                    all_samples.append((i, float(sm[0]), float(sm[1])))
                    if sampling:
                        buf.append(np.asarray(sm, dtype=float))
                else:
                    # лицо потеряно — сбросить фильтр, чтобы не было прыжка
                    filt.reset()
                    prev = None
                remain = max(0.0, t_end - now)
                phase_settle = now < t_settle
                if fullscreen:
                    canvas = np.zeros((screen_h, screen_w, 3), np.uint8)
                    cx, cy = int(sx), int(sy)
                else:
                    canvas = np.zeros((screen_h // 2, screen_w // 2, 3), np.uint8)
                    cx, cy = int(sx / 2), int(sy / 2)
                if phase_settle:
                    # кольцо — идёт саккада, данные не пишем (Hannibal delay)
                    cv2.circle(canvas, (cx, cy), 14, (0, 165, 255), 2)
                else:
                    # маленькая точка (r=9): точнее фиксация взгляда
                    cv2.circle(canvas, (cx, cy), 9, (0, 0, 255), -1)
                cv2.putText(canvas, f"{i+1}/{len(pts)} смотри {remain:.1f}c det {n_ok}/{max(1,n_total)} cut {n_cut}", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.imshow(win, canvas)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    raise KeyboardInterrupt
            if buf:
                det_rate = n_ok / max(1, n_total)
                if det_rate < 0.3:
                    print(f"Точка {i+1}: мало детекций ({det_rate:.0%}) — пропущена")
                    bad_streak += 1
                    if bad_streak >= 10:
                        print("10 точек подряд без детекций — прерываю, проверь свет/посадку")
                        break
                    continue
                try:
                    m, s, nin, ntot = robust_mean(buf)
                except ValueError:
                    print(f"Точка {i+1}: пустой буфер — пропущена")
                    bad_streak += 1
                    if bad_streak >= 10:
                        print("10 точек подряд без детекций — прерываю, проверь свет/посадку")
                        break
                    continue
                if float(np.mean(s)) > 0.12:
                    print(f"Точка {i+1}: шумно (std {np.mean(s):.3f}) — взята медиана, держи голову ровнее")
                feats.append(m)
                screens.append((sx, sy))
                bad_streak = 0
            else:
                print(f"Точка {i+1}: лицо терялось — пропущена")
                bad_streak += 1
                if bad_streak >= 10:
                    print("10 точек подряд без детекций — прерываю, проверь свет/посадку")
                    break
    except KeyboardInterrupt:
        print("Калибровка прервана")
    finally:
        cv2.destroyWindow(win)
    # сырые сэмплы для анализа (как Hannibal data/gaze_samples_*.npz)
    try:
        if all_samples:
            C.ensure_profile_dir()
            ts = time.strftime("%Y%m%d_%H%M%S")
            a = np.array(all_samples, dtype=float)
            np.savez(C.PROFILE_DIR / f"gaze_samples_{ts}.npz",
                     samples=a, feats=np.array(feats), screens=np.array(screens))
    except Exception:
        pass
    return np.array(feats), np.array(screens)
