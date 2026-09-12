"""CSV-лог сессии: gaze ~15Гц + dwell-события (дока 8.4)."""
import csv
import json
import time
from .. import config as C


class SessionLog:
    def __init__(self, name="session", meta=None, flush_every=30):
        C.ensure_profile_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.path = C.PROFILE_DIR / f"{name}_{ts}.csv"
        self.f = open(self.path, "w", newline="", encoding="utf-8")
        self.w = csv.writer(self.f)
        self.w.writerow(["t", "kind", "x", "y", "key", "text"])
        self._n = 0
        self._flush_every = max(1, int(flush_every))
        if meta:
            try:
                mp = self.path.with_suffix(".json")
                mp.write_text(json.dumps({"ts": ts, **meta}, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    def gaze(self, x, y):
        self.w.writerow([time.time(), "gaze", f"{x:.1f}", f"{y:.1f}", "", ""])
        self._tick()

    def event(self, key, text=""):
        self.w.writerow([time.time(), "dwell", "", "", key, text])
        self.flush()

    def _tick(self):
        self._n += 1
        if self._n % self._flush_every == 0:
            self.flush()

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass

    def close(self):
        try:
            self.flush()
            self.f.close()
        except Exception:
            pass
        return self.path
