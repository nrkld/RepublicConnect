"""EyeConnect: preview | calibrate | cursor.

Примеры:
  python -m eyeconnect.main --mode preview
  python -m eyeconnect.main --mode calibrate
  python -m eyeconnect.main --mode cursor --click  (dwell-клик взглядом)
"""
import argparse
import time
import cv2
import numpy as np

from . import config as C
from .gaze.capture import Camera
from .gaze.facemesh import FaceTracker
from .gaze.filter import GazeFilter
from .gaze.regressor import GazeRegressor
from .ui.calibration import run_calibration
from .ui.cursor import load_or_calibrate, run_cursor
from .eval.metrics import accuracy_precision


def profile_path(name="gaze.npz"):
    return C.PROFILE_DIR / name


def make_tracker(name="l2cs"):
    """Фабрика трекеров: unigaze (ViT-H, самый точный) | l2cs (точный, pitch/yaw) | facemesh (лёгкий 2D)."""
    if name == "unigaze":
        from .gaze.unigaze_backend import UniGazeTracker
        print("Загрузка UniGaze ViT-H (веса ~2.5ГБ + прогрев CUDA)...", flush=True)
        return UniGazeTracker()
    if name == "l2cs":
        from .gaze.l2cs_backend import L2CSTracker
        print("Загрузка L2CS (веса 96МБ + прогрев CUDA)...", flush=True)
        return L2CSTracker()
    from .gaze.facemesh import FaceTracker
    return FaceTracker()


def calib_params(args):
    """Фиксированная калибровка 126 точек."""
    grid = ("auto", C.CALIB_POINTS)
    dwell = float(args.calib_dwell) if args.calib_dwell else None
    avg_s = 1.0 if args.tracker in ("l2cs", "unigaze") else None
    return grid, dwell, avg_s, C.CALIB_POINTS


