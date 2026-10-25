"""거래 하루치 전체 시장 거래대금을 모아 data/turnover.json에 쌓는다.

왜 따로 있나
------------
정배열·섹터 탭은 코스피200·코스닥150 구성종목 351개만 본다. 그런데 HTS의
거래대금 상위에는 그 밖의 종목과 ETF도 섞여 들어온다. 그래서 거래대금만은
**상장 전 종목**을 따로 모은다.

네이버 업종 API(`m.stock.naver.com/api/stocks/industry`)는 업종별 종목 목록을
주면서 종목마다 `accumulatedTradingValueRaw`(그날 거래대금, 원)를 함께 준다.
업종 79개를 훑는 데 170여 번이면 끝나므로, 종목마다 일봉을 받는 것보다 훨씬
싸고 **추정이 아니라 거래소가 집계한 값**이다.

한계
----
이 API는 '지금' 상태만 준다. 과거 날짜는 돌려주지 않으므로 하루치씩 모아
쌓는다. 10/1~10/22처럼 이미 지나간 날은 `backfill_turnover.py`가 일봉으로
채우며, 그 날들은 `exact: false`로 표시한다.
"""
import datetime as dt
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import krx_alignment as ka  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "turnover.json"

FROM = "2026-10-01"      # 이 날짜부터 보관한다
TOP = 15                 # 하루에 세우는 상위 종목 수
SECTOR_TOP = 5           # 파레토 막대를 눌렀을 때 보여줄 섹터 내 상위 종목
MAX_DAYS = 120           # 하루 40KB 안팎으로 늘어나므로 6개월쯤에서 끊는다
MARKETS = ("KOSPI", "KOSDAQ")   # 코넥스는 거래대금이 미미해 뺀다
FUND_KINDS = {"etf", "etn"}     # 거래대금 상위에서 빼는 종류
SPAC_MARK = "스팩"              # 기업인수목적회사. 이름으로만 가려낼 수 있다


def fetch_market_snapshot():
    """상장 전 종목의 오늘치 거래대금. (date, rows) 를 돌려준다."""
    groups = {}
    for page in range(1, 20):
        data = ka.get_json(f"{ka.INDUSTRY_URL}?page={page}")
        rows = (data or {}).get("groups") or []
        if not rows:
            break
        before = len(groups)
        for g in rows:
            groups[g["no"]] = g["name"]
        if len(groups) == before:
            break
        time.sleep(0.05)
    if not groups:
        raise RuntimeError("no sector groups returned")

    seen, traded_at = {}, {}
    for no, sector in groups.items():
        for page in range(1, 8):
            data = ka.get_json(f"{ka.INDUSTRY_URL}/{no}?page={page}&pageSize=100")
            stocks = (data or {}).get("stocks") or []
            for s in stocks:
                market = (s.get("stockExchangeType") or {}).get("name")
                if market not in MARKETS:
                    continue
                value = s.get("accumulatedTradingValueRaw")
                if not value:
                    continue
                code = s["itemCode"]
                seen[code] = {
                    "code": code,
                    "name": s.get("stockName") or code,
                    "sector": sector,
                    "market": market,
                    "kind": s.get("stockEndType") or "stock",
                    "value": int(value) / 1e8,                    # 억원
                    "close": _num(s.get("closePriceRaw")),
                    "chg": _num(s.get("fluctuationsRatio")),
                    "cap": _round(_num(s.get("marketValueRaw"), 1e8)),  # 억원
                }
                day = (s.get("localTradedAt") or "")[:10]
                if day:
                    traded_at[day] = traded_at.get(day, 0) + 1
            if len(stocks) < 100:
                break
            time.sleep(0.05)

    if not seen:
        raise RuntimeError("no stocks with turnover returned")
    # 한두 종목이 거래정지 등으로 옛 날짜를 들고 있을 수 있어 최빈값을 쓴다.
    date = max(traded_at, key=lambda d: traded_at[d])
    return date, list(seen.values())


