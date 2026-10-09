# Pre-analysis plan: Kalshi expected rate change and TLT across Fed meetings

Written and committed 2026-10-09, before any data for this study was read. At this commit `data/` is empty: no Kalshi candles have been read from the EventLens store, and no stock bars have been fetched.

## Question

Across past FOMC meetings, when the Kalshi market-implied expected rate change for the upcoming meeting rises, does TLT fall beyond what SPY explains?

This is an out-of-sample follow-up to `../fed-oct`. That study used the October 2026 hold market and TLT hourly bars from 2026-07-08 to 2026-10-05. The primary test here uses none of those hours.

## Sample

- **Primary sample:** every scheduled FOMC meeting from May 2023 through June 2026 that has a KXFEDDECISION event. That's 26 meetings, listed below.
- **Not in the primary sample:**
  - **July 2026** (decided 2026-07-29). Its whole window lies inside fed-oct's data window, so its TLT hours are already in-sample. It's used only in exploratory check 8.
  - **September and October 2026**, which fed-oct used. October 2026 hasn't been decided yet.
- **Matching meetings to Kalshi events:**
  - Each meeting is matched to the KXFEDDECISION event whose markets close on its decision date.
  - The ticker is expected to be `KXFEDDECISION-<YY><MON>`; step 2 confirms it.
  - A meeting with no event in the store is reported as missing and isn't replaced.

| # | Decision (statement 2:00 PM ET) | Expected event | Window: 10 sessions before the decision day |
|---|---|---|---|
| 1 | 2023-05-03 | 23MAY | 2023-04-19 → 05-02 |
| 2 | 2023-06-14 | 23JUN | 05-31 → 06-13 |
| 3 | 2023-07-26 | 23JUL | 07-12 → 07-25 |
| 4 | 2023-09-20 | 23SEP | 09-06 → 09-19 |
| 5 | 2023-11-01 | 23NOV | 10-18 → 10-31 |
| 6 | 2023-12-13 | 23DEC | 11-29 → 12-12 |
| 7 | 2024-01-31 | 24JAN | 2024-01-17 → 01-30 |
| 8 | 2024-03-20 | 24MAR | 03-06 → 03-19 |
| 9 | 2024-05-01 | 24MAY | 04-17 → 04-30 |
| 10 | 2024-06-12 | 24JUN | 05-29 → 06-11 |
| 11 | 2024-07-31 | 24JUL | 07-17 → 07-30 |
| 12 | 2024-09-18 | 24SEP | 09-04 → 09-17 |
| 13 | 2024-11-07 (Thu) | 24NOV | 10-24 → 11-06 |
| 14 | 2024-12-18 | 24DEC | 12-04 → 12-17 |
| 15 | 2025-01-29 | 25JAN | 2025-01-14 → 01-28 (01-20 closed) |
| 16 | 2025-03-19 | 25MAR | 03-05 → 03-18 |
| 17 | 2025-05-07 | 25MAY | 04-23 → 05-06 |
| 18 | 2025-06-18 | 25JUN | 06-04 → 06-17 |
| 19 | 2025-07-30 | 25JUL | 07-16 → 07-29 |
| 20 | 2025-09-17 | 25SEP | 09-03 → 09-16 |
| 21 | 2025-10-29 | 25OCT | 10-15 → 10-28 |
| 22 | 2025-12-10 | 25DEC | 11-25 → 12-09 (11-27 closed; 11-28 closes 13:00) |
| 23 | 2026-01-28 | 26JAN | 2026-01-13 → 01-27 (01-19 closed) |
| 24 | 2026-03-18 | 26MAR | 03-04 → 03-17 |
| 25 | 2026-04-29 | 26APR | 04-15 → 04-28 |
| 26 | 2026-06-17 | 26JUN | 06-03 → 06-16 |
| — | 2026-07-29 | 26JUL | 07-15 → 07-28 (exploratory only) |

The code recomputes these windows from a hard-coded 2023–2026 NYSE holiday and early-close list. It stops if they don't match this table, or if the sessions present in the stock bars differ from the calendar.

## Kalshi side: expected rate change E(t)

**Source.**
- Data: hourly candles (`period_min = 60`) from the EventLens store's `kalshi_markets`, `kalshi_candles` and `fetch_coverage` tables.
- Connection: role `eventlens_app`, which can only read, with every transaction opened `READ ONLY`.
- Credentials: `DATABASE_URL` sits in this folder's `.env.local`, which is gitignored. A script builds it from `~/eventlens/.env.local` and prints no values.

