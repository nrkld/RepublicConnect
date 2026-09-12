"""Тесты hybrid/kb_targets.py: pytest-стиль (def test_*) и прямой запуск.

Без камеры/eyeconnect: только duck-typed стабы + fallback-конструктор.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # корень Ramazan/

from hybrid import kb_targets
from hybrid.kb_targets import (
    LAYOUTS, SPECIAL, keyboard_targets, keyboard_targets_for_lang,
)

W, H = 1280, 720


class _Stub:
    """Минимальный duck-typed DwellKeyboard без layout_rects (fallback-путь)."""

    def __init__(self, lang="KZ", pred=None, w=W, h=H):
        self.lang = lang
        self.pred = list(pred) if pred else []
        self.w, self.h = w, h


def _by_name(ts):
    return {t.name: t for t in ts}


def _overlaps(a, b):
    # строгое пересечение внутренностей (касание гранями — норма)
    return (a.left < b.right and b.left < a.right
            and a.top < b.bottom and b.top < a.bottom)


def test_all_langs_covered_no_overlap():
    for lang in ("KZ", "RU", "EN"):
        ts = keyboard_targets_for_lang(lang, W=W, H=H)
        got = _by_name(ts)
        letters = set("".join(LAYOUTS[lang]))
        assert letters <= set(got), (lang, letters - set(got))
        assert len(got) == len(letters) + len(SPECIAL) + 3, lang  # +PRED:0-2
        assert {t.name for t in ts if t.name.startswith("PRED:")} == {
            "PRED:0", "PRED:1", "PRED:2"}, lang
        for t in ts:
            assert t.kind == "key", (lang, t)
            assert 0 <= t.left < t.right <= W, (lang, t)
            assert 0 <= t.top < t.bottom <= H, (lang, t)
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                assert not _overlaps(ts[i], ts[j]), (
                    lang, ts[i].name, ts[j].name)
        centres = {(t.cx, t.cy) for t in ts}
        assert len(centres) == len(ts), lang


def test_lang_sos_present():
    for lang in ("KZ", "RU", "EN"):
        got = _by_name(keyboard_targets(_Stub(lang)))
        assert "LANG" in got and "SOS" in got, lang


def test_lang_change_changes_set():
    sets = {}
    for lang in ("KZ", "RU", "EN"):
        got = _by_name(keyboard_targets(_Stub(lang)))
        letters = {n for n in got if len(n) == 1}
        sets[lang] = letters
    assert sets["KZ"] != sets["RU"] != sets["EN"]
    assert sets["KZ"] != sets["EN"]
    assert "Ә" in sets["KZ"] and "Ә" not in sets["EN"]
    assert "Q" in sets["EN"] and "Q" not in sets["KZ"]


def test_pred_words_in_zones():
    words = ["сәлем", "әлем", "күн"]
    plain = _by_name(keyboard_targets_for_lang("KZ", W=W, H=H))
    with_words = _by_name(keyboard_targets_for_lang("KZ", pred_words=words,
                                                    W=W, H=H))
    assert {"PRED:0", "PRED:1", "PRED:2"} <= set(with_words)
    # слова не двигают зоны: геометрия 1-в-1
    for k in ("PRED:0", "PRED:1", "PRED:2"):
        a, b = plain[k], with_words[k]
        assert (a.left, a.top, a.right, a.bottom) == (
            b.left, b.top, b.right, b.bottom), k
    via_kb = _by_name(keyboard_targets(_Stub("KZ", pred=words)))
    assert {"PRED:0", "PRED:1", "PRED:2"} <= set(via_kb)


def test_duck_typing_no_eyeconnect():
    assert not any(m == "eyeconnect" or m.startswith("eyeconnect.")
                   for m in sys.modules), "kb_targets не должен тянуть eyeconnect"
    ts = keyboard_targets(object())  # пустой объект -> дефолт KZ
    assert "Ә" in _by_name(ts)
    # стаб с родным layout_rects() и совпадающим размером — reuse 0 px
    rects = kb_targets._compute_rects("RU", W, H)
    kb = _Stub("RU")
    kb.layout_rects = lambda: rects
    ts = keyboard_targets(kb)
    for t in ts:
        x0, y0, kw, kh = rects[t.name]
        assert (t.left, t.top, t.right, t.bottom) == (
            x0, y0, x0 + kw, y0 + kh), t.name
    # чужой размер -> пересчёт под запрошенный W/H
    small = keyboard_targets(_Stub("EN", w=640, h=360), W=640, H=360)
    ref = keyboard_targets_for_lang("EN", W=640, H=360)
    assert [(t.left, t.top, t.right, t.bottom) for t in small] == [
        (t.left, t.top, t.right, t.bottom) for t in ref]
    try:
        keyboard_targets_for_lang("XX", W=W, H=H)
    except Exception:
        raise AssertionError("неизвестный язык должен фолбэчиться в KZ")
    else:
        assert "Ә" in _by_name(keyboard_targets_for_lang("XX", W=W, H=H))


def test_geometry_matches_keyboard_formulas():
    # EN: 3 ряда -> rh=(720-150-70)/4=125; ряд 0: n=10, kw=min(180,124-14)=110
    got = _by_name(keyboard_targets_for_lang("EN", W=1280, H=720))
    q = got["Q"]  # первая клавиша, x_start=(1280-10*124)/2=20
    assert (q.left, q.top, q.right, q.bottom) == (20.0, 150.0, 130.0, 261.0), q
    # LANG: y0=720-125-10=585, w=310-14=296, h=115
    lang = got["LANG"]
    assert (lang.left, lang.top, lang.right, lang.bottom) == (
        20.0, 585.0, 316.0, 700.0), lang
    # PRED:1: pw=(1240-28)/3, x0=20+418
    pw = (1280 - 40 - 2 * 14) / 3
    p1 = got["PRED:1"]
    assert (p1.left, p1.top, p1.right, p1.bottom) == (
        20 + (pw + 14), 78, 20 + (pw + 14) + pw, 138), p1


if __name__ == "__main__":
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for name, fn in fns:
        fn()
        print(f"ok {name}")
    print("KB SMOKE OK")
