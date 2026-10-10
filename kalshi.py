"""Kalshi side of PLAN.md: match each meeting to its event, map outcomes to basis points, and
build the expected rate change E(t) at every hour mark.

    python kalshi.py audit   # metadata only (no prices): writes results/kalshi_markets.csv
    python kalshi.py build   # E(t) into data/kalshi/ (gitignored), counts into results/
    python kalshi.py daily   # close-to-close ΔE from the built marks into data/kalshi/daily.csv

Store units: prices are integer micro-dollars, null when Kalshi left the value out.
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import meetings as M
from db import connect

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
DATA = HERE / "data" / "kalshi"

SERIES = "KXFEDDECISION"
HOUR = pd.Timedelta(hours=1)
LOOKBACK = pd.Timedelta(days=7)
STALE_MAX = 0.05          # rule 4: a silent outcome counts as 0 if its last estimate was at most this
SUM_RANGE = (0.80, 1.20)  # Σp outside this: the book doesn't hang together
LIQUID_P, LIQUID_SPREAD = 0.05, 0.05  # exploratory check 7

HOLD_LABELS = {"No change", "Hike 0bps", "No cut/hike", "Fed maintains rate"}
LABEL = re.compile(r"^(Cut|Hike) (>?)(\d+)(?:bps)?$")
# Irregular suffixes mapped by their settlement text, as the user approved
# (PLAN.md, Deviations, 2026-10-09, item 2). The label must still read as shown here.
SUFFIX_OVERRIDES = {
    "FEDDECISION-23DEC-C24": "Cut >25bps",
    "FEDDECISION-23MAY-TC25": "Cut >25bps",
    "FEDDECISION-23MAY-TH50": "Hike >50bps",
}


def map_label(label):
    """(bp, bp for exploratory check 6, suffixes consistent with the label), or None if it doesn't fit."""
    if label in HOLD_LABELS:
        return 0, 0, {"H0"}
    m = LABEL.match(label or "")
    if not m:
        return None
    word, open_ended, x = m.group(1), m.group(2) == ">", int(m.group(3))
    sign, letter = (-1, "C") if word == "Cut" else (1, "H")
    if open_ended:
        return sign * (x + 25), sign * (x + 50), {f"{letter}>{x}", f"{letter}{x + 1}"}
    return sign * x, sign * x, {f"{letter}{x}"}


def to_ny(series):
    return pd.to_datetime(series, utc=True).dt.tz_convert(M.NY)


def audit(conn):
    """Match events and map outcomes; stop (exit 1) on anything the stop rule covers."""
    markets = pd.DataFrame(
        conn.execute(
            """select id, ticker, event_ticker, yes_sub_title, open_time, close_time
               from kalshi_markets where series_ticker = %s""",
            [SERIES],
        ).fetchall(),
        columns=["market_id", "ticker", "event", "yes_sub_title", "open_time", "close_time"],
    )
    markets["open_time"], markets["close_time"] = to_ny(markets["open_time"]), to_ny(markets["close_time"])
    rows, problems = [], []
    for meeting in M.meetings(include_exploratory=True):
        hit = markets[markets["close_time"].dt.date == meeting["decision"]]
        events = sorted(hit["event"].unique())
        if len(events) != 1:
            problems.append(f"{meeting['decision']}: {len(events)} events close that day {events}")
            continue
        for mk in hit.sort_values("ticker").itertuples():
            suffix = mk.ticker[len(mk.event) + 1:]
            mapped = map_label(mk.yes_sub_title)
            if mapped is None:
                problems.append(f"{mk.ticker}: label {mk.yes_sub_title!r} doesn't fit the table")
                continue
            bp, bp_alt, suffixes = mapped
            if mk.ticker in SUFFIX_OVERRIDES:
                if mk.yes_sub_title != SUFFIX_OVERRIDES[mk.ticker]:
                    problems.append(f"{mk.ticker}: label changed to {mk.yes_sub_title!r}")
                    continue
                mapped_by = "settlement text (approved deviation)"
            elif suffix in suffixes:
                mapped_by = "label and suffix agree"
            else:
                problems.append(f"{mk.ticker}: suffix {suffix} disagrees with label {mk.yes_sub_title!r}")
                continue
            rows.append({
                "meeting": meeting["meeting"], "decision": meeting["decision"], "primary": meeting["primary"],
                "event": mk.event, "ticker": mk.ticker, "market_id": mk.market_id, "yes_sub_title": mk.yes_sub_title,
                "bp": bp, "bp_alt": bp_alt, "mapped_by": mapped_by,
                "open_time": mk.open_time, "close_time": mk.close_time,
            })
    out = pd.DataFrame(rows)
    for event, group in out.groupby("event"):
        if group["bp"].duplicated().any():
            problems.append(f"{event}: two outcomes map to the same bp, so they overlap")
    if problems:
        print("STOP (PLAN.md stop rule):", *problems, sep="\n  ")
        sys.exit(1)
    return out