def apply_overrides(rows):
    """다른 탭과 같은 업종 수정(`data/sector_overrides.json`)을 거래대금에도 적용한다.

    적용하지 않으면 SK스퀘어가 섹터 탭에서는 '지주사', 거래대금 탭에서는
    '반도체와반도체장비'로 갈려 보인다.
    """
    index = {r["code"]: r for r in rows}
    sectors = {code: r["sector"] for code, r in index.items()}
    applied = ka.apply_sector_overrides(sectors, {c: r["name"] for c, r in index.items()})
    for code, sector in sectors.items():
        index[code]["sector"] = sector
    return applied


def _round(v):
    return None if v is None else round(v)


def _num(raw, divide=1.0):
    try:
        return round(float(str(raw).replace(",", "")) / divide, 2)
    except (TypeError, ValueError):
        return None


def is_operating_company(row):
    """ETF·ETN·스팩을 뺀다.

    셋 다 거래대금 상위에 자주 올라오지만 사업을 하는 회사가 아니라서,
    "어느 종목에 돈이 몰렸나"를 보는 데 방해가 된다. ETF·ETN은 네이버가
    `stockEndType`으로 구분해 주고, 스팩은 그런 구분이 없어 이름으로
    가려낸다(국내 스팩은 예외 없이 이름에 '스팩'이 들어간다).
    """
    return row["kind"] not in FUND_KINDS and SPAC_MARK not in row["name"]


def summarise(rows, top=TOP, sector_top=SECTOR_TOP):
    """한 시장의 상위 종목과 섹터 합계."""
    rows = sorted(rows, key=lambda r: (-r["value"], r["code"]))
    sectors = {}
    for r in rows:
        agg = sectors.setdefault(r["sector"], [0.0, 0, []])
        agg[0] += r["value"]
        agg[1] += 1
        if len(agg[2]) < sector_top:          # rows가 이미 내림차순이다
            agg[2].append([r["code"], round(r["value"])])
    return {
        "total": round(sum(r["value"] for r in rows)),
        "n": len(rows),
        "top": [{
            "c": r["code"], "s": r["sector"], "k": r["kind"],
            "v": round(r["value"]), "p": r["close"], "r": r["chg"], "cap": r["cap"],
        } for r in rows[:top]],
        "sectors": sorted(([name, round(value), count, members]
                           for name, (value, count, members) in sectors.items()),
                          key=lambda b: (-b[1], b[0])),
    }


def day_payload(rows):
    """시장(KOSPI/KOSDAQ)별 한 묶음."""
    keep = [r for r in rows if is_operating_company(r)]
    return {market: summarise([r for r in keep if r["market"] == market])
            for market in MARKETS}


def load():
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"from": FROM, "names": {}, "days": {}}


def main():
    date, rows = fetch_market_snapshot()
    moved = apply_overrides(rows)
    if moved:
        print(f"sector overrides applied to {moved} names")
    dropped = len(rows) - sum(1 for r in rows if is_operating_company(r))
    print(f"{date}: {len(rows)} listed names across {', '.join(MARKETS)}"
          f" ({dropped} ETF/ETN/스팩 제외)")

    doc = load()
    days = doc.get("days", {})
    days[date] = {"exact": True, "markets": day_payload(rows)}
    days = {d: v for d, v in days.items() if d >= FROM}
    if len(days) > MAX_DAYS:
        days = {d: days[d] for d in sorted(days)[-MAX_DAYS:]}

    names = doc.get("names", {})
    names.update({r["code"]: r["name"] for r in rows})
    kept = {c for d in days.values() for block in d["markets"].values()
            for c in ([r["c"] for r in block["top"]]
                      + [code for s in block["sectors"] for code, _ in s[3]])}

    payload = {
        "generated_at": dt.datetime.now(ka.KST).isoformat(),
        "from": FROM,
        "names": {c: names[c] for c in sorted(kept) if c in names},
        "dates": sorted(days),
        "days": days,
    }
    changed = ka.write_if_changed(OUT, payload, separators=(",", ":"))

    board = days[date]["markets"]
    for market in MARKETS:
        best = board[market]["top"][0]
        print(f"  {market}: {board[market]['total']:,}억 "
              f"({board[market]['n']}종목), 1위 "
              f"{names.get(best['c'], best['c'])} {best['v']:,}억")
    print(f"{'Saved' if changed else 'Unchanged —'} {len(payload['dates'])} days "
          f"({payload['dates'][0]} ~ {payload['dates'][-1]}), "
          f"{OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