**Outcomes to basis points.** Each outcome is mapped from its `yes_sub_title`, and the ticker suffix is checked against it.

| Outcome | bp |
|---|---|
| Hold | 0 |
| Cut 25 / Hike 25 | −25 / +25 |
| Cut 50 / Hike 50 (where listed) | −50 / +50 |
| Cut >25 / Hike >25 (legacy) | −50 / +50 |
| Any other open-ended "> X bp" | ∓(X + 25) |

- **Open-ended outcomes** are set at the next 25 bp step past their threshold, because the Fed moves in 25 bp steps. Setting them at X + 50 is exploratory check 6.
- **Stop rule.** No candles are read, and the plan is amended only after asking, if any of these happens:
  - an outcome's label doesn't fit the table;
  - an outcome's label and ticker suffix disagree;
  - two of an event's outcomes overlap.

**Each outcome's probability at an hour mark t.** The book in effect at t is the latest hourly candle ending at or before t, looking back up to 7 days. Kalshi writes a candle only when something changes, so a quiet hour keeps the last candle's quotes. A bid of 0 or none counts as no bid; an ask of $1 or none counts as no ask.

1. **Both sides quoted** (ask ≥ bid): p = (bid + ask) / 2.
2. **Ask only:** p = ask / 2, since the probability lies somewhere between 0 and the ask.
3. **Bid only:** p = (bid + 1) / 2.
4. **Neither side, or no candle in the last 7 days:**
   - p = 0 if the outcome's last estimate under rules 1–3 was 5¢ or less, or it never had one.
   - Otherwise E(t) is missing.

**Expected change.** E(t) = Σ pᵢ·bpᵢ / Σ pᵢ, in bp, over the event's outcome markets that are open at t. Dividing by Σ pᵢ renormalizes probabilities that don't sum to 1.

**E(t) is missing when any of these holds:**
- Σ pᵢ is outside [0.80, 1.20], because the book doesn't hang together.
- `fetch_coverage` doesn't span the stretch from the candle used up to t for every open outcome. That's a collection gap, which is different from an empty book.
- t is after any of the event's markets' close time.

**ΔE** over an interval is E(t) − E(t − 1h). It's used only if E is defined at both ends and the same outcome markets are open at both ends. A market opening or closing in between would move E mechanically.

**Reported per meeting, before any stock data is fetched:**
- hours with a valid E;
- intervals with nonzero ΔE;
- the distribution of Σ pᵢ;
- how often rules 2–4 applied;
- hours dropped, by reason.

## Stock side

**30-minute bars**
- TLT and SPY 30-minute bars from Twelve Data's `/time_series`, one request per symbol per meeting. That's 26 meetings plus July 2026.
- Each request uses `timezone=America/New_York`, `start_date` = 09:30 on the window's first session, `end_date` = 16:00 on the decision day, and regular hours only.

**Daily bars** (for exploratory check 4)
- One request per symbol for 2023-04-17 → 2026-07-29.
- `adjust=all`, so TLT's monthly and SPY's quarterly ex-dividend drops don't enter close-to-close returns.

**Credits**
- 27 meetings × 2 symbols = 54 for the 30-minute bars, plus 2 for the daily bars: **56 in total**. The free plan allows 800 a day.
- The script stops before going past 70, which leaves room for retries.
- The first request (TLT, May 2023) tests whether history reaches back that far. If it doesn't, I stop and report.

**Pacing**
- One request every 10 s, which is 6 a minute, under the limit of 8. The whole fetch takes about 10 minutes.
- On a 429 it waits 65 s and retries, at most 3 times.

**Storage and secrecy**
- Raw responses go in `data/twelvedata/`, which is gitignored and never committed. A file already on disk is never fetched again.
- `data/README.md` is committed. It lists file names, row counts and SHA-256 hashes, and no prices.
- The API key comes from `.env.local` and goes in a request header, never in a URL or log.
- `results/` holds only aggregates such as estimates, p-values and counts, never price or return series.

## Window and alignment

- **Window.** For each meeting: the 10 NYSE sessions before the decision day, plus the decision day up to 14:00 ET.
- **Hour marks.** Top of each hour, 10:00 to 16:00 ET.
  - The price at mark H is the close of the 30-minute bar ending at H.
  - E at mark H comes from the Kalshi candle ending at H.
