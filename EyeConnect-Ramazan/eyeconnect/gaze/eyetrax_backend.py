"""EyeTrax backend для EyeConnect (vendored в third_party/EyeTrax).

Upstream: https://github.com/ck-zhang/EyeTrax (MIT, Zhang C. 2025).
Локальная копия: third_party/EyeTrax/ (+ LICENSE.EyeTrax-MIT).
Pip-вариант: pip install eyetrax (предпочтителен на ноутбуке).

Почему EyeTrax лучше встроенного FaceTracker:
- фичи инвариантны к движению головы (якорь на середину глаз + поворот
  по осям x/y/z + нормировка на межзрачковое расстояние + yaw/pitch/roll);
- встроенный blink-детектор по EAR с адаптивным порогом;
- готовые калибровки 9p/5p/dense/lissajous + фильтры kalman/kalman_ema/kde;
- save/load модели из коробки.

Совместимость:
- FaceTracker.process() возвращает 2D feat (nx,ny) для GazeRegressor.
- EyeTrax возвращает HIGH-DIM вектор -> с GazeRegressor НЕ совместим.
  Используйте связку EyeTraxTracker + estimator.predict() напрямую,
  либо переобучите свой регрессор на EyeTrax-фичах.

Пример:
    from eyeconnect.gaze.eyetrax_backend import EyeTraxTracker
    tr = EyeTraxTracker()  # pip eyetrax или vendored копия
    feat, blink = tr.extract_features(frame)
    if feat is not None and not blink:
        x, y = tr.predict([feat])[0]
"""
from __future__ import annotations

import sys
from pathlib import Path


def _ensure_eyetrax_importable():
    """Пробует pip-версию, иначе подключает vendored third_party/EyeTrax."""
    try:
        import eyetrax  # type: ignore
        return eyetrax
    except Exception:
        pass
    # корень репо: .../EyeConnect-Ramazan/
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / "third_party" / "EyeTrax"
        if (cand / "eyetrax" / "__init__.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            break
    import eyetrax  # type: ignore
    return eyetrax


def create_estimator(model_name: str = "ridge", **kw):
    """Создать upstream GazeEstimator (ленивый импорт mediapipe внутри)."""
    eyetrax = _ensure_eyetrax_importable()
    return eyetrax.GazeEstimator(model_name=model_name, **kw)


class EyeTraxTracker:
    """Тонкая обёртка над upstream GazeEstimator под стиль EyeConnect.

    - extract_features(bgr) -> (feat|None, blink: bool)
    - process(bgr) -> (feat|None, conf: float, dbg: dict) — для preview-цикла
    - train(X, y) / predict(X) / save(path) / load(path) / close()
    """

    def __init__(self, model_name: str = "ridge", **kw):
        eyetrax = _ensure_eyetrax_importable()
        self._eyetrax = eyetrax
        self.estimator = eyetrax.GazeEstimator(model_name=model_name, **kw)
        self.trained = False

    def extract_features(self, bgr):
        try:
            feat, blink = self.estimator.extract_features(bgr)
        except Exception:
            return None, False
        if feat is None:
            return None, False
        return feat, bool(blink)

    def process(self, bgr):
        """Совместимый с FaceTracker.process() вывод для preview."""
        feat, blink = self.extract_features(bgr)
        if feat is None:
            return None, 0.0, {}
        conf = 0.0 if blink else 0.9
        return feat, conf, {"blink": blink, "dim": int(feat.shape[0]) if hasattr(feat, "shape") else -1}

    def train(self, X, y, **kw):
        self.estimator.train(X, y, **kw)
        self.trained = True
        return self

    def predict(self, X):
        return self.estimator.predict(X)

    def save(self, path):
        self.estimator.save_model(path)

    def load(self, path):
        self.estimator.load_model(path)
        self.trained = True
        return self

    def close(self):
        try:
            self.estimator.close()
        except Exception:
            pass
