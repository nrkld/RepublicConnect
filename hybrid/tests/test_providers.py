"""Тесты провайдеров: pytest-compatible (def test_*) и прямой запуск.

Только фейки — без камеры/OC. Порядок гейтов сверен с run_cursor.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # корень Ramazan/

from hybrid.providers import (AsyncGaze, AutoProvider, GazeProvider,
                               MouseProvider, PointerSample, _predict)

W, H = 1920, 1080


class FakeCam:
    def __init__(self, frames):
        self.frames = list(frames)
        self.reads = 0

    def read(self):
        self.reads += 1
        if not self.frames:
            return None
        f = self.frames.pop(0)
        self.frames.append(f)  # зациклить последний сценарий
        return f


class FakeTracker:
    """Сценарий: список (feat, conf, dbg); повтор последнего, когда кончится."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def process(self, f):
        self.calls += 1
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


class FakeFilterPass:
    def __init__(self):
        self.updates = 0
        self.resets = 0

    def update(self, feat):
        self.updates += 1
        return feat

    def reset(self):
        self.resets += 1


class FakeFilterEMA:
    """Эмулирует сходимость настоящего GazeFilter: шаг ограничен alpha."""

    def __init__(self, alpha=0.5):
        self.a = alpha
        self.state = None
        self.resets = 0

    def update(self, feat):
        if self.state is None:
            self.state = tuple(feat)
        else:
            self.state = tuple(a * v + (1 - a) * s
                               for a, v, s in zip([self.a] * len(feat), feat, self.state))
        return self.state

    def reset(self):
        self.resets += 1
        self.state = None


class FakeReg:
    """predict: feat (fx, fy) -> экран. map_ позволяет точечные подмены."""

    def __init__(self, w=W, h=H, map_=None):
        self.w = w
        self.h = h
        self.map_ = map_ or {}

    def predict(self, feat):
        key = (round(float(feat[0]), 4), round(float(feat[1]), 4))
        if key in self.map_:
            return self.map_[key]
        return (float(feat[0]) * self.w, float(feat[1]) * self.h)


def _gaze(script, filt=None, reg=None, **kw):
    cam = FakeCam([object()] * 50)
    tr = FakeTracker(script)
    flt = filt or FakeFilterPass()
    return GazeProvider(cam, tr, flt, reg or FakeReg(), W, H, **kw), cam, tr, flt


def test_gaze_steady_and_wink():
    g, _, _, _ = _gaze([((0.5, 0.5), 0.9, {"wink": "left"})])
    s = g.poll()
    assert s.valid and s.src == "gaze" and s.note == "ok", s
    assert (s.x, s.y) == (960.0, 540.0)  # старт из центра = предсказанию
    assert s.wink == "left"
    g2, _, _, _ = _gaze([((0.5, 0.5), 0.9, {"wink": "right"})])
    assert g2.poll().wink == "right"
    g3, _, _, _ = _gaze([((0.5, 0.5), 0.9, {})], wink=False)
    assert g3.poll().wink is None
    g4, _, _, _ = _gaze([((0.5, 0.5), 0.9, {"wink": "left"})], wink=False)
    assert g4.poll().wink is None, "выключенный wink не должен просачиваться"


def test_gaze_no_face_resets_and_recovers():
    filt = FakeFilterPass()
    g, _, _, _ = _gaze([((0.5, 0.5), 0.9, {}),
                        (None, 0.0, {}),
                        ((0.5, 0.5), 0.1, {}),
                        ((0.55, 0.55), 0.9, {})], filt=filt)  # рядом: мимо jump-гейта
    assert g.poll().note == "ok"
    assert g.poll().note == "no-face"   # feat None
    assert g.poll().note == "no-face"   # conf < lost_conf
    assert filt.resets == 3  # 1 в конструкторе + 2 потери лица
    s = g.poll()  # прыжок фичи после потери — НЕ blink (prev сброшен)
    assert s.valid and s.note == "ok", s


def test_gaze_blink_gate_skips_frame():
    filt = FakeFilterPass()
    g, _, _, _ = _gaze([((0.5, 0.5), 0.9, {}),
                        ((5.0, 5.0), 0.9, {}),
                        ((0.5, 0.5), 0.9, {}),
                        ((0.5, 0.5), 0.9, {})], filt=filt)
    assert g.poll().valid
    b = g.poll()
    assert not b.valid and b.note == "blink", b
    # возврат тоже скачок в фичах — режется, дальше steady идёт
    assert g.poll().note == "blink"
    assert filt.updates == 1, "битые кадры не должны кормить фильтр"
    assert g.poll().valid
    assert filt.updates == 2


