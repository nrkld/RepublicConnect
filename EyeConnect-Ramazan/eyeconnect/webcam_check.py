import argparse
import time
from pathlib import Path

import cv2

from eyeconnect import config as C
from eyeconnect.gaze.capture import Camera
from eyeconnect.gaze.facemesh import FaceTracker


def default_out_path() -> Path:
    d = C.PROFILE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d / "webcam_check.jpg"


def main(n_frames: int = 150, out: Path | None = None):
    out = Path(out) if out else default_out_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    cam = Camera()
    tr = FaceTracker()
    print("backend=", tr.backend, flush=True)
    try:
        N = n_frames
        det = 0
        best = None
        bestconf = -1
        bfeat = None
        bdbg = {}
        last = None
        lastdbg = {}
        t0 = time.time()
        for i in range(N):
            f = cam.read()
            if f is None:
                continue
            last = f
            feat, conf, dbg = tr.process(f)
            lastdbg = dbg
            if feat is not None:
                det += 1
                if conf > bestconf:
                    bestconf = conf
                    best = f.copy()
                    bfeat = feat
                    bdbg = dbg
        print(f"frames={N} det={det} elapsed={time.time()-t0:.1f}s fps={cam.fps:.1f}", flush=True)
        out_img = best if best is not None else last
        if out_img is not None:
            dbg = bdbg if best is not None else lastdbg
            h, w = out_img.shape[:2]
            for k in ("l_iris", "r_iris"):
                if k in dbg:
                    x, y = dbg[k]
                    # dbg уже в пикселях текущего кадра — без пересчета через FRAME_W/H
                    cx = int(max(0, min(w - 1, x)))
                    cy = int(max(0, min(h - 1, y)))
                    cv2.circle(out_img, (cx, cy), 6, (0, 0, 255), -1)
            if best is not None:
                msg = f"det {det}/{N} feat={bfeat[0]:.2f},{bfeat[1]:.2f}"
            else:
                msg = f"det 0/{N} NO FACE - sядьте перед камерой в 60см"
            cv2.putText(out_img, msg, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imwrite(str(out), out_img)
            print(f"saved {out}", flush=True)
    finally:
        cam.release()
        tr.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Проверка камеры и трекинга лица")
    ap.add_argument("--frames", type=int, default=150)
    ap.add_argument("--out", type=str, default=None,
                    help="куда сохранить кадр (по умолчанию ~/.eyeconnect/webcam_check.jpg)")
    args = ap.parse_args()
    main(n_frames=args.frames, out=args.out)
