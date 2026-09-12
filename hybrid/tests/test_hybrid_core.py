"""Тесты hybrid-core: pytest-compatible (def test_*) и прямой запуск.

Без камеры/UIA. Ничего не двигает курсор (set_pos зовём только в текущую
позицию) и не кликает (do_click проверяем по сигнатуре, без вызова).
"""
import inspect
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # корень Ramazan/

from hybrid import snap_core
from hybrid import win_cursor
from hybrid import profiles
from hybrid.config import MOUSE, GAZE, get_preset


def _targets():
    a = snap_core.Target.from_rect(100, 100, 180, 140, name="A")
    b = snap_core.Target.from_rect(200, 100, 280, 140, name="B")
    return a, b


def test_presets_match_legacy():
    assert (MOUSE["capture"], MOUSE["release"]) == (20.0, 35.0)  # magnetcursor/config.py
    assert (GAZE["capture"], GAZE["release"]) == (120.0, 180.0)  # snap-дефолты/тесты
    for src in ("mouse", "gaze"):
        p = get_preset(src)
        assert p["release"] >= p["capture"]
    try:
        get_preset("nose")
        raise AssertionError("неизвестный пресет должен бросить ValueError")
    except ValueError:
        pass


def test_make_snap_sources():
    m = snap_core.make_snap("mouse")
    assert (m.cap, m.rel) == (20.0, 35.0)
    g = snap_core.make_snap("gaze")
    assert (g.cap, g.rel) == (120.0, 180.0)
    assert g.away_frames > m.away_frames  # взгляд терпимее к дрожанию


def test_snap_capture_miss_hysteresis():
    m = snap_core.MagnetSnap(120, 180)
    t = snap_core.Target.from_rect(100, 100, 200, 140, name="OK")
    sx, sy, got, snapped = m.update(90, 110, [t])
    assert snapped and got is t and (sx, sy) == (150.0, 120.0)
    m.reset()
    sx, sy, got, snapped = m.update(900, 700, [t])
    assert not snapped and got is None and (sx, sy) == (900, 700)
    m.reset()
    m.update(90, 110, [t])
    sx, sy, got, snapped = m.update(200 + 150, 120, [t])  # за capture, внутри release
    assert snapped and got is t
    sx, sy, got, snapped = m.update(200 + 250, 120, [t])  # за release
    assert not snapped and got is None


def test_snap_neighbours_and_tear():
    a, b = _targets()
    m = snap_core.MagnetSnap(120, 180)
    _, _, got, _ = m.update(110, 120, [a, b])
    assert got is a
    _, _, got, _ = m.update(195, 120, [a, b])
    assert got is a, "гистерезис: не прыгать между соседями"
    m.reset()
    _, _, got, _ = m.update(260, 120, [a, b])
    assert got is b
    m2 = snap_core.MagnetSnap(100, 150, flick_px=45.0)
    t2 = snap_core.Target.from_rect(100, 100, 200, 140, name="OK")
    m2.update(150, 120, [t2])
    assert m2.note_movement(150 + 60, 120, 60.0) is True
    m2.update(150, 120, [t2])
    assert m2.note_movement(160, 120, 10.0) is False
    assert m2.note_movement(175, 120, 15.0) is False
    assert m2.note_movement(195, 120, 20.0) is True