def test_gaze_jump_gate_and_recovery():
    # feat почти не двигается (blink-гейт молчит), а предсказание телепортится.
    # grace выключен — проверяем сырой гейт.
    reg = FakeReg(map_={(0.5, 0.5): (960.0, 540.0), (0.51, 0.51): (1900.0, 1000.0)})
    g, _, _, _ = _gaze([((0.5, 0.5), 0.9, {}),
                        ((0.51, 0.51), 0.9, {}),
                        ((0.51, 0.51), 0.9, {}),
                        ((0.5, 0.5), 0.9, {})], reg=reg, jump_grace=0)
    assert g.poll().note == "ok"
    j = g.poll()
    assert not j.valid and j.note == "jump", j
    assert (j.x, j.y) == (960.0, 540.0), "стоим на последней валидной"
    assert g.poll().note == "jump", "дергание на месте не отпускает гейт"
    s = g.poll()
    assert s.valid and (s.x, s.y) == (960.0, 540.0), s


def test_gaze_genuine_saccade_passes():
    # настоящая саккада: фильтр сходится постепенно, шаги мелкие — гейт пропускает
    filt = FakeFilterEMA(alpha=0.3)
    g, _, _, _ = _gaze([((0.5, 0.5), 0.9, {}), ((0.9, 0.9), 0.9, {})], filt=filt)
    assert g.poll().note == "ok"  # фиксация старта
    # первый кадр саккады режется blink-гейтом (как в run_cursor), дальше идёт
    assert g.poll().note == "blink"
    s = None
    for _ in range(25):  # двойное EMA (фильтр + выход) сходится не сразу
        s = g.poll()
        assert s.valid, s
    assert abs(s.x - 0.9 * W) < 5 and abs(s.y - 0.9 * H) < 5, s


def test_gaze_jump_grace_converges():
    # стартовая фиксация в дальнем углу: grace даёт сойтись, гейт не щёлкает
    reg = FakeReg(map_={(0.9, 0.9): (1900.0, 1000.0), (0.91, 0.91): (100.0, 100.0)})
    g, _, tr, _ = _gaze([((0.9, 0.9), 0.9, {})], reg=reg)
    s = None
    for _ in range(15):
        s = g.poll()
        assert s.valid, s
    assert abs(s.x - 1900.0) < 5 and abs(s.y - 1000.0) < 5, s
    # grace вышел — телепорт снова режется (feat рядом, blink молчит)
    tr.script = [((0.91, 0.91), 0.9, {})]
    j = g.poll()
    assert not j.valid and j.note == "jump", j


def test_gaze_clip_and_no_frame():
    reg = FakeReg(map_={(0.5, 0.5): (-50.0, 3000.0)})
    g, _, _, _ = _gaze([((0.5, 0.5), 0.9, {})], reg=reg)
    s = g.poll()  # первый кадр: EMA тянет от центра к обрезанной точке
    assert s.valid and s.x < W / 2 and s.y > H / 2, s
    cam = FakeCam([])
    tr = FakeTracker([((0.5, 0.5), 0.9, {})])
    g2 = GazeProvider(cam, tr, FakeFilterPass(), FakeReg(), W, H)
    n = g2.poll()
    assert not n.valid and n.note == "no-frame", n
    assert tr.calls == 0, "без кадра трекер не дёргаем"


def test_predict_static_stays():
    a = (PointerSample(100, 100, True, None, "ok", "gaze"), 1000.0)
    b = (PointerSample(100, 100, True, None, "ok", "gaze"), 1001.0)
    out = _predict(a, b, 1001.05)
    assert (out.x, out.y) == (100.0, 100.0) and out.valid


