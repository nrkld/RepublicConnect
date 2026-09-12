"""Тесты движка: pytest-compatible (def test_*) и прямой запуск.

Всё на фейках: курсор/цели/оверлей/провайдер/часы. ОС не трогаем.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # корень Ramazan/

from hybrid import engine
from hybrid.providers import PointerSample
from hybrid.snap_core import Target


class FakeCursor:
    IS_WIN = True

    def __init__(self, pos):
        self.pos = [float(pos[0]), float(pos[1])]
        self.sets = []
        self.clicks = []

    def ensure_dpi_aware(self):
        pass

    def get_pos(self):
        return (self.pos[0], self.pos[1])

    def set_pos(self, x, y):
        self.sets.append((float(x), float(y)))
        self.pos = [float(x), float(y)]
        return True

    def pressed(self, vk):
        return False

    def do_click(self, x, y, button="left"):
        self.clicks.append((float(x), float(y), button))
        return True


class FakeTargets:
    def __init__(self, ts):
        self._ts = list(ts)
        self.last_ms = 1.0
        self.last_count = len(ts)
        self.last_is_browser = False
        self.last_weblinks = 0
        self.last_fg = 0

    def start(self):
        pass

    def stop(self):
        pass

    def request_refresh(self):
        pass

    def clear(self):
        pass

    def get(self):
        return list(self._ts)


class FakeOverlay:
    def __init__(self):
        self.targets = []
        self.states = []
        self.counts = []

    def start(self):
        pass

    def stop(self):
        pass

    def set_target(self, key):
        self.targets.append(key)

    def set_state(self, on):
        self.states.append(on)

    def set_count(self, n):
        self.counts.append(n)

    def poll_action(self):
        return None


class ScriptProvider:
    def __init__(self, samples):
        self.samples = list(samples)
        self.notes = []

    def poll(self):
        if len(self.samples) > 1:
            return self.samples.pop(0)
        return self.samples[0]

    def note_output(self, x, y):
        self.notes.append((float(x), float(y)))


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _gaze(x, y, wink=None):
    return PointerSample(float(x), float(y), True, wink, "ok", "gaze")


def _mouse(x, y):
    return PointerSample(float(x), float(y), True, None, "mouse", "mouse")


def _ok_btn():
    return Target.from_rect(100, 100, 200, 140, name="OK")


def _run(provider, targets, cursor, overlay, clock, **kw):
    kw.setdefault("sleep_fn", lambda s: None)
    kw.setdefault("time_fn", clock)
    kw.setdefault("max_iters", 3)
    engine.run_loop(provider, targets=targets, cursor=cursor,
                    overlay=overlay, **kw)


def test_gaze_snaps_to_center():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    prov = ScriptProvider([_gaze(90, 110)])
    _run(prov, FakeTargets([_ok_btn()]), cur, ov, clock, source="gaze")
    assert cur.sets and cur.sets[-1] == (150.0, 120.0), cur.sets
    assert (100, 100, 200, 140) in ov.targets  # рамка показана
    assert prov.notes and prov.notes[-1] == (150.0, 120.0)  # auto-якорь обновлён


def test_gaze_passthrough_without_magnet():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    _run(ScriptProvider([_gaze(90, 110)]), FakeTargets([_ok_btn()]),
         cur, ov, clock, source="gaze", magnet=False)
    assert cur.sets[-1] == (90.0, 110.0), cur.sets


def test_invalid_sample_holds():
    cur, ov, clock = FakeCursor((5, 5)), FakeOverlay(), FakeClock()
    bad = PointerSample(5, 5, False, None, "no-face", "gaze")
    _run(ScriptProvider([_gaze(90, 110), bad, bad]), FakeTargets([]),
         cur, ov, clock, source="gaze")
    assert cur.sets == [(90.0, 110.0)], cur.sets  # дальше стоим


def test_wink_clicks_snapped_center():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    _run(ScriptProvider([_gaze(90, 110, wink="left")]), FakeTargets([_ok_btn()]),
         cur, ov, clock, source="gaze")
    assert cur.clicks == [(150.0, 120.0, "left")], cur.clicks  # в центр, не в сырую точку
    cur2, ov2 = FakeCursor((0, 0)), FakeOverlay()
    _run(ScriptProvider([_gaze(90, 110, wink="right")]), FakeTargets([_ok_btn()]),
         cur2, ov2, FakeClock(), source="gaze", wink_click=False)
    assert cur2.clicks == []


def test_mouse_preset_and_tearoff():
    t = _ok_btn()
    # точка в 30px от кнопки: mouse-пресет (20) не липнет (gaze-пресет лип бы)
    cur, ov, clock = FakeCursor((230, 120)), FakeOverlay(), FakeClock()
    _run(ScriptProvider([_mouse(230, 120)]), FakeTargets([t]),
         cur, ov, clock, source="mouse")
    assert cur.sets == [], cur.sets
    # рывок из центра: вырывание + cooldown, затем повторный захват
    cur, ov, clock = FakeCursor((150, 120)), FakeOverlay(), FakeClock()
    prov = ScriptProvider([_mouse(150, 120)])
    frames = {"n": 0}

    def hook(sample, out):
        frames["n"] += 1
        if frames["n"] == 1:
            cur.pos = [200.0, 120.0]  # пользователь дёрнул (+50px рывок)
        elif frames["n"] == 2:
            clock.advance(0.1)  # ещё cooldown — стоим
        elif frames["n"] == 3:
            clock.advance(1.0)  # cooldown вышел

    _run(prov, FakeTargets([t]), cur, ov, clock, source="mouse",
         max_iters=4, on_frame=hook)
    assert cur.sets == [(150.0, 120.0)], cur.sets  # только повторный захват


def test_engine_dwell_clicks_snapped():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    prov = ScriptProvider([_gaze(90, 110)])

    def hook(s, o):
        clock.advance(0.2)

    _run(prov, FakeTargets([_ok_btn()]), cur, ov, clock, source="gaze",
         dwell_s=0.5, max_iters=5, on_frame=hook)
    assert cur.clicks == [(150.0, 120.0, "left")], cur.clicks


def test_engine_dwell_suppressed_unsnapped():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    prov = ScriptProvider([_gaze(90, 110)])

    def hook(s, o):
        clock.advance(0.2)

    _run(prov, FakeTargets([_ok_btn()]), cur, ov, clock, source="gaze",
         magnet=False, dwell_s=0.5, max_iters=5, on_frame=hook)
    assert cur.clicks == [], cur.clicks


def test_pick_compute_device():
    dev, name = engine.pick_compute_device()
    assert (dev == "cpu" or dev.startswith("cuda")) and name


def test_needs_calibration():
    import json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        assert engine.needs_calibration(home=home) == "нет профиля"
        leg = home / ".eyeconnect"
        leg.mkdir()
        (leg / "gaze.npz").write_bytes(b"x")
        assert engine.needs_calibration(home=home) == "нет метаданных"
        (leg / "gaze_meta.json").write_text(json.dumps(
            {"screen_w": 1, "screen_h": 1, "tracker": "unigaze"}))
        r = engine.needs_calibration(home=home)
        assert r is not None and "1x1" in r, r


def test_cli_check_smoke():
    from hybrid.__main__ import main
    assert main([]) == 0


def test_loop_default_120hz():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    sleeps = []
    _run(ScriptProvider([_gaze(90, 110)]), FakeTargets([]), cur, ov, clock,
         source="gaze", sleep_fn=sleeps.append)
    assert sleeps and set(sleeps) == {1 / 120}, set(sleeps)


def test_null_targets_degradation():
    cur, ov, clock = FakeCursor((0, 0)), FakeOverlay(), FakeClock()
    _run(ScriptProvider([_gaze(90, 110)]), engine._NullTargets(),
         cur, ov, clock, source="gaze")
    assert cur.sets[-1] == (90.0, 110.0), cur.sets


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("ENGINE SMOKE OK")
