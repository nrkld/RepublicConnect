"""Пресеты гибрида: mouse — точная мышь, gaze — дрожащий взгляд.

Мыши хватает малых радиусов (20/35). Взгляд: capture 70/release 120 —
компромисс между дотягиванием при точности 1-2° и возможностью уйти
на соседний элемент.
"""
MOUSE = {
    "capture": 20.0,
    "release": 35.0,
    "flick": 45.0,
    "cooldown": 0.6,
    "away_frames": 3,
}

GAZE = {
    "capture": 70.0,
    "release": 120.0,
    "flick": 45.0,
    "cooldown": 1.0,  # взгляд срывается чаще — пауза дольше
    "away_frames": 4,
}

_PRESETS = {"mouse": MOUSE, "gaze": GAZE}


def get_preset(source="mouse"):
    """Копия пресета (можно менять без побочек)."""
    try:
        base = _PRESETS[source]
    except KeyError:
        raise ValueError(f"source должен быть {sorted(_PRESETS)}, получен {source!r}")
    p = dict(base)
    if not p["release"] >= p["capture"]:
        raise ValueError("выход должен быть >= входа")
    return p
