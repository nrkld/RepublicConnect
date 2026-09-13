"""Канонический магнит-снап (копия логики magnetcursor/snap.py, поведение 1-в-1).

Жёсткий снап к интерактивным элементам с гистерезисом (чистая логика, без Windows).
Вход — сырая точка (мышь сейчас, взгляд в Фазе 3). Выход — центр цели или сырая точка.
Гистерезис против дребезга: войти — CAPTURE_RADIUS, выйти — RELEASE_RADIUS (больше).
"""
import math
from dataclasses import dataclass


@dataclass
class Target:
    cx: float  # точка снапа (центр / ClickablePoint)
    cy: float
    left: float = 0
    top: float = 0
    right: float = 0
    bottom: float = 0
    name: str = ""
    kind: str = ""

    @classmethod
    def from_rect(cls, left, top, right, bottom, name="", kind=""):
        return cls(cx=(left + right) / 2.0, cy=(top + bottom) / 2.0,
                   left=left, top=top, right=right, bottom=bottom,
                   name=name, kind=kind)

    def dist_to_rect(self, x, y):
        dx = max(self.left - x, 0.0, x - self.right)
        dy = max(self.top - y, 0.0, y - self.bottom)
        return math.hypot(dx, dy)


class MagnetSnap:
    def __init__(self, capture_radius=120.0, release_radius=180.0,
                 flick_px=45.0, away_frames=3):
        assert release_radius >= capture_radius, "выход должен быть >= входа"
        self.cap = capture_radius
        self.rel = release_radius
        self.flick_px = flick_px      # резкий рывок за кадр = сразу отпустить
        self.away_frames = away_frames  # кадров тяги прочь подряд = отпустить
        self.current = None  # Target, к которому прилипли
        self._d_prev = 0.0
        self._away_streak = 0

    def reset(self):
        self.current = None
        self._d_prev = 0.0
        self._away_streak = 0

    def update(self, x, y, targets):
        """-> (sx, sy, target|None, snapped: bool)."""
        # 1) держим текущую цель, пока не вышли за release-радиус
        if self.current is not None:
            if targets:
                match = None
                for t in targets:
                    if math.hypot(t.cx - self.current.cx,
                                   t.cy - self.current.cy) <= 2.0:
                        match = t
                        break
                self.current = match
            if self.current is not None and self.current.dist_to_rect(x, y) <= self.rel:
                t = self.current
                return t.cx, t.cy, t, True
            self.current = None
        # 2) ищем ближайшую цель в радиусе захвата
        best, best_d = None, self.cap
        for t in targets:
            d = t.dist_to_rect(x, y)
            if d <= self.cap and (best is None or d < best_d):
                best, best_d = t, d
        if best is not None:
            self.current = best
            self._d_prev = 0.0
            self._away_streak = 0
            return best.cx, best.cy, best, True
        return x, y, None, False

    def note_movement(self, x, y, user_moved):
        """Сдвиг мыши на user_moved px за кадр.

        True = вырывание: резкий рывок или устойчивая тяга прочь от центра.
        """
        if self.current is None:
            return False
        if user_moved >= self.flick_px:
            return True
        d = math.hypot(x - self.current.cx, y - self.current.cy)
        if user_moved <= 1.0:
            self._away_streak = 0
        elif d > self._d_prev + 2.0 and user_moved > 3.0:
            self._away_streak += 1
        elif d < self._d_prev - 2.0:
            self._away_streak = 0
        self._d_prev = d
        return self._away_streak >= self.away_frames


def make_snap(source="mouse", **overrides):
    """MagnetSnap из пресета hybrid.config (source: mouse|gaze)."""
    from .config import get_preset
    p = get_preset(source)
    p.update(overrides)
    return MagnetSnap(p["capture"], p["release"], p["flick"], p.get("away_frames", 3))
