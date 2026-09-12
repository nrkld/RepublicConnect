"""Геометрическая нормализация взгляда (дока 4.3).

Вход: координаты ирисов и уголков глаз в пикселях кадра.
Выход: нормализованный вектор [0..1] + оценка дистанции по ирису.
Инвариантно к расстоянию 50-70см и размеру лица.

Рисерч-ноты:
- Hannibal730: PCA контура + анизотропная нормализация (разные масштабы +/-)
  даёт лучшую вертикаль, чем деление на ширину глаза. У нас lite-версия:
  горизонталь по ширине глаза, вертикаль по ней же (шумно) — см. audit в CALIBRATION.md.
  Полный PCA — фаза 3 (нужен весь контур 16 точек, сейчас только уголки).
- MediaPipe Iris НЕ даёт gaze, только landmarks + depth-from-iris (11.7мм, <10%).
- Blink/saccade надо резать до усреднения — helpers ниже.
"""
import numpy as np

IRIS_REAL_MM = 11.7  # средний диаметр ириса, Chelak & Yuan


def norm_eye(iris_xy, outer_xy, inner_xy, top_xy=None, bottom_xy=None):
    """Нормализация одного глаза -> (nx, ny) в [0..1]."""
    w = float(np.linalg.norm(np.asarray(inner_xy) - np.asarray(outer_xy))) + 1e-6
    nx = (float(iris_xy[0]) - float(outer_xy[0])) / w
    if top_xy is not None and bottom_xy is not None:
        h = float(np.linalg.norm(np.asarray(bottom_xy) - np.asarray(top_xy))) + 1e-6
        ny = (float(iris_xy[1]) - float(top_xy[1])) / h
    else:
        ny = (float(iris_xy[1]) - float(outer_xy[1])) / w
    return float(np.clip(nx, -0.5, 1.5)), float(np.clip(ny, -0.5, 1.5))


def fuse_eyes(left_n, right_n):
    return ((left_n[0] + right_n[0]) / 2.0, (left_n[1] + right_n[1]) / 2.0)


def estimate_distance_mm(iris_px, focal_px=650.0):
    """d = f * D_real / D_px. focal_px калибруется один раз на камеру."""
    iris_px = max(float(iris_px), 1.0)
    return float(focal_px * IRIS_REAL_MM / iris_px)


def features_from_eyes(l_iris, l_outer, l_inner, r_iris, r_outer, r_inner):
    ln = norm_eye(l_iris, l_outer, l_inner)
    rn = norm_eye(r_iris, r_outer, r_inner)
    fx, fy = fuse_eyes(ln, rn)
    return np.array([fx, fy], dtype=np.float64)


def eye_width_px(outer_xy, inner_xy) -> float:
    """Ширина глаза в px — прокси дистанции/масштаба + детектор сдвига головы."""
    return float(np.linalg.norm(np.asarray(inner_xy) - np.asarray(outer_xy)))


def is_saccade(prev_feat, cur_feat, thr: float = 0.25) -> bool:
    """Резкий прыжок фичи между кадрами — моргание/саккада/потеря. Резать до усреднения."""
    try:
        d = float(np.linalg.norm(np.asarray(cur_feat) - np.asarray(prev_feat)))
    except Exception:
        return True
    return d > thr


def head_shift_ratio(calib_eye_w: float, cur_eye_w: float) -> float:
    """|w_cur-w_calib|/w_calib. >0.15 (HEAD_SHIFT_THR) — голова уехала, точность упадет."""
    if calib_eye_w <= 0:
        return 0.0
    return abs(float(cur_eye_w) - float(calib_eye_w)) / float(calib_eye_w)


def robust_mean(feats, max_std_mult: float = 2.0):
    """Медиана + отсев выбросов по MAD. Возвращает (mean, std, n_inliers, n_total)."""
    a = np.asarray(feats, dtype=float)
    if a.size == 0:
        raise ValueError("пустой буфер")
    if a.ndim == 1:
        a = a.reshape(1, -1)
    med = np.median(a, axis=0)
    dist = np.linalg.norm(a - med, axis=1)
    mad = float(np.median(dist)) + 1e-9
    keep = dist <= max_std_mult * 2.5 * mad
    if keep.sum() < max(2, len(a) // 2):
        keep = np.ones(len(a), dtype=bool)  # слишком строго — берем всё
    inl = a[keep]
    return (np.mean(inl, axis=0), np.std(inl, axis=0), int(keep.sum()), int(len(a)))
