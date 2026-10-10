"""A priori power (PLAN.md, Power): the smallest effect the primary test detects 80% of the time.

Uses the real design, meaning the primary sample's ΔE series and sessions from the Kalshi side,
and no stock data. Simulated TLT returns are y = θ·ΔE + u, where u is Student-t(4) noise with a
lognormal volatility multiplier per session (sd of log 0.3), doubled in intervals with
|ΔE| ≥ 0.25 bp, and scaled to overall sd 1. θ is therefore in units of σ per bp. The stand-in
for SPY is simulated once, independently of ΔE. Each dataset is tested as in the primary test,
with 399 bootstrap draws. Power is the share of datasets with p < 0.05 and b̂ < 0.
"""

from pathlib import Path

import numpy as np
import pandas as pd

from inference import ALPHA, SEED, WildClusterTest

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
POWER_SEED = SEED + 1
DATASETS = 2_000
DRAWS = 399
TARGET = 0.80
SESSION_LOG_SD = 0.3
NEWS_BP, NEWS_SCALE = 0.25, 2.0
SIGMAS = (0.20, 0.30, 0.40)  # TLT residual sd, % per hour


def design():
    iv = pd.read_csv(HERE / "data" / "kalshi" / "intervals.csv")
    iv = iv[iv["primary"] & iv["dE"].notna()].reset_index(drop=True)
    sessions = pd.factorize(iv["session"])[0]
    return iv["dE"].to_numpy(), sessions


def noise(rng, sessions, h, scale):
    m = np.exp(SESSION_LOG_SD * rng.normal(size=sessions.max() + 1))[sessions]
    return rng.standard_t(4, len(sessions)) / np.sqrt(2) * m * h * scale


def power_at(theta, test, dE, sessions, h, scale, rng, datasets=DATASETS):
    detect = reject = 0
    for _ in range(datasets):
        y = theta * dE + noise(rng, sessions, h, scale)
        b, _, _ = test.fit(y)
        p = test.pvalue(y, test.weights(DRAWS, rng))
        reject += p < ALPHA
        detect += (p < ALPHA) and (b < 0)
    return detect / datasets, reject / datasets


def main():
    rng = np.random.default_rng(POWER_SEED)
    dE, sessions = design()
    n, G = len(dE), sessions.max() + 1
    h = np.where(np.abs(dE) >= NEWS_BP, NEWS_SCALE, 1.0)
    # E[m^2] = exp(2 * 0.3^2) for the lognormal multiplier; t(4)/sqrt(2) has unit variance.
    scale = 1 / np.sqrt(np.exp(2 * SESSION_LOG_SD**2) * np.mean(h**2))
    x = noise(rng, sessions, np.ones(n), 1.0)  # SPY stand-in, independent of ΔE
    X = np.column_stack([np.ones(n), x, dE])
    test = WildClusterTest(X, 2, sessions)

    # Grid around a rough sandwich guess of the 80% effect, extended until it brackets 80%.
    dc = dE - dE.mean()
    se_guess = np.sqrt(np.sum(dc**2 * (h * scale) ** 2 * np.exp(2 * SESSION_LOG_SD**2))) / np.sum(dc**2)
    guess = 2.8 * se_guess
    rows = []

    def run(theta):
        pw, rej = power_at(-theta, test, dE, sessions, h, scale, rng)
        rows.append({"theta_sigma_per_bp": theta, "power": pw, "mc_se": np.sqrt(pw * (1 - pw) / DATASETS),
                     "two_sided_rejection": rej, "datasets": DATASETS, "draws": DRAWS})
        print(f"θ = {theta:.4f} σ/bp: power {pw:.3f} (two-sided rejection {rej:.3f})", flush=True)
        return pw

    run(0.0)
    multipliers = [0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0]
    for mult in multipliers:
        run(mult * guess)
    while max(r["power"] for r in rows) < TARGET:
        multipliers.append(multipliers[-1] * 1.4)
        run(multipliers[-1] * guess)
    while min(r["power"] for r in rows if r["theta_sigma_per_bp"] > 0) > TARGET:
        multipliers.insert(0, multipliers[0] / 1.4)
        run(multipliers[0] * guess)

    grid = pd.DataFrame(rows).sort_values("theta_sigma_per_bp").reset_index(drop=True)
    pos = grid[grid["theta_sigma_per_bp"] > 0]
    above = pos[pos["power"] >= TARGET].iloc[0]
    below = pos[pos["theta_sigma_per_bp"] < above["theta_sigma_per_bp"]].iloc[-1]
    mde = below["theta_sigma_per_bp"] + (TARGET - below["power"]) * (
        above["theta_sigma_per_bp"] - below["theta_sigma_per_bp"]) / (above["power"] - below["power"])
    confirm, _ = power_at(-mde, test, dE, sessions, h, scale, rng)
    print(f"MDE θ = {mde:.4f} σ/bp; confirmed power {confirm:.3f} ± {np.sqrt(confirm * (1 - confirm) / DATASETS):.3f}")

    # Partial correlation at the MDE: ΔE net of the intercept and the SPY stand-in, against unit noise.
    perp = dE - X[:, :2] @ np.linalg.lstsq(X[:, :2], dE, rcond=None)[0]
    r_mde = mde * perp.std() / np.sqrt(mde**2 * perp.var() + 1)
    size = grid.loc[grid["theta_sigma_per_bp"] == 0].iloc[0]
    summary = {
        "n_intervals": n, "n_sessions": G, "n_nonzero_dE": int((np.abs(dE) > 1e-12).sum()),
        "sd_dE_bp": dE.std(), "news_intervals": int((h > 1).sum()),
        "size_two_sided": size["two_sided_rejection"], "size_negative": size["power"],
        "mde_theta_sigma_per_bp": mde, "mde_confirmed_power": confirm,
        "mde_confirmed_mc_se": np.sqrt(confirm * (1 - confirm) / DATASETS),
        "mde_partial_r": r_mde,
        **{f"mde_b_pct_per_bp_sigma_{s:.2f}": mde * s for s in SIGMAS},
        **{f"mde_tlt_pct_per_25bp_sigma_{s:.2f}": 25 * mde * s for s in SIGMAS},
        "seed": POWER_SEED, "datasets_per_theta": DATASETS, "draws": DRAWS,
    }
    RESULTS.mkdir(exist_ok=True)
    grid.round(5).to_csv(RESULTS / "power.csv", index=False)
    pd.Series(summary).to_csv(RESULTS / "power_summary.csv", header=["value"])
    print(pd.Series(summary).to_string())


if __name__ == "__main__":
    main()