def test_predict_moves_ahead_and_clamps():
    a = (PointerSample(0, 0, True, None, "ok", "gaze"), 1000.0)
    b = (PointerSample(100, 0, True, None, "ok", "gaze"), 1001.0)  # 100px/с
    out = _predict(a, b, 1001.05)  # +5px
    assert abs(out.x - 105.0) < 1e-9 and out.y == 0.0
    out = _predict(a, b, 1002.0, max_lead_s=10.0, max_lead_px=120.0)  # +100px
    assert abs(out.x - 200.0) < 1e-9
    out = _predict(a, b, 1005.0, max_lead_s=10.0, max_lead_px=120.0)  # упор в кламп
    assert abs(out.x - 220.0) < 1e-9
    assert _predict(None, b, 1001.5) is b[0]
    bad = (PointerSample(0, 0, False, None, "no-face", "gaze"), 1001.0)
    assert _predict(a, bad, 1001.5) is bad[0]
    assert _predict(a, b, 1000.5) is b[0]  # назад во времени — как есть


def test_async_lifecycle():
    inner = FakeGazeScript([PointerSample(7, 8, True, None, "ok", "gaze")])
    ag = AsyncGaze(inner).start()
    try:
        import time as _t
        deadline = _t.time() + 5.0
        while ag.stats()["polls"] < 2 and _t.time() < deadline:
            _t.sleep(0.02)
        assert ag.stats()["polls"] >= 2
        s = ag.poll()
        assert s.valid and (s.x, s.y) == (7.0, 8.0), s
    finally:
        ag.stop()
    assert not (ag._thread is not None and ag._thread.is_alive())


def test_async_start_warmup_waits():
    inner = FakeGazeScript([PointerSample(7, 8, True, None, "ok", "gaze")])
    ag = AsyncGaze(inner)
    ag.start(warmup_polls=3, timeout=5.0)
    try:
        assert ag.stats()["polls"] >= 3
    finally:
        ag.stop()


def test_mouse_provider():
    from hybrid import win_cursor
    m = MouseProvider()
    s = m.poll()
    assert isinstance(s, PointerSample) and s.valid and s.src == "mouse", s
    assert (s.x, s.y) == tuple(float(v) for v in win_cursor.get_pos())
    m.reset()  # no-op, не бросает


class FakeMouse:
    def __init__(self, pos):
        self.pos = list(pos)

    def poll(self):
        return PointerSample(float(self.pos[0]), float(self.pos[1]),
                             True, None, "mouse", "mouse")

    def reset(self):
        pass


class FakeGazeScript:
    def __init__(self, samples):
        self.samples = list(samples)
        self.polls = 0

    def poll(self):
        self.polls += 1
        if len(self.samples) > 1:
            return self.samples.pop(0)
        return self.samples[0]

    def reset(self):
        pass


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _ok(x, y):
    return PointerSample(float(x), float(y), True, None, "ok", "gaze")


def _bad():
    return PointerSample(0, 0, False, None, "no-face", "gaze")


def test_auto_gaze_leads_mouse_follows_on_move():
    clock = FakeClock()
    auto = AutoProvider(FakeGazeScript([_ok(100, 100)]), FakeMouse((500, 500)),
                        time_fn=clock)
    s = auto.poll()  # якорь = мышь, движения нет -> gaze
    assert s.src == "gaze" and (s.x, s.y) == (100, 100), s
    auto.mouse.pos = [510, 500]  # пользователь дёрнул мышь
    s = auto.poll()
    assert s.src == "mouse" and (s.x, s.y) == (510, 500), s
    s = auto.poll()  # cooldown держит мышь
    assert s.src == "mouse", s
    clock.advance(2.0)
    s = auto.poll()  # cooldown вышел -> снова gaze
    assert s.src == "gaze", s


def test_auto_hold_and_loop_moves_ignored():
    clock = FakeClock()
    mouse = FakeMouse((500, 500))
    auto = AutoProvider(FakeGazeScript([_ok(100, 100), _bad()]), mouse, time_fn=clock)
    s = auto.poll()
    assert s.src == "gaze", s
    auto.note_output(s.x, s.y)  # цикл поставил курсор в точку взгляда...
    mouse.pos = [100, 100]      # ...ОС отразила это в GetCursorPos — не движение юзера
    clock.advance(2.0)
    s = auto.poll()
    assert s.src == "hold" and not s.valid, s  # gaze сдох -> держим последнюю


def test_auto_reset():
    clock = FakeClock()
    auto = AutoProvider(FakeGazeScript([_ok(1, 1)]), FakeMouse((2, 2)), time_fn=clock)
    auto.poll()
    auto.reset()
    assert auto._anchor is None and auto._last is None


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("PROVIDERS SMOKE OK")
