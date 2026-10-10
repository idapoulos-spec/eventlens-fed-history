"""PLAN.md's primary test, then the exploratory checks. Writes aggregates only to results/ and
figures/: never a price or return series.

Primary (confirmatory): pooled OLS over the 26 primary meetings,
    r_TLT,t = a + β·r_SPY,t + b·ΔE_t + e_t,
returns in % over hourly intervals within a session, ΔE in bp. The test is a wild cluster restricted
bootstrap by session (inference.py: Webb weights, 9,999 draws, seed 20261009), two-sided at 5%.
The prediction is b < 0.

    python analysis.py primary   # the confirmatory test only
    python analysis.py           # then the exploratory checks
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import meetings as M
from inference import ALPHA, DRAWS, SEED, WildClusterTest

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"
FIGURES = HERE / "figures"
SYMBOLS = ("TLT", "SPY")
NONZERO = 1e-12


def bars_30min(symbol, meeting):
    body = json.loads((DATA / "twelvedata" / f"{symbol}_30min_{meeting}.json").read_text())
    df = pd.DataFrame(body["values"])
    # Bars are stamped at their open, New York time; a bar opening at H-30min closes at mark H.
    opens = pd.to_datetime(df["datetime"]).dt.tz_localize(M.NY)
    return pd.Series(df["close"].astype(float).values, index=opens + pd.Timedelta(minutes=30)).sort_index()


def daily_closes(symbol):
    body = json.loads((DATA / "twelvedata" / f"{symbol}_1day_all.json").read_text())
    df = pd.DataFrame(body["values"])
    return pd.Series(df["close"].astype(float).values, index=pd.to_datetime(df["datetime"]).dt.date).sort_index()


def hourly_sample():
    """The Kalshi interval grid with each symbol's % return over the same interval."""
    iv = pd.read_csv(DATA / "kalshi" / "intervals.csv")
    for col in ("start", "end"):
        iv[col] = pd.to_datetime(iv[col], utc=True).dt.tz_convert(M.NY)
    iv["session"] = pd.to_datetime(iv["session"]).dt.date
    iv["decision"] = pd.to_datetime(iv["decision"]).dt.date
    for symbol in SYMBOLS:
        r = pd.Series(np.nan, index=iv.index)
        for meeting, idx in iv.groupby("meeting").groups.items():
            closes = bars_30min(symbol, meeting)
            p0 = closes.reindex(iv.loc[idx, "start"]).values
            p1 = closes.reindex(iv.loc[idx, "end"]).values
            r.loc[idx] = 100 * (p1 / p0 - 1)
        iv[f"r_{symbol}"] = r
    iv["year"] = iv["decision"].map(lambda d: d.year)
    return iv


def daily_sample():
    dv = pd.read_csv(DATA / "kalshi" / "daily.csv")
    for col in ("session", "prev_session", "decision"):
        dv[col] = pd.to_datetime(dv[col]).dt.date
    for symbol in SYMBOLS:
        closes = daily_closes(symbol)
        dv[f"r_{symbol}"] = 100 * (closes.reindex(dv["session"]).values / closes.reindex(dv["prev_session"]).values - 1)
    dv["year"] = dv["decision"].map(lambda d: d.year)
    return dv


def usable(df, de="dE"):
    return df[df[de].notna() & df["r_TLT"].notna() & df["r_SPY"].notna()]


