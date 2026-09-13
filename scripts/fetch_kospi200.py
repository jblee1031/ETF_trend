"""Build moving-average alignment signals for the KOSPI 200 constituents.

Data sources (both Naver Finance, no API key needed):
  - constituent list: finance.naver.com/sise/entryJongmok.naver (paginated, 10/page)
  - daily closes:     fchart.stock.naver.com/sise.nhn (same endpoint as fetch_prices.py)

Every run recomputes the whole snapshot history from raw prices, so a skipped or
failed run leaves no permanent gap in the output.

Outputs:
  data/kospi200_tickers.json  - the constituent list as of this run (also the
                                fallback universe if the list page ever breaks)
  data/kospi200_signals.json  - per-date lists of stocks in bullish MA alignment:
    {
      "generated_at": "2026-09-13T18:20:00+09:00",
      "universe_size": 201,
      "dates": ["2026-06-18", ..., "2026-09-11"],   # snapshot dates, ascending
      "names": {"005930": "삼성전자", ...},
      "snapshots": {
        "2026-09-11": [
          {
            "c": "005930",              # code
            "p": 259500,                # close
            "r": -3.53,                 # pct change vs previous close
            "m": [ma5, ma10, ma20, ma60, ma120],
            "s": 3,                     # consecutive days of 5>10>20 alignment
            "f": 3                      # consecutive days of the full 5-MA alignment (0 = not full)
          },
          ...
        ]
      },
      "chart_dates": ["2026-03-14", ..., "2026-09-11"],
      "series": {"005930": [71200, null, 71900, ...]}   # aligned with chart_dates
    }

  A row is present when 5>10>20 holds; "f" > 0 marks the full 5-line alignment.
  "series" carries close prices for the trend chart and only covers stocks that
  reach full alignment on at least one snapshot date.
"""
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TICKERS_PATH = ROOT / "data" / "kospi200_tickers.json"
SIGNALS_PATH = ROOT / "data" / "kospi200_signals.json"

MA_WINDOWS = [5, 10, 20, 60, 120]
HISTORY_POINTS = 260   # trading days to pull; needs >= max(MA) + SNAPSHOT_DAYS
SNAPSHOT_DAYS = 60     # trading days of signal history to publish
CHART_DAYS = 130       # trading days of close prices to publish for the trend chart

LIST_URL = "https://finance.naver.com/sise/entryJongmok.naver"
CHART_URL = "https://fchart.stock.naver.com/sise.nhn"
HEADERS = {"User-Agent": "Mozilla/5.0 (ETF-Trend-Dashboard data fetcher)"}
KST = timezone(timedelta(hours=9))

ROW_RE = re.compile(r'code=(\w{6})" target="_parent">([^<]+)</a>')


def fetch_universe(max_pages=40):
    """Scrape the KOSPI 200 constituent list, one page at a time until it runs dry."""
    stocks = {}
    for page in range(1, max_pages + 1):
        resp = requests.get(LIST_URL, params={"page": page}, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        rows = ROW_RE.findall(resp.content.decode("euc-kr", errors="replace"))
        if not rows:
            break
        for code, name in rows:
            stocks.setdefault(code, name.strip())
        time.sleep(0.15)
    return stocks


def load_saved_universe():
    if not TICKERS_PATH.exists():
        return None
    with TICKERS_PATH.open("r", encoding="utf-8") as f:
        saved = json.load(f)
    return {t["code"]: t["name"] for t in saved["tickers"]}


def fetch_history(code, retries=3):
    params = {"symbol": code, "timeframe": "day", "count": HISTORY_POINTS, "requestType": 0}
    url = f"{CHART_URL}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            return parse_chart_xml(resp.content.decode("euc-kr", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {code}: {last_err}")


