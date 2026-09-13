"""FaceMesh+Iris обёртка с поддержкой MediaPipe 0.10 (solutions) и 1.x (tasks).

Возвращает на кадр: feat (nx,ny), conf, debug-точки. При отсутствии модели —
отвал в mouse-fallback (для разработки UI без камеры/лица).
"""
import numpy as np

# Индексы FaceMesh (478): уголки глаз + ирисы (refined landmarks)
L_OUTER, L_INNER = 33, 133
R_OUTER, R_INNER = 362, 263
L_IRIS = [474, 475, 476, 477]
R_IRIS = [469, 470, 471, 472]
# Веки для EAR (открытость глаза): верх/низ
L_TOP, L_BOT = 159, 145
R_TOP, R_BOT = 386, 374

try:
    import mediapipe as mp
    _MP = mp
except Exception:
    _MP = None

from .normalize import features_from_eyes


def _download_model(url: str, dest, timeout: int = 60):
    """Скачать модель с таймаутом и проверкой размера. Битый файл удаляет."""
    import os
    import urllib.request
    tmp = str(dest) + ".tmp"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        import os
        if os.path.getsize(tmp) < 1_000_000:
            raise RuntimeError(f"модель слишком маленькая: {tmp}")
        os.replace(tmp, dest)
    except Exception:
        try:
            import os
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
        raise


class FaceTracker:
    MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                 "face_landmarker/float16/1/face_landmarker.task")

    def __init__(self, min_conf: float = 0.5):
        self.min_conf = min_conf
        self.backend = "none"
        self.fm = None
        self._tasks = None
        if _MP is not None:
            # 1) legacy solutions (MediaPipe 0.10.x, на Pi)
            try:
                if hasattr(_MP, "solutions") and hasattr(_MP.solutions, "face_mesh"):
                    self.fm = _MP.solutions.face_mesh.FaceMesh(
                        max_num_faces=1, refine_landmarks=True,
                        min_detection_confidence=min_conf,
                        min_tracking_confidence=min_conf)
                    self.backend = "solutions"
                    print("[tracker] backend=solutions")
                    return
            except Exception as e:
                print(f"[tracker] solutions недоступен: {e}")
            # 2) tasks API (MediaPipe 1.x, на ноутбуке) + автозагрузка модели
            try:
                import time
                from pathlib import Path
                import urllib.request
                model = Path.home() / ".eyeconnect" / "face_landmarker.task"
                model.parent.mkdir(parents=True, exist_ok=True)
                if not model.exists() or model.stat().st_size < 1_000_000:
                    print(f"[tracker] качаю модель {model.name} (~5МБ)...")
                    _download_model(self.MODEL_URL, model, timeout=60)
                import mediapipe as mp
                BaseOptions = mp.tasks.BaseOptions
                FaceLandmarker = mp.tasks.vision.FaceLandmarker
                FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
                VisionRunningMode = mp.tasks.vision.RunningMode
                opts = FaceLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=str(model)),
                    running_mode=VisionRunningMode.VIDEO,
                    num_faces=1,
                    min_face_detection_confidence=min_conf,
                    min_face_presence_confidence=min_conf,
                    min_tracking_confidence=min_conf)
                self._tasks = FaceLandmarker.create_from_options(opts)
                self._mp_image = mp.Image
                self._mp_format = mp.ImageFormat
                self._t0_mono = time.monotonic()
                self._last_ms = 0
                self.backend = "tasks"
                print("[tracker] backend=tasks")
                return
            except Exception as e:
                print(f"[tracker] tasks недоступен: {e}")
                self.backend = "none"
        print(f"[tracker] backend={self.backend} (работает только --mouse режим)")

    def process(self, bgr):
        """-> (feat(2,) | None, conf float, dbg dict)."""
        import cv2
        import time
        h, w = bgr.shape[:2]

        def build_feat(lm_get):
            def pt(i):
                x, y = lm_get(i)
                return (x * w, y * h)

            def ear(outer, inner, top, bot):
                # Eye Aspect Ratio: высота / ширина (безразмерный, инвариант масштаба)
                we = float(np.linalg.norm(np.asarray(pt(inner)) - np.asarray(pt(outer)))) + 1e-9
                he = float(np.linalg.norm(np.asarray(pt(top)) - np.asarray(pt(bot))))
                return he / we

            l_iris = np.mean([pt(i) for i in L_IRIS], axis=0)
            r_iris = np.mean([pt(i) for i in R_IRIS], axis=0)
            ear_l = ear(L_OUTER, L_INNER, L_TOP, L_BOT)
            ear_r = ear(R_OUTER, R_INNER, R_TOP, R_BOT)
            feat = features_from_eyes(l_iris, pt(L_OUTER), pt(L_INNER),
                                      r_iris, pt(R_OUTER), pt(R_INNER),
                                      l_w=max(ear_l, 0.02), r_w=max(ear_r, 0.02))
            dbg = {"l_iris": tuple(l_iris), "r_iris": tuple(r_iris),
                   "ear_l": ear_l, "ear_r": ear_r}
            return feat, dbg

        # tasks backend (1.x)
        if self._tasks is not None:
            try:
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                mp_img = self._mp_image(image_format=self._mp_format.SRGB, data=rgb)
                # реальные монотонные таймстампы вместо +=33 (иначе дрейф при fps!=30)
                cur_ms = int((time.monotonic() - self._t0_mono) * 1000)
                if cur_ms <= self._last_ms:
                    cur_ms = self._last_ms + 1
                self._last_ms = cur_ms
                res = self._tasks.detect_for_video(mp_img, cur_ms)
                if not res.face_landmarks:
                    return None, 0.0, {}
                lm = res.face_landmarks[0]
                feat, dbg = build_feat(lambda i: (lm[i].x, lm[i].y))
                return feat, 0.9, dbg
            except Exception:
                return None, 0.0, {}
        # legacy solutions backend (0.10.x)
        if self.fm is None:
            return None, 0.0, {}
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        res = self.fm.process(rgb)
        if not res.multi_face_landmarks:
            return None, 0.0, {}
        lm = res.multi_face_landmarks[0].landmark
        try:
            feat, dbg = build_feat(lambda i: (lm[i].x, lm[i].y))
            return feat, 0.9, dbg
        except Exception:
            return None, 0.0, {}

    def close(self):
        try:
            if self.fm is not None:
                self.fm.close()
        except Exception:
            pass
        finally:
            self.fm = None
        try:
            if self._tasks is not None:
                self._tasks.close()
        except Exception:
            pass
        finally:
            self._tasks = None
