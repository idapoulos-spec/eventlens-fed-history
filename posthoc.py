"""POST-HOC diagnostics, requested after the primary result was seen. Not in PLAN.md and not
confirmatory. They show how much the primary estimate rests on a few sessions.

1. Leave out each of the 10 most influential sessions in turn, then all 10 together, and rerun
   the primary specification and test. "Influential" means a session's share of the bootstrap's
   numerator at b0 = 0, i.e. of sum_g s_g^2 with s_g = sum_{i in g} a_i u_i over the null-imposed
   residuals. This is the share reported when the primary result came in. Each session's DFBETA
   (b̂ without it minus b̂ with it) is listed alongside.
2. For each of those sessions, the hour that contributes most to its score (largest |a_i u_i|),
   with its ΔE, for the news search in WRITEUP.md. No TLT or SPY returns are written out.
"""

import numpy as np
import pandas as pd

import analysis as A
from inference import WildClusterTest

TOP = 10


def main():
    hourly = A.hourly_sample()
    df = A.usable(hourly[hourly["primary"]]).reset_index(drop=True)
    X = np.column_stack([np.ones(len(df)), df["r_SPY"], df["dE"]])
    y = df["r_TLT"].to_numpy()
    codes, sessions = pd.factorize(df["session"])
    test = WildClusterTest(X, 2, codes)
    u = test.I_Hr @ test._sorted(y)           # null-imposed residuals, in the test's sorted order
    contrib = test.a * u                      # each hour's term in its session's s_g
    s = np.add.reduceat(contrib, test.starts)
    share = s**2 / np.sum(s**2)
    sess_sorted = sessions[codes[test.order]]
    first_rows = test.starts

    base = A.run_test(df)
    ranked = np.argsort(share)[::-1][:TOP]
    rows, hours = [], []
    for rank, g in enumerate(ranked, 1):
        session = sess_sorted[first_rows[g]]
        res = A.run_test(df[df["session"] != session])
        rows.append({"left_out": str(session), "rank": rank, "meeting": df.loc[df["session"] == session, "meeting"].iloc[0],
                     "score_share": share[g], "dfbeta": res["b"] - base["b"],
                     **{k: res[k] for k in ("n", "b", "ci_low", "ci_high", "p")}})
        stop = first_rows[g + 1] if g + 1 < len(first_rows) else len(contrib)
        within = np.arange(first_rows[g], stop)
        top_hour = within[np.argmax(np.abs(contrib[within]))]
        row = df.iloc[test.order[top_hour]]
        hours.append({"rank": rank, "session": str(session), "meeting": row["meeting"],
                      "hour_et": f"{row['start']:%H:%M}-{row['end']:%H:%M}", "dE_bp": round(row["dE"], 2),
                      "share_of_session_score": float(contrib[top_hour] ** 2 / np.sum(contrib[within] ** 2))})
    top_sessions = [r["left_out"] for r in rows]
    together = A.run_test(df[~df["session"].astype(str).isin(top_sessions)])
    out = pd.DataFrame([
        {"left_out": "none (primary)", "rank": 0, **{k: base[k] for k in ("n", "b", "ci_low", "ci_high", "p")}},
        *rows,
        {"left_out": f"all top {TOP} together", "rank": None, **{k: together[k] for k in ("n", "b", "ci_low", "ci_high", "p")}},
    ])
    out.to_csv(A.RESULTS / "posthoc_influence.csv", index=False)
    pd.DataFrame(hours).to_csv(A.RESULTS / "posthoc_hours.csv", index=False)
    pd.set_option("display.width", 200)
    print(out.round(4).to_string(index=False))
    print()
    print(pd.DataFrame(hours).round(3).to_string(index=False))
    print(f"\ntop {TOP} sessions' share of the score: {share[ranked].sum():.3f}")


if __name__ == "__main__":
    main()
