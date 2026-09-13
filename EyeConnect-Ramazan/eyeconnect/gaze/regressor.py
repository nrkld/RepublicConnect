"""Полиномиальная Ridge-регрессия 2-й степени, 126 точек, веса углов 1.5x.

Рисерч: Ridge -20% MSE vs обычный poly (моб. трекер); плотная сетка точнее на краях;
homography хуже всех;
RANSAC нужен при морганиях; WebGazer: ridge + weightedRidge (новые клики весом выше).
Здесь: RidgeCV по ALPHAS + 1 итерация RANSAC (сброс худшей точки) + LOO-валидация.
"""
import numpy as np
from pathlib import Path
from sklearn.preprocessing import PolynomialFeatures
try:
    from sklearn.linear_model import RidgeCV, Ridge
except Exception:  # старый sklearn
    from sklearn.linear_model import Ridge
    RidgeCV = None
from .. import config as C


def _make_model(alpha):
    if alpha == "auto" and RidgeCV is not None:
        return RidgeCV(alphas=list(C.RIDGE_ALPHAS))
    return Ridge(alpha=float(alpha) if alpha != "auto" else 1.0)


class GazeRegressor:
    kind = "poly"

    def __init__(self, alpha="auto"):
        self.alpha_opt = alpha
        self.alpha = 1.0 if alpha == "auto" else float(alpha)
        self.poly = PolynomialFeatures(degree=2, include_bias=False)
        self.mx = _make_model(alpha)
        self.my = _make_model(alpha)
        self.trained = False
        self.calib_eye_w = 0.0  # средняя ширина глаза на калибровке (детектор сдвига головы)

    def fit(self, feats_xy, screens_xy, edge_weight: float = C.EDGE_WEIGHT,
            sample_weight=None, calib_eye_w: float = 0.0):
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        if X.ndim != 2 or X.shape[1] != 2:
            raise ValueError(f"feats_xy должны быть (N,2), получено {X.shape}")
        if Y.ndim != 2 or Y.shape[1] != 2:
            raise ValueError(f"screens_xy должны быть (N,2), получено {Y.shape}")
        if X.shape[0] != Y.shape[0]:
            raise ValueError(f"N feats ({X.shape[0]}) != N screens ({Y.shape[0]})")
        if X.shape[0] < 4:
            raise ValueError(f"Нужно минимум 4 точки калибровки, получено {X.shape[0]}")
        # вес 1.5x точкам у краёв экрана (периферия сложнее)
        mx, my = X[:, 0].mean(), X[:, 1].mean()
        dist = np.abs(X[:, 0] - mx) + np.abs(X[:, 1] - my)
        thr = np.quantile(dist, 0.6)
        w = np.where(dist >= thr, edge_weight, 1.0).astype(float)
        if sample_weight is not None:
            w = w * np.asarray(sample_weight, dtype=float)
        Xp = self.poly.fit_transform(X)
        self.mx = _make_model(self.alpha_opt)
        self.my = _make_model(self.alpha_opt)
        self.mx.fit(Xp, Y[:, 0], sample_weight=w)
        self.my.fit(Xp, Y[:, 1], sample_weight=w)
        # запомнить выбранный alpha (RidgeCV) для save/load
        try:
            self.alpha = float(self.mx.alpha_)
        except Exception:
            pass
        self.calib_eye_w = float(calib_eye_w or 0.0)
        self.trained = True
        return self

    def fit_robust(self, feats_xy, screens_xy, **kw):
        """Fit + 1 итерация RANSAC: сбросить худшую точку если residual > 2.5*median. Возвращает (self, info)."""
        self.fit(feats_xy, screens_xy, **kw)
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        preds = np.array([self.predict(f) for f in X])
        res = np.linalg.norm(preds - Y, axis=1)
        med = float(np.median(res)) + 1e-9
        worst = int(np.argmax(res))
        info = {"residuals": res, "dropped": None, "median_res": med}
        if C.CALIB_RANSAC and len(X) >= 5 and res[worst] > 2.5 * med:
            mask = np.ones(len(X), dtype=bool)
            mask[worst] = False
            info["dropped"] = worst
            self.fit(X[mask], Y[mask], **kw)
            preds2 = np.array([self.predict(f) for f in X])
            info["residuals_refit"] = np.linalg.norm(preds2 - Y, axis=1)
        return self, info

    def per_point_errors(self, feats_xy, screens_xy):
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        preds = np.array([self.predict(f) for f in X])
        return np.linalg.norm(preds - Y, axis=1)

    def loo_error(self, feats_xy, screens_xy, **kw):
        """Leave-one-out: честная оценка без повторного прогона. N=9 — быстро."""
        from copy import deepcopy
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        errs = []
        for i in range(len(X)):
            mask = np.ones(len(X), dtype=bool)
            mask[i] = False
            try:
                m = GazeRegressor(alpha=self.alpha_opt)
                m.fit(X[mask], Y[mask], **kw)
                p = np.array(m.predict(X[i]))
                errs.append(float(np.linalg.norm(p - Y[i])))
            except Exception:
                continue
        errs = np.array(errs, dtype=float)
        if errs.size == 0:
            return {"loo_px": float("nan"), "loo_std": float("nan"), "n": 0}
        return {"loo_px": float(errs.mean()), "loo_std": float(errs.std()), "n": int(errs.size)}

    def predict(self, feat_xy):
        if not self.trained:
            raise RuntimeError("Регрессор не обучен: сначала fit() или load()")
        Xp = self.poly.transform(np.asarray(feat_xy, dtype=float).reshape(1, -1))
        return float(self.mx.predict(Xp)[0]), float(self.my.predict(Xp)[0])

    def save(self, path: Path):
        if not self.trained:
            raise RuntimeError("Нечего сохранять: регрессор не обучен")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, kind=np.array("poly"), coef_x=self.mx.coef_, b_x=self.mx.intercept_,
                 coef_y=self.my.coef_, b_y=self.my.intercept_,
                 powers=self.poly.powers_, alpha=np.array(self.alpha),
                 calib_eye_w=np.array(self.calib_eye_w))

    def load(self, path: Path):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Профиль не найден: {path}. Запустите --mode calibrate")
        try:
            d = np.load(path, allow_pickle=False)
        except Exception as e:
            raise RuntimeError(f"Профиль битый ({path}): {e}. Перекалибруйте") from e
        try:
            for k in ("coef_x", "b_x", "coef_y", "b_y", "powers"):
                if k not in d:
                    raise KeyError(f"нет ключа {k}")
            # восстанавливаем полином: в sklearn>=1.8 powers_ это read-only
            # property, вычисляемое из degree/include_bias, поэтому просто
            # fit на dummy с теми же параметрами (degree=2, include_bias=False).
            self.poly = PolynomialFeatures(degree=2, include_bias=False)
            self.poly.fit(np.zeros((1, 2)))
            if "powers" in d:
                try:
                    saved = np.asarray(d["powers"])
                    cur = np.asarray(self.poly.powers_)
                    if saved.shape != cur.shape or not np.array_equal(saved, cur):
                        raise KeyError("powers mismatch: профиль от другой версии полинома")
                except KeyError:
                    raise
                except Exception:
                    pass  # старый/битый powers — игнорим, fit уже задал корректный
            try:
                self.poly.n_output_features_ = int(d["coef_x"].shape[0])
            except Exception:
                pass
            if "alpha" in d:
                self.alpha = float(d["alpha"])
            # после load всегда обычный Ridge (веса уже запечены)
            self.mx = Ridge(alpha=self.alpha)
            self.my = Ridge(alpha=self.alpha)
            self.mx.coef_ = d["coef_x"]
            self.mx.intercept_ = d["b_x"]
            self.my.coef_ = d["coef_y"]
            self.my.intercept_ = d["b_y"]
            for m in (self.mx, self.my):
                m.n_features_in_ = self.poly.n_output_features_
            self.calib_eye_w = float(d["calib_eye_w"]) if "calib_eye_w" in d else 0.0
        except Exception as e:
            raise RuntimeError(f"Профиль битый ({path}): {e}. Перекалибруйте") from e
        self.trained = True
        return self


