"""Единый профиль ~/.eyeconnect_hybrid с обратной совместимостью.

Старые пути (~/.eyeconnect/gaze.npz, ~/.magnetcursor/) не трогаем и не удаляем:
resolve_* сначала смотрит гибрид, потом legacy. migrate_legacy только копирует.
Переключение записей на гибрид — в Фазе 6 (упаковка).
"""
import shutil
from pathlib import Path

HYBRID_DIR_NAME = ".eyeconnect_hybrid"
LEGACY_EYE_NAME = ".eyeconnect"
LEGACY_MAG_NAME = ".magnetcursor"

GAZE_NPZ = "gaze.npz"
GAZE_META = "gaze_meta.json"
MAGNET_JSON = "magnet.json"


def _home(home=None):
    return Path(home) if home is not None else Path.home()


def hybrid_dir(home=None):
    return _home(home) / HYBRID_DIR_NAME


def ensure_hybrid_dir(home=None):
    d = hybrid_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    return d


def gaze_npz_path(home=None):
    return hybrid_dir(home) / GAZE_NPZ


def gaze_meta_path(home=None):
    return hybrid_dir(home) / GAZE_META


def magnet_json_path(home=None):
    return hybrid_dir(home) / MAGNET_JSON


def crash_log_path(home=None):
    return hybrid_dir(home) / "hybrid_crash.log"


def legacy_eyeconnect_dir(home=None):
    return _home(home) / LEGACY_EYE_NAME


def legacy_magnet_dir(home=None):
    return _home(home) / LEGACY_MAG_NAME


def resolve_gaze_npz(home=None):
    """Путь к рабочему gaze.npz: гибрид -> legacy -> None."""
    p = gaze_npz_path(home)
    if p.exists():
        return p
    leg = legacy_eyeconnect_dir(home) / GAZE_NPZ
    return leg if leg.exists() else None


def resolve_gaze_meta(home=None):
    p = gaze_meta_path(home)
    if p.exists():
        return p
    leg = legacy_eyeconnect_dir(home) / GAZE_META
    return leg if leg.exists() else None


def migrate_legacy(home=None, overwrite=False):
    """Скопировать legacy-профиль в гибрид (legacy остаётся). -> {имя: путь назначения}."""
    done = {}
    leg = legacy_eyeconnect_dir(home)
    dst_dir = ensure_hybrid_dir(home)
    for name in (GAZE_NPZ, GAZE_META):
        src = leg / name
        if not src.exists():
            continue
        dst = dst_dir / name
        if dst.exists() and not overwrite:
            continue
        try:
            shutil.copy2(src, dst)
            done[name] = str(dst)
        except Exception:
            pass
    return done
