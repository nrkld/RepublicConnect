"""Клики гибрида (Фаза 4): dwell-фиксация + подмигивания через один роутер.

- DwellClicker: фиксация сырой точки взгляда в радиусе dwell_radius дольше
  dwell_s -> клик. Логика 1-в-1 из eyeconnect run_cursor (anchor/anchor_t0).
- ClickRouter: wink left/right по фронту + dwell только по снапнутой цели
  (защита от кликов в пустоту) + общий cooldown от даблкликов.
  Координаты клика — всегда снапнутая точка, не сырой взгляд.

Только stdlib. Время инжектится (time_fn) для тестов.
"""
import math
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ClickEvent:
    kind: str  # left|right|dwell (dwell бьёт как ЛКМ)
    x: float
    y: float


class DwellClicker:
    def __init__(self, dwell_s=1.2, radius_px=45.0):
        self.dwell_s = max(0.1, float(dwell_s))
        self.radius_px = float(radius_px)
        self.anchor = None
        self.anchor_t0 = 0.0

    def reset(self):
        self.anchor = None
        self.anchor_t0 = 0.0

    def update(self, x, y, now, armed):
        """-> (clicked: bool, progress: 0..1). Без armed якорь сброшен, клика нет."""
        if not armed:
            self.reset()
            return False, 0.0
        if (self.anchor is None or math.hypot(x - self.anchor[0], y - self.anchor[1])
                > self.radius_px):
            self.anchor = (float(x), float(y))
            self.anchor_t0 = now
            return False, 0.0
        prog = min(1.0, (now - self.anchor_t0) / self.dwell_s)
        if prog >= 1.0:
            self.reset()  # анти-даблклик: нужна новая фиксация
            return True, 1.0
        return False, prog


class ClickRouter:
    def __init__(self, dwell_s=1.2, dwell_radius=45.0, dwell_on=True,
                 wink_on=True, cooldown_s=1.0, time_fn=None):
        self.dwell = DwellClicker(dwell_s, dwell_radius)
        self.dwell_on = dwell_on
        self.wink_on = wink_on
        self.cooldown_s = cooldown_s
        self._time = time_fn or time.time
        self._last_wink = None
        self._last_click_t = float("-inf")
        self._last_src = None

    def reset(self):
        self.dwell.reset()
        self._last_wink = None
        self._last_click_t = float("-inf")
        self._last_src = None

    def note_invalid(self):
        """Битый кадр: dwell-якорь и фронт wink сбросить."""
        self.dwell.reset()
        self._last_wink = None

    def update(self, sample, snapped, tx, ty):
        """Решение о клике в точке (tx, ty). -> ClickEvent | None."""
        now = self._time()
        if sample.src != self._last_src:
            self._last_src = sample.src
            self.dwell.reset()
        wink = sample.wink if self.wink_on else None
        if wink in ("left", "right") and wink != self._last_wink:
            self._last_wink = wink
            self.dwell.reset()
            if now - self._last_click_t >= self.cooldown_s:
                self._last_click_t = now
                return ClickEvent(wink, float(tx), float(ty))
            return None
        self._last_wink = wink
        if self.dwell_on and sample.src != "mouse":
            # якорь — сырой взгляд (дрожание честно сбрасывает), клик — в цель
            clicked, _ = self.dwell.update(sample.x, sample.y, now, armed=snapped)
            if clicked and now - self._last_click_t >= self.cooldown_s:
                self._last_click_t = now
                return ClickEvent("dwell", float(tx), float(ty))
        return None