def run_test(df, cluster_col="session", de="dE", interval=True):
    """b, its interval and p for the ΔE coefficient, plus the fit's β and R²."""
    df = usable(df, de)
    dE = df[de].to_numpy()
    out = {"n": len(df), "meetings": df["meeting"].nunique(), "sessions": df["session"].nunique(),
           "nonzero_dE": int((np.abs(dE) > NONZERO).sum())}
    if out["nonzero_dE"] == 0:
        return {**out, "note": "ΔE never moved, so b isn't estimable"}
    X = np.column_stack([np.ones(len(df)), df["r_SPY"], dE])
    y = df["r_TLT"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    test = WildClusterTest(X, 2, pd.factorize(df[cluster_col])[0]).test(y, draws=DRAWS, seed=SEED, interval=interval)
    return {
        **out, "clusters": test["clusters"], "cluster_by": cluster_col,
        "b": test["b"], "ci_low": test.get("ci_low"), "ci_high": test.get("ci_high"), "p": test["p"],
        "t_cr1": test["t"], "se_cr1": test["se_cr1"],
        "b_per_25bp": 25 * test["b"], "beta_spy": coef[1], "alpha": coef[0],
        "r2": 1 - resid.var() / y.var(), "resid_sd": resid.std(ddof=3),
    }


def decision(res):
    if res["p"] < ALPHA:
        return "Supported" if res["b"] < 0 else "Opposite sign"
    return "Not detected"


def main(mode):
    RESULTS.mkdir(exist_ok=True)
    FIGURES.mkdir(exist_ok=True)
    hourly = hourly_sample()
    daily = daily_sample()
    primary = hourly[hourly["primary"]]

    # Stock-side counts per meeting (no prices).
    counts = hourly.groupby("meeting", sort=False).apply(lambda g: pd.Series({
        "intervals_grid": len(g), "with_dE": int(g["dE"].notna().sum()),
        "with_TLT_and_SPY": int((g["r_TLT"].notna() & g["r_SPY"].notna()).sum()),
        "used": len(usable(g)),
    }), include_groups=False)
    counts.to_csv(RESULTS / "stock_coverage.csv")

    # ---- Primary (confirmatory) ----
    res = run_test(primary)
    res["decision"] = decision(res)
    power = pd.read_csv(RESULTS / "power_summary.csv", index_col=0)["value"]
    mde_b = power["mde_theta_sigma_per_bp"] * res["resid_sd"]
    res["mde_b_at_realized_sd"] = mde_b  # descriptive placement of the a priori MDE
    res["ci_excludes_minus_mde"] = bool(res["ci_low"] > -mde_b)
    pd.Series(res).to_csv(RESULTS / "primary.csv", header=["value"])
    print("PRIMARY:", pd.Series(res).to_string(), sep="\n")
    if mode == "primary":
        return

    # ---- Exploratory ----
    rows = []

    def add(check, subset, df, **kw):
        r = run_test(df, **kw)
        rows.append({"check": check, "subset": subset, **r})
        b = r.get("b")
        print(f"  {check:<28} {subset:<14} n={r['n']:<5} " + (r.get("note", "") if b is None else
              f"b={b:+.4f} [{r['ci_low']:+.4f}, {r['ci_high']:+.4f}] p={r['p']:.4f}"), flush=True)

    print("EXPLORATORY:")
    for meeting, g in primary.groupby("meeting", sort=False):
        add("1 per meeting", meeting, g)
    for year, g in primary.groupby("year"):
        add("2 by year", str(year), g)
    add("3 excl. decision days", "all", primary[~primary["decision_day"]])
    dprim = daily[daily["primary"]]
    add("4 daily", "all", dprim)
    add("4 daily", "all, by meeting", dprim, cluster_col="meeting")
    for year, g in dprim.groupby("year"):
        add("4 daily by year", str(year), g)
    add("5 clustered by meeting", "all", primary, cluster_col="meeting")
    add("6 open-ended at X+50", "all", primary, de="dE_alt")
    add("7 liquid books only", "all", primary[primary["liquid"]])
    add("8 add July 2026", "27 meetings", hourly)
    five = {m["meeting"]: set(M.window(m["decision"], 5)) for m in M.meetings()}
    add("9 5-session window", "all", primary[[s in five[m] for m, s in zip(primary["meeting"], primary["session"])]])
    exploratory = pd.DataFrame(rows)
    exploratory.to_csv(RESULTS / "exploratory.csv", index=False)

    forest(exploratory[(exploratory["check"] == "1 per meeting")], res, FIGURES / "per_meeting.png")


# Reference palette (dataviz skill): slot-1 blue for the marks, neutral ink for text and rules.
INK, INK_2, MUTED, RULE, SURFACE, SERIES = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#fcfcfb", "#2a78d6"
CLIP = 1.0  # x-axis half-width, % per bp: wider intervals are drawn to the edge with an arrow


def forest(per, primary, path):
    """Per-meeting b and 95% interval, clipped to ±CLIP so the narrow intervals stay readable."""
    per = per.reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(7.2, 8.4), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    y = np.arange(len(per))[::-1]
    ax.axvline(0, color=MUTED, lw=0.8, zorder=1)
    ax.axvline(primary["b"], color=INK_2, lw=1, ls=(0, (4, 3)), zorder=1)
    ax.text(primary["b"], len(per) - 0.3, f" pooled primary b = {primary['b']:+.3f}", color=INK_2, fontsize=8,
            ha="left", va="bottom")
    labels = []
    for yi, row in zip(y, per.itertuples()):
        name = f"{row.subset}  ({row.nonzero_dE} hours ΔE moved)"
        if pd.isna(row.b):
            labels.append(f"{row.subset}  (ΔE never moved: not estimable)")
            continue
        lo, hi = max(row.ci_low, -CLIP), min(row.ci_high, CLIP)
        ax.plot([lo, hi], [yi, yi], color=SERIES, lw=2, solid_capstyle="round", zorder=2)
        for edge, clipped in ((lo, row.ci_low < -CLIP), (hi, row.ci_high > CLIP)):
            if clipped:
                ax.annotate("", xy=(edge, yi), xytext=(edge - 0.06 * np.sign(edge), yi),
                            arrowprops={"arrowstyle": "-|>", "color": SERIES, "lw": 1.2})
        if abs(row.b) <= CLIP:
            ax.plot(row.b, yi, "o", ms=6, color=SERIES, mec=SURFACE, mew=1.5, zorder=3)
        else:
            ax.plot(np.sign(row.b) * CLIP, yi, ">" if row.b > 0 else "<", ms=7, color=SERIES, zorder=3)
            ax.text(np.sign(row.b) * CLIP * 0.97, yi + 0.32, f"b = {row.b:+.1f}", color=INK_2, fontsize=7,
                    ha="right" if row.b > 0 else "left")
        if row.ci_low < -CLIP or row.ci_high > CLIP:
            name += "  †"
        labels.append(name)
    ax.set_yticks(y, labels, fontsize=8, color=INK)
    ax.set_xlim(-CLIP * 1.05, CLIP * 1.05)
    ax.set_ylim(-0.8, len(per) + 0.4)
    ax.tick_params(axis="x", colors=INK_2, labelsize=8)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=RULE, lw=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(RULE)
    ax.set_xlabel("b: TLT % return per 1 bp rise in the expected rate change (95% bootstrap interval)",
                  color=INK_2, fontsize=8)
    ax.set_title("Exploratory check 1: per-meeting estimates", color=INK, fontsize=10, loc="left")
    fig.text(0.01, 0.005, f"† interval runs past ±{CLIP:g}; arrows mark the cut. Not a confirmatory test.",
             color=MUTED, fontsize=7)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(path, dpi=150, facecolor=SURFACE)


if __name__ == "__main__":
    import sys

    main(sys.argv[1] if len(sys.argv) > 1 else "all")
