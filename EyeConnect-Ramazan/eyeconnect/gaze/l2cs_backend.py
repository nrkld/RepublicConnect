"""L2CS-Net backend для EyeConnect (точный gaze по лицу: pitch/yaw).

Upstream: https://github.com/Ahmednull/L2CS-Net (MIT, L2CS-Net, ICIP 2022).
Код: third_party/L2CS-Net/l2cs/ (+ LICENSE.L2CS-MIT).
Детектор лиц: https://github.com/elliottzheng/face-detection (RetinaFace),
  код: third_party/face-detection/face_detection/.
Веса: ~/.eyeconnect/models/l2cs_gaze360_resnet50.safetensors (Gaze360,
  3.92° MPIIGaze / 10.41° Gaze360; зеркало HuggingFace py-feat/l2cs,
  ключи 1-в-1 с официальным L2CSNet_gaze360.pkl) или env L2CS_WEIGHTS.
Pip-зависимости: torch, torchvision, safetensors, huggingface_hub.

Выход — углы взгляда (pitch, yaw) в радианах на лицо. Для экрана нужна
персональная калибровка 126 точек: фича [pitch, yaw] -> GazeRegressor/RBF
(как MacGaze: базовый вектор + RBF-персонализация поверх).

Пример:
    from eyeconnect.gaze.l2cs_backend import L2CSTracker
    tr = L2CSTracker()  # device auto: cuda если есть, иначе cpu
    feat, conf, dbg = tr.process(frame)  # feat=[pitch, yaw] лучш. лица
    print(dbg['pitch_deg'], dbg['yaw_deg'], conf)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "third_party" / "L2CS-Net" / "l2cs" / "__init__.py").exists():
            return parent
    return here.parents[2]


def _ensure_imports():
    """Подключить vendored l2cs + face_detection, если pip-версий нет."""
    root = _repo_root()
    for sub in ("L2CS-Net", "face-detection"):
        cand = root / "third_party" / sub
        if (cand / ("l2cs" if "L2CS" in sub else "face_detection") / "__init__.py").exists():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
    try:
        from face_detection import RetinaFace  # type: ignore
    except Exception:
        # старый PyPI face-detection 0.2.2 без RetinaFace — сказать прямо
        raise ImportError(
            "Нужен face_detection с RetinaFace (git-master elliottzheng/face-detection). "
            "Без git: скачай ZIP релиза и pip install <папка>. "
            "В проекте уже есть third_party/face-detection/ — он подхватится сам."
        )
    from l2cs.utils import getArch  # type: ignore
    return RetinaFace, getArch


def resolve_weights() -> Path:
    env = os.environ.get("L2CS_WEIGHTS")
    if env and Path(env).expanduser().exists():
        return Path(env).expanduser()
    home = Path.home() / ".eyeconnect" / "models" / "l2cs_gaze360_resnet50.safetensors"
    if home.exists():
        return home
    # официальный .pkl рядом с кодом (положи вручную с Google Drive)
    root = _repo_root()
    for cand in sorted((root / "third_party" / "L2CS-Net" / "models").glob("*.pkl")):
        return cand
    raise FileNotFoundError(
        f"Веса L2CS не найдены. Ожидалось: {home} "
        "(качается: huggingface_hub hf_hub_download('py-feat/l2cs', "
        "'l2cs_gaze360_resnet50.safetensors')). "
        "Либо укажи L2CS_WEIGHTS=/путь/к/L2CSNet_gaze360.pkl"
    )


class L2CSTracker:
    """Точный gaze-трекер: RetinaFace + L2CS-Net ResNet50.

    process(bgr) совместим с FaceTracker по сигнатуре:
      -> (feat [pitch, yaw] рад | None, conf=score лица, dbg dict).
    """

    def __init__(self, device: str = "auto", arch: str = "ResNet50",
                 conf_thr: float = 0.5, weights=None):
        import numpy as np
        import torch
        import torch.nn as nn

        RetinaFace, getArch = _ensure_imports()
        self._np = np
        self._torch = torch

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        w = Path(weights).expanduser() if weights else resolve_weights()
        self.weights_path = w
        self.model = getArch(arch, 90)
        if w.suffix == ".safetensors":
            from safetensors.torch import load_file
            sd = load_file(str(w), device="cpu")
            self.model.load_state_dict(sd)
        else:  # официальный .pkl (torch.save state_dict)
            sd = torch.load(str(w), map_location="cpu")
            self.model.load_state_dict(sd)
        self.model.to(self.device)
        self.model.eval()

        if self.device.type == "cpu":
            self.detector = RetinaFace()
        else:
            self.detector = RetinaFace(gpu_id=self.device.index or 0)
        self.softmax = nn.Softmax(dim=1).to(self.device)
        self.idx_tensor = torch.FloatTensor([i for i in range(90)]).to(self.device)
        self.conf_thr = float(conf_thr)

    def predict_gaze(self, frame_bgr):
        """Все лица кадра -> [{'pitch','yaw' (рад),'bbox','landmarks','score'}]."""
        import cv2
        np, torch = self._np, self._torch
        faces = self.detector(frame_bgr)
        if faces is None:
            return []
        out = []
        for box, landmark, score in faces:
            if float(score) < self.conf_thr:
                continue
            x_min, y_min = max(0, int(box[0])), max(0, int(box[1]))
            x_max, y_max = int(box[2]), int(box[3])
            if x_max <= x_min or y_max <= y_min:
                continue
            img = frame_bgr[y_min:y_max, x_min:x_max]
            if img.size == 0:
                continue
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (224, 224))
            from l2cs.utils import prep_input_numpy  # type: ignore
            with torch.no_grad():
                inp = prep_input_numpy(img, self.device)
                gaze_pitch, gaze_yaw = self.model(inp)
                pp = self.softmax(gaze_pitch)
                yp = self.softmax(gaze_yaw)
                pitch = float(torch.sum(pp.data * self.idx_tensor, dim=1) * 4 - 180)
                yaw = float(torch.sum(yp.data * self.idx_tensor, dim=1) * 4 - 180)
            out.append({
                "pitch": float(np.deg2rad(pitch)),
                "yaw": float(np.deg2rad(yaw)),
                "pitch_deg": pitch,
                "yaw_deg": yaw,
                "bbox": [x_min, y_min, x_max, y_max],
                "landmarks": landmark,
                "score": float(score),
            })
        out.sort(key=lambda d: d["score"], reverse=True)
        return out

    def process(self, frame_bgr):
        """(feat [pitch, yaw] | None, conf, dbg) — как FaceTracker.process()."""
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
