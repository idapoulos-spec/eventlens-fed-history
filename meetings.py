"""FOMC meetings, the NYSE calendar, and each meeting's window of hourly intervals (PLAN.md).

The windows are recomputed here from the calendar and checked against PLAN.md's table, so a
mismatch stops everything downstream.
"""

import datetime as dt
import re
from pathlib import Path

import pandas as pd

NY = "America/New_York"
PLAN = Path(__file__).resolve().parent / "PLAN.md"

# Scheduled FOMC decisions (statement at 2:00 PM ET) and the expected Kalshi event suffix.
PRIMARY = [
    ("2023-05-03", "23MAY"), ("2023-06-14", "23JUN"), ("2023-07-26", "23JUL"), ("2023-09-20", "23SEP"),
    ("2023-11-01", "23NOV"), ("2023-12-13", "23DEC"),
    ("2024-01-31", "24JAN"), ("2024-03-20", "24MAR"), ("2024-05-01", "24MAY"), ("2024-06-12", "24JUN"),
    ("2024-07-31", "24JUL"), ("2024-09-18", "24SEP"), ("2024-11-07", "24NOV"), ("2024-12-18", "24DEC"),
    ("2025-01-29", "25JAN"), ("2025-03-19", "25MAR"), ("2025-05-07", "25MAY"), ("2025-06-18", "25JUN"),
    ("2025-07-30", "25JUL"), ("2025-09-17", "25SEP"), ("2025-10-29", "25OCT"), ("2025-12-10", "25DEC"),
    ("2026-01-28", "26JAN"), ("2026-03-18", "26MAR"), ("2026-04-29", "26APR"), ("2026-06-17", "26JUN"),
]
# In fed-oct's data window, so exploratory only (PLAN.md, exploratory check 8).
EXPLORATORY = [("2026-07-29", "26JUL")]
SERIES = "KXFEDDECISION"

# NYSE full-day closures and 1:00 PM early closes, 2023-2026.
HOLIDAYS = {dt.date.fromisoformat(d) for d in [
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29", "2023-06-19", "2023-07-04",
    "2023-09-04", "2023-11-23", "2023-12-25",
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19", "2024-07-04",
    "2024-09-02", "2024-11-28", "2024-12-25",
    "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
]}
EARLY_CLOSES = {dt.date.fromisoformat(d) for d in [
    "2023-07-03", "2023-11-24", "2024-07-03", "2024-11-29", "2024-12-24", "2025-07-03", "2025-11-28",
    "2025-12-24", "2026-11-27", "2026-12-24",
]}

SESSIONS_BEFORE = 10
FIRST_MARK_HOUR = 10       # no Kalshi mark at 09:30
DECISION_LAST_HOUR = 14    # nothing at or after the 2:00 PM statement


def is_session(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def previous_sessions(d, n):
    """The n sessions before date d, oldest first."""
    out = []
    while len(out) < n:
        d -= dt.timedelta(days=1)
        if is_session(d):
            out.append(d)
    return out[::-1]


def close_hour(d):
    return 13 if d in EARLY_CLOSES else 16


def ny(d, hour):
    return pd.Timestamp(dt.datetime.combine(d, dt.time(hour)), tz=NY)


def meetings(include_exploratory=False):
    rows = PRIMARY + (EXPLORATORY if include_exploratory else [])
    return [
        {"decision": dt.date.fromisoformat(d), "suffix": s, "event": f"{SERIES}-{s}", "primary": (d, s) in PRIMARY}
        for d, s in rows
    ]


def window(decision, sessions_before=SESSIONS_BEFORE):
    """Sessions in a meeting's window: the sessions before the decision day, then the decision day."""
    assert is_session(decision), decision
    return previous_sessions(decision, sessions_before) + [decision]


def intervals(meeting, sessions_before=SESSIONS_BEFORE):
    """One row per hourly interval: consecutive top-of-hour marks within one session."""
    decision = meeting["decision"]
    rows = []
    for d in window(decision, sessions_before):
        last = DECISION_LAST_HOUR if d == decision else close_hour(d)
        for h in range(FIRST_MARK_HOUR, last):
            rows.append({
                "event": meeting["event"], "decision": decision, "session": d, "decision_day": d == decision,
                "start": ny(d, h), "end": ny(d, h + 1),
            })
    return pd.DataFrame(rows)


def all_intervals(include_exploratory=False, sessions_before=SESSIONS_BEFORE):
    return pd.concat([intervals(m, sessions_before) for m in meetings(include_exploratory)], ignore_index=True)


def plan_table():
    """PLAN.md's meeting table as {decision: (event suffix, first session, last session)}."""
    table = {}
    pattern = re.compile(r"^\| (?:\d+|—) \| (\d{4}-\d{2}-\d{2})[^|]*\| (\w+) \| ((?:\d{4}-)?\d{2}-\d{2}) → (\d{2}-\d{2})")
    for line in PLAN.read_text().splitlines():
        m = pattern.match(line)
        if not m:
            continue
        decision = dt.date.fromisoformat(m.group(1))
        first = m.group(3) if len(m.group(3)) == 10 else f"{decision.year}-{m.group(3)}"
        table[decision] = (m.group(2), dt.date.fromisoformat(first), dt.date.fromisoformat(f"{decision.year}-{m.group(4)}"))
    return table


def check_plan():
    """Stop unless the windows computed here match PLAN.md, and the planned sizes hold."""
    table = plan_table()
    ms = meetings(include_exploratory=True)
    assert set(table) == {m["decision"] for m in ms}, "PLAN.md lists different meetings"
    for m in ms:
        sessions = window(m["decision"])[:-1]
        expected = table[m["decision"]]
        got = (m["suffix"], sessions[0], sessions[-1])
        assert got == expected, f"{m['decision']}: computed {got}, PLAN.md says {expected}"
    primary = all_intervals()
    n_sessions = primary.groupby(["event", "session"]).ngroups
    assert (len(primary), n_sessions, primary["event"].nunique()) == (1661, 286, 26), (len(primary), n_sessions)
    return len(table)


if __name__ == "__main__":
    n = check_plan()
    print(f"windows match PLAN.md for {n} meetings; primary: 1661 intervals, 286 sessions, 26 meetings")
