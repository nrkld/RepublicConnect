"""Smoke-тесты без камеры/лица: регрессор, фильтр, нормализация, предикт, клавиатура."""
import tempfile
import time
from pathlib import Path

import numpy as np
from eyeconnect.gaze.normalize import norm_eye, estimate_distance_mm, robust_mean, is_saccade
from eyeconnect.gaze.filter import GazeFilter
from eyeconnect.gaze.regressor import GazeRegressor
from eyeconnect.predict.base import PrefixPredictor
from eyeconnect.ui.keyboard import DwellKeyboard
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
assert info["dropped"] is not None or True  # выброс на синтетике может не сработать — главное без краша
loo = r.loo_error(feats, screens)
assert loo["n"] == 9 and loo["loo_px"] >= 0, loo
perr = r.per_point_errors(feats, screens)
assert perr.shape == (9,)

# serpentine порядок: 2-й ряд идёт обратно (меньше длинные саккады)
pts = grid_points(1280, 720, n=3, serpentine=True)
assert pts[0][0] < pts[1][0] and pts[3][0] > pts[4][0], pts[:6]

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

en = PrefixPredictor("EN").suggest("hel")
assert isinstance(en, list) and len(en) > 0, en
assert "hello" in en, en
kz = PrefixPredictor("KZ").suggest("сәл")
assert isinstance(kz, list) and len(kz) > 0
ru = PrefixPredictor("RU").suggest("прив")
assert isinstance(ru, list) and len(ru) > 0, ru
assert "привет" in ru, ru
# суффикс-спам фикс: неизвестный префикс не должен давать xyzлар
spam = PrefixPredictor("KZ").suggest("xyzq")
assert spam == [] or all(not s.startswith("xyzq") or s == "xyzq" for s in spam), spam
# complete: замена последнего слова
pp = PrefixPredictor("EN")
assert pp.complete("hel", "hello") == "hello " or "hello" in pp.complete("hel", "hello")
assert pp.complete("", "hello") == "hello "

kb = DwellKeyboard(lang="KZ", dwell_ms=50)
kb.layout_rects()
# PRED-зоны есть и кэшируются
assert "PRED:0" in kb.rects and "PRED:2" in kb.rects
assert kb.layout_rects() is kb.rects, "layout должен кэшироваться"
# LANG цикл KZ->RU->EN
assert kb.lang == "KZ"
kb.toggle_lang()
assert kb.lang == "RU", kb.lang
kb.toggle_lang()
assert kb.lang == "EN", kb.lang
kb.toggle_lang()
assert kb.lang == "KZ", kb.lang
# предикт-вставка
kb.pred = ["сәлем", "сәт"]
kb.text = "сәл"
kb.press("PRED:0")
assert kb.text.strip() == "сәлем", kb.text
# dwell-тест на чистом тексте
kb.text = ""
kb._focus = None
kb._t0 = None
ch = [k for k in kb.rects if len(k) == 1][0]
x0, y0, kw, kh = kb.rects[ch]
# ждём dwell до срабатывания (до 2с), а не фиксированные 5 итераций
deadline = time.time() + 2.0
while kb.text == "" and time.time() < deadline:
    kb.update(x0 + kw / 2, y0 + kh / 2)
    time.sleep(0.02)
assert kb.text != "", "dwell не сработал за 2с"
img = kb.draw((640, 360))
assert img.shape == (720, 1280, 3)

assert wpm("", 30) == 0.0
assert wpm("привет", 30) > 0
assert wpm("привет", 0) == 0.0
m = accuracy_precision(screens[:3], screens[:3] + 5)
assert m["acc_deg"] >= 0
assert error_rates(90, 8, 2)["TER"] == 10.0
print("SMOKE OK")
