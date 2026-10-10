# Kalshi expected rate change and TLT across 26 Fed meetings: one-page summary

**Question.** Across past Fed meetings, when Kalshi's market-implied expected rate change rises, does TLT fall beyond what SPY explains? This is an out-of-sample follow-up to my October 2026 study ([fed-oct](../fed-oct/SUMMARY.md)), which found TLT moving with the hold probability.

**Data.**
- **Kalshi:** hourly quotes for every outcome market of the 26 FOMC meetings from May 2023 to June 2026, read from my EventLens database.
  - Each outcome maps to basis points.
  - The expected change E is the probability-weighted average of those, renormalized.
- **Stocks:** TLT, with SPY as the market, as 30-minute bars from Twelve Data (56 API credits).
- **Window:** the 10 trading days before each decision, plus the decision morning. Trading hours only, never across a night.
- **Sample:** 1,635 hourly intervals in 286 sessions. E moved in 553 of them.
- **Left out:** July 2026, because its hours overlap the earlier study.

**Approach: pre-registered, with a git trail.**
- The plan was committed before any data was read.
- Every later choice was committed as a dated deviation before the data it affected was seen:
  - the outcome mapping for three oddly named tickers;
  - a rule for choosing the hourly or the daily design.
- The test is one pooled regression: TLT's return on SPY's return and the change in E.
- p-values come from a wild cluster bootstrap by trading session (9,999 draws). I checked the code against statsmodels and against brute-force refits.
- Power was simulated before any stock data was fetched. The design can reliably detect only a TLT move of about 2.7% or more per 25 bp repricing.

**Result (confirmatory).**

| b̂ (TLT % per 1 bp rise in expected rate change) | 95% interval | p | Implied TLT move per 25 bp |
|---|---|---|---|
| **−0.032** | [−0.152, +0.007] | **0.178** | −0.79% |

- **Not detected, and inconclusive under the pre-registered rule.** p ≥ 0.05, and the interval doesn't exclude the minimum detectable effect (−0.108).
- The sign is the predicted one, and the earlier study's rough effect (about −0.09) lies inside the interval. So this study neither confirms nor refutes it.
- **Fragility (post-hoc; not in the plan):**
  - One hour, May 31, 2023 13:00–14:00, holds 46% of all the variation in E.
  - The 10 most influential sessions hold 90% of the bootstrap's score.
  - Leaving any one of them out keeps b̂ between −0.021 and −0.067, with p from 0.11 to 0.29. The decision never changes, but the p-value and interval are fragile.

**Exploratory checks (pre-registered, not confirmatory).** By year, excluding decision days, daily data, meeting-level clustering, alternative outcome mapping, liquid books only, adding July 2026, and a shorter window:
- Every pooled variant is negative, with p from 0.08 to 0.65.
- 1 of 40 exploratory tests has p < 0.05, about what chance predicts.

**What moves the market's expectations (post-hoc).** Nine of the eleven most influential hours line up with identifiable news, and in each one E moved the way the news implies:
- 10:00 JOLTS releases (hot → up, weak → down);
- the Bank of Canada's surprise hike;
- Jefferson's "skip" remarks;
- Powell's speech;
- the July 2025 reports that Trump would fire Powell.

That supports E as a measure of expectations. It says nothing about the TLT link.

**Limitations.**
- **Power:** the minimum detectable effect is about 3.4 times this study's own estimate.
- **Information in a few hours:** a handful of hours carry most of it.
- **What the hourly design misses:** the 8:30 data releases fall before the open. The pre-committed daily alternative captures them but turned out less powerful.
- **One-sided books:** half of the outcome quotes needed the one-sided-book rule.
- **Correlation, not causation.** Not a forecast or a trading signal.

**What I'd do next.** Use higher-frequency data around scheduled 10:00 releases, or Treasury futures, which trade through 8:30. Then pre-register a single-meeting replication of the October result.

*Full write-up: [WRITEUP.md](WRITEUP.md). Plan and dated deviations: [PLAN.md](PLAN.md). Code: `kalshi.py`, `inference.py`, `power.py`, `analysis.py`, `posthoc.py`; results in `results/`.*