def merged_coverage(conn, tickers):
    """Per ticker, sorted non-overlapping [lo, hi) ranges of candle end times some fetch covered."""
    rows = conn.execute(
        """select series_key, lower(covered), upper(covered) from fetch_coverage
           where source = 'kalshi' and interval = '60' and series_key = any(%s)""",
        [list(tickers)],
    ).fetchall()
    cov = {t: [] for t in tickers}
    for key, lo, hi in sorted(rows, key=lambda r: (r[0], r[1])):
        lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
        ranges = cov[key]
        if ranges and lo <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], hi))
        else:
            ranges.append((lo, hi))
    return cov


def covered(ranges, after, upto):
    """Whether every hourly candle end in (after, upto] lies inside one covered range."""
    first = after.floor("h") + HOUR
    if first > upto:
        return True
    return any(lo <= first and hi > upto for lo, hi in ranges)


def estimate(bid, ask):
    """(probability, rule) for one candle's closing book; rule 4 means no usable quote."""
    has_bid = bid is not None and bid > 0
    has_ask = ask is not None and ask < 1
    if has_bid and has_ask:
        return ((bid + ask) / 2, 1) if ask >= bid else (None, "crossed")
    if has_ask:
        return ask / 2, 2
    if has_bid:
        return (bid + 1) / 2, 3
    return None, 4


class Outcome:
    """One outcome market's candles, with each candle's estimate and the last usable one so far."""

    def __init__(self, info, candles, ranges):
        self.info, self.ranges = info, ranges
        c = candles.sort_values("end_ts")
        self.ends = list(c["end_ts"])
        self.ends_ns = np.array([e.value for e in self.ends], dtype=np.int64)
        self.books = [(None if pd.isna(b) else b / 1e6, None if pd.isna(a) else a / 1e6)
                      for b, a in zip(c["bid"], c["ask"])]
        self.estimates = [estimate(b, a) for b, a in self.books]
        last, self.last_usable = None, []
        for p, rule in self.estimates:
            if rule in (1, 2, 3):
                last = p
            self.last_usable.append(last)

    def at(self, t):
        """(p or None, rule or missing reason, liquid) at mark t."""
        i = int(np.searchsorted(self.ends_ns, t.value, side="right")) - 1
        has_recent = i >= 0 and self.ends[i] > t - LOOKBACK
        after = self.ends[i] if has_recent else max(t - LOOKBACK, self.info["open_time"])
        if not covered(self.ranges, after, t):
            return None, "coverage", False
        if has_recent:
            p, rule = self.estimates[i]
            if rule in (1, 2, 3):
                bid, ask = self.books[i]
                liquid = p <= LIQUID_P or (rule == 1 and ask - bid <= LIQUID_SPREAD)
                return p, rule, liquid
        last = self.last_usable[i] if i >= 0 else None
        if last is None or last <= STALE_MAX:
            return 0.0, "4_zero", True
        return None, "stale_quote", False


def mark_times(meeting):
    """Every mark a meeting needs: intraday marks of its window, and the close of the session before it."""
    sessions = M.window(meeting["decision"])
    pre = M.previous_sessions(sessions[0], 1)[0]
    marks = [(M.ny(pre, M.close_hour(pre)), pre, False)]
    for d in sessions:
        last = M.DECISION_LAST_HOUR if d == meeting["decision"] else M.close_hour(d)
        marks += [(M.ny(d, h), d, True) for h in range(M.FIRST_MARK_HOUR, last + 1)]
    return marks


