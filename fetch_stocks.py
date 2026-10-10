"""Fetch TLT and SPY bars from Twelve Data as PLAN.md's Stock side says, into data/twelvedata/.

- 30-minute bars: one request per symbol per meeting (26 primary + July 2026), start_date 09:30
  on the window's first session, end_date 16:00 on the decision day, New York time, regular hours.
- Daily bars: one request per symbol, 2023-04-17 to 2026-07-29, adjust=all.
- One request every 10 s (6 a minute; the free plan allows 8). On a 429, wait 65 s, at most 3 retries.
- Stops before a 71st credit. A file already on disk is never fetched again.
- The first request (TLT, May 2023) checks that history reaches back that far; if not, it stops.
- The API key goes in a header, never in a URL or the output. Nothing here prints a price.
"""

import csv
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

import meetings as M
from env import read_env

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "twelvedata"
LOG = OUT / "requests.csv"
BASE = "https://api.twelvedata.com/time_series"
SYMBOLS = ("TLT", "SPY")
PACE_S, RETRY_WAIT_S, RETRIES = 10, 65, 3
CREDIT_CAP = 70
DAILY_RANGE = ("2023-04-17", "2026-07-29")


def requests_planned():
    planned = []
    for m in M.meetings(include_exploratory=True):
        first = M.window(m["decision"])[0]
        for symbol in SYMBOLS:
            planned.append({
                "file": f"{symbol}_30min_{m['meeting']}.json", "symbol": symbol, "meeting": m["meeting"],
                "params": {"symbol": symbol, "interval": "30min", "timezone": M.NY, "outputsize": "5000",
                           "start_date": f"{first} 09:30:00", "end_date": f"{m['decision']} 16:00:00"},
            })
    for symbol in SYMBOLS:
        planned.append({
            "file": f"{symbol}_1day_all.json", "symbol": symbol, "meeting": "",
            "params": {"symbol": symbol, "interval": "1day", "outputsize": "5000", "adjust": "all",
                       "start_date": DAILY_RANGE[0], "end_date": DAILY_RANGE[1]},
        })
    # The May 2023 TLT request goes first, as the history check.
    return planned


