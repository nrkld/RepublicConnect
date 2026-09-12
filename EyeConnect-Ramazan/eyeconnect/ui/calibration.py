"""Калибровка 9 точек 3x3 serpentine (дока 4.4, Прил.В): settle + 3с фиксация, robust-mean.

Рисерч-приемы: serpentine порядок (меньше длинные саккады, лучше circular/spiral),
delay после смены точки (Hannibal730), медиана+MAD вместо mean, резка саккад,
RANSAC-refit в регрессоре, LOO-валидация, drift-контроль.
"""
import time
import cv2
import numpy as np
from .. import config as C
from ..gaze.normalize import robust_mean, is_saccade


def grid_points(w, h, n=C.CALIB_GRID, margin: float = 0.12, serpentine: bool = True):
    """Сетка точек. n: int (n x n), (cols, rows) или ("auto", N) — N точек с
    РАВНЫМИ интервалами по X и Y (блок центрируется, см. auto_grid)."""
    if isinstance(n, (tuple, list)) and n and n[0] == "auto":
        return auto_grid(w, h, int(n[1]), margin=margin, serpentine=serpentine)
    if isinstance(n, (tuple, list)):
        cols, rows = max(2, int(n[0])), max(2, int(n[1]))
    else:
        cols = rows = max(2, int(n))
    xs = np.linspace(w * margin, w * (1 - margin), cols)
    ys = np.linspace(h * margin, h * (1 - margin), rows)
    pts = []
    for r, y in enumerate(ys):
        row = xs if (r % 2 == 0 or not serpentine) else xs[::-1]
        for x in row:
            pts.append((float(x), float(y)))
    return pts


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
                    grid=None, dwell_s=None, wait=True, margin=None):
    """Интерактив: смотри на точку. Возвращает (feats, screens).
    Внутри: settle-игнор, резка саккад, robust-mean, сырые сэмплы в .npz для анализа.
    grid: (cols, rows) | ("auto", N) — N равноудалённых точек; дефолт auto-120.
      dwell_s: фиксация на точку (дефолт 1.5с для плотной / 3.0с для 3x3).
      margin: отступ крайних точек от рамки (доля); дефолт 0.035 для плотной
      (точки почти у краёв), 0.12 для 3x3. wait: стартовый экран с кнопкой."""
    if isinstance(grid, (tuple, list)) and grid and grid[0] == "auto":
        cols = rows = 0
        dense = True
    else:
        cols, rows = grid or (C.CALIB_DENSE_COLS, C.CALIB_DENSE_ROWS)
        dense = cols * rows > 16
    mgn = float(margin) if margin is not None else (
        C.CALIB_MARGIN_DENSE if dense else C.CALIB_MARGIN_SPARSE)
    nspec = grid if (isinstance(grid, (tuple, list)) and bool(grid) and grid[0] == "auto") else (cols, rows)
    pts = grid_points(screen_w, screen_h, n=nspec, margin=mgn, serpentine=True)
    dwell = float(dwell_s) if dwell_s else (
        C.CALIBDWELL_DENSE_S if len(pts) > 16 else C.CALIBDWELL_S)
    feats, screens = [], []
    avg_window = float(avg_s) if avg_s else float(C.CALIB_AVG_S)
    all_samples = []  # (point_idx, feat) для gaze_samples_*.npz
    win = "EyeConnect калибровка (Q - отмена)"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, screen_w // 2, screen_h // 2)
    if wait:
        total = len(pts) * (dwell + 0.3)
        is_auto = isinstance(nspec, (tuple, list)) and bool(nspec) and nspec[0] == "auto"
        grid_label = f"{nspec[1]} равноуд." if is_auto else f"{cols}x{rows}"
        try:
            wait_for_start(win, [
                f"Точек: {len(pts)} ({grid_label}), ~{total:.0f} сек.",
                "Сядь 60см, смотри на красную точку.",
                "ПРОБЕЛ/клик — начать, Q — отмена.",
            ], w=screen_w // 2, h=200)
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
                feat, conf, _ = tracker.process(f)
                n_total += 1
                now = time.time()
                sampling = now >= t_avg_start and now >= t_settle
                if feat is not None and conf >= C.MP_MIN_CONF:
                    # резка саккад/морганий до усреднения
                    if prev is not None and is_saccade(prev, feat):
                        n_cut += 1
                        filt.reset()
                        prev = None
                        continue
                    prev = feat
                    n_ok += 1
                    sm = filt.update(feat)
                    all_samples.append((i, float(sm[0]), float(sm[1])))
                    if sampling:
                        buf.append(np.asarray(sm, dtype=float))
                else:
                    # лицо потеряно — сбросить фильтр, чтобы не было прыжка
                    filt.reset()
                    prev = None
                remain = max(0.0, t_end - now)
                phase_settle = now < t_settle
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
                    continue
                try:
                    m, s, nin, ntot = robust_mean(buf)
                except ValueError:
                    print(f"Точка {i+1}: пустой буфер — пропущена")
                    continue
                if float(np.mean(s)) > 0.12:
                    print(f"Точка {i+1}: шумно (std {np.mean(s):.3f}) — взята медиана, держи голову ровнее")
                feats.append(m)
                screens.append((sx, sy))
            else:
                print(f"Точка {i+1}: лицо терялось — пропущена")
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