def build(conn, outcomes):
    marks, rule_rows = [], []
    for meeting in M.meetings(include_exploratory=True):
        group = outcomes[outcomes["meeting"] == meeting["meeting"]]
        until = M.ny(meeting["decision"], 15).tz_convert("UTC")
        candles = pd.DataFrame(
            conn.execute(
                """select market_id, end_ts, yes_bid_close, yes_ask_close from kalshi_candles
                   where market_id = any(%s) and period_min = 60 and end_ts <= %s""",
                [list(map(int, group["market_id"])), until.to_pydatetime()],
            ).fetchall(),
            columns=["market_id", "end_ts", "bid", "ask"],
        )
        candles["end_ts"] = to_ny(candles["end_ts"])
        cov = merged_coverage(conn, group["ticker"])
        book = [Outcome(info, candles[candles["market_id"] == info["market_id"]], cov[info["ticker"]])
                for info in group.to_dict("records")]
        first_close = group["close_time"].min()
        for t, session, in_window in mark_times(meeting):
            row = {"meeting": meeting["meeting"], "primary": meeting["primary"], "t": t, "session": session,
                   "in_window": in_window, "E": np.nan, "E_alt": np.nan, "sum_p": np.nan, "liquid": False,
                   "open_set": "", "missing": ""}
            open_now = [o for o in book if o.info["open_time"] <= t < o.info["close_time"]]
            if t >= first_close:
                row["missing"] = "after_close"
            elif not open_now:
                row["missing"] = "not_open"
            else:
                states = [o.at(t) for o in open_now]
                if in_window:
                    rule_rows += [{"meeting": meeting["meeting"], "rule": str(s[1])} for s in states]
                reasons = [s[1] for s in states if s[0] is None]
                if reasons:
                    row["missing"] = "coverage" if "coverage" in reasons else reasons[0]
                else:
                    p = np.array([s[0] for s in states])
                    total = p.sum()
                    row["sum_p"] = total
                    row["open_set"] = " ".join(sorted(o.info["ticker"] for o in open_now))
                    row["liquid"] = all(s[2] for s in states)
                    if not SUM_RANGE[0] <= total <= SUM_RANGE[1]:
                        row["missing"] = "sum_out_of_range"
                    else:
                        row["E"] = float(p @ np.array([o.info["bp"] for o in open_now]) / total)
                        row["E_alt"] = float(p @ np.array([o.info["bp_alt"] for o in open_now]) / total)
            marks.append(row)
    return pd.DataFrame(marks), pd.DataFrame(rule_rows)


def hourly_intervals(marks):
    """Every interval on the meetings' grid, with ΔE where E is valid at both ends and the outcome set is unchanged."""
    grid = M.all_intervals(include_exploratory=True)
    keyed = marks.set_index(["meeting", "t"])
    start = keyed.loc[list(zip(grid["meeting"], grid["start"]))].reset_index(drop=True)
    end = keyed.loc[list(zip(grid["meeting"], grid["end"]))].reset_index(drop=True)
    out = grid.copy()
    out["primary"] = end["primary"].values
    ok = start["E"].notna() & end["E"].notna() & (start["open_set"] == end["open_set"])
    out["dE"] = np.where(ok, end["E"] - start["E"], np.nan)
    out["dE_alt"] = np.where(ok, end["E_alt"] - start["E_alt"], np.nan)
    out["liquid"] = ok & start["liquid"].values & end["liquid"].values
    out["missing"] = np.where(ok, "", np.where(start["missing"] != "", start["missing"], end["missing"]))
    out.loc[~ok & (out["missing"] == ""), "missing"] = "outcome_set_changed"
    return out