- **Intervals.** An interval joins two consecutive marks within one session, never spanning overnight, a weekend or a holiday.
  - A full session gives 6 intervals (10–11 … 15–16).
  - The decision day gives 4 (10–11 … 13–14), so nothing at or after the 2:00 PM statement is used.
  - The early close on 2025-11-28 gives 3.
  - 09:30–10:00 isn't used, since there's no Kalshi mark at 09:30.
- **Planned size.** 1,661 intervals in 286 sessions across 26 meetings. An interval missing TLT, SPY or E at either end is dropped and counted.
- **Returns.** Simple returns from bar closes, in percent. ΔE is in bp.
- **Why 10 sessions.**
  1. Trading and news about a meeting concentrate in its last two weeks, when its market is most liquid. That matters most for the thinner 2023–24 books.
  2. It covers the FOMC blackout (from the second Saturday before the meeting), when expectations move on data releases rather than Fed speakers, plus a few days before it.
  3. Every window starts at least 27 calendar days after the previous decision. Windows never overlap, and none contains a previous decision day.
  4. 286 sessions gives the cluster bootstrap plenty of clusters.

  The length is fixed now and not varied. A 5-session window is exploratory check 9.

## Primary test (confirmatory)

The model is a pooled OLS over all 26 meetings:

`r_TLT,t = a + β·r_SPY,t + b·ΔE_t + e_t`

