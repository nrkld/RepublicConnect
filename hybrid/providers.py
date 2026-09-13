"""Провайдеры указателя (Фаза 2): единый источник координат для гибридного цикла.

- PointerSample: один кадр указателя (x, y, valid, wink, note, src).
- GazeProvider: cam.read -> tracker.process -> filt.update -> reg.predict
  с гейтами из eyeconnect/ui/cursor.py run_cursor (потеря лица, резка саккад,
  jump-gate, EMA выхода). Без imshow/SetCursorPos — только данные.
- MouseProvider: тонкая обёртка над win_cursor.get_pos.
- AutoProvider: mouse ведёт при движении (с cooldown-залипанием),
  иначе gaze, иначе hold последней точки. Цикл обязан звать note_output()
  после каждого set_pos, иначе собственные движения цикла будут приняты
  за пользователя (тот же приём, что last_set в magnetcursor/service.py).

Только stdlib. Коллабораторы (cam/tracker/filt/reg) — duck-typed, без импорта
eyeconnect: тесты подсовывают фейки, прод — настоящие классы.
"""
import math
import threading
import time
from dataclasses import dataclass

from . import win_cursor as _wc


@dataclass(frozen=True)
class PointerSample:
    x: float
    y: float
    valid: bool
    wink: str | None = None   # "left"/"right" (подмигивание) или None
    note: str = "ok"             # ok|no-frame|no-face|blink|jump|mouse|hold
    src: str = "gaze"            # gaze|mouse|hold


def _feat_dist(a, b):
    """Норма разности фич (копия eyeconnect.normalize.is_saccade без numpy)."""
    try:
        return float(math.dist(a, b))
    except Exception:
        return float("inf")


class GazeProvider:
    def __init__(self, cam, tracker, filt, reg, width, height,
                 lost_conf=0.3, saccade_thr=0.25, jump_px=500.0,
                 ema_alpha=0.45, wink=True, jump_grace=5):
        """Дефолты = константы eyeconnect (MP_LOST_CONF, is_saccade.thr, jump_px, alpha).
        jump_grace — первых N валидных кадров после старта/возврата без jump-гейта
        (даём EMA сойтись; иначе стартовая фиксация в углу защёлкивает гейт)."""
        self.cam = cam
        self.tracker = tracker
        self.filt = filt
        self.reg = reg
        self.w = width
        self.h = height
        self.lost_conf = lost_conf
        self.saccade_thr = saccade_thr
        self.jump_px = jump_px
        self.ema_alpha = ema_alpha
        self.wink_enabled = wink
        self.jump_grace = jump_grace
        self.reset()

    def reset(self):
        try:
            self.filt.reset()
        except Exception:
            pass
        self._sm_x = self.w / 2.0
        self._sm_y = self.h / 2.0
        self._has_pos = False
        self._prev = None
        self._grace_left = self.jump_grace

    def poll(self):
        try:
            f = self.cam.read()
        except Exception:
            return PointerSample(self._sm_x, self._sm_y, False, None, "no-frame", "gaze")
        if f is None:
            return PointerSample(self._sm_x, self._sm_y, False, None, "no-frame", "gaze")
        try:
            out = self.tracker.process(f)
            feat, conf, dbg = out
        except Exception:
            return PointerSample(self._sm_x, self._sm_y, False, None, "no-face", "gaze")
        try:
            conf_v = float(conf)
        except Exception:
            conf_v = float("-inf")
        if feat is None or not conf_v >= self.lost_conf:
            try:
                self.filt.reset()
            except Exception:
                pass
            self._prev = None
            self._grace_left = self.jump_grace  # возврат — заново сходимся
            return PointerSample(self._sm_x, self._sm_y, False, None, "no-face", "gaze")
        # гейт морганий на фичах: резкий скачок — кадр пропускаем целиком,
        # фильтр не травим. Опору обновляем: следующий steady-кадр проходит.
        if self._prev is not None and _feat_dist(self._prev, feat) > self.saccade_thr:
            self._prev = tuple(feat)
            self._grace_left = self.jump_grace
            return PointerSample(self._sm_x, self._sm_y, False, None, "blink", "gaze")
        try:
            self._prev = tuple(feat)
        except Exception:
            self._prev = feat
        try:
            sm = self.filt.update(feat)
        except Exception:
            return PointerSample(self._sm_x, self._sm_y, False, None, "no-face", "gaze")
        try:
            gx, gy = self.reg.predict(sm)
            gx = float(gx)
            gy = float(gy)
        except Exception:
            return PointerSample(self._sm_x, self._sm_y, False, None, "jump", "gaze")
        if not (math.isfinite(gx) and math.isfinite(gy)):
            return PointerSample(self._sm_x, self._sm_y, False, None, "jump", "gaze")
        gx = float(min(max(gx, 0), self.w - 1))
        gy = float(min(max(gy, 0), self.h - 1))
        # анти-моргание на выходе: телепорт дальше jump_px за кадр — стоим.
        # Порядок важен (как в run_cursor): фильтр уже обновлён и сходится,
        # поэтому настоящая саккада проходит мелкими шагами, а одиночный
        # выброс режется здесь.
        # Краевой случай апстрима (чиним здесь, Фаза 3): первая фиксация далеко
        # от центра (>jump_px/0.55 от старта) защёлкивала гейт навсегда — grace
        # даёт EMA сойтись, дальше гейт работает как раньше.
        if (self._has_pos and self._grace_left <= 0
                and math.hypot(gx - self._sm_x, gy - self._sm_y) > self.jump_px):
            return PointerSample(self._sm_x, self._sm_y, False, None, "jump", "gaze")
        if self._grace_left > 0:
            self._grace_left -= 1
        self._has_pos = True
        a = self.ema_alpha
        self._sm_x = a * gx + (1 - a) * self._sm_x
        self._sm_y = a * gy + (1 - a) * self._sm_y
        wink_ev = None
        if self.wink_enabled and isinstance(dbg, dict):
            w = dbg.get("wink")
            if w in ("left", "right"):
                wink_ev = w
        return PointerSample(self._sm_x, self._sm_y, True, wink_ev, "ok", "gaze")