class RBFMapper:
    """Точная гауссова RBF-интерполяция фичи -> экран (персонализация в духе MacGaze).

    Решаем Φ·W = Y (Φ_ij = exp(-||c_i-c_j||²/2σ²) + nugget), predict(x) = k(x)·W.
    В отличие от взвешенного среднего — точна на калибровочных точках и гладка
    между ними; нелинейности по краям держит лучше полинома 2-й степени.
    σ подбирается автоматически по LOO из кандидатов (доли медианы до соседа).
    Формат save/load — тот же gaze.npz (centers/targets/sigma).
    """
    kind = "rbf"
    SIGMA_GRID = (0.5, 1.0, 2.0, 4.0)
    NUGGET = 1e-6
    SIGMA_FLOOR = 1e-3
    KERNEL_FLOOR = 1e-6

    def __init__(self, sigma="auto"):
        self.sigma_opt = sigma
        self.sigma = 0.1
        self.centers = None
        self.targets = None
        self.weights = None
        self.trained = False

    @staticmethod
    def _kernel(A, B, sigma):
        d2 = np.sum((A[:, None, :] - B[None, :, :]) ** 2, axis=-1)
        return np.exp(-d2 / (2 * sigma ** 2))

    @classmethod
    def _solve(cls, X, Y, sigma):
        Phi = cls._kernel(X, X, sigma) + np.eye(len(X)) * cls.NUGGET
        try:
            return np.linalg.solve(Phi, Y)
        except np.linalg.LinAlgError:
            return np.linalg.lstsq(Phi, Y, rcond=None)[0]

    @staticmethod
    def _base_sigma(X):
        # медиана дистанции до ближайшего соседа (масштаб сетки)
        d = np.linalg.norm(X[:, None, :] - X[None, :, :], axis=-1)
        np.fill_diagonal(d, np.inf)
        med = float(np.median(np.min(d, axis=1)))
        if not np.isfinite(med):
            return RBFMapper.SIGMA_FLOOR
        return max(med, RBFMapper.SIGMA_FLOOR)

    def fit(self, feats_xy, screens_xy):
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        if X.ndim != 2 or Y.ndim != 2 or X.shape[0] != Y.shape[0]:
            raise ValueError(f"feats {X.shape} / screens {Y.shape} — нужны (N,D),(N,2)")
        if X.shape[0] < 3:
            raise ValueError(f"Нужно минимум 3 точки, получено {X.shape[0]}")
        self.centers = X.copy()
        self.targets = Y.copy()
        if self.sigma_opt == "auto":
            base = self._base_sigma(X)
            best, best_err = None, float("inf")
            for f in self.SIGMA_GRID:
                err = self._loo_with_sigma(X, Y, base * f)["loo_px"]
                if err == err and err < best_err:  # err==err отсекает nan
                    best, best_err = base * f, err
            self.sigma = best if best else base * 2.0
            self.sigma = max(float(self.sigma), self.SIGMA_FLOOR)
        else:
            self.sigma = max(float(self.sigma_opt), self.SIGMA_FLOOR)
        self.weights = self._solve(X, Y, self.sigma)
        self.trained = True
        return self

    @classmethod
    def _loo_with_sigma(cls, X, Y, sigma):
        errs = []
        for i in range(len(X)):
            mask = np.ones(len(X), dtype=bool)
            mask[i] = False
            try:
                W = cls._solve(X[mask], Y[mask], sigma)
                k = cls._kernel(X[i:i + 1], X[mask], sigma)
                p = k @ W
                errs.append(float(np.linalg.norm(p[0] - Y[i])))
            except Exception:
                continue
        errs = np.array(errs, dtype=float)
        if errs.size == 0:
            return {"loo_px": float("nan"), "loo_std": float("nan"), "n": 0}
        return {"loo_px": float(errs.mean()), "loo_std": float(errs.std()), "n": int(errs.size)}

    def predict(self, feat_xy):
        if not self.trained:
            raise RuntimeError("RBFMapper не обучен: сначала fit() или load()")
        q = np.asarray(feat_xy, dtype=float).reshape(1, -1)
        if not bool(np.all(np.isfinite(q))):
            m = np.mean(self.targets, axis=0)
            return float(m[0]), float(m[1])
        k = self._kernel(q, self.centers, self.sigma)
        if float(np.max(k)) < self.KERNEL_FLOOR:
            j = int(np.argmin(np.sum((self.centers - q) ** 2, axis=1)))
            t = self.targets[j]
            return float(t[0]), float(t[1])
        p = (k @ self.weights)[0]
        return float(p[0]), float(p[1])

    def per_point_errors(self, feats_xy, screens_xy):
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        return np.linalg.norm(np.array([self.predict(f) for f in X]) - Y, axis=1)

    def loo_error(self, feats_xy, screens_xy):
        # честный LOO при уже выбранной σ (без повторного тюнинга внутри)
        X = np.asarray(feats_xy, dtype=float)
        Y = np.asarray(screens_xy, dtype=float)
        if not self.trained:
            self.fit(X, Y)
        return self._loo_with_sigma(X, Y, self.sigma)

    def save(self, path: Path):
        if not self.trained:
            raise RuntimeError("Нечего сохранять: RBFMapper не обучен")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, kind=np.array("rbf"), centers=self.centers,
                 targets=self.targets, sigma=np.array(self.sigma))

    def load(self, path: Path):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Профиль не найден: {path}. Запустите --mode calibrate")
        try:
            d = np.load(path, allow_pickle=True)
            self.centers = np.asarray(d["centers"], dtype=float)
            self.targets = np.asarray(d["targets"], dtype=float)
            self.sigma = max(float(d["sigma"]), self.SIGMA_FLOOR)
            self.weights = self._solve(self.centers, self.targets, self.sigma)
        except Exception as e:
            raise RuntimeError(f"Профиль битый ({path}): {e}. Перекалибруйте") from e
        self.trained = True
        return self


