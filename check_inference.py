"""Checks of inference.py on synthetic data (PLAN.md, Verification). Exits non-zero on failure.

1. CR1 standard errors match statsmodels' cov_type="cluster".
2. Each closed-form bootstrap t equals a brute-force refit on the rebuilt returns.
3. A planted effect is recovered, and rejected.
4. With no effect, the test rejects about 5% of the time.
"""

import numpy as np
import statsmodels.api as sm

from inference import WildClusterTest


def synthetic(rng, G=120, per=6, effect=0.0):
    clusters = np.repeat(np.arange(G), per)
    n = len(clusters)
    x = rng.standard_t(4, n)
    dE = np.where(rng.random(n) < 0.3, rng.normal(0, 1, n), 0.0)
    u = rng.standard_t(4, n) * np.exp(0.3 * rng.normal(size=G))[clusters] * np.where(dE != 0, 2, 1)
    X = np.column_stack([np.ones(n), x, dE])
    y = 0.1 + 0.3 * x + effect * dE + u
    return X, y, clusters


def brute_t(X, y, clusters, k, b0):
    fit = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": clusters})
    return (fit.params[k] - b0) / fit.bse[k]


def main():
    rng = np.random.default_rng(1)

    # 1. CR1 matches statsmodels.
    X, y, clusters = synthetic(rng, effect=0.2)
    test = WildClusterTest(X, 2, clusters)
    b, se, t = test.fit(y)
    ref = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": clusters})
    assert np.isclose(b, ref.params[2]) and np.isclose(se, ref.bse[2]), (b, se, ref.params[2], ref.bse[2])
    print(f"1. CR1 matches statsmodels: b {b:.6f} se {se:.6f}")

    # 2. Closed-form bootstrap t equals refitting, at b0 = 0 and at another null value.
    order = test.order
    Xs, ys, cs = X[order], y[order], clusters[order]
    W = test.weights(5, np.random.default_rng(2))
    for b0 in (0.0, 0.15):
        Xr = np.delete(Xs, 2, axis=1)
        restricted = sm.OLS(ys - b0 * Xs[:, 2], Xr).fit()
        _, cluster_index = np.unique(cs, return_inverse=True)
        Ws0 = W @ test._sums(test.I_Hr @ ys - b0 * test.z)
        WC = W @ test._C(test.I_Hr @ ys - b0 * test.z).T
        closed = Ws0 / np.sqrt(test.c * np.sum(WC ** 2, axis=1))
        for d in range(W.shape[0]):
            ystar = restricted.fittedvalues + b0 * Xs[:, 2] + restricted.resid * W[d, cluster_index]
            assert np.isclose(closed[d], brute_t(Xs, ystar, cs, 2, b0)), (b0, d)
    print("2. closed-form bootstrap t equals brute-force refits (10 draws, two null values)")

    # 3. A planted effect is recovered and rejected.
    X, y, clusters = synthetic(np.random.default_rng(3), G=300, effect=0.5)
    res = WildClusterTest(X, 2, clusters).test(y, draws=999)
    assert res["p"] < 0.01 and res["ci_low"] < 0.5 < res["ci_high"], res
    print(f"3. planted 0.5: b {res['b']:.3f}, 95% interval [{res['ci_low']:.3f}, {res['ci_high']:.3f}], p {res['p']:.4f}")

    # 4. Size under no effect.
    rng = np.random.default_rng(4)
    X, _, clusters = synthetic(rng)
    test = WildClusterTest(X, 2, clusters)
    rejections, sims = 0, 1000
    for _ in range(sims):
        y = 0.1 + 0.3 * X[:, 1] + rng.standard_t(4, len(X)) * np.where(X[:, 2] != 0, 2, 1)
        rejections += test.pvalue(y, test.weights(199, rng)) < 0.05
    rate = rejections / sims
    assert 0.03 <= rate <= 0.07, rate
    print(f"4. rejection rate with no effect: {rate:.3f} ({sims} datasets, 199 draws each)")


if __name__ == "__main__":
    main()