- **Hypotheses.** H0: b = 0, tested two-sided. The prediction is b < 0: TLT falls when the expected rate change rises.
- **Statistic.** The t of b̂, with CR1 cluster-robust standard errors clustered by New York trading session.
- **p-value: wild cluster restricted bootstrap.**
  - Fit the model with b = 0 imposed.
  - Rebuild TLT returns as that restricted fit plus its residuals, each session's residuals multiplied by one Webb six-point weight.
  - Refit the full model and recompute t.
  - 9,999 draws, seed 20261009. p = (1 + #{|t*| ≥ |t|}) / 10,000.
- **95% interval.** Every b that the same bootstrap doesn't reject at 5%, found by test inversion.
- **Decision rule (α = 0.05).**
  - **Supported:** p < 0.05 and b̂ < 0.
  - **Opposite sign:** p < 0.05 and b̂ > 0. Reported as contrary to the prediction, not as support.
  - **Not detected:** p ≥ 0.05. This isn't evidence of no effect. If the 95% interval excludes −MDE (see Power), the writeup may say effects that large are unlikely. Otherwise the result is inconclusive.
- **This is the only confirmatory test.** No multiplicity adjustment applies. Everything else is exploratory, whatever its p-value.
- **Also reported:** b̂ and its interval; 25·b̂, TLT's move for a full 25 bp repricing; β̂; R²; and the numbers of intervals, sessions, meetings, and intervals with nonzero ΔE.
- **No outlier removal or winsorizing.**

## Power (a priori; run and committed before any stock data is fetched)

The minimum detectable effect (MDE) is simulated on the real design: the 26 meetings' actual ΔE series and session structure, from the Kalshi side alone. No stock data is used.

- **Simulated returns.** y = β·x + θ·ΔE + u, where:
  - x stands in for SPY and is simulated independently of ΔE.
  - u is Student-t(4) noise, with a lognormal volatility multiplier per session (sd of log 0.3).
  - u's volatility doubles in intervals with |ΔE| ≥ 0.25 bp, which are news hours.
  - u is rescaled to overall sd σ.
- **Testing.** Each simulated dataset is tested exactly as in the primary test, with 399 bootstrap draws. There are 2,000 datasets per θ, on a grid that brackets 80%. Power is the share with p < 0.05 and b̂ < 0.
- **The MDE** is the smallest |θ| with 80% power, interpolated on the grid and then confirmed with 2,000 fresh datasets (Monte Carlo SE reported).
- **Size check.** The rejection rate at θ = 0 is reported to check the test.
- **Units.** The MDE is given as:
  - a partial correlation;
  - b in units of σ per bp;
  - b in % per bp for σ = 0.20, 0.30 and 0.40% per hour;
  - TLT's move for a 25 bp repricing.

  After the data is in, the realized residual sd places the MDE on that grid. This is descriptive only.
- **Caveat.** If ΔE correlates with SPY, less of its variation is left after the control, so this power is slightly optimistic.

## Exploratory (labelled as such; no confirmatory claims)

All use the same bootstrap. Subsamples are fitted with their own β.

1. **Per meeting.** One regression per meeting, each with 11 sessions as clusters. Shown as a forest plot with each meeting's count of nonzero ΔE intervals.
2. **By year.** 2023 (6 meetings), 2024 (8), 2025 (8), 2026 (4).
3. **Excluding decision days.**
4. **Daily data.**
   - TLT's close-to-close returns (adjusted daily bars) on SPY's and on ΔE between Kalshi values at consecutive session closes.
   - The 10 pre-decision sessions per meeting give 260 intervals. These include overnight moves.
   - Decision days are left out, because their close-to-close return straddles the statement.
   - Pooled and by year; not per meeting, which would leave only 10 observations each.
   - Session clusters are single observations here, so the bootstrap is heteroskedasticity-robust only. A version clustered by meeting is also reported.

Added beyond the requested list:

5. The primary specification with the bootstrap clustered by meeting (26 clusters).
6. Open-ended outcomes set at ∓(X + 50) bp.
7. Liquid books only: hours where every outcome priced above 5¢ is quoted on both sides with a spread of at most 5¢.
8. Add July 2026, for 27 meetings.
9. A 5-session window (plus the decision day).

## Reporting rules

- Neutral language: describe correlation, not causation. If ΔE moves SPY, controlling for SPY removes part of the effect being studied, and the writeup says so.
- No trading signals or recommendations.
- Every meeting is reported, whatever its result.
- Any change to this plan is added under Deviations, dated, before the data it affects is read.

## Order of work (each step committed before the next starts)

1. This plan.
2. Metadata audit: tickers, titles, open and close times, and coverage, with no prices. Then the outcome mapping, checked against the stop rule.
3. Kalshi E(t) and its diagnostics.
4. Power simulation. **Checkpoint: report the MDE and wait for the go-ahead.**
5. Fetch stock data.
6. Primary test, then the exploratory analyses, then the writeup.

## Deviations

### 2026-10-09: after the metadata audit (step 2), before any candles were read

The audit read market tickers, titles, settlement rules, strikes, and open and close times. It read no prices, and no candles had been read at this point. The matched events and every outcome's mapping are in `results/kalshi_markets.csv`.

1. **Event tickers.**
   - In the store's `KXFEDDECISION` series, the 14 events before December 2024 are named `FEDDECISION-…`, not `KXFEDDECISION-…`. Two of them also break the `<YY><MON>` pattern: `FEDDECISION-24JAN31` and `FEDDECISION-24MAR20`.
   - The matching rule hasn't changed: the event whose markets close on the decision date. It picks exactly one event per meeting.
   - January 2024 has a second event for the same meeting, `FEDDECISION-24JAN`, whose markets closed on 2024-01-26. The rule doesn't pick it, so it isn't used.
   - Each matched event opened more than 7 days before its window. All of an event's markets opened at the same time.
2. **Irregular ticker suffixes.** The stop rule fired here, and the user decided how to proceed.
   - `FEDDECISION-23DEC-C24` has a suffix that fits no convention. `FEDDECISION-23MAY-TC25` and `-TH50` use a `T` prefix that appears nowhere else.
   - For all three, the title, subtitle, settlement rules and `custom_strike` agree. They read "Cut >25bps", "Cut >25bps" and "Hike >50bps".
   - With the user's approval, an outcome with an irregular suffix is mapped by its settlement text:
     - C24 and TC25 map to −50 bp.
     - TH50 maps to +75 bp.
     - In exploratory check 6 they map to −75, −75 and +100 bp.
3. **Hold labels.** Depending on the event, the hold outcome is labelled "No change", "Hike 0bps", "No cut/hike" or "Fed maintains rate". All of these mean the rate is unchanged, so all map to Hold (0 bp).
4. **A consequence of the rules, not a change to them: decision-day intervals.**
   - Every market closes at 13:55 or 13:59 ET on the decision day.
   - Under the rule that E is missing after the close, E(14:00) is missing. Each decision day therefore gives 3 intervals (10–13), not 4.
   - The planned maximum becomes 1,635 intervals in 286 sessions.
   - The user chose to keep the rule as written.
5. `FEDDECISION-24JUN` lists 4 outcomes, with no "Hike >25bps". E is computed over the outcomes listed, as the plan says.
