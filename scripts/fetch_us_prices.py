"""Fetch daily close prices for the US stocks/ETFs listed in data/us_groups.json.

Data source: Yahoo Finance chart API (query1/query2.finance.yahoo.com). No API
key required for the basic chart endpoint.

Output: data/us_prices.json (same shape as data/prices.json)
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
GROUPS_PATH = ROOT / "data" / "us_groups.json"
OUTPUT_PATH = ROOT / "data" / "us_prices.json"

RANGE = "6mo"
YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
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


def fetch_history(code, retries=3):
    last_err = None
    for attempt in range(retries):
        host = YAHOO_HOSTS[attempt % len(YAHOO_HOSTS)]
        url = f"https://{host}/v8/finance/chart/{code}?range={RANGE}&interval=1d"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            history = []
            for ts, close in zip(timestamps, closes):
                if close is None:
                    continue
                date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                history.append({"date": date_str, "close": round(close, 4)})
            return history
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {code}: {last_err}")


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
        time.sleep(0.3)  # be polite to yahoo

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
        if not result:
            sys.exit(1)


if __name__ == "__main__":
    main()
