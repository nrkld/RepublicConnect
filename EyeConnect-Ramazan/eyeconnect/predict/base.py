"""Частотный предикт MVP: префиксные подсказки top-3 (дока 5.2-5.3 упрощённо).

Полноценные kenlm/Presage — фаза 3. Здесь встроенные мини-словари EN/KZ/RU
+ автозагрузка data/kz_top5k.txt, data/ru_top5k.txt и data/en_top10k.txt (по слову на строку).
"""
from pathlib import Path

_EN_MINI = """the be to of and a in that have hello how are you what where when with for this from
they say her she will one all would there their eye type gaze keyboard help thanks please""".split()

_KZ_MINI = """және бұл деп сәлем қалайсың рахмет көмек үшін мен сен біз сіз олар бар жоқ
керек болады еді аты жөні мектеп компьютер көз перне сөз сөйлеу""".split()

_RU_MINI = """и в не на я что ты с а он она это как привет спасибо помощь да нет
можно нужно глаз клавиатура слово речь компьютер помощь взгляд печатать""".split()

_KZ_SUFFIX = ["лар", "лер", "дар", "дер", "ның", "нің", "ға", "ге", "ды", "ді"]

_LANG_FILES = {
    "KZ": "kz_top5k.txt",
    "RU": "ru_top5k.txt",
    "EN": "en_top10k.txt",
}

_MINI = {"KZ": _KZ_MINI, "RU": _RU_MINI, "EN": _EN_MINI}

_PUNCT = ".,!?;:«»\"'()[]{}"


def _last_token(text: str) -> str:
    """Последнее слово без пунктуации, в исходном регистре."""
    if not text or not text.strip():
        return ""
    tok = text.strip().split()[-1]
    return tok.strip(_PUNCT)


class PrefixPredictor:
    def __init__(self, lang="KZ"):
        if lang not in _MINI:
            lang = "KZ"
        self.lang = lang
        self.words = list(_MINI[lang])
        self._load_external(lang)
        # множество для быстрой проверки "слово набрано целиком" (KZ суффиксы)
        self._known = {w.lower() for w in self.words}

    def _load_external(self, lang):
        base = Path(__file__).resolve().parents[1] / "data"
        fn = base / _LANG_FILES.get(lang, "kz_top5k.txt")
        if fn.exists():
            try:
                extra = []
                for w in fn.read_text(encoding="utf-8").splitlines():
                    w = w.strip()
                    if not w or len(w) > 40:
                        continue
                    extra.append(w)
                    if len(extra) >= 10000:
                        break
                # дедуп, внешние выше приоритетом, сохраняем порядок
                seen = set()
                dedup = []
                for w in extra + self.words:
                    wl = w.lower()
                    if wl not in seen:
                        seen.add(wl)
                        dedup.append(w)
                self.words = dedup
            except Exception:
                pass

    def suggest(self, prefix: str, n=3):
        p = _last_token(prefix or "")
        if not p:
            return self.words[:n]
        pl = p.lower()
        out = [w for w in self.words if w.lower().startswith(pl) and w.lower() != pl]
        # KZ: суффиксы только если слово набрано целиком (иначе был спам xyzлар)
        if self.lang == "KZ" and len(out) < n and pl in self._known:
            out += [p + s for s in _KZ_SUFFIX]
        return out[:n]

    def complete(self, text: str, word: str) -> str:
        """Заменить последнее слово на word + пробел. Сохраняет регистр начала."""
        if not word:
            return text
        t = text or ""
        if not t.strip():
            return word + " "
        parts = t.split()
        # сохранить заглавность префикса: если юзер набирал капсом — капсом и вставить
        last = parts[-1]
        core = last.strip(_PUNCT)
        if core.isupper():
            word = word.upper()
        elif core[:1].isupper():
            word = word[:1].upper() + word[1:]
        # заменить только core, пунктуацию-хвост отбросить
        prefix = t[: len(t) - len(last)]
        return prefix + word + " "
