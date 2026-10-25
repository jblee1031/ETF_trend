"""지나간 날짜의 거래대금을 일봉으로 채운다 (한 번만 돌리는 용도).

`fetch_turnover.py`가 쓰는 업종 API는 '오늘'만 준다. 그래서 탭을 처음 열 때
필요한 과거 구간(기본 10/1부터)은 종목마다 일봉을 받아 `종가 × 거래량`으로
추정해 채운다. 3천 종목을 훑으므로 20~30분 걸리고, 이렇게 채운 날은
`exact: false`로 남아 화면에 '추정'으로 표시된다.

이미 들어 있는 `exact: true` 날짜는 건드리지 않는다.
"""
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.parse

import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import krx_alignment as ka  # noqa: E402
import fetch_turnover as ft  # noqa: E402

CANDLES = 40   # 10/1부터면 30거래일이면 충분하지만 여유를 둔다


def candles(code, retries=2):
    params = {"symbol": code, "timeframe": "day", "count": CANDLES, "requestType": 0}
    url = f"{ka.CHART_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=ka.HEADERS, timeout=10)
            resp.raise_for_status()
            return ka.parse_chart_xml(resp.content.decode("euc-kr", errors="replace"))
        except Exception:  # noqa: BLE001
            time.sleep(0.5 + attempt)
    return []


def main():
    out = ft.OUT
    doc = ft.load()
    days = doc.get("days", {})
    exact = {d for d, v in days.items() if v.get("exact")}
    print(f"already exact: {sorted(exact) or '(none)'}")

    print("listing the market ...", flush=True)
    _today, listed = ft.fetch_market_snapshot()
    print(f"{len(listed)} names to walk", flush=True)

    # 종목별 과거 일봉 → 날짜별 거래대금 추정
    per_date = {}
    names = dict(doc.get("names", {}))
    for i, row in enumerate(listed, 1):
        names[row["code"]] = row["name"]
        for candle in candles(row["code"]):
            date = candle["date"]
            if date < ft.FROM or date in exact:
                continue
            if not candle.get("volume") or not candle.get("close"):
                continue
            per_date.setdefault(date, []).append({
                **row,
                "value": candle["close"] * candle["volume"] / 1e8,
                "close": candle["close"],
                "chg": None,          # 일봉만으로는 기준가를 알 수 없다
            })
        if i % 200 == 0:
            print(f"  {i}/{len(listed)} ... {len(per_date)} dates so far", flush=True)
        time.sleep(0.12)

    for date, rows in per_date.items():
        days[date] = {"exact": False, "markets": ft.day_payload(rows)}
    days = {d: v for d, v in days.items() if d >= ft.FROM}

    kept = {c for d in days.values() for m in d["markets"].values()
            for f in m.values()
            for c in ([r["c"] for r in f["top"]]
                      + [code for s in f["sectors"] for code, _ in s[3]])}
    payload = {
        "generated_at": dt.datetime.now(ka.KST).isoformat(),
        "from": ft.FROM,
        "names": {c: names[c] for c in sorted(kept) if c in names},
        "dates": sorted(days),
        "days": days,
    }
    ka.write_if_changed(out, payload, separators=(",", ":"))
    estimated = [d for d, v in days.items() if not v.get("exact")]
    print(f"\nfilled {len(estimated)} estimated days: {sorted(estimated)}")
    print(f"total {len(payload['dates'])} days, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
