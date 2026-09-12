"""Пресеты гибрида: mouse — точная мышь, gaze — дрожащий взгляд.

Мыши хватает малых радиусов (20/35). Взгляду с точностью 1-2° нужны большие
(120/180 — как дефолты MagnetSnap и тесты): иначе снап не дотянется.
"""
MOUSE = {
    "capture": 20.0,
    "release": 35.0,
    "flick": 45.0,
    "cooldown": 0.6,
    "away_frames": 3,
}

GAZE = {
    "capture": 120.0,
    "release": 180.0,
    "flick": 45.0,
    "cooldown": 1.0,  # взгляд срывается чаще — пауза дольше
    "away_frames": 5,  # саккады/нистагм не должны сразу отпускать
}

_PRESETS = {"mouse": MOUSE, "gaze": GAZE}


def get_preset(source="mouse"):
    """Копия пресета (можно менять без побочек)."""
    try:
        base = _PRESETS[source]
    except KeyError:
        raise ValueError(f"source должен быть {sorted(_PRESETS)}, получен {source!r}")
    p = dict(base)
    assert p["release"] >= p["capture"], "выход должен быть >= входа"
    return p