def load_mapper(path: Path):
    """Диспетчер загрузки профиля: poly (GazeRegressor) или rbf (RBFMapper)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Профиль не найден: {path}. Запустите --mode calibrate")
    try:
        d = np.load(path, allow_pickle=True)
        kind = str(d["kind"]) if "kind" in d else "poly"
    except Exception:
        kind = "poly"
    m = RBFMapper() if kind == "rbf" else GazeRegressor()
    return m.load(path)


def select_mapper(feats_xy, screens_xy):
    """Обучить poly-robust и RBF, сравнить честным LOO, вернуть (mapper, info).

    info: {chosen, poly_loo_px, rbf_loo_px, dropped (RANSAC poly)}.
    """
    X = np.asarray(feats_xy, dtype=float)
    Y = np.asarray(screens_xy, dtype=float)
    poly, pinfo = GazeRegressor(alpha="auto").fit_robust(X, Y)
    poly_loo = poly.loo_error(X, Y)
    rbf = RBFMapper().fit(X, Y)
    rbf_loo = rbf.loo_error(X, Y)
    pl, rl = float(poly_loo["loo_px"]), float(rbf_loo["loo_px"])
    # RBF выигрывает только с запасом 10% (иначе стабильный poly)
    chosen = "rbf" if (rl == rl and (pl != pl or rl < 0.9 * pl)) else "poly"
    info = {"chosen": chosen, "poly_loo_px": pl, "rbf_loo_px": rl,
            "dropped": pinfo.get("dropped")}
    return (rbf if chosen == "rbf" else poly), info


if __name__ == "__main__":
    # синтетика без камеры: линейный кейс -> poly, нелинейный -> rbf
    rng = np.random.default_rng(0)
    feats = rng.random((25, 2))
    lin = feats * np.array([1920, 1080])
    m, info = select_mapper(feats, lin)
    print("linear:", info["chosen"], info)
    edge = lin + 150 * np.sin(feats * np.pi) ** 2  # края тянет
    m2, info2 = select_mapper(feats, edge)
    print("nonlinear:", info2["chosen"], info2)
