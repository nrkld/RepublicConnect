"""Метрики пилота (дока разд. 9): WPM, accuracy/precision в градусах, TER/CER/UER."""
import math
import numpy as np
from .. import config as C


def wpm(text: str, seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    t = (text or "").strip()
    if len(t) <= 1:
        return 0.0
    return max(0.0, ((len(t) - 1) / seconds) * 60 * (1 / 5))


def px_to_deg(err_px: float, px_mm: float = None, dist_mm: float = None) -> float:
    # px_mm по горизонтали; для квадратных пикселей вертикаль та же.
    # Если экран не 24" — поправьте SCREEN_W_MM/VIEW_DIST_MM в config.py, иначе ошибка до 30%.
    if px_mm is None:
        px_mm = C.SCREEN_W_MM / C.SCREEN_W_PX
    if dist_mm is None:
        dist_mm = C.VIEW_DIST_MM
    if dist_mm <= 0:
        return 0.0
    return math.degrees(math.atan((max(0.0, err_px) * px_mm) / dist_mm))


def accuracy_precision(targets_xy, preds_xy):
    t = np.asarray(targets_xy, float)
    p = np.asarray(preds_xy, float)
    err = np.linalg.norm(t - p, axis=1)
    acc_px, prec_px = float(err.mean()), float(err.std())
    return {"acc_px": acc_px, "prec_px": prec_px,
            "acc_deg": px_to_deg(acc_px), "prec_deg": px_to_deg(prec_px)}


def error_rates(correct: int, fixed: int, unfixed: int):
    tot = max(1, correct + fixed + unfixed)
    cer = fixed / tot * 100
    uer = unfixed / tot * 100
    return {"CER": cer, "UER": uer, "TER": cer + uer}
