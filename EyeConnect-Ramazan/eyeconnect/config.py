"""EyeConnect shared config (дока разд. 4-6)."""
from pathlib import Path

# Видео
FRAME_W, FRAME_H = 640, 480
CAM_INDEX = 0
FPS_TARGET = 30

# MediaPipe
MP_MIN_CONF = 0.5
MP_LOST_CONF = 0.3

# Калибровка: только плотная сетка 126 равноудалённых точек (~4 мин),
# settle 0.8с, 0.4с усреднение. Других сеток нет.
CALIB_POINTS = 126
CALIBDWELL_S = 1.5
# Рисерч: Ridge -20% MSE vs poly; плотная сетка точнее на краях, Ridge есть чем кормиться;
# smooth-pursuit 0.91° но дольше; drift-коррекция 7 точек каждые N проб (15с).
CALIB_MARGIN = 0.035  # точки почти у краёв
CALIB_SETTLE_S = 0.8  # игнор после смены точки (саккада) — идея Hannibal730 delay<per-point
CALIB_AVG_S = 0.4
EDGE_WEIGHT = 1.5
CALIB_RANSAC = True  # отсев худшей точки по residual + refit
RIDGE_ALPHAS = (0.1, 1.0, 10.0)  # RidgeCV автоподбор
VALID_MAX_DEG = 2.0  # цель прод ≤2.0°, лаб ≤1.5°
HEAD_SHIFT_THR = 0.15  # смена ширины глаз >15% vs калибровки = сдвиг головы

# Сглаживание: EMA alpha=0.4 по 5 кадрам + Калман
EMA_ALPHA = 0.4
EMA_N = 5

# Геометрия для перевода px -> градусы (ноутбук по умолчанию, переопределить под монитор)
SCREEN_W_PX, SCREEN_H_PX = 1920, 1080
SCREEN_W_MM = 531.0  # 24" 16:9, померять линейкой и поправить
VIEW_DIST_MM = 600.0  # 50-70см по доке

PROFILE_DIR = Path.home() / ".eyeconnect"


def ensure_profile_dir() -> Path:
    """Создать ~/.eyeconnect лениво (без побочек на import)."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DIR
