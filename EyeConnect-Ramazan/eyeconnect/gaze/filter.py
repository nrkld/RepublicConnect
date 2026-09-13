"""EMA + фильтр Калмана constant-velocity (дока 4.5)."""
import numpy as np
from .. import config as C


class EMA:
    def __init__(self, alpha: float = C.EMA_ALPHA):
        self.a = alpha
        self.v = None

    def update(self, x):
        x = np.asarray(x, dtype=float)
        if not bool(np.all(np.isfinite(x))):
            if self.v is None:
                return np.zeros_like(x)
            return self.v.copy()
        self.v = x if self.v is None else self.a * x + (1 - self.a) * self.v
        return self.v.copy()

    def reset(self):
        self.v = None


class Kalman2D:
    """Позиция+скорость, предсказывает при моргании/потере трекинга."""

    def __init__(self, q=1e-4, r=1e-2):
        self.x = np.zeros(4)  # px, py, vx, vy
        self.P = np.eye(4)
        self.Q = np.eye(4) * q
        self.R = np.eye(2) * r
        self.init = False

    def update(self, z, dt=1 / 30):
        z = np.asarray(z, dtype=float)
        if not bool(np.all(np.isfinite(z))):
            return self.x[:2].copy()
        # clamp dt: защита от зависших кадров / скачков времени
        dt = float(max(1e-3, min(0.2, dt)))
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]])
        H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
        if not self.init:
            self.x[:2] = z
            self.x[2:] = 0.0
            self.P = np.eye(4)
            self.init = True
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        y = z - H @ self.x
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ H) @ self.P
        return self.x[:2].copy()

    def predict(self, dt=1 / 30):
        dt = float(max(1e-3, min(0.2, dt)))
        F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]])
        self.x = F @ self.x
        return self.x[:2].copy()

    def reset(self):
        self.x = np.zeros(4)
        self.P = np.eye(4)
        self.init = False


class GazeFilter:
    def __init__(self):
        self.ema = EMA()
        self.kf = Kalman2D()

    def update(self, feat_xy, dt=1 / 30):
        e = self.ema.update(feat_xy)
        return self.kf.update(e, dt)

    def predict(self, dt=1 / 30):
        return self.kf.predict(dt)

    def reset(self):
        """Вызывать при потере лица, чтобы не было прыжка при возврате."""
        self.ema.reset()
        self.kf.reset()
