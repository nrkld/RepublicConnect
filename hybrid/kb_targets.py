"""Цели dwell-клавиатуры для магнит-снапа (только stdlib).

Строит ``list[Target]`` (``hybrid.snap_core.Target``) из состояния
``DwellKeyboard`` (``EyeConnect-Ramazan/eyeconnect/ui/keyboard.py``)
БЕЗ импорта ``eyeconnect``: duck-typing + автономный fallback
``keyboard_targets_for_lang()`` без зависимости от ``DwellKeyboard``.

Геометрия — 1-в-1 формулы ``DwellKeyboard.layout_rects()``:
копии констант/раскладок ниже помечены источником. Порядок обхода
(буквы по рядам, затем SPECIAL, затем PRED:0-2) тоже повторяет оригинал.

Допуск расхождения:
- ``keyboard_targets(kb)`` при совпадении размера ``kb.w/kb.h`` с ``W/H``
  переиспользует словарь ``kb.layout_rects()`` напрямую — расхождение 0 px;
- иначе (стаб без ``layout_rects()`` или другой размер) геометрия
  пересчитывается теми же формулами с теми же константами —
  пофлотовая идентичность текущему ``keyboard.py``, расхождение 0 px;
- относительно отрисованного ``draw()``: там координаты округляются
  через ``int()`` — допуск <= 1 px на грань.
- Зона PAUSE (угол 80x80) в ``layout_rects()`` отсутствует специально
  (обрабатывается отдельно в ``update()``) — здесь её тоже нет.
"""

from .snap_core import Target

# --- Копии из EyeConnect-Ramazan/eyeconnect/ui/keyboard.py ---
LAYOUTS = {
    "EN": ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM,."],
    "RU": ["ЙЦУКЕНГШЩЗХЪ", "ФЫВАПРОЛДЖЭ", "ЯЧСМИТЬБЮ,."],
    "KZ": ["ӘІҢҒҮҰҚӨҺ", "АБВГДЕЖЗИ", "ЙКЛМНОПРСТ", "УФХЦЧШЩЪЫ", "ЬЭЮЯ,.?"],
}
LANG_CYCLE = ["KZ", "RU", "EN"]
SPECIAL = ["LANG", "SPACE", "DEL", "SOS"]
# --- Копии из EyeConnect-Ramazan/eyeconnect/config.py ---
KEY_CENTER = 150
KEY_EDGE = 180
KEY_GAP = 14
# --- Магические числа из DwellKeyboard.layout_rects() ---
_TOP = 150          # верх отдаём под текст + предикт
_BOTTOM_RESERVE = 70  # запас снизу в формуле высоты ряда
_SPEC_DY = 10       # отступ нижнего ряда спецкнопок
_PRED_Y = 78        # верхняя грань предикт-зон
_PRED_H = 60        # высота предикт-зон
_SIDE = 20          # боковой отступ (в формулах как w - 40)
_N_PRED = 3         # число кликабельных предикт-зон

__all__ = [
    "LAYOUTS", "LANG_CYCLE", "SPECIAL",
    "KEY_CENTER", "KEY_EDGE", "KEY_GAP",
    "keyboard_targets", "keyboard_targets_for_lang",
]


def _norm_lang(lang):
    return lang if lang in LAYOUTS else "KZ"


def _compute_rects(lang, W, H):
    """Точная копия арифметики DwellKeyboard.layout_rects()."""
    lang = _norm_lang(lang)
    rows = LAYOUTS[lang]
    rects = {}
    top = _TOP
    rh = (H - top - _BOTTOM_RESERVE) / (len(rows) + 1)
    for r, row in enumerate(rows):
        n = len(row)
        # периферия крупнее для взгляда: верх/низ ряды до KEY_EDGE
        max_kw = KEY_EDGE if (r == 0 or r == len(rows) - 1) else KEY_CENTER
        kw = min(max_kw, (W - 2 * _SIDE) / max(n, 1) - KEY_GAP)
        y0 = top + r * rh
        x_start = (W - n * (kw + KEY_GAP)) / 2
        for i, ch in enumerate(row):
            x0 = x_start + i * (kw + KEY_GAP)
            rects[ch] = (x0, y0, kw, rh - KEY_GAP)
    # нижний ряд спецкнопок
    y0 = H - rh - _SPEC_DY
    for i, s in enumerate(SPECIAL):
        x0 = _SIDE + i * ((W - 2 * _SIDE) / len(SPECIAL))
        rects[s] = (x0, y0, (W - 2 * _SIDE) / len(SPECIAL) - KEY_GAP, rh - _SPEC_DY)
    # верхний ряд предикта: 3 кликабельные зоны PRED:0..2
    pw = (W - 2 * _SIDE - 2 * KEY_GAP) / _N_PRED
    for i in range(_N_PRED):
        x0 = _SIDE + i * (pw + KEY_GAP)
        rects[f"PRED:{i}"] = (x0, _PRED_Y, pw, _PRED_H)
    return rects


def _targets_from_rects(rects):
    """dict {key: (x0, y0, w, h)} -> list[Target] (name=key, kind="key")."""
    out = []
    for key, (x0, y0, kw, kh) in rects.items():
        out.append(Target.from_rect(x0, y0, x0 + kw, y0 + kh,
                                    name=key, kind="key"))
    return out


def keyboard_targets_for_lang(lang="KZ", pred_words=None, W=1280, H=720):
    """Цели клавиатуры по коду языка — без зависимости от DwellKeyboard.

    ``pred_words`` принимается для симметрии API (слова живут только
    в подписях ``draw()``): зон всегда 3 (PRED:0-2), геометрия от слов
    не зависит. Неизвестный язык -> "KZ" (как ``DwellKeyboard.__init__``).
    """
    return _targets_from_rects(_compute_rects(_norm_lang(lang), W, H))


def keyboard_targets(kb, W=1280, H=720):
    """Цели по состоянию DwellKeyboard (duck-typing, без импорта eyeconnect).

    Использует от ``kb`` только то, что нужно:
    - ``kb.layout_rects()`` (если есть и размер ``kb.w/kb.h`` совпадает
      с ``W/H`` — словарь берётся как есть, расхождение 0 px);
    - иначе ``kb.lang`` (+ ``kb.pred`` читается, но на геометрию не влияет:
      предикт меняет лишь подписи зон в ``draw()``) и геометрия
      пересчитывается формулами ``_compute_rects`` для ``W/H``.
    Неизвестный/отсутствующий язык -> "KZ".
    """
    if kb is None:
        return keyboard_targets_for_lang("KZ", None, W, H)
    lang = getattr(kb, "lang", "KZ")
    _ = getattr(kb, "pred", None)  # duck-совместимость: читаем, не используем
    meth = getattr(kb, "layout_rects", None)
    rects = None
    kb_w = getattr(kb, "w", W)
    kb_h = getattr(kb, "h", H)
    if callable(meth):
        try:
            got = meth()
        except Exception:
            got = None
        if isinstance(got, dict) and got and kb_w == W and kb_h == H:
            rects = got
    elif isinstance(meth, dict) and meth and kb_w == W and kb_h == H:
        rects = meth
    if rects is None:
        rects = _compute_rects(_norm_lang(lang), W, H)
    return _targets_from_rects(rects)
