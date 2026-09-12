"""Виртуальная dwell-клавиатура OpenCV: EN + RU + KZ-кириллица (дока 4.6, 5.5).

Раскладка крупная: центр 150px / периферия 180px.
Dwell MVP 1000мс с кольцом-прогрессом. Зоны: SOS, LANG (KZ->RU->EN),
SPACE, DEL, PRED:0-2 (кликабельный предикт top-3), пауза взглядом в левый-верхний угол 3с.
"""
import time
from pathlib import Path

import cv2
import numpy as np
from .. import config as C

# PIL для KZ-кириллицы: cv2 Hershey не рендерит ӘІҢҒҮҰҚӨҺ (показывает ????).
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except Exception:
    _PIL_OK = False

_FONT_CACHE: dict = {}


def _find_font_file():
    cand = [
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
        Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    ]
    for p in cand:
        if p.exists():
            return str(p)
    return None


def _get_font(px: int):
    if not _PIL_OK:
        return None
    if px in _FONT_CACHE:
        return _FONT_CACHE[px]
    fp = _find_font_file()
    try:
        f = ImageFont.truetype(fp, px) if fp else ImageFont.load_default()
    except Exception:
        try:
            f = ImageFont.load_default()
        except Exception:
            return None
    _FONT_CACHE[px] = f
    return f

LAYOUTS = {
    "EN": ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM,."],
    "RU": ["ЙЦУКЕНГШЩЗХЪ", "ФЫВАПРОЛДЖЭ", "ЯЧСМИТЬБЮ,."],
    "KZ": ["ӘІҢҒҮҰҚӨҺ", "АБВГДЕЖЗИ", "ЙКЛМНОПРСТ", "УФХЦЧШЩЪЫ", "ЬЭЮЯ,.?"],
}
LANG_CYCLE = ["KZ", "RU", "EN"]
SPECIAL = ["LANG", "SPACE", "DEL", "SOS"]
PAUSE_DWELL = 3.0
PAUSE_SIZE = 80


