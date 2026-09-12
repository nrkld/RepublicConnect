"""Подмигивания поверх любого gaze-трекера: левое = ЛКМ, правое = ПКМ.

EAR (Eye Aspect Ratio) берётся из FaceTracker (MediaPipe, дёшево ~15мс):
- если gaze-трекер сам FaceTracker — EAR переиспользуется из его dbg;
- иначе (L2CS) — отдельный FaceTracker только для EAR.
Моргание обоими глазами кликом НЕ считается.

Событие — по фронту (закрыл -> клик один раз, держать можно сколько угодно),
плюс cooldown на случай дребезга. Порог адаптивный: среднее истории x ratio.
"""
from __future__ import annotations

import time
from collections import deque


class WinkTracker:
    """Обёртка: gaze через inner-трекер + wink через EAR."""

    def __init__(self, inner=None, inner_name="l2cs",
                 ear_ratio=0.7, hist_len=50, min_hist=15, cooldown_s=0.8):
        from .facemesh import FaceTracker
        self._FaceTracker = FaceTracker
        if inner is None:
            if inner_name == "l2cs":
                from .l2cs_backend import L2CSTracker
                inner = L2CSTracker()
            else:
                inner = FaceTracker()
        self.inner = inner
        self.reuse_ear = isinstance(inner, FaceTracker)
        self.ear_tracker = None if self.reuse_ear else FaceTracker()
        self.hist_l = deque(maxlen=hist_len)
        self.hist_r = deque(maxlen=hist_len)
        self.ear_ratio = float(ear_ratio)
        self.min_hist = int(min_hist)
        self.cooldown_s = float(cooldown_s)
        self._prev_wink = None
        self._last_click_t = 0.0

    @staticmethod
    def _mean(dq):
        return sum(dq) / len(dq) if dq else 0.2

    def process(self, bgr):
        feat, conf, dbg = self.inner.process(bgr)
        dbg = dict(dbg)
        ear_l = dbg.get("ear_l")
        ear_r = dbg.get("ear_r")
        if (ear_l is None or ear_r is None) and self.ear_tracker is not None:
            try:
                _, _, dbg2 = self.ear_tracker.process(bgr)
                ear_l = dbg2.get("ear_l", ear_l)
                ear_r = dbg2.get("ear_r", ear_r)
            except Exception:
                pass
        wink = None
        if ear_l is not None and ear_r is not None:
            dbg["ear_l"], dbg["ear_r"] = float(ear_l), float(ear_r)
            if len(self.hist_l) < self.min_hist:
                # прогрев: считаем что в начале глаза открыты
                self.hist_l.append(float(ear_l))
                self.hist_r.append(float(ear_r))
            else:
                thr_l = self._mean(self.hist_l) * self.ear_ratio
                thr_r = self._mean(self.hist_r) * self.ear_ratio
                l_closed = ear_l < thr_l
                r_closed = ear_r < thr_r
                # историю копим только открытыми глазами, иначе порог уплывёт
                if not l_closed:
                    self.hist_l.append(float(ear_l))
                if not r_closed:
                    self.hist_r.append(float(ear_r))
                if l_closed and not r_closed:
                    wink = "left"
                elif r_closed and not l_closed:
                    wink = "right"
                # оба закрыты = моргание, не клик
                now = time.monotonic()
                if wink and wink != self._prev_wink and \
                        (now - self._last_click_t) >= self.cooldown_s:
                    dbg["wink"] = wink
                    self._last_click_t = now
                self._prev_wink = wink
        return feat, conf, dbg

    def close(self):
        for t in (self.inner, self.ear_tracker):
            try:
                if t is not None:
                    t.close()
            except Exception:
                pass
