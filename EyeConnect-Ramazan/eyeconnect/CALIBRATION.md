# Калибровка EyeConnect — рисерч, аудит, улучшения

> Проект использует ТОЛЬКО плотную калибровку 126 точек (~4 мин). Режим 9 точек удалён.

## 1. Что говорит наука и open-source

**Точность ориентиры (литература + замеры):**
- 2D-mapping методы: обычно ≤2°, appearance-based без калибровки 3-3.7° (ETH-XGaze 3.7°, MPIIGaze 3.4°).
- Webcam-калиброванная: 1.05°/0.09° (GazeFollower, 12-13 точек, 968 кадров, 50см), 1.4°/1.1° (Kaduk 2024), 1.44-1.45° средний (вебкам vs EyeLink 0.91°).
- Точек: 5≈9 для poly/RANSAC/Lasso/SVR, но **Ridge выигрывает от +4 точек**; 14 точек → 0.5° (Blignaut); 9 точек — оптимум скорость/точность.
- Ridge **-20% MSE vs обычный polynomial** (моб. трекер). Homography — худшая. Symbolic regression — лучше, но тяжелая.
- Smooth-pursuit: 0.91° (лучше статики 9 точек), но дольше и сложнее для ЦА с НОДА.
- Паттерны: rectangular/serpentine > circular/spiral. Рандомный порядок хуже — длинные саккады.
- Webcam 30Гц — стандарт; drift: перекалибровка 7 точек каждые N проб (~15с) как в лаб-стандартах.

**Готовые решения (GitHub):**
- `brownhci/WebGazer` (3.9k★): ridge + weightedRidge (новые клики весом выше) + threadedRidge, 9-point, self-calibration по кликам, TFFacemesh. `YoujingYu99/WebGazerImproved`: GP-регрессор -22% ошибки vs linear, но тяжелый для Pi.
- `Hannibal730/Webcam-Eye-gazing-point-Tracker` (2024): MediaPipe FaceMesh → **eye-contour PCA → анизотропная нормализация (± масштабы отдельно)** → ridge dual без штрафа на intercept → OneEuro+EMA. Delay после смены точки, serpentine, `GridRxC_PatchWxH.pkl` + `gaze_samples_*.npz`. — главный референс для нас.
- `antoinelame/GazeTracking` → `Haakeye/Gaze-Tracking` v2: dlib→MediaPipe, head-tilt immunity через 3D, EAR-blink, без dlib/CMake.
- `jeffasante/gazetrack`: 9-point default, poly+Ridge, save/load, validator (50-200px accuracy) — ближайший аналог нашей структуры.
- `ocular-motor-lab/OpenIris`, `GazeVisual-Lib`, `PyGaze`, `eViacam` (голова→мышь), `maciejrytlewski/GazeControl`.
- MediaPipe Iris: даёт landmarks + depth-from-iris (11.7мм, <10%), но **НЕ gaze** — нужен маппинг.

## 2. Аудит EyeConnect (было)

1. `regressor: Ridge(alpha=1.0)` фиксированный — без RidgeCV, без RANSAC. Выброс (моргание) ломает всю сетку.
2. `calibration: mean(buf)` — mean чувствителен к выбросам; саккады/моргания в окне 0.4с тянут центр.
3. Порядок row-major — длинные перелеты справа-налево между рядами.
4. Нет settle/delay — первые кадры после смены точки (глаз ещё летит) попадают в выборку.
5. `normalize: ny=(iris_y-outer_y)/w` — вертикаль шумная; нет PCA/анизотропии; нет детектора сдвига головы.
6. Валидация только train-fit (оптимистична), LOO не было. Вердикта OK/ПЛОХО не было.
7. Сырые сэмплы не сохранялись — нельзя разобрать плохую калибровку постфактум.

## 3. Что улучшено сейчас

- `config`: `CALIB_SETTLE_S=0.8`, `RIDGE_ALPHAS=(0.1,1,10)`, `CALIB_RANSAC=True`, `VALID_MAX_DEG=2.0`, `HEAD_SHIFT_THR=0.15`.
- `gaze/normalize`: `robust_mean` (медиана+MAD), `is_saccade(thr=0.25)`, `eye_width_px`, `head_shift_ratio`.
- `gaze/regressor`: `alpha="auto"` → RidgeCV; `fit_robust` (сброс худшей точки при residual>2.5*median + refit); `loo_error` (честная оценка); `per_point_errors`; `calib_eye_w` в профиле.
- `ui/calibration` + `ui/cursor.fullscreen_calibrate`: serpentine, settle-кольцо → заливка, резка саккад, robust-mean, `cut` счётчик, `gaze_samples_*.npz`.
- `main cmd_calibrate`: train + LOO в px/°, худшая точка, вердикт OK/СРЕДНЕ/ПЛОХО, печать alpha.
- `test_smoke`: RidgeCV alpha, RANSAC, LOO, serpentine, robust_mean, saccade.

## 4. Уровень проекта vs референсы

| Фича | EyeConnect now | WebGazer | Hannibal730 | GazeFollower |
|---|---|---|---|---|
| Трекинг | FaceMesh+iris 2D | TFFacemesh | FaceMesh+iris+PCA | DL fine-tune |
| Маппинг | Poly2+RidgeCV+RANSAC | ridge/weighted | ridge dual | personalized DL |
| Точек | 9 serpentine | 9 + clicks | RxC serpentine | 12-13 (~968 кадров) |
| Delay/settle | 0.8с да | нет | да | да |
| Outlier | MAD+RANSAC | нет | — | — |
| Валидация | LOO + train | accuracy page | — | D3 samples |
| Drift | нет (roadmap) | implicit clicks | restart при смене монитора | re-cal |
| Смузи | EMA+Kalman | — | OneEuro+EMA | — |
| Датасеты | gaze_samples.npz | 51-subj dataset | .npz/.pkl | ETH-XGaze |

## 5. Roadmap

- **Фаза 2 (дешево):** drift-коррекция: 4 угла + центр 15с implicitly во время печати; weightedRidge (последние dwell-клики весом выше как в WebGazer); blink→click через EAR; head-shift варнинг по `eye_width`.
- **Фаза 3 (средне):** PCA контура + анизотропная нормализация (нужны 16 точек контура, сейчас 2 уголка); smooth-pursuit опция (круг 8с, 200+ сэмплов); OneEuro вместо Калмана.
- **Фаза 4 (тяжело/RPi5+):** GP-регрессор (-22% по WebGazerImproved) или fine-tune ETH-XGaze/MPIIGaze; стерео/глубина.
