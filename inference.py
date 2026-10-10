"""PLAN.md's test: OLS, the t of one coefficient with CR1 cluster-robust standard errors, and a
wild cluster restricted bootstrap (null imposed, Webb six-point weights, one per cluster).

Everything the bootstrap needs is linear in the restricted residuals, so each draw's t is
closed-form: with a = the coefficient's row of (X'X)^-1 X' and residuals u under the null,
b* - b0 = sum_g w_g s_g with s_g = sum_{i in g} a_i u_i, and the draw's cluster scores are
sum_h w_h C[g, h] with C[g, h] = sum_{i in g} a_i [(I - H)(u * 1{h})]_i.
The same pattern as ../fed-oct/app_method.py, for several regressors and CR1 by cluster.
"""

import numpy as np

WEBB = np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])
SEED = 20261009
DRAWS = 9_999
ALPHA = 0.05


class WildClusterTest:
    def __init__(self, X, k, clusters):
        X = np.asarray(X, float)
        clusters = np.asarray(clusters)
        self.order = np.argsort(clusters, kind="stable")
        X = X[self.order]
        g = clusters[self.order]
        self.starts = np.flatnonzero(np.r_[True, g[1:] != g[:-1]])
        self.n, self.K = X.shape
        self.G = len(self.starts)
        self.k = k
        self.X = X
        M = np.linalg.solve(X.T @ X, X.T)
        self.a = M[k]
        self.I_H = np.eye(self.n) - X @ M
        Xr = np.delete(X, k, axis=1)
        self.I_Hr = np.eye(self.n) - Xr @ np.linalg.solve(Xr.T @ Xr, Xr.T)
        self.z = self.I_Hr @ X[:, k]  # restricted residuals at b0 are u0 - b0 * z
        self.P = np.add.reduceat(self.a[:, None] * self.I_H, self.starts, axis=0)  # G x n
        self.c = self.G / (self.G - 1) * (self.n - 1) / (self.n - self.K)

    def _sorted(self, y):
        return np.asarray(y, float)[self.order]

    def _sums(self, v):
        return np.add.reduceat(self.a * v, self.starts)

    def _C(self, u):
        return np.add.reduceat(self.P * u[None, :], self.starts, axis=1)

    def fit(self, y):
        """Estimate, CR1 standard error and t (against 0) of the coefficient."""
        y = self._sorted(y)
        b = self.a @ y
        se = np.sqrt(self.c * np.sum(self._sums(self.I_H @ y) ** 2))
        return b, se, b / se

    def weights(self, draws, rng):
        return WEBB[rng.integers(0, 6, size=(draws, self.G))]

    def pvalue(self, y, W, b0=0.0):
        """Two-sided bootstrap p for H0: coefficient = b0, with weight matrix W (draws x G)."""
        return self._inverter(y, W)(b0)

    def _inverter(self, y, W):
        y = self._sorted(y)
        b, se, _ = self.fit(y)
        u0 = self.I_Hr @ y
        Ws0, Wsz = W @ self._sums(u0), W @ self._sums(self.z)
        WC0, WCz = W @ self._C(u0).T, W @ self._C(self.z).T
        draws = W.shape[0]

        def p_at(b0):
            observed = abs(b - b0) / se
            num = Ws0 - b0 * Wsz
            den = np.sqrt(self.c * np.sum((WC0 - b0 * WCz) ** 2, axis=1))
            ok = den > 0
            exceed = np.sum(np.abs(num[ok]) / den[ok] >= observed * (1 - 1e-12))
            return (1 + exceed) / (1 + draws)

        return p_at

    def test(self, y, draws=DRAWS, seed=SEED, alpha=ALPHA, interval=True):
        """Estimate, CR1 se and t, bootstrap p for b = 0, and the interval of b0 the test doesn't reject."""
        b, se, t = self.fit(y)
        W = self.weights(draws, np.random.default_rng(seed))
        p_at = self._inverter(y, W)
        out = {"b": b, "se_cr1": se, "t": t, "p": p_at(0.0), "draws": draws, "clusters": self.G, "n": self.n}
        if interval:
            out["ci_low"], out["ci_high"] = (_bound(p_at, b, se, side, alpha) for side in (-1, 1))
        return out


def _bound(p_at, b, se, side, alpha):
    """Edge of the set {b0 : p(b0) > alpha} on one side of b, by doubling then bisection."""
    inside, step = b, 2 * se
    outside = b + side * step
    k = 0
    while p_at(outside) > alpha:
        if k == 30:
            return np.nan
        inside, step = outside, step * 2
        outside = b + side * step
        k += 1
    for _ in range(60):
        if abs(outside - inside) <= 1e-7 * se:
            break
        mid = (inside + outside) / 2
        if p_at(mid) > alpha:
            inside = mid
        else:
            outside = mid
    return (inside + outside) / 2
