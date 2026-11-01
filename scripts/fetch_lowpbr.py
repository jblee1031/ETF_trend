"""거래소 저PBR기업 명단에 현재 주가·시총·연간 실적을 붙여 data/lowpbr.json 을 만든다.

명단 자체(`data/lowpbr_source.json`)는 거래소가 **매년 5월·11월 첫 거래일에만**
갱신하므로 손으로 관리한다. 반대로 주가·시총·PBR은 매일 바뀌므로 이 스크립트가
매일 덧붙인다. 그래서 둘을 파일로 나눠 뒀다.

종목코드는 따로 받아 두지 않고 `fetch_turnover.fetch_market_snapshot()` 이 훑는
전 종목 목록에서 **이름으로 찾는다**. 그 목록에 시장·업종·시총·종가·등락률이 모두
들어 있어서, 151번 따로 조회하는 것보다 싸고 다른 탭과 숫자가 어긋나지 않는다.
이름이 안 맞으면 조용히 빠지는 대신 stderr 로 알린다 — 명단은 거래소 표를 옮겨
적은 것이라 표기가 상장 종목명과 다를 수 있기 때문이다.
"""
import datetime as dt
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import krx_alignment as ka  # noqa: E402
import fetch_turnover as ft  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "lowpbr_source.json"
OUT = ROOT / "data" / "lowpbr.json"

STOCK_URL = "https://m.stock.naver.com/api/stock"
# 연간 실적에서 뽑아 쓰는 줄. 네이버는 억원 단위 문자열로 준다.
WANT_ROWS = ("매출액", "영업이익", "당기순이익", "ROE", "부채비율", "주당배당금")


def norm(name):
    """표기 차이를 흡수한다. 거래소 표는 공백·대소문자가 들쭉날쭉하다."""
    return name.replace(" ", "").replace("&", "&").upper()


def totals(code):
    """현재 PBR·PER·배당수익률 등. 거래소 공표값은 반기 기준이라 현재와 다르다."""
    data = ka.get_json(f"{STOCK_URL}/{code}/integration")
    out = {}
    for info in (data or {}).get("totalInfos") or []:
        out[info.get("code")] = info.get("value")
    desc = {info.get("code"): info.get("valueDesc")
            for info in (data or {}).get("totalInfos") or []}
    return out, desc


def annual(code):
    """최근 '확정된' 연간 실적 한 해치. 컨센서스(isConsensus=Y)는 건너뛴다."""
    data = ka.get_json(f"{STOCK_URL}/{code}/finance/annual")
    info = (data or {}).get("financeInfo") or {}
    titles = [t for t in info.get("trTitleList") or [] if t.get("isConsensus") != "Y"]
    rows = {r.get("title"): r.get("columns") or {} for r in info.get("rowList") or []}
    for title in reversed(titles):                 # 최신 연도부터 거슬러 올라간다
        key = title.get("key")
        got = {}
        for want in WANT_ROWS:
            raw = (rows.get(want) or {}).get(key) or {}
            got[want] = _num(raw.get("value"))
        if got.get("매출액") is not None:          # 숫자가 있는 가장 최근 연도
            got["기준"] = (title.get("title") or "").rstrip(".")
            return got
    return None


def _num(raw):
    if raw in (None, "", "-"):
        return None
    try:
        return float(str(raw).replace(",", ""))
    except ValueError:
        return None


def _pct(raw):
    return _num(str(raw).replace("배", "").replace("%", "").replace("원", "")
                if raw is not None else None)


def main():
    src = json.loads(SRC.read_text(encoding="utf-8"))
    aliases = {norm(k): v for k, v in (src.get("aliases") or {}).items()
               if not k.startswith("_")}

    print("listing the market ...", flush=True)
    trade_date, listed = ft.fetch_market_snapshot()
    ft.apply_overrides(listed)                     # 다른 탭과 같은 업종 분류
    by_name = {}
    for row in listed:
        by_name.setdefault(norm(row["name"]), row)
    print(f"{len(listed)} listed names, trade date {trade_date}", flush=True)

    rows, missing = [], []
    wanted = [(market, name, pbr)
              for market, entries in src["list"].items()
              for name, pbr in entries]
    for i, (market, name, krx_pbr) in enumerate(wanted, 1):
        hit = by_name.get(norm(aliases.get(norm(name), name))) or by_name.get(norm(name))
        if not hit:
            missing.append(f"{market}:{name}")
            continue
        code = hit["code"]
        info, desc = totals(code)
        time.sleep(0.1)
        fin = annual(code)
        time.sleep(0.1)
        rows.append({
            "c": code,
            "n": hit["name"],
            "m": hit["market"],
            "sec": hit["sector"],
            "pbr0": krx_pbr,                       # 거래소 공표값(반기)
            "pbr": _pct(info.get("pbr")),          # 현재 PBR
            "pbrAt": desc.get("pbr"),
            "per": _pct(info.get("per")),
            "dy": _pct(info.get("dividendYieldRatio")),
            "bps": _pct(info.get("bps")),
            "p": hit["close"],
            "r": hit["chg"],
            "cap": hit["cap"],                     # 억원
            "hi52": _pct(info.get("highPriceOf52Weeks")),
            "lo52": _pct(info.get("lowPriceOf52Weeks")),
            "fin": fin,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(wanted)} ...", flush=True)

    if missing:
        print(f"WARN {len(missing)} names did not match a listed stock: "
              f"{', '.join(missing)}", file=sys.stderr)

    rows.sort(key=lambda r: (r["m"] != "KOSPI", r["pbr0"], r["n"]))
    payload = {
        "generated_at": dt.datetime.now(ka.KST).isoformat(),
        "trade_date": trade_date,
        **{k: v for k, v in src.items() if k not in ("list", "aliases", "_comment")},
        "counts": {"KOSPI": sum(1 for r in rows if r["m"] == "KOSPI"),
                   "KOSDAQ": sum(1 for r in rows if r["m"] == "KOSDAQ")},
        "listed": len(wanted),
        "unmatched": missing,
        "rows": rows,
    }
    changed = ka.write_if_changed(OUT, payload, separators=(",", ":"))
    print(f"{'Saved' if changed else 'Unchanged —'} {len(rows)}/{len(wanted)} names, "
          f"{OUT.stat().st_size // 1024} KB")
    if rows:
        cheap = min(rows, key=lambda r: r["pbr0"])
        print(f"  lowest published PBR: {cheap['n']} {cheap['pbr0']}배 "
              f"(현재 {cheap['pbr']}배)")


if __name__ == "__main__":
    main()
