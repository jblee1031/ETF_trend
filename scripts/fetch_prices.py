"""Fetch daily close prices for the ETFs listed in data/groups.json.

Data source: Naver Finance chart API (fchart.stock.naver.com). Works for both
plain numeric KRX tickers and the alphanumeric issue codes used by some newer
spot/commodity ETFs (e.g. 0072R0).

Output: data/prices.json
{
  "generated_at": "2026-08-23T15:40:12+09:00",
  "tickers": {
    "252670": {
      "name": "KODEX 200선물인버스2X",
      "history": [{"date": "2026-05-20", "close": 82}, ...]   # ascending by date
    },
    ...
  }
}
"""
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
GROUPS_PATH = ROOT / "data" / "groups.json"
OUTPUT_PATH = ROOT / "data" / "prices.json"

HISTORY_POINTS = 120  # trading days of history to keep (~roughly 5-6 months)
NAVER_CHART_URL = "https://fchart.stock.naver.com/sise.nhn"
HEADERS = {"User-Agent": "Mozilla/5.0 (ETF-Trend-Dashboard data fetcher)"}
KST = timezone(timedelta(hours=9))


def load_groups():
    with GROUPS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def unique_tickers(groups):
    seen = {}
    for group in groups:
        for t in group["tickers"]:
            seen[t["code"]] = t["name"]
    return seen


def fetch_history(code, count=HISTORY_POINTS, retries=3):
    params = {
        "symbol": code,
        "timeframe": "day",
        "count": count,
        "requestType": 0,
    }
    url = f"{NAVER_CHART_URL}?{urllib.parse.urlencode(params)}"
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            text = resp.content.decode("euc-kr", errors="replace")
            return parse_chart_xml(text)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {code}: {last_err}")


def parse_chart_xml(text):
    """Pull out date/close pairs from the <item data="date|open|high|low|close|volume" /> tags."""
    history = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("<item"):
            continue
        start = line.find('data="')
        if start == -1:
            continue
        start += len('data="')
        end = line.find('"', start)
        fields = line[start:end].split("|")
        if len(fields) < 5:
            continue
        raw_date, _open, _high, _low, close = fields[:5]
        if not raw_date or not close:
            continue
        try:
            close_val = float(close)
        except ValueError:
            continue
        date_str = f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        history.append({"date": date_str, "close": close_val})
    return history


def main():
    groups = load_groups()
    tickers = unique_tickers(groups)

    result = {}
    failures = []
    for code, name in tickers.items():
        try:
            history = fetch_history(code)
            if not history:
                failures.append(code)
                continue
            result[code] = {"name": name, "history": history}
            print(f"OK   {code} {name} ({len(history)} points)")
        except Exception as exc:  # noqa: BLE001
            failures.append(code)
            print(f"FAIL {code} {name}: {exc}", file=sys.stderr)
        time.sleep(0.3)  # be polite to naver

    output = {
        "generated_at": datetime.now(KST).isoformat(),
        "tickers": result,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(result)} tickers to {OUTPUT_PATH}")
    if failures:
        print(f"Failed tickers: {failures}", file=sys.stderr)
        # Don't fail the whole run for a handful of bad tickers; only fail
        # hard if nothing at all came back.
        if not result:
            sys.exit(1)


if __name__ == "__main__":
    main()
