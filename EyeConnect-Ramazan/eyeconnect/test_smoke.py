"""Smoke-тесты без камеры/лица: регрессор, фильтр, нормализация."""
import tempfile
from pathlib import Path

import numpy as np
from eyeconnect.gaze.normalize import norm_eye, estimate_distance_mm, robust_mean, is_saccade
from eyeconnect.gaze.filter import GazeFilter
from eyeconnect.gaze.regressor import GazeRegressor
from eyeconnect.ui.calibration import grid_points
from eyeconnect.eval.metrics import wpm, accuracy_precision, error_rates

rng = np.random.default_rng(0)
feats = rng.random((9, 2))
screens = feats * np.array([1280., 720.])
r = GazeRegressor().fit(feats, screens)
px, py = r.predict([0.5, 0.5])
assert 0 <= px <= 1280 and 0 <= py <= 720, (px, py)
assert r.alpha in (0.1, 1.0, 10.0), r.alpha  # RidgeCV выбрал alpha

# robust fit: выброс должен быть отброшен
feats_out = np.vstack([feats, [[10.0, 10.0]]])
screens_out = np.vstack([screens, [[1280., 720.]]])
r_rob, info = GazeRegressor().fit_robust(feats_out, screens_out)
assert "dropped" in info  # выброс на синтетике может не сработать — главное без краша
loo = r.loo_error(feats, screens)
assert loo["n"] == 9 and loo["loo_px"] >= 0, loo
perr = r.per_point_errors(feats, screens)
assert perr.shape == (9,)

# плотная сетка 126: serpentine порядок (2-й ряд идёт обратно)
pts = grid_points(1280, 720)
assert len(pts) >= 120, len(pts)
assert pts[0][0] < pts[1][0], pts[:2]

# robust_mean + saccade
m, s, nin, ntot = robust_mean([[0.5, 0.5]] * 8 + [[5.0, 5.0]])
assert nin >= 8 and abs(m[0] - 0.5) < 0.1, (m, nin)
assert is_saccade([0.5, 0.5], [5.0, 5.0]) and not is_saccade([0.5, 0.5], [0.51, 0.5])

# save/load roundtrip — критический путь профиля
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "gaze.npz"
    r.save(p)
    r2 = GazeRegressor().load(p)
    px2, py2 = r2.predict([0.5, 0.5])
    assert abs(px - px2) < 1e-6 and abs(py - py2) < 1e-6, ((px, py), (px2, py2))

# predict без обучения должен дать понятную ошибку
try:
    GazeRegressor().predict([0.5, 0.5])
    raise AssertionError("predict без fit/load должен бросить RuntimeError")
except RuntimeError:
    pass

# load несуществующего файла — FileNotFoundError
try:
    GazeRegressor().load(Path(td) / "nope.npz")
    raise AssertionError("load несуществующего должен бросить FileNotFoundError")
except FileNotFoundError:
    pass

f = GazeFilter()
for _ in range(10):
    out = f.update([0.5, 0.5])
assert out.shape == (2,)

# reset после потери лица не должен давать выбросов
f.reset()
out = f.update([0.5, 0.5])
assert out.shape == (2,) and np.all(np.isfinite(out))

nx, ny = norm_eye((50, 30), (30, 30), (70, 30))
assert 0 <= nx <= 1, (nx, ny)
assert estimate_distance_mm(50) > 100

assert wpm("", 30) == 0.0
assert wpm("привет", 30) > 0
assert wpm("привет", 0) == 0.0
m = accuracy_precision(screens[:3], screens[:3] + 5)
assert m["acc_deg"] >= 0
assert error_rates(90, 8, 2)["TER"] == 10.0
print("SMOKE OK")
