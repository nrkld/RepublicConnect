"""UniGaze трекер (ViT-H/14, joint-модель) для EyeConnect.

Upstream: https://github.com/ut-vision/UniGaze (код) +
  https://huggingface.co/UniGaze/UniGaze-models (веса) —
  WACV 2026 "UniGaze: Towards Universal Gaze Estimation via Large-scale
  Pre-Training" (MAE ViT, обучен на объединении ETH-XGaze/MPII/GazeCapture/
  EYEDIAP/Gaze360; кросс-доменная ошибка ~5-7° против ~10° у L2CS-Gaze360).
Код upstream'а НЕ вендорим (лицензия MG-NC-RAI, не MIT): используем pip-пакет
  `unigaze` (только загрузчик весов) + face_alignment (FAN-68) + torch.
Нормализация лица — собственная реализация стандартного алгоритма
  Zhang et al. ETRA-2018 (focal 960 / dist 600 / ROI 224, warp через solvePnP),
  3D-модель — 6 точек对应 FAN [36,39,42,45,31,35].
Веса: HF-кэш (unigaze_h14_joint.safetensors, ~2.5ГБ). Лицензия весов MG-NC-RAI:
  только некоммерческое использование (персональный ассистивный — ок),
  веса в git НЕ коммитим.

Выход — [pitch, yaw] в радианах (камерная система, после денормализации),
  совместим с FaceTracker/L2CSTracker по сигнатуре process().
Для экрана нужна калибровка: фича [pitch, yaw] -> GazeRegressor/RBF.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

# 3D-модель лица (мм) для solvePnP: строки generic-модели под FAN-индексы
# [36, 39, 42, 45, 31, 35] (уголки глаз + крылья носа). Значения — из
# общедоступной модели ETH-XGaze/UniGaze (face_model.txt, строки 20/23/26/29/15/19).
_PNP_3D = np.array([
    [-46.51, -38.33, 36.42],   # 36: внешний угол правого глаза
    [-17.76, -32.59, 29.08],   # 39: внутренний угол правого глаза
    [18.04, -30.96, 29.06],    # 42: внутренний угол левого глаза
    [44.74, -34.11, 36.73],    # 45: внешний угол левого глаза
    [-10.61, 12.96, 21.62],    # 31: левое крыло носа
    [11.29, 13.86, 21.84],     # 35: правое крыло носа
], dtype=np.float64)
_PNP_2D = (36, 39, 42, 45, 31, 35)

_FOCAL_NORM = 960.0
_DIST_NORM = 600.0
_ROI = 224
_HEAD_POSE_GATE_DEG = 80.0
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _pitchyaw_to_vector(py):
    """[pitch, yaw] -> единичный 3D-вектор (та же конвенция, что у UniGaze)."""
    p, y = float(py[0]), float(py[1])
    return np.array([np.cos(p) * np.sin(y), np.sin(p),
                     np.cos(p) * np.cos(y)], dtype=np.float64)


def _vector_to_pitchyaw(v):
    """Единичный 3D-вектор -> [pitch, yaw] рад."""
    v = np.asarray(v, dtype=np.float64).reshape(3)
    v = v / (np.linalg.norm(v) + 1e-12)
    return np.array([np.arcsin(np.clip(v[1], -1.0, 1.0)),
                     np.arctan2(v[0], v[2])], dtype=np.float64)


class UniGazeTracker:
    """Gaze-трекер: RetinaFace (кэш) + FAN-68 + нормализация + UniGaze ViT-H.

    process(bgr) -> (feat [pitch, yaw] рад | None, conf, dbg).
    """

    def __init__(self, model_name: str = "unigaze_h14_joint",
                 device: str = "auto", conf_thr: float = 0.5,
                 det_interval: int = 3, det_width: int = 400,
                 warmup: bool = True):
        import torch
        import face_alignment
        from unigaze import load as unigaze_load
        from .l2cs_backend import _ensure_imports as _l2cs_imports

        self._torch = torch
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        RetinaFace, _ = _l2cs_imports()
        if self.device.type == "cpu":
            self.detector = RetinaFace()
        else:
            self.detector = RetinaFace(gpu_id=self.device.index or 0)

        import face_alignment as _fa
        self.fa = _fa.FaceAlignment(
            _fa.LandmarksType.TWO_D, flip_input=False,
            device=str(self.device), compile=False)

        print(f"[unigaze] загрузка {model_name} (веса ~2.5ГБ, HF-кэш)...",
              flush=True)
        self.model_name = model_name
        self.model = unigaze_load(model_name, device=str(self.device))

        self.conf_thr = float(conf_thr)
        self._det_interval = max(1, int(det_interval))
        self._det_width = max(160, int(det_width))
        self._det_counter = 0
        self._cached_faces = []
        if warmup:
            self.warmup()

    # -- нормализация (ETRA-2018, собственная реализация) -------------------
    @staticmethod
    def _dummy_camera(image):
        h, w = image.shape[:2]
        f = float(w * 4)
        cam = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]],
                       dtype=np.float64)
        return cam, np.zeros((1, 5), dtype=np.float64)

    def _normalize_face(self, image_bgr, lm68):
        """FAN-68 landmarks -> (warp224_rgb, R). None если поза дикая."""
        import cv2
        cam, dist = self._dummy_camera(image_bgr)
        pts2d = np.ascontiguousarray(
            lm68[list(_PNP_2D), :].astype(np.float64).reshape(6, 1, 2))
        ok, hr, ht = cv2.solvePnP(_PNP_3D.reshape(6, 1, 3), pts2d, cam, dist,
                                  flags=cv2.SOLVEPNP_EPNP)
        if not ok:
            return None, None
        _, hr, ht = cv2.solvePnP(_PNP_3D.reshape(6, 1, 3), pts2d, cam, dist,
                                 hr, ht, True)
        hR = cv2.Rodrigues(hr)[0]
        # центр лица: среднее центров глаз и носа (в камерных координатах)
        fm = _PNP_3D.T
        Fc = hR @ fm + ht.reshape(3, 1)
        eye_c = Fc[:, 0:4].mean(axis=1, keepdims=True)
        nose_c = Fc[:, 4:6].mean(axis=1, keepdims=True)
        center = np.concatenate((eye_c, nose_c), axis=1).mean(axis=1,
                                                              keepdims=True)
        distance = float(np.linalg.norm(center))
        cam_norm = np.array([[_FOCAL_NORM, 0, _ROI / 2],
                             [0, _FOCAL_NORM, _ROI / 2],
                             [0, 0, 1.0]])
        S = np.diag([1.0, 1.0, _DIST_NORM / distance])
        hRx = hR[:, 0]
        forward = (center / distance).reshape(3)
        down = np.cross(forward, hRx)
        down /= np.linalg.norm(down) + 1e-12
        right = np.cross(down, forward)
        right /= np.linalg.norm(right) + 1e-12
        R = np.stack([right, down, forward], axis=0)
        W = cam_norm @ S @ R @ np.linalg.inv(cam)
        warp = cv2.warpPerspective(image_bgr, W, (_ROI, _ROI),
                                   flags=cv2.INTER_LINEAR)
        # гейт дикой позы головы в нормализованном пространстве
        hR_norm = R @ hR
        hr_norm = np.array([np.arcsin(np.clip(hR_norm[1, 2], -1, 1)),
                            np.arctan2(hR_norm[0, 2], hR_norm[2, 2])])
        if float(np.linalg.norm(hr_norm)) > np.deg2rad(_HEAD_POSE_GATE_DEG):
            return None, None
        rgb = cv2.cvtColor(warp, cv2.COLOR_BGR2RGB)
        return rgb, R

    def _to_tensor(self, rgb224):
        t = self._torch.from_numpy(
            rgb224.astype(np.float32) / 255.0).permute(2, 0, 1)
        t = (t - self._torch.from_numpy(_IMAGENET_MEAN).view(3, 1, 1)) / \
            self._torch.from_numpy(_IMAGENET_STD).view(3, 1, 1)
        return t.unsqueeze(0).to(self.device)

    # -- публичное ----------------------------------------------------------
    def warmup(self):
        t0 = time.perf_counter()
        print("[unigaze] прогрев CUDA (первый запуск ~30-60с)...", flush=True)
        try:
            try:
                self._torch.backends.cudnn.benchmark = True
            except Exception:
                pass
            dh = int(480 * self._det_width / 640)
            try:
                self.detector(
                    np.zeros((dh, self._det_width, 3), dtype=np.uint8))
            except Exception:
                pass
            import cv2
            img = cv2.imread(str(Path.home() / ".eyeconnect" /
                                 "webcam_check.jpg"))
            if img is None:
                img = (np.random.rand(480, 640, 3) * 255).astype(np.uint8)
            try:
                self.fa.get_landmarks(img)
            except Exception:
                pass
            with self._torch.no_grad():
                fake = self._torch.randn(1, 3, _ROI, _ROI).to(self.device)
                self.model(fake)
            if self.device.type == "cuda":
                self._torch.cuda.synchronize()
        except Exception as e:
            print(f"[unigaze] warmup пропущен: {e}", flush=True)
        print(f"[unigaze] готов за {time.perf_counter() - t0:.1f}с",
              flush=True)

    def _detect(self, frame_bgr):
        import cv2
        self._det_counter += 1
        if self._det_counter % self._det_interval == 0 or not self._cached_faces:
            h, w = frame_bgr.shape[:2]
            scale = self._det_width / w if w > self._det_width else 1.0
            if scale < 1.0:
                small = cv2.resize(frame_bgr,
                                   (self._det_width, int(h * scale)))
                raw = self.detector(small)
                faces = []
                if raw is not None:
                    for box, _lm, score in raw:
                        faces.append(([float(v) / scale for v in box],
                                      float(score)))
            else:
                raw = self.detector(frame_bgr)
                faces = [(list(map(float, box)), float(score))
                         for box, _lm, score in (raw or [])]
            self._cached_faces = faces
        return self._cached_faces

    def predict_gaze(self, frame_bgr):
        faces = self._detect(frame_bgr)
        out = []
        for (box, score) in faces:
            if score < self.conf_thr:
                continue
            x1, y1 = max(0, int(box[0])), max(0, int(box[1]))
            x2, y2 = int(box[2]), int(box[3])
            if x2 <= x1 or y2 <= y1:
                continue
            try:
                lms = self.fa.get_landmarks(
                    frame_bgr, detected_faces=[[x1, y1, x2, y2]])
            except Exception:
                continue
            if not lms:
                continue
            norm = self._normalize_face(frame_bgr, np.asarray(lms[0]))
            rgb224, R = norm
            if rgb224 is None:
                continue
            with self._torch.no_grad():
                ret = self.model(self._to_tensor(rgb224))
                py = np.asarray(
                    ret["pred_gaze"][0].detach().float().cpu()).reshape(2)
            # денормализация в камерную систему
            v = _pitchyaw_to_vector(py).reshape(3, 1)
            v = np.linalg.inv(R) @ v
            pitch, yaw = _vector_to_pitchyaw(v)
            out.append({"pitch": float(pitch), "yaw": float(yaw),
                        "pitch_deg": float(np.degrees(pitch)),
                        "yaw_deg": float(np.degrees(yaw)),
                        "bbox": [x1, y1, x2, y2], "score": float(score)})
        out.sort(key=lambda d: d["score"], reverse=True)
        return out

    def process(self, frame_bgr):
        import numpy as np
        try:
            faces = self.predict_gaze(frame_bgr)
        except Exception:
            return None, 0.0, {}
        if not faces:
            return None, 0.0, {}
        best = faces[0]
        feat = np.array([best["pitch"], best["yaw"]], dtype=np.float64)
        dbg = {"pitch_deg": best["pitch_deg"], "yaw_deg": best["yaw_deg"],
               "bbox": best["bbox"], "n_faces": len(faces)}
        return feat, best["score"], dbg

    def close(self):
        self.detector = None
        try:
            del self.model
        except Exception:
            pass