class DwellKeyboard:
    def __init__(self, lang="KZ", dwell_ms: int = C.DWELL_MS, w=1280, h=720):
        if lang not in LAYOUTS:
            lang = "KZ"
        self.lang = lang
        self.dwell = dwell_ms / 1000
        self.w, self.h = w, h
        self.text = ""
        self._focus = None
        self._t0 = None
        self._pause_until = 0
        self.pred = []
        self.rects = {}
        self._cache_key = None

    def toggle_lang(self):
        try:
            i = LANG_CYCLE.index(self.lang)
            self.lang = LANG_CYCLE[(i + 1) % len(LANG_CYCLE)]
        except ValueError:
            self.lang = "KZ"
        self._cache_key = None

    def layout_rects(self):
        key = (self.lang, self.w, self.h)
        if self._cache_key == key and self.rects:
            return self.rects
        rows = LAYOUTS[self.lang]
        self.rects = {}
        top = 150  # верх отдаём под текст + предикт
        rh = (self.h - top - 70) / (len(rows) + 1)
        for r, row in enumerate(rows):
            n = len(row)
            # периферия крупнее для взгляда: верх/низ ряды до KEY_EDGE
            max_kw = C.KEY_EDGE if (r == 0 or r == len(rows) - 1) else C.KEY_CENTER
            kw = min(max_kw, (self.w - 40) / max(n, 1) - C.KEY_GAP)
            y0 = top + r * rh
            x_start = (self.w - n * (kw + C.KEY_GAP)) / 2
            for i, ch in enumerate(row):
                x0 = x_start + i * (kw + C.KEY_GAP)
                self.rects[ch] = (x0, y0, kw, rh - C.KEY_GAP)
        # нижний ряд спецкнопок
        y0 = self.h - rh - 10
        for i, s in enumerate(SPECIAL):
            x0 = 20 + i * ((self.w - 40) / len(SPECIAL))
            self.rects[s] = (x0, y0, (self.w - 40) / len(SPECIAL) - C.KEY_GAP, rh - 10)
        # верхний ряд предикта: 3 кликабельные зоны PRED:0..2
        pw = (self.w - 40 - 2 * C.KEY_GAP) / 3
        for i in range(3):
            x0 = 20 + i * (pw + C.KEY_GAP)
            self.rects[f"PRED:{i}"] = (x0, 78, pw, 60)
        self._cache_key = key
        return self.rects

    def _apply_pred(self, idx: int):
        """Вставить предикт №idx вместо последнего слова."""
        if idx < 0 or idx >= len(self.pred):
            return None
        word = self.pred[idx]
        if not word:
            return None
        t = self.text
        if not t.strip():
            self.text = word + " "
        else:
            # заменить последнее слово, отбросив хвост-пунктуацию
            parts = t.split()
            prefix = t[: len(t) - len(parts[-1])]
            self.text = prefix + word + " "
        return word

    def update(self, gx, gy):
        """gx,gy — координаты взгляда в px окна. Возвращает событие-строку или None."""
        now = time.time()
        if now < self._pause_until:
            return None
        # пауза: взгляд в угол PAUSE_DWELL с — упрощённо: если в углу, ставим паузу 3с
        if gx < PAUSE_SIZE and gy < PAUSE_SIZE:
            if self._focus != "PAUSE":
                self._focus, self._t0 = "PAUSE", now
            elif now - self._t0 > PAUSE_DWELL:
                self._pause_until = now + 3.0
                self._focus = None
                return "PAUSE"
            return None
        key = None
        for k, (x0, y0, kw, kh) in self.layout_rects().items():
            if x0 <= gx <= x0 + kw and y0 <= gy <= y0 + kh:
                key = k
                break
        if key != self._focus:
            self._focus, self._t0 = key, now
            return None
        dwell_need = PAUSE_DWELL if key == "PAUSE" else self.dwell
        if key is not None and (now - self._t0) >= dwell_need:
            self._focus, self._t0 = None, now
            return self.press(key)
        return None

    def press(self, key):
        if key == "LANG":
            self.toggle_lang()
        elif key == "SPACE":
            self.text += " "
        elif key == "DEL":
            self.text = self.text[:-1]
        elif key == "SOS":
            # без лишних пробелов по краям — не ломает WPM и предикт
            self.text = (self.text + " [SOS] ").strip() + " "
        elif key == "PAUSE":
            pass
        elif key.startswith("PRED:"):
            try:
                idx = int(key.split(":")[1])
            except Exception:
                return key
            w = self._apply_pred(idx)
            return f"PRED:{w}" if w else key
        else:
            self.text += key
        return key

    def progress(self):
        if self._focus is None or self._t0 is None:
            return 0.0
        need = PAUSE_DWELL if self._focus == "PAUSE" else self.dwell
        return min(1.0, (time.time() - self._t0) / need)

    def draw(self, gaze=None):
        img = np.zeros((self.h, self.w, 3), np.uint8)
        cv2.rectangle(img, (0, 0), (self.w, 150), (30, 30, 30), -1)
        # пауза-угол: всегда виден + прогресс
        cv2.rectangle(img, (0, 0), (PAUSE_SIZE, PAUSE_SIZE), (40, 40, 40), -1)
        if self._focus == "PAUSE":
            p = self.progress()
            cv2.ellipse(img, (PAUSE_SIZE // 2, PAUSE_SIZE // 2),
                        (28, 28), 0, 0, int(360 * p), (0, 255, 255), 4)
        if time.time() < self._pause_until:
            cv2.putText(img, "PAUSE", (8, 48),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        rects = self.layout_rects()
        for k, (x0, y0, kw, kh) in rects.items():
            if k.startswith("PRED:"):
                col = (30, 110, 160)
            else:
                col = (70, 70, 70) if k not in SPECIAL else (50, 90, 140)
            if k == self._focus:
                col = (0, 160, 0)
            cv2.rectangle(img, (int(x0), int(y0)), (int(x0 + kw), int(y0 + kh)), col, -1)
            if k == self._focus:
                p = self.progress()
                cv2.ellipse(img, (int(x0 + kw / 2), int(y0 + kh / 2)),
                            (30, 30), 0, 0, int(360 * p), (0, 255, 0), 4)
        if gaze is not None:
            cv2.circle(img, (int(gaze[0]), int(gaze[1])), 10, (0, 0, 255), 2)
        # Текст поверх — через PIL (кириллица KZ/RU), fallback на cv2 если PIL нет
        pred_words = list(self.pred[:3])
        while len(pred_words) < 3:
            pred_words.append("—")
        texts = [
            (self.text[-48:] or " ", (90, 12), 28, (255, 255, 255)),
            (f"[{self.lang}] dwell {self.dwell:.1f}s LANG: KZ->RU->EN", (90, 44), 18, (0, 255, 255)),
        ]
        for k, (x0, y0, kw, kh) in rects.items():
            if k.startswith("PRED:"):
                try:
                    idx = int(k.split(":")[1])
                    label = pred_words[idx] if idx < len(pred_words) else "—"
                except Exception:
                    label = "—"
                texts.append((label, (int(x0) + 10, int(y0 + 16)), 22, (255, 255, 255)))
            else:
                texts.append((k, (int(x0) + 12, int(y0 + kh / 2 - 14)), 26, (255, 255, 255)))
        if _PIL_OK:
            try:
                pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                dr = ImageDraw.Draw(pil)
                for s, (tx, ty), sz, col_bgr in texts:
                    fnt = _get_font(sz)
                    # PIL: RGB, cv2: BGR
                    col_rgb = (col_bgr[2], col_bgr[1], col_bgr[0])
                    dr.text((tx, ty), s, font=fnt, fill=col_rgb)
                img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
                return img
            except Exception:
                pass
        # fallback без PIL (латиница ок, KZ/RU будет ????)
        cv2.putText(img, self.text[-48:], (90, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        for k, (x0, y0, kw, kh) in rects.items():
            label = k
            if k.startswith("PRED:"):
                try:
                    label = pred_words[int(k.split(':')[1])]
                except Exception:
                    label = "—"
            cv2.putText(img, label.encode("ascii", "replace").decode(),
                        (int(x0) + 12, int(y0 + kh / 2 + 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        return img
