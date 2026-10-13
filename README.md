# Kalshi expected rate change and TLT across 26 Fed meetings

Across the 26 FOMC meetings from May 2023 to June 2026, when Kalshi's market-implied expected rate change for the upcoming meeting rises, does TLT fall beyond what SPY explains?

**Headline: inconclusive.** The pre-registered test gives b̂ = −0.032 % per bp (95% interval [−0.152, +0.007], p = 0.178). That's the predicted sign, but it isn't detected. The design could reliably detect only an effect about 3.4 times larger (2.7% on TLT per 25 bp repricing, against an estimate of −0.8%), so the result neither shows the effect nor rules it out.

## Read

- [SUMMARY.md](SUMMARY.md): the one-page version.
- [WRITEUP.md](WRITEUP.md): the full write-up, with the confirmatory test, the pre-registered exploratory checks and the post-hoc diagnostics kept separate.
- [PLAN.md](PLAN.md): the pre-analysis plan and every dated deviation from it.

## Pre-registered

The plan was committed (`676211d`, 2026-10-09) before any data was read. Each later choice was committed before the data it affected was seen, and the power analysis was committed before any stock data was fetched. Run `git log --reverse` to see the sequence. [WRITEUP.md](WRITEUP.md#what-was-fixed-and-when) has a table of what each commit fixed and what data had been seen by then.

## Reproduce

The data isn't included. `data/` is gitignored except for [data/README.md](data/README.md), which lists the SHA-256 of every file used. To rerun the study you need:

- **An EventLens database** with the Kalshi hourly candles for the Fed decision events, reachable through a read-only Postgres role.
- **A Twelve Data API key.** The free plan is enough: the fetch uses 56 credits.
- **Python 3.12** and the pinned packages in `requirements.txt`.

Put both secrets in a gitignored `.env.local`:

```
DATABASE_URL=postgresql://...
TWELVE_DATA_API_KEY=...
```

Then run, in order:

```sh
pip install -r requirements.txt
python meetings.py            # meeting windows, checked against PLAN.md
python kalshi.py audit        # event matching and outcome mapping (metadata only)
python kalshi.py build        # E(t) and hourly ΔE into data/kalshi/
python kalshi.py daily        # daily ΔE
python check_inference.py     # synthetic checks of the bootstrap
python power.py hourly        # a priori power, from Kalshi data only
python power.py daily
python power.py compare       # the pre-committed hourly-or-daily rule
python fetch_stocks.py        # TLT and SPY bars into data/twelvedata/
python analysis.py            # the primary test, then the exploratory checks
python posthoc.py             # post-hoc influence diagnostics
```

TLT and SPY prices and returns never leave `data/`. Twelve Data can revise past bars, so a new fetch may not match the hashes in [data/README.md](data/README.md).

## Not a trading signal

This study measures a correlation, not a cause: news can move both the Kalshi markets and TLT at once. It isn't a forecast or a trading signal.
