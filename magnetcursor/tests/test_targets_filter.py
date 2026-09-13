"""Тесты строгого фильтра целей: только контролы, без текстового мусора.

pytest-стиль (def test_*) + прямой запуск (python magnetcursor/tests/test_targets_filter.py).
Кейсы сохранены 1-в-1 из исходного скрипта.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
for _p in (_HERE.parents[2], _HERE.parents[1]):  # Ramazan/, magnetcursor-репо
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

uiautomation = pytest.importorskip("uiautomation")
import uiautomation as auto
from magnetcursor.targets import TargetCache, _accept, _default_strict

CT = auto.ControlType


def test_strict_controls_always_accepted():
    # строгий набор — всегда цели
    for c in (CT.ButtonControl, CT.HyperlinkControl, CT.MenuItemControl,
              CT.TabItemControl, CT.CheckBoxControl, CT.RadioButtonControl,
              CT.SplitButtonControl):
        assert _accept(c, lambda: False, strict=True) is True
        assert _accept(c, lambda: False, strict=False) is True


def test_strict_rejects_text_junk():
    # текстовый мусор: strict режет даже с «кликабельными» паттернами
    for c in (CT.TextControl, CT.ImageControl, CT.CustomControl,
              CT.DataItemControl, CT.TreeItemControl):
        assert _accept(c, lambda: True, strict=True) is False
        assert _accept(c, lambda: False, strict=True) is False


def test_listitem_desktop_only_in_strict():
    # ListItem в strict — только ярлыки рабочего стола
    assert _accept(CT.ListItemControl, lambda: False, strict=True) is False
    assert _accept(CT.ListItemControl, lambda: False, strict=True, desktop=True) is True


def test_nonstrict_legacy_behavior():
    # не-strict — как раньше: списки/деревья из базового набора, текст с Invoke — да
    assert _accept(CT.ListItemControl, lambda: False, strict=False) is True
    assert _accept(CT.TreeItemControl, lambda: False, strict=False) is True
    assert _accept(CT.TextControl, lambda: True, strict=False) is True
    assert _accept(CT.TextControl, lambda: False, strict=False) is False
    assert _accept(CT.PaneControl, lambda: False, strict=False) is False


def test_default_strict_from_config():
    # дефолт — из конфига (MAGNET_STRICT=True)
    assert _default_strict() is True
    assert TargetCache(strict=True).strict is True
    assert TargetCache().strict is True


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("TARGETS FILTER SMOKE OK")
