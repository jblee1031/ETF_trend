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
CACHE = pathlib.Path(__file__).resolve().parent.parent / ".cache" / "backfill_candles.json"


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


def load_cache():
    """지난 실행이 받아 둔 일봉. 집계 방식만 바꿔 다시 돌릴 때 재사용한다."""
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")


def main():
    out = ft.OUT
    doc = ft.load()
    days = doc.get("days", {})
    exact = {d for d, v in days.items() if v.get("exact")}
    print(f"already exact: {sorted(exact) or '(none)'}")

    print("listing the market ...", flush=True)
    _today, listed = ft.fetch_market_snapshot()
    ft.apply_overrides(listed)          # 다른 탭과 같은 업종 분류를 쓴다
    print(f"{len(listed)} names to walk", flush=True)

    # 종목별 과거 일봉 → 날짜별 거래대금 추정
    cache = load_cache()
    print(f"cached candles for {len(cache)} codes", flush=True)
    per_date = {}
    names = dict(doc.get("names", {}))
    fetched = 0
    for i, row in enumerate(listed, 1):
        names[row["code"]] = row["name"]
        got = cache.get(row["code"])
        if got is None:
            got = [[c["date"], c["close"], c["volume"]] for c in candles(row["code"])]
            cache[row["code"]] = got
            fetched += 1
            time.sleep(0.12)
        # 일봉에는 기준가가 없어 전일 종가 대비로 계산한다. 유상증자·액면분할처럼
        # 기준가가 따로 정해지는 날은 거래소 공시값과 다를 수 있다.
        prev = {}
        last = None
        for date, close, _volume in got:
            if last is not None:
                prev[date] = last
            last = close
        for date, close, volume in got:
            if date < ft.FROM or date in exact or not volume or not close:
                continue
            before = prev.get(date)
            chg = round((close / before - 1) * 100, 2) if before else None
            # 가격제한폭은 ±30%다. 그걸 넘었다면 종가끼리 비교한 탓(증자·분할 등으로
            # 기준가가 따로 정해진 날)이므로, 틀린 숫자를 보여주느니 비워 둔다.
            if chg is not None and abs(chg) > 31:
                chg = None
            per_date.setdefault(date, []).append({
                **row,
                "value": close * volume / 1e8,
                "close": close,
                "chg": chg,
            })
        if i % 200 == 0:
            print(f"  {i}/{len(listed)} ({fetched} fetched) ... "
                  f"{len(per_date)} dates so far", flush=True)
            save_cache(cache)
    save_cache(cache)
    print(f"fetched {fetched}, reused {len(listed) - fetched} from cache", flush=True)

    for date, rows in per_date.items():
        days[date] = {"exact": False, "markets": ft.day_payload(rows)}
    days = {d: v for d, v in days.items() if d >= ft.FROM}

    kept = {c for d in days.values() for block in d["markets"].values()
            for c in ([r["c"] for r in block["top"]]
                      + [code for s in block["sectors"] for code, _ in s[3]])}
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