def get(params, key):
    request = urllib.request.Request(f"{BASE}?{urlencode(params)}", headers={"Authorization": f"apikey {key}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(), response.headers.get("api-credits-left")
    except urllib.error.HTTPError as err:
        return err.code, err.read(), err.headers.get("api-credits-left")


def bar_sessions(body):
    return sorted({v["datetime"][:10] for v in body.get("values", [])})


def check_history(body, item):
    """The first request must cover the May 2023 window's first session."""
    first = str(M.window(M.meetings()[0]["decision"])[0])
    sessions = bar_sessions(body)
    if not sessions or sessions[0] > first:
        sys.exit(f"STOP: Twelve Data's 30-minute history for {item['symbol']} doesn't reach {first} "
                 f"(earliest returned: {sessions[0] if sessions else 'none'}). Nothing more fetched.")
    print(f"history check ok: {item['symbol']} 30-minute bars reach {sessions[0]}")


def log_row(row):
    new = not LOG.exists()
    with LOG.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def fetch():
    key = read_env().get("TWELVE_DATA_API_KEY")
    if not key:
        sys.exit("TWELVE_DATA_API_KEY is not set in .env.local (run make_env.py)")
    OUT.mkdir(parents=True, exist_ok=True)
    planned = requests_planned()
    todo = [p for p in planned if not (OUT / p["file"]).exists()]
    print(f"{len(planned)} files planned, {len(todo)} to fetch (credit cap {CREDIT_CAP})")
    spent, last = 0, 0.0
    for i, item in enumerate(todo):
        for attempt in range(RETRIES + 1):
            if spent >= CREDIT_CAP:
                sys.exit(f"STOP: credit cap {CREDIT_CAP} reached; {len(todo) - i} files not fetched")
            time.sleep(max(0.0, last + PACE_S - time.monotonic()))
            last = time.monotonic()
            status, raw, credits_left = get(item["params"], key)
            spent += 1
            try:
                body = json.loads(raw)
            except ValueError:
                body = {}
            error = body.get("status") == "error" or status != 200
            code = body.get("code", status) if error else 200
            log_row({"at": dt.datetime.now().isoformat(timespec="seconds"), "file": item["file"], "attempt": attempt + 1,
                     "http": status, "code": code, "rows": len(body.get("values", [])), "credits_left": credits_left})
            if code == 429 and attempt < RETRIES:
                print(f"{item['file']}: rate limited, waiting {RETRY_WAIT_S} s")
                time.sleep(RETRY_WAIT_S)
                continue
            if error:
                message = str(body.get("message", "")).replace(key, "[redacted]")[:200]
                sys.exit(f"STOP: {item['file']}: error {code}: {message}")
            break
        if item is planned[0]:
            check_history(body, item)
        (OUT / item["file"]).write_bytes(raw)
        print(f"[{i + 1}/{len(todo)}] {item['file']}: {len(body.get('values', []))} bars "
              f"({bar_sessions(body)[0] if body.get('values') else '-'} to "
              f"{bar_sessions(body)[-1] if body.get('values') else '-'}), credits used this run {spent}", flush=True)
    print(f"done: {spent} requests this run")


def check_and_manifest():
    """Sessions and bar counts against the calendar (counts only), and data/README.md's manifest."""
    problems, rows = [], []
    for m in M.meetings(include_exploratory=True):
        expected = M.window(m["decision"])
        for symbol in SYMBOLS:
            body = json.loads((OUT / f"{symbol}_30min_{m['meeting']}.json").read_text())
            if body.get("meta", {}).get("exchange_timezone") != M.NY:
                problems.append(f"{symbol} {m['meeting']}: exchange timezone {body.get('meta', {}).get('exchange_timezone')}")
            times = {v["datetime"] for v in body["values"]}
            got = sorted({t[:10] for t in times})
            if got != [str(d) for d in expected]:
                problems.append(f"{symbol} {m['meeting']}: sessions {got[0]}..{got[-1]} ({len(got)}) differ from the calendar")
            for d in expected:
                close = M.close_hour(d)
                want = {f"{d} {h:02d}:{mi:02d}:00" for h in range(9, close) for mi in (0, 30) if (h, mi) >= (9, 30)}
                missing = want - times
                if missing:
                    problems.append(f"{symbol} {m['meeting']}: {len(missing)} missing bars on {d}")
    for path in sorted(OUT.glob("*.json")):
        body = json.loads(path.read_text())
        values = body.get("values", [])
        stamps = sorted(v["datetime"] for v in values)
        rows.append((path.name, len(values), stamps[0] if stamps else "", stamps[-1] if stamps else "",
                     hashlib.sha256(path.read_bytes()).hexdigest()))
    return problems, rows


def write_readme(rows):
    log = list(csv.DictReader(LOG.open()))
    lines = [
        "# Data",
        "",
        "Nothing in this folder is committed except this README (see `.gitignore`).",
        "Stock prices come from Twelve Data, whose free plan doesn't allow displaying its data publicly.",
        "",
        "- `kalshi/`: E(t) at every hour mark, and the hourly and daily ΔE, built by `kalshi.py` from the EventLens store.",
        "- `twelvedata/`: raw Twelve Data `/time_series` responses, fetched by `fetch_stocks.py`, plus `requests.csv`, its request log.",
        "",
        f"Fetched {log[0]['at'][:10]}: {len(log)} requests, so at most {len(log)} credits.",
        "Times are New York time: the bar's open for 30-minute bars, and the trading date for daily bars.",
        "",
        "| File | Rows | First bar | Last bar | SHA-256 |",
        "|---|---|---|---|---|",
        *[f"| `{name}` | {n} | {first} | {last} | `{sha}` |" for name, n, first, last, sha in rows],
        "",
        "To regenerate: run `python make_env.py`, then `python fetch_stocks.py`. Twelve Data can revise past bars, "
        "so a new fetch may not match these hashes.",
        "",
    ]
    (HERE / "data" / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    if sys.argv[1:] != ["check"]:
        fetch()
    problems, rows = check_and_manifest()
    write_readme(rows)
    print("calendar check:", "ok" if not problems else f"{len(problems)} problems")
    for p in problems:
        print("  ", p)