class MouseProvider:
    def poll(self):
        x, y = _wc.get_pos()
        return PointerSample(float(x), float(y), True, None, "mouse", "mouse")

    def reset(self):
        pass


class AutoProvider:
    def __init__(self, gaze, mouse, mouse_thr=2.0, cooldown=1.0, time_fn=None):
        """cooldown — сколько держать мышь после последнего её движения (как magnet COOLDOWN)."""
        self.gaze = gaze
        self.mouse = mouse
        self.mouse_thr = mouse_thr
        self.cooldown = cooldown
        self._time = time_fn or time.time
        self._anchor = None      # куда цикл последний раз ставил курсор
        self._last = None        # последний отданный сэмпл
        self._last_mouse_move = float("-inf")

    def reset(self):
        try:
            self.gaze.reset()
        except Exception:
            pass
        try:
            self.mouse.reset()
        except Exception:
            pass
        self._anchor = None
        self._last = None
        self._last_mouse_move = float("-inf")

    def stats(self):
        """Статистика внутреннего gaze-провайдера (для отчёта engine), если есть."""
        fn = getattr(self.gaze, "stats", None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
        return {}

    def note_output(self, x, y):
        """Цикл сообщает, куда поставил курсор (не считать это движением пользователя)."""
        self._anchor = (float(x), float(y))

    def poll(self):
        now = self._time()
        m = self.mouse.poll()
        if self._anchor is None:
            self._anchor = (m.x, m.y)
        if math.hypot(m.x - self._anchor[0], m.y - self._anchor[1]) > self.mouse_thr:
            self._last_mouse_move = now
        if (now - self._last_mouse_move) < self.cooldown:
            out = PointerSample(m.x, m.y, True, None, "mouse", "mouse")
            self._last = out
            # курсор не двигаем — фактическая позиция и есть выход цикла
            self._anchor = (m.x, m.y)
            return out
        g = self.gaze.poll()
        if g.valid:
            out = PointerSample(g.x, g.y, True, g.wink, g.note, "gaze")
            self._last = out
            return out
        if self._last is not None:
            return PointerSample(self._last.x, self._last.y, False, None, "hold", "hold")
        return PointerSample(m.x, m.y, False, None, "hold", "hold")


def _predict(prev, last, now, max_lead_s=0.12, max_lead_px=120.0):
    """Чистая функция: экстраполировать точку на now по двум последним сэмплам.

    prev/last: (PointerSample, t). Стоим -> та же точка; рывок скорости ->
    упираемся в max_lead_px от последнего замера (не улетаем)."""
    if last is None:
        return None
    ls, lt = last
    if prev is None:
        return ls
    ps, pt = prev
    if not ls.valid or not ps.valid:
        return ls
    dt = lt - pt
    if dt <= 1e-6:
        return ls
    lead = min(max(0.0, now - lt), max_lead_s)
    if lead <= 0:
        return ls
    dx = (ls.x - ps.x) / dt * lead
    dy = (ls.y - ps.y) / dt * lead
    d = math.hypot(dx, dy)
    if d <= 1e-9:
        return ls
    if d > max_lead_px:
        dx, dy = dx / d * max_lead_px, dy / d * max_lead_px
    return PointerSample(ls.x + dx, ls.y + dy, True, ls.wink, ls.note, ls.src)


class AsyncGaze:
    """Gaze-инференс в фоне: тяжёлый poll не тормозит цикл 120 Гц.

    Поток непрерывно опрашивает inner и кладёт (sample, t) под замок.
    poll() отдаёт последний замер + экстраполяцию (_predict), без блокировок
    инференса. Ошибка inner -> invalid-сэмпл, поток живёт дальше."""

    def __init__(self, inner, time_fn=None, max_lead_s=0.12, max_lead_px=120.0):
        self.inner = inner
        self._time = time_fn or time.time
        self.max_lead_s = max_lead_s
        self.max_lead_px = max_lead_px
        self._lock = threading.Lock()
        self._prev = None
        self._last = None
        self._polls = 0
        self._t0 = None
        self._last_dur = 0.0
        self._errors = 0
        self._stop_ev = threading.Event()
        self._thread = None

    def start(self, warmup_polls=0, timeout=180.0):
        """Старт + опционально дождаться N кадров (прогрев потока).

        Первые инференсы в свежем потоке катастрофически медленные
        (замер: 16-21с на RTX 5060 — per-thread init CUDA/cuDNN),
        дальше быстро. warmup>0 переносит эту цену в предсказуемый старт."""
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if not alive:
                self._stop_ev.clear()
                self._thread = threading.Thread(target=self._loop, daemon=True)
                self._thread.start()
        if warmup_polls > 0:
            import time as _t
            try:
                deadline_self = self._time() + timeout
            except Exception:
                deadline_self = None
            deadline_real = _t.time() + timeout
            while self.stats()["polls"] < warmup_polls:
                if _t.time() >= deadline_real:
                    break
                if deadline_self is not None:
                    try:
                        if self._time() >= deadline_self:
                            break
                    except Exception:
                        pass
                _t.sleep(0.05)
        return self

    def _loop(self):
        while not self._stop_ev.is_set():
            t0 = self._time()
            try:
                s = self.inner.poll()
            except Exception:
                s = PointerSample(0, 0, False, None, "error", "gaze")
                now = self._time()
                with self._lock:
                    self._errors += 1
                    if self._t0 is None:
                        self._t0 = now
                    self._prev, self._last = self._last, (s, now)
                    self._polls += 1
                    self._last_dur = now - t0
                try:
                    import time as _t
                    _t.sleep(0.01)
                except Exception:
                    pass
                continue
            now = self._time()
            with self._lock:
                if self._t0 is None:
                    self._t0 = now
                self._prev, self._last = self._last, (s, now)
                self._polls += 1
                self._last_dur = now - t0

    def poll(self):
        with self._lock:
            prev, last = self._prev, self._last
        if last is None:
            return PointerSample(0, 0, False, None, "cold", "gaze")
        return _predict(prev, last, self._time(),
                        self.max_lead_s, self.max_lead_px)

    def reset(self):
        try:
            self.inner.reset()
        except Exception:
            pass
        with self._lock:
            self._prev = None
            self._last = None
            self._polls = 0
            self._errors = 0
            self._t0 = None
            self._last_dur = 0.0

    def stop(self, timeout=2.0):
        with self._lock:
            th = self._thread
            self._thread = None
        self._stop_ev.set()
        if th is not None:
            th.join(timeout=timeout)

    def stats(self):
        with self._lock:
            polls, t0 = self._polls, self._t0
            last = self._last
            dur, err = self._last_dur, self._errors
            alive = self._thread is not None and self._thread.is_alive()
        now = self._time()
        el = max(now - t0, 1e-6) if t0 is not None else 0.0
        age = (now - last[1]) * 1000 if last else -1.0
        return {"polls": polls, "hz": polls / el if el else 0.0,
                "age_ms": age, "last_ms": dur * 1000, "errors": err,
                "alive": alive}
