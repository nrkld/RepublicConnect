"""Тесты магнита: только логика snap.py — без Windows, камеры, UIA.

pytest-стиль (def test_*) + прямой запуск (python magnetcursor/tests/test_magnet.py).
Кейсы 1-11 сохранены 1-в-1 из исходного скрипта.
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[2], _HERE.parents[1]):  # Ramazan/, magnetcursor-репо
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from magnetcursor.snap import MagnetSnap, Target


def _ok_button():
    return Target.from_rect(100, 100, 200, 140, name="OK")


def test_capture_near_button():
    # 1) рядом с кнопкой -> снап в её центр
    m = MagnetSnap(120, 180)
    t = _ok_button()
    sx, sy, got, snapped = m.update(90, 110, [t])
    assert snapped and got is t and (sx, sy) == (150.0, 120.0), (sx, sy, snapped)


def test_miss_far():
    # 2) далеко -> свободно, сырая точка без изменений
    m = MagnetSnap(120, 180)
    t = _ok_button()
    sx, sy, got, snapped = m.update(900, 700, [t])
    assert not snapped and got is None and (sx, sy) == (900, 700)


def test_inside_button():
    # 3) точка внутри кнопки -> снап
    m = MagnetSnap(120, 180)
    t = _ok_button()
    sx, sy, _got, snapped = m.update(150, 120, [t])
    assert snapped and (sx, sy) == (150.0, 120.0)


def test_hysteresis_hold_and_release():
    # 4) гистерезис: вышли за capture (120), но не за release (180) -> держит
    # 5) вышли за release -> отпускает (продолжение того же захвата)
    m = MagnetSnap(120, 180)
    t = _ok_button()
    m.update(90, 110, [t])  # вошли
    _, _, got, snapped = m.update(200 + 150, 120, [t])  # 150px от центра, вне кнопки
    assert snapped and got is t, "должен держать до release-радиуса"
    _, _, got, snapped = m.update(200 + 250, 120, [t])
    assert not snapped and got is None, "должен отпустить за release-радиусом"


def test_neighbours_hysteresis():
    # 6) две соседние кнопки: не прыгает, пока держится первая
    m = MagnetSnap(120, 180)
    a = Target.from_rect(100, 100, 180, 140, name="A")
    b = Target.from_rect(200, 100, 280, 140, name="B")
    _, _, got, _ = m.update(110, 120, [a, b])
    assert got is a
    _, _, got, _ = m.update(195, 120, [a, b])  # ближе к B, но A в release
    assert got is a, "гистерезис: не прыгать между соседями"


def test_nearest_wins_free():
    # 7) ближайшая побеждает при свободном поиске
    m = MagnetSnap(120, 180)
    a = Target.from_rect(100, 100, 180, 140, name="A")
    b = Target.from_rect(200, 100, 280, 140, name="B")
    _, _, got, _ = m.update(260, 120, [a, b])
    assert got is b


def test_empty_targets():
    # 8) пустой список целей
    m = MagnetSnap(120, 180)
    sx, sy, _got, snapped = m.update(150, 120, [])
    assert not snapped and (sx, sy) == (150, 120)


def test_flick_tear():
    # 9) вырывание резким рывком
    m2 = MagnetSnap(100, 150, flick_px=45.0)
    t2 = _ok_button()
    m2.update(150, 120, [t2])  # снапнулись в центр
    assert m2.note_movement(150 + 60, 120, 60.0) is True, "рывок должен отпускать"


def test_steady_pull_tear():
    # 10) устойчивая тяга прочь за 3 кадра
    m2 = MagnetSnap(100, 150, flick_px=45.0)
    t2 = _ok_button()
    m2.update(150, 120, [t2])
    assert m2.note_movement(160, 120, 10.0) is False
    assert m2.note_movement(175, 120, 15.0) is False
    assert m2.note_movement(195, 120, 20.0) is True, "тяга прочь должна отпускать"


def test_jitter_holds():
    # 11) дрожание на месте не отпускает
    m2 = MagnetSnap(100, 150, flick_px=45.0)
    t2 = _ok_button()
    m2.update(150, 120, [t2])
    for px, py in [(152, 119), (149, 121), (151, 120), (150, 119), (152, 120)]:
        assert m2.note_movement(px, py, 2.0) is False
    assert m2.current is t2


if __name__ == "__main__":
    fns = [
        (k, v)
        for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("MAGNET SMOKE OK")