def parse_chart_xml(text):
    """Pull date/close pairs out of <item data="date|open|high|low|close|volume" /> tags."""
    history = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("<item"):
            continue
        start = line.find('data="')
        if start == -1:
            continue
        start += len('data="')
        fields = line[start:line.find('"', start)].split("|")
        if len(fields) < 5:
            continue
        raw_date, _open, _high, _low, close = fields[:5]
        if not raw_date or not close:
            continue
        try:
            close_val = float(close)
        except ValueError:
            continue
        history.append((f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}", close_val))
    return history


def moving_averages(closes):
    """Rolling means for every window, as lists aligned with `closes` (None until warm)."""
    out = {}
    for window in MA_WINDOWS:
        series = []
        total = 0.0
        for i, close in enumerate(closes):
            total += close
            if i >= window:
                total -= closes[i - window]
            series.append(total / window if i >= window - 1 else None)
        out[window] = series
    return out


def build_rows(history):
    """Per-date alignment rows for one stock, keyed by date.

    Short alignment is MA5 > MA10 > MA20; full alignment additionally requires
    MA20 > MA60 > MA120. Streaks count consecutive trading days each condition
    has held, ending on that date.
    """
    dates = [d for d, _ in history]
    closes = [c for _, c in history]
    mas = moving_averages(closes)

    rows = {}
    short_streak = 0
    full_streak = 0
    for i, date in enumerate(dates):
        values = [mas[w][i] for w in MA_WINDOWS]
        ma5, ma10, ma20, ma60, ma120 = values

        short_ok = None not in (ma5, ma10, ma20) and ma5 > ma10 > ma20
        full_ok = short_ok and None not in (ma60, ma120) and ma20 > ma60 > ma120

        short_streak = short_streak + 1 if short_ok else 0
        full_streak = full_streak + 1 if full_ok else 0
        if not short_ok:
            continue

        prev = closes[i - 1] if i > 0 else None
        rows[date] = {
            "p": round(closes[i], 2),
            "r": round((closes[i] / prev - 1) * 100, 2) if prev else None,
            "m": [round(v) if v is not None else None for v in values],
            "s": short_streak,
            "f": full_streak,
        }
    return dates, rows


def main():
    try:
        universe = fetch_universe()
        if len(universe) < 100:
            raise RuntimeError(f"constituent list looks truncated ({len(universe)} names)")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN constituent list fetch failed ({exc}); falling back to saved list", file=sys.stderr)
        universe = load_saved_universe()
        if not universe:
            print("FATAL no constituent list available", file=sys.stderr)
            sys.exit(1)
    else:
        TICKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TICKERS_PATH.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "generated_at": datetime.now(KST).isoformat(),
                    "tickers": [{"code": c, "name": n} for c, n in universe.items()],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    print(f"Universe: {len(universe)} stocks")

    all_dates = set()
    per_stock = {}
    failures = []
    for code, name in universe.items():
        try:
            history = fetch_history(code)
            if len(history) < max(MA_WINDOWS):
                failures.append(code)
                print(f"SKIP {code} {name}: only {len(history)} points", file=sys.stderr)
                continue
            dates, rows = build_rows(history)
            all_dates.update(dates)
            per_stock[code] = {"rows": rows, "closes": dict(history)}
            print(f"OK   {code} {name} ({len(rows)} aligned days)")
        except Exception as exc:  # noqa: BLE001
            failures.append(code)
            print(f"FAIL {code} {name}: {exc}", file=sys.stderr)
        time.sleep(0.3)  # be polite to naver

    if not per_stock:
        print("FATAL no price history collected", file=sys.stderr)
        sys.exit(1)

    sorted_dates = sorted(all_dates)
    snapshot_dates = sorted_dates[-SNAPSHOT_DAYS:]
    chart_dates = sorted_dates[-CHART_DAYS:]

    snapshots = {}
    charted = set()
    for date in snapshot_dates:
        rows = []
        for code, stock in per_stock.items():
            row = stock["rows"].get(date)
            if row:
                rows.append({"c": code, **row})
                if row["f"]:
                    charted.add(code)
        rows.sort(key=lambda r: (-r["f"], -r["s"], r["c"]))
        snapshots[date] = rows

    series = {
        code: [per_stock[code]["closes"].get(d) for d in chart_dates]
        for code in sorted(charted)
    }

    output = {
        "generated_at": datetime.now(KST).isoformat(),
        "universe_size": len(universe),
        "dates": snapshot_dates,
        "names": {code: universe[code] for code in per_stock},
        "snapshots": snapshots,
        "chart_dates": chart_dates,
        "series": series,
    }
    SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SIGNALS_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))

    latest = snapshot_dates[-1]
    short_n = len(snapshots[latest])
    full_n = sum(1 for r in snapshots[latest] if r["f"])
    print(f"\nSaved {len(snapshot_dates)} snapshot dates to {SIGNALS_PATH}")
    print(f"Latest {latest}: {short_n} short-aligned, {full_n} fully aligned")
    print(f"Chart series: {len(series)} stocks x {len(chart_dates)} days")
    if failures:
        print(f"Failed/skipped tickers: {failures}", file=sys.stderr)


if __name__ == "__main__":
    main()