def test_snap_matches_magnetcursor():
    """Поведение 1-в-1 с magnetcursor.snap (если пакет рядом импортируется)."""
    try:
        from magnetcursor.snap import Target as MT, MagnetSnap as MM
    except ImportError:
        sib = Path(__file__).resolve().parents[2] / "magnetcursor"
        if str(sib) not in sys.path:
            sys.path.insert(0, str(sib))
        # сбросить закэшированный namespace-пакет от неудачной попытки выше
        for k in [k for k in sys.modules
                  if k == "magnetcursor" or k.startswith("magnetcursor.")]:
            sys.modules.pop(k)
        try:
            from magnetcursor.snap import Target as MT, MagnetSnap as MM
        except ImportError:
            print("skip test_snap_matches_magnetcursor: magnetcursor не найден")
            return
    a, b = _targets()
    ma = MT.from_rect(100, 100, 180, 140, name="A")
    mb = MT.from_rect(200, 100, 280, 140, name="B")
    ops = [(110, 120), (195, 120), (900, 700), (260, 120), (150, 120)]
    m1, m2 = snap_core.MagnetSnap(120, 180), MM(120, 180)
    for x, y in ops:
        r1 = m1.update(x, y, [a, b])
        r2 = m2.update(x, y, [ma, mb])
        n1 = r1[2].name if r1[2] else None
        n2 = r2[2].name if r2[2] else None
        assert (r1[0], r1[1], n1, r1[3]) == (r2[0], r2[1], n2, r2[3]), ((x, y), r1, r2)


def test_snap_local_fallback_matches():
    """Локальный fallback snap.py (без hybrid) ведёт себя как канон."""
    import importlib.util
    snap_path = (Path(__file__).resolve().parents[2]
                 / "magnetcursor" / "magnetcursor" / "snap.py")
    if not snap_path.exists():
        print("skip test_snap_local_fallback_matches: snap.py не найден")
        return
    saved = {k: sys.modules.pop(k) for k in
             [k for k in sys.modules if k == "hybrid" or k.startswith("hybrid.")]}
    sys.modules["hybrid"] = None  # любой import hybrid -> ImportError
    try:
        spec = importlib.util.spec_from_file_location("magnet_snap_local", snap_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("hybrid", None)
        sys.modules.update(saved)
    a = mod.Target.from_rect(100, 100, 180, 140, name="A")
    b = mod.Target.from_rect(200, 100, 280, 140, name="B")
    ha = snap_core.Target.from_rect(100, 100, 180, 140, name="A")
    hb = snap_core.Target.from_rect(200, 100, 280, 140, name="B")
    m1, m2 = mod.MagnetSnap(120, 180), snap_core.MagnetSnap(120, 180)
    for x, y in [(110, 120), (195, 120), (900, 700), (260, 120)]:
        r1 = m1.update(x, y, [a, b])
        r2 = m2.update(x, y, [ha, hb])
        n1 = r1[2].name if r1[2] else None
        n2 = r2[2].name if r2[2] else None
        assert (r1[0], r1[1], n1, r1[3]) == (r2[0], r2[1], n2, r2[3]), ((x, y), r1, r2)


def test_win_cursor_safe():
    win_cursor.ensure_dpi_aware()  # не должна бросать
    x, y = win_cursor.get_pos()
    assert isinstance(x, int) and isinstance(y, int)
    # set_pos только в текущую позицию — курсор зримо не двигается
    assert win_cursor.set_pos(x, y) in (True, False)
    assert win_cursor.set_sys_cursor is win_cursor.set_pos  # alias для eyeconnect
    assert win_cursor.pressed(0x7B) in (True, False)
    w, h = win_cursor.screen_size()
    assert w > 0 and h > 0
    # do_click НЕ вызываем (реальный клик!) — проверяем только сигнатуру
    sig = inspect.signature(win_cursor.do_click)
    assert list(sig.parameters) == ["x", "y", "button"]


def test_profiles_resolve_and_migrate():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        assert profiles.resolve_gaze_npz(home=home) is None
        leg = home / ".eyeconnect"
        leg.mkdir()
        (leg / "gaze.npz").write_bytes(b"fake-npz")
        (leg / "gaze_meta.json").write_text("{}")
        assert profiles.resolve_gaze_npz(home=home) == leg / "gaze.npz"
        done = profiles.migrate_legacy(home=home)
        assert set(done) == {"gaze.npz", "gaze_meta.json"}
        assert profiles.resolve_gaze_npz(home=home) == home / ".eyeconnect_hybrid" / "gaze.npz"
        assert (leg / "gaze.npz").exists(), "legacy не удаляем"
        done2 = profiles.migrate_legacy(home=home)  # без overwrite — пусто
        assert done2 == {}


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("HYBRID SMOKE OK")
