"""Тесты кликов: pytest-compatible (def test_*) и прямой запуск."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # корень Ramazan/

from hybrid.clicks import ClickEvent, ClickRouter, DwellClicker
from hybrid.providers import PointerSample


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _ps(x=100.0, y=100.0, wink=None):
    return PointerSample(float(x), float(y), True, wink, "ok", "gaze")


def test_dwell_fires_once_and_needs_refixation():
    d = DwellClicker(dwell_s=1.0, radius_px=45.0)
    assert d.update(100, 100, 1000.0, True) == (False, 0.0)
    clicked, prog = d.update(100, 100, 1000.5, True)
    assert clicked is False and abs(prog - 0.5) < 1e-9
    assert d.update(100, 100, 1001.0, True)[0] is True
    # якорь сброшен — сразу второй не стреляет
    assert d.update(100, 100, 1001.0, True) == (False, 0.0)


def test_dwell_movement_and_disarm_reset():
    d = DwellClicker(dwell_s=1.0, radius_px=45.0)
    d.update(100, 100, 1000.0, True)
    assert d.update(300, 100, 1000.9, True) == (False, 0.0)  # вышли из радиуса
    d.update(300, 100, 1000.9, True)
    assert d.update(300, 100, 1001.9, True)[0] is True
    assert d.update(300, 100, 1002.0, False) == (False, 0.0)  # мимо цели — сброс
    assert d.anchor is None


def test_router_wink_edge_and_cooldown():
    clock = FakeClock()
    r = ClickRouter(dwell_on=False, cooldown_s=10.0, time_fn=clock)
    ev = r.update(_ps(wink="left"), True, 150, 120)
    assert ev == ClickEvent("left", 150.0, 120.0)
    assert r.update(_ps(wink="left"), True, 150, 120) is None  # держим — тишина
    assert r.update(_ps(), True, 150, 120) is None
    clock.advance(11.0)  # cooldown вышел
    ev = r.update(_ps(wink="right"), True, 150, 120)
    assert ev == ClickEvent("right", 150.0, 120.0)  # другой фронт — можно
    r2 = ClickRouter(dwell_on=False, wink_on=False, time_fn=clock)
    assert r2.update(_ps(wink="left"), True, 150, 120) is None


def test_router_dwell_only_when_snapped():
    clock = FakeClock()
    r = ClickRouter(dwell_s=0.5, wink_on=False, time_fn=clock)
    for _ in range(5):
        assert r.update(_ps(), False, 150, 120) is None  # мимо цели — никогда
        clock.advance(0.2)
    ev = None
    for _ in range(5):
        ev = r.update(_ps(), True, 150, 120)
        clock.advance(0.2)
        if ev is not None:
            break
    assert ev == ClickEvent("dwell", 150.0, 120.0)


def test_router_cooldown_swallows_rapid_second():
    clock = FakeClock()
    r = ClickRouter(dwell_s=0.5, cooldown_s=10.0, time_fn=clock)
    assert r.update(_ps(wink="left"), True, 150, 120).kind == "left"
    clock.advance(0.6)  # dwell успел бы, но cooldown держит
    for _ in range(4):
        assert r.update(_ps(), True, 150, 120) is None
        clock.advance(0.2)
    r.note_invalid()
    clock.advance(11.0)
    ev = None
    for _ in range(6):
        ev = r.update(_ps(), True, 150, 120)
        clock.advance(0.2)
        if ev is not None:
            break
    assert ev is not None and ev.kind == "dwell"


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("CLICKS SMOKE OK")