def daily_intervals(marks):
    """Close-to-close ΔE over each meeting's pre-decision sessions (exploratory check 4, and
    PLAN.md's 2026-10-10 deviation), the first from the close of the session before the window."""
    marks = marks.copy()
    marks["t"] = pd.to_datetime(marks["t"], utc=True).dt.tz_convert(M.NY)
    marks["open_set"] = marks["open_set"].fillna("")
    keyed = marks.set_index(["meeting", "t"])
    rows = []
    for meeting in M.meetings(include_exploratory=True):
        sessions = M.window(meeting["decision"])[:-1]
        closes = M.previous_sessions(sessions[0], 1) + sessions
        for d0, d1 in zip(closes, closes[1:]):
            a = keyed.loc[(meeting["meeting"], M.ny(d0, M.close_hour(d0)))]
            b = keyed.loc[(meeting["meeting"], M.ny(d1, M.close_hour(d1)))]
            ok = pd.notna(a["E"]) and pd.notna(b["E"]) and a["open_set"] == b["open_set"]
            rows.append({
                "meeting": meeting["meeting"], "primary": meeting["primary"], "decision": meeting["decision"],
                "session": d1, "prev_session": d0,
                "start": M.ny(d0, M.close_hour(d0)), "end": M.ny(d1, M.close_hour(d1)),
                "dE": b["E"] - a["E"] if ok else np.nan, "dE_alt": b["E_alt"] - a["E_alt"] if ok else np.nan,
                "liquid": bool(ok and a["liquid"] and b["liquid"]),
            })
    return pd.DataFrame(rows)


def diagnostics(outcomes, marks, rules, intervals):
    rows = []
    window_marks = marks[marks["in_window"]]
    for meeting, g in window_marks.groupby("meeting", sort=False):
        iv = intervals[intervals["meeting"] == meeting]
        r = rules[rules["meeting"] == meeting]["rule"].value_counts()
        valid = g[g["E"].notna()]
        row = {
            "meeting": meeting, "event": outcomes.loc[outcomes["meeting"] == meeting, "event"].iloc[0],
            "primary": bool(g["primary"].iloc[0]),
            "marks": len(g), "marks_valid": len(valid),
            **{f"marks_missing_{k}": int((g["missing"] == k).sum())
               for k in ["after_close", "coverage", "stale_quote", "sum_out_of_range", "not_open"]},
            "intervals_planned": len(iv), "intervals_valid": int(iv["dE"].notna().sum()),
            "intervals_nonzero_dE": int((iv["dE"].abs() > 1e-12).sum()),
            "intervals_liquid": int(iv["liquid"].sum()),
            **{f"outcome_marks_rule_{k}": int(r.get(k, 0)) for k in ["1", "2", "3", "4_zero", "stale_quote", "crossed", "coverage"]},
            "sum_p_min": valid["sum_p"].min(), "sum_p_p05": valid["sum_p"].quantile(0.05),
            "sum_p_median": valid["sum_p"].median(), "sum_p_p95": valid["sum_p"].quantile(0.95),
            "sum_p_max": valid["sum_p"].max(),
        }
        rows.append(row)
    return pd.DataFrame(rows).round(4)


def main(mode):
    if mode == "daily":
        daily = daily_intervals(pd.read_csv(DATA / "marks.csv"))
        daily.to_csv(DATA / "daily.csv", index=False)
        primary = daily[daily["primary"]]
        print(f"daily primary: {primary['dE'].notna().sum()} of {len(primary)} intervals have ΔE; "
              f"{(primary['dE'].abs() > 1e-12).sum()} nonzero")
        return
    RESULTS.mkdir(exist_ok=True)
    with connect() as conn:
        outcomes = audit(conn)
        cols = ["meeting", "decision", "primary", "event", "ticker", "yes_sub_title", "bp", "bp_alt", "mapped_by",
                "open_time", "close_time"]
        outcomes[cols].to_csv(RESULTS / "kalshi_markets.csv", index=False)
        print(f"audit ok: {outcomes['event'].nunique()} events, {len(outcomes)} outcomes -> results/kalshi_markets.csv")
        if mode == "audit":
            return
        marks, rules = build(conn, outcomes)
    intervals = hourly_intervals(marks)
    DATA.mkdir(parents=True, exist_ok=True)
    marks.to_csv(DATA / "marks.csv", index=False)
    intervals.to_csv(DATA / "intervals.csv", index=False)
    diag = diagnostics(outcomes, marks, rules, intervals)
    diag.to_csv(RESULTS / "kalshi_diagnostics.csv", index=False)
    primary = intervals[intervals["primary"]]
    print(f"primary: {primary['dE'].notna().sum()} of {len(primary)} intervals have ΔE; "
          f"{(primary['dE'].abs() > 1e-12).sum()} nonzero; missing by reason: "
          f"{primary.loc[primary['dE'].isna(), 'missing'].value_counts().to_dict()}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "audit")