def cmd_preview(args):
    cam = Camera(args.camera)
    tr = make_tracker(args.tracker)
    flt = GazeFilter()
    print("Q — выход")
    while True:
        f = cam.read()
        if f is None:
            continue
        feat, conf, dbg = tr.process(f)
        if feat is not None:
            sm = flt.update(feat)
            if "pitch_deg" in dbg:  # L2CS: углы вместо nx,ny
                txt = (f"pitch {dbg['pitch_deg']:.1f} yaw {dbg['yaw_deg']:.1f} "
                       f"conf {conf:.2f} fps {cam.fps:.1f}")
            else:
                txt = f"feat {feat[0]:.2f},{feat[1]:.2f} conf {conf:.2f} fps {cam.fps:.1f}"
            if "ear_l" in dbg:  # открытость глаз для подмигиваний
                txt += f" ear {dbg['ear_l']:.2f}/{dbg['ear_r']:.2f}"
        else:
            txt = f"no face fps {cam.fps:.1f}"
        cv2.putText(f, txt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        for k in ("l_iris", "r_iris"):
            if k in dbg:
                x, y = dbg[k]
                h0, w0 = f.shape[:2]
                sx = int(max(0, min(w0 - 1, x)))
                sy = int(max(0, min(h0 - 1, y)))
                cv2.circle(f, (sx, sy), 5, (0, 0, 255), -1)
        if "bbox" in dbg:  # L2CS: рамка лица
            x1, y1, x2, y2 = dbg["bbox"]
            cv2.rectangle(f, (x1, y1), (x2, y2), (255, 0, 0), 2)
        cv2.imshow("preview", f)
        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
            break
    tr.close()
    cam.release()
    cv2.destroyAllWindows()


def cmd_calibrate(args):
    cam = Camera(args.camera)
    tr = make_tracker(args.tracker)
    flt = GazeFilter()
    grid, dwell, avg_s, n_pts = calib_params(args)
    feats, screens = run_calibration(cam, tr, flt, avg_s=avg_s, grid=grid,
                                     dwell_s=dwell, wait=not args.no_wait)
    tr.close()
    cam.release()
    need = max(4, n_pts // 4)
    if len(feats) < need:
        print(f"Мало точек ({len(feats)}/{n_pts}, нужно {need}) — калибровка не сохранена")
        return
    from .gaze.regressor import select_mapper
    reg, sel = select_mapper(feats, screens)
    print(f"Маппер: poly LOO {sel['poly_loo_px']:.1f}px vs rbf LOO {sel['rbf_loo_px']:.1f}px "
          f"-> выбран {sel['chosen']}")
    if sel.get("dropped") is not None:
        print(f"RANSAC: точка {sel['dropped']+1} выброшена как выброс (моргание), refit без неё")
    preds = [reg.predict(f) for f in feats]
    m = accuracy_precision(screens, preds)
    loo = reg.loo_error(feats, screens)
    from .eval.metrics import px_to_deg
    loo_deg = px_to_deg(loo['loo_px']) if loo['n'] else float('nan')
    perr = reg.per_point_errors(feats, screens)
    worst = int(perr.argmax()) if len(perr) else -1
    print(f"train-fit: acc {m['acc_px']:.1f}px / {m['acc_deg']:.2f}° (оптимистично)")
    print(f"LOO-честная: {loo['loo_px']:.1f}px / {loo_deg:.2f}° n={loo['n']} (цель ≤{C.VALID_MAX_DEG:.1f}°)")
    if worst >= 0:
        print(f"Худшая точка: №{worst+1} err {perr[worst]:.1f}px — при повторе смотри ровнее на края")
    if loo_deg <= C.VALID_MAX_DEG:
        print("ВЕРДИКТ: OK — можно работать")
    elif loo_deg <= 3.0:
        print("ВЕРДИКТ: СРЕДНЕ — сядь 60см, ровный свет, перекалибруй края")
    else:
        print("ВЕРДИКТ: ПЛОХО — перекалибруй: свет в лицо, камера на уровне глаз, не двигай головой")
    if not (loo_deg == loo_deg and loo_deg <= 3.0):
        print("Профиль НЕ сохранён (вердикт ПЛОХО) — исправь условия и перекалибруй")
        return
    if getattr(reg, "kind", "poly") == "poly":
        print(f"alpha RidgeCV: {reg.alpha}")
    else:
        print(f"sigma RBF: {reg.sigma:.4f}")
    reg.save(profile_path())
    try:
        from .ui.cursor import save_profile
        save_profile(reg, 1280, 720, args.tracker)
    except Exception:
        pass
    print(f"Сохранено: {profile_path()} (+ gaze_samples_*.npz для анализа)")


def cmd_cursor(args):
    cam = Camera(args.camera)
    tr = make_tracker(args.tracker)
    if not args.no_wink:
        from .gaze.wink import WinkTracker
        tr = WinkTracker(inner=tr)  # левое подмигивание=ЛКМ, правое=ПКМ
    flt = GazeFilter()
    try:
        grid, dwell, avg_s, n_pts = calib_params(args)
        reg, W, H = load_or_calibrate(cam, tr, flt, force=args.recalib,
                                       tracker_name=args.tracker, avg_s=avg_s,
                                       grid=grid, dwell_s=dwell,
                                       wait=not args.no_wait)
        run_cursor(cam, tr, flt, reg, W, H, syscursor=not args.no_syscursor,
                   click=args.click, click_dwell_ms=args.click_dwell,
                   overlay=not args.no_overlay, wink=not args.no_wink)
    finally:
        tr.close()
        cam.release()
        cv2.destroyAllWindows()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["preview", "calibrate", "cursor"], default="preview")
    ap.add_argument("--camera", type=int, default=C.CAM_INDEX)
    ap.add_argument("--recalib", action="store_true", help="перекалибровать заново")
    ap.add_argument("--no-syscursor", action="store_true", help="не двигать системный курсор")
    ap.add_argument("--click", action="store_true", help="dwell-клик в cursor-режиме (фиксация 1.2с)")
    ap.add_argument("--click-dwell", type=int, default=1200, help="dwell для клика, мс")
    ap.add_argument("--tracker", choices=["unigaze", "l2cs", "facemesh"], default="unigaze",
                    help="трекер взгляда: unigaze (ViT-H, самый точный) | l2cs (точный, torch) | facemesh (лёгкий)")
    ap.add_argument("--no-overlay", action="store_true",
                    help="cursor-режим: без чёрного fullscreen, просто мышь + маленькое окно статуса")
    ap.add_argument("--calib-dwell", type=float, default=None,
                    help="фиксация на точку, сек (дефолт 1.5)")
    ap.add_argument("--no-wait", action="store_true",
                    help="пропустить стартовый экран калибровки (сразу точки)")
    ap.add_argument("--no-wink", action="store_true",
                    help="выключить клики подмигиванием (левое=ЛКМ, правое=ПКМ)")
    args = ap.parse_args()
    {"preview": cmd_preview, "calibrate": cmd_calibrate,
     "cursor": cmd_cursor}[args.mode](args)


if __name__ == "__main__":
    main()
