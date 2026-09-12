"""Тесты оверлея (magnetcursor/overlay.py) — pytest-стиль, без живых циклов.

- существующие методы на месте (Overlay + NullOverlay);
- set_progress неблокирующий, не падает, стирается (фейк-канвас + очередь);
- старт/стоп без Tcl-ругательств в stderr — через subprocess, т.к. сообщение
  "Tcl_AsyncDelete: async handler deleted by the wrong thread" печатает сам
  интерпретатор Tcl в stderr уже после выхода (внутрипроцессный capsys его
  не видит). Живой цикл один и короткий (один старт/стоп в дочернем процессе).
"""

import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[2], _HERE.parents[1]):  # Ramazan/, magnetcursor-репо
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from magnetcursor.overlay import NullOverlay, Overlay

from magnetcursor import overlay as ov_mod

# --- существующие методы на месте -------------------------------------------

_PRESENT = ("start", "stop", "poll_action",
            "set_target", "set_state", "set_count", "set_progress")


@pytest.mark.parametrize("name", _PRESENT)
def test_methods_present_on_overlay(name):
    assert callable(getattr(Overlay, name, None)), f"Overlay.{name} missing"


@pytest.mark.parametrize("name", _PRESENT)
def test_methods_present_on_null_overlay(name):
    assert callable(getattr(NullOverlay, name, None)), f"NullOverlay.{name} missing"


def test_null_overlay_set_progress_noop():
    NullOverlay().set_progress(100, 100, 0.5)
    NullOverlay().set_progress(100, 100, None)
    assert NullOverlay().poll_action() is None


# --- set_progress: неблокирующий, кладёт команду в очередь -------------------

def _drain(ov):
    items = []
    try:
        while True:
            items.append(ov._q.get_nowait())
    except Exception:
        pass
    return items


def test_set_progress_queues_without_start():
    ov = Overlay()
    ov.set_progress(10, 20, 0.5)
    ov.set_progress(10, 20, None)
    ov.set_progress(10, 20, 1.0)
    kinds = _drain(ov)
    assert kinds[0] == ("PROGRESS", (10, 20, 0.5))
    assert kinds[1] == ("PROGRESS", (10, 20, None))
    assert kinds[2] == ("PROGRESS", (10, 20, 1.0))
    assert ov.poll_action() is None  # пустой _out


# --- _draw_progress: рисует дугу и стирает -----------------------------------

class _FakeCanvas:
    def __init__(self):
        self.deleted = []
        self.arcs = []

    def delete(self, tag):
        self.deleted.append(tag)

    def create_arc(self, x0, y0, x1, y1, **kw):
        self.arcs.append(((x0, y0, x1, y1), kw))
        return 1


def test_draw_progress_draws_arc():
    cv = _FakeCanvas()
    ov_mod._draw_progress(cv, 100, 100, 0.5)
    assert "progress" in cv.deleted
    assert len(cv.arcs) == 1
    (_box, kw) = cv.arcs[0]
    assert kw.get("tags") == "progress"
    assert kw.get("outline") == ov_mod.PROGRESS_COLOR
    assert kw.get("width") == ov_mod.PROGRESS_WIDTH
    assert kw.get("extent") == pytest.approx(-180.0)


@pytest.mark.parametrize("frac", [None, 0.0, 1.0, 1.5, -0.2])
def test_draw_progress_erases(frac):
    cv = _FakeCanvas()
    ov_mod._draw_progress(cv, 100, 100, frac)
    assert "progress" in cv.deleted
    assert cv.arcs == []


def test_draw_progress_none_xy_erases():
    cv = _FakeCanvas()
    ov_mod._draw_progress(cv, None, None, 0.5)
    assert "progress" in cv.deleted
    assert cv.arcs == []


# --- проводка в tick(): PROGRESS обрабатывается, смена цели всё чистит -------

def test_tick_wiring_progress_and_target_clear():
    run_src = inspect.getsource(Overlay._run)
    assert "PROGRESS" in run_src, "tick() должен обрабатывать команду PROGRESS"
    assert 'delete("all")' in run_src or "delete('all')" in run_src, \
        "смена TARGET чистит канвас (рамка + прогресс)"
    helper_src = inspect.getsource(ov_mod._draw_progress)
    assert "create_arc" in helper_src, "прогресс рисуется дугой create_arc"
    assert "progress" in helper_src


# --- живой старт/стоп в subprocess: без Tcl_AsyncDelete в stderr -------------

_SUBPROCESS_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {repo!r})
    from magnetcursor import overlay as m
    if not m._HAS_TK:
        print("SKIP_NO_TK")
        raise SystemExit(0)
    try:
        ov = m.Overlay()
        ov.start()
        time.sleep(0.8)
        th = ov._thread
        if th is None or not th.is_alive():
            print("SKIP_NO_DISPLAY")
            raise SystemExit(0)
        ov.set_target((100, 100, 200, 150))
        time.sleep(0.3)
        ov.set_progress(150, 120, 0.5)
        time.sleep(0.3)
        ov.set_progress(150, 120, None)
        ov.set_target((120, 120, 220, 170))
        time.sleep(0.3)
        ov.stop()
        time.sleep(0.2)
        print("OVERLAY_SUBPROCESS_OK")
    except SystemExit:
        raise
    except Exception as ex:
        print("SUBPROCESS_FAIL: %r" % (ex,))
        raise SystemExit(2)
""")


def test_start_stop_no_tcl_complaints_in_subprocess():
    repo = str(_HERE.parents[1])
    script = _SUBPROCESS_SCRIPT.format(repo=repo)
    try:
        r = subprocess.run([sys.executable, "-c", script],
                           capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail("оверлей-subprocess завис (timeout 30s)")
    out, err = r.stdout or "", r.stderr or ""
    if "SKIP_NO_TK" in out or "SKIP_NO_DISPLAY" in out:
        pytest.skip("нет дисплея/tkinter — живой старт/стоп пропущен")
    assert "Tcl_AsyncDelete" not in err, f"Tcl ругается в stderr: {err[-500:]}"
    assert "Tcl_AsyncDelete" not in out
    assert r.returncode == 0, f"код {r.returncode}, out={out[-500:]}, err={err[-500:]}"
    assert "OVERLAY_SUBPROCESS_OK" in out, f"нет маркера OK: {out[-500:]}"
