"""Shared pipeline for the KRX moving-average alignment dashboards.

fetch_kospi200.py and fetch_kosdaq150.py each supply a universe (code -> name)
and call build(); everything downstream — prices, moving averages, alignment
snapshots, sector/market-cap enrichment, JSON output — lives here.

Output shape (data/<market>_signals.json):
  {
    "generated_at": "2026-09-13T21:00:00+09:00",
    "universe_size": 201,
    "dates": ["2026-07-16", ..., "2026-09-11"],   # snapshot dates, ascending
    "names":   {"005930": "삼성전자", ...},
    "sectors": {"005930": "반도체와반도체장비", ...},
    "caps":    {"005930": 1548000, ...},          # market cap, 억원
    "snapshots": {
      "2026-09-11": [
        {
          "c": "005930",            # code
          "p": 259500,              # close
          "r": -3.53,               # official pct change vs the exchange base price
          "m": [ma5, ma10, ma20, ma60, ma120],
          "s": 3,                   # consecutive days of 5>10>20 alignment
          "f": 3                    # consecutive days of full alignment (0 = not full)
        },
        ...
      ]
    },
    "chart_dates": [...],
    "series": {"005930": [71200, null, ...]},     # aligned with chart_dates
    "index": {"label": "코스피200", "note": null,
              "dates": [...], "closes": [...]},     # benchmark closes for the summary
    "market": {                                    # whole universe, not just aligned rows
      "2026-09-11": {
        "adv": 48, "dec": 149, "flat": 3, "median": -1.19,
        "gainers": [["000000", 7.73], ...],        # top 5 by daily change
        "losers":  [["000000", -8.32], ...],
        "sectors": [["전기제품", 5, 3.4], ...]      # [name, members, cap-weighted change], best first
      }
    }
  }

A row exists only when 5>10>20 holds; "f" > 0 marks the full 5-line alignment.
"series" covers just the stocks that reach full alignment at least once.
"""
import json
import re
import statistics
import sys
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

MA_WINDOWS = [5, 10, 20, 60, 120]
TEMPLATE_WINDOWS = [50, 150, 200]   # Minervini's trend template uses these
SNAPSHOT_DAYS = 40     # trading days of signal history to publish (~2 months)
CHART_DAYS = 110       # close prices kept for the trend chart; covers a 3-month
                       # window even when the oldest snapshot date is selected
SLOPE_LOOKBACK = 22    # ~1 month, for "is the 200-day average still rising"
WEEKS52 = 250          # trading days standing in for a 52-week window
# Enough history that MA200 exists SLOPE_LOOKBACK days before the oldest
# snapshot date: 200 + 22 + 40, plus slack for holidays and halts.
HISTORY_POINTS = 300

CHART_URL = "https://fchart.stock.naver.com/sise.nhn"
INDUSTRY_URL = "https://m.stock.naver.com/api/stocks/industry"
HEADERS = {"User-Agent": "Mozilla/5.0 (ETF-Trend-Dashboard data fetcher)"}
MOBILE_HEADERS = {**HEADERS, "Referer": "https://m.stock.naver.com/"}
KST = timezone(timedelta(hours=9))

HOLDINGS_URL = "https://navercomp.wisereport.co.kr/v2/ETF/index.aspx?cmp_cd={code}"
AUTOCOMPLETE_URL = "https://ac.stock.naver.com/ac"
CU_DATA_RE = re.compile(r"var CU_data = (\{.*?\});", re.S)
NON_STOCK = {"원화현금"}


def etf_holdings(etf_code, retries=3):
    """Stock names in an ETF's published creation-unit basket."""
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(HOLDINGS_URL.format(code=etf_code), headers=HEADERS, timeout=20)
            resp.raise_for_status()
            match = CU_DATA_RE.search(resp.text)
            if not match:
                raise RuntimeError("could not find CU_data in the ETF page")
            rows = json.loads(match.group(1))["grid_data"]
            return [r["STK_NM_KOR"] for r in rows if r["STK_NM_KOR"] not in NON_STOCK]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(3 + attempt * 5)
    raise RuntimeError(f"holdings for {etf_code} unavailable: {last_err}")


def universe_from_etf(etf_code, market_type):
    """Index membership read from a full-replication tracker ETF.

    Neither exchange nor portal publishes the constituent lists openly any
    more — KRX requires a login and Naver retired its KOSPI 200 page (HTTP 410,
    2026-09-17) — but the tracker ETFs still publish their baskets. The basket
    only has names, so each is resolved to a ticker through Naver's
    autocomplete, restricted to the index's own market to avoid homonyms.
    """
    stocks = {}
    unresolved = []
    for name in etf_holdings(etf_code):
        url = f"{AUTOCOMPLETE_URL}?q={urllib.parse.quote(name)}&target=stock"
        data = get_json(url, headers={**HEADERS, "Referer": "https://finance.naver.com/"})
        hits = [i for i in (data or {}).get("items", [])
                if i.get("name") == name and i.get("typeCode") == market_type]
        if hits:
            stocks[hits[0]["code"]] = name
        else:
            unresolved.append(name)
        time.sleep(0.1)
    if unresolved:
        print(f"WARN could not resolve tickers for: {unresolved}", file=sys.stderr)
    return stocks


def get_json(url, headers=MOBILE_HEADERS, timeout=10):
    """GET returning parsed JSON, or None — these endpoints answer with HTML past the last page."""
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        return resp.json() if resp.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


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


def fetch_sector_and_cap():
    """Map every listed KRX stock to its sector name and market cap (억원).

    Naver groups the market into ~79 WICS sectors; walking each sector's member
    list is far cheaper than asking per stock, and the member rows carry the
    market cap too.
    """
    groups = {}
    for page in range(1, 20):
        data = get_json(f"{INDUSTRY_URL}?page={page}")
        rows = (data or {}).get("groups") or []
        if not rows:
            break
        before = len(groups)
        for g in rows:
            groups[g["no"]] = g["name"]
        if len(groups) == before:
            break
        time.sleep(0.1)

    sectors, caps = {}, {}
    for no, name in groups.items():
        for page in range(1, 8):
            data = get_json(f"{INDUSTRY_URL}/{no}?page={page}&pageSize=100")
            stocks = (data or {}).get("stocks") or []
            for s in stocks:
                sectors[s["itemCode"]] = name
                cap = (s.get("marketValue") or "").replace(",", "")
                if cap.isdigit():
                    caps[s["itemCode"]] = int(cap)
            if len(stocks) < 100:
                break
            time.sleep(0.05)
        time.sleep(0.05)
    return sectors, caps


def moving_averages(closes, windows=None):
    """Rolling means for every window, as lists aligned with `closes` (None until warm)."""
    out = {}
    for window in windows or MA_WINDOWS:
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


def relative_strength_raw(closes, i):
    """IBD-style weighted price performance, the input to the RS percentile.

    raw = 0.4*r(63) + 0.2*r(126) + 0.2*r(189) + 0.2*r(252), where r(n) is the
    return over the last n trading days. Quarters that predate the stock's
    history are dropped and the remaining weights renormalised.
    """
    spans = [(63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2)]
    total = 0.0
    weight_sum = 0.0
    for span, weight in spans:
        j = i - span
        if j < 0 or not closes[j]:
            continue
        total += weight * (closes[i] / closes[j] - 1)
        weight_sum += weight
    return total / weight_sum if weight_sum else None


def template_metrics(history):
    """Per-date Minervini trend-template inputs for one stock, keyed by date.

    Stores the raw measurements only; the pass/fail count and the RS percentile
    need the whole universe, so they are finished in build().
    """
    dates = [d for d, _ in history]
    closes = [c for _, c in history]
    mas = moving_averages(closes, TEMPLATE_WINDOWS)

    out = {}
    for i, date in enumerate(dates):
        ma50, ma150, ma200 = (mas[w][i] for w in TEMPLATE_WINDOWS)
        if None in (ma50, ma150, ma200):
            continue
        prior = mas[200][i - SLOPE_LOOKBACK] if i >= SLOPE_LOOKBACK else None
        if not prior:
            continue

        window = [c for c in closes[max(0, i - WEEKS52 + 1):i + 1] if c]
        high52, low52 = max(window), min(window)
        close = closes[i]

        out[date] = {
            "close": close,
            "ma50": ma50,
            "ma150": ma150,
            "ma200": ma200,
            "slope": (ma200 / prior - 1) * 100,
            "above_low": (close / low52 - 1) * 100,
            "below_high": (1 - close / high52) * 100,
            "rs_raw": relative_strength_raw(closes, i),
        }
    return out


def template_checks(m, rs):
    """The eight trend-template conditions, in Minervini's order."""
    return [
        m["close"] > m["ma150"] and m["close"] > m["ma200"],
        m["ma150"] > m["ma200"],
        m["slope"] > 0,
        m["ma50"] > m["ma150"] and m["ma50"] > m["ma200"],
        m["close"] > m["ma50"],
        m["above_low"] >= 30,
        m["below_high"] <= 25,
        rs is not None and rs >= 70,
    ]


def write_if_changed(path, payload, **dump_kwargs):
    """Write JSON unless the file already holds the same data.

    generated_at is ignored in the comparison: the workflow retries several
    times a day, and a timestamp-only change would otherwise commit each time.
    """
    def body(d):
        return {k: v for k, v in d.items() if k != "generated_at"}

    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                if body(json.load(f)) == body(payload):
                    return False
        except ValueError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, **dump_kwargs)
    return True


def save_universe(path, universe):
    # Sorted by code: the sources list by market cap or weight, which reshuffles
    # daily and would bury real index changes in the git history.
    write_if_changed(
        path,
        {
            "generated_at": datetime.now(KST).isoformat(),
            "tickers": [{"code": c, "name": n} for c, n in sorted(universe.items())],
        },
        indent=2,
    )


def load_universe(path):
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return {t["code"]: t["name"] for t in json.load(f)["tickers"]}


INDEX_POINTS = 170   # 120-day MA and a 60-day window, even at the oldest snapshot date


def fetch_index(symbol, label, note):
    try:
        history = fetch_history(symbol)[-INDEX_POINTS:]
    except Exception as exc:  # noqa: BLE001
        print(f"WARN index {symbol} unavailable: {exc}", file=sys.stderr)
        return None
    if not history:
        print(f"WARN index {symbol} returned no data", file=sys.stderr)
        return None
    return {
        "label": label,
        "note": note,
        "dates": [d for d, _ in history],
        "closes": [c for _, c in history],
    }


PRICE_LIST_URL = "https://m.stock.naver.com/api/stock/{code}/price?pageSize=60&page=1"


def daily_changes(history, code):
    """Daily % change per date, measured against the exchange's base price.

    The base price is normally the previous close, so close-to-close is the
    fallback. But the exchange occasionally sets it differently (on 2026-09-15
    it differed for nearly every stock), and then close-to-close disagrees with
    the official change and even breaks the ±30% price limit. Naver's daily
    price list carries the official change for the last 60 sessions.
    """
    changes = {
        history[i][0]: (history[i][1] / history[i - 1][1] - 1) * 100
        for i in range(1, len(history))
        if history[i - 1][1]
    }
    rows = get_json(PRICE_LIST_URL.format(code=code))
    if not isinstance(rows, list):
        print(f"WARN {code}: official daily changes unavailable, using close-to-close", file=sys.stderr)
        return changes
    for r in rows:
        try:
            changes[r["localTradedAt"][:10]] = float(r["fluctuationsRatio"])
        except (KeyError, TypeError, ValueError):
            continue
    return changes


def market_day(date, per_stock, sectors, caps):
    """Breadth, top movers and sector moves for the whole universe on one date.

    Sector moves are weighted by the latest market cap rather than each day's,
    which is close enough over a 40-day window and avoids a cap history.
    """
    moves = {c: s["chg"][date] for c, s in per_stock.items() if date in s["chg"]}
    if not moves:
        return None
    values = list(moves.values())
    # Ties broken by code so the result doesn't depend on universe order, which
    # differs between a fresh ETF basket and the saved fallback list.
    rising = sorted(moves.items(), key=lambda kv: (-kv[1], kv[0]))
    falling = sorted(moves.items(), key=lambda kv: (kv[1], kv[0]))

    groups = {}
    for code, move in moves.items():
        groups.setdefault(sectors.get(code, "기타"), []).append((code, move))
    sector_moves = []
    for name, members in groups.items():
        if len(members) < 2:
            continue
        weight = sum(caps.get(c, 0) for c, _ in members)
        if weight:
            avg = sum(m * caps.get(c, 0) for c, m in members) / weight
        else:
            avg = sum(m for _, m in members) / len(members)
        sector_moves.append([name, len(members), round(avg, 2)])
    sector_moves.sort(key=lambda s: (-s[2], s[0]))

    return {
        "adv": sum(1 for v in values if v > 0),
        "dec": sum(1 for v in values if v < 0),
        "flat": sum(1 for v in values if v == 0),
        "median": round(statistics.median(values), 2),
        "gainers": [[c, round(v, 2)] for c, v in rising[:5] if v > 0],
        "losers": [[c, round(v, 2)] for c, v in falling[:5] if v < 0],
        "sectors": sector_moves,
    }


def build(market, fetch_universe, min_universe, index_symbol, index_label, index_note=None):
    """Run the whole pipeline for one market and write its two data files."""
    tickers_path = DATA_DIR / f"{market}_tickers.json"
    signals_path = DATA_DIR / f"{market}_signals.json"

    try:
        universe = fetch_universe()
        if len(universe) < min_universe:
            raise RuntimeError(f"universe looks truncated ({len(universe)} names)")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN universe fetch failed ({exc}); falling back to saved list", file=sys.stderr)
        universe = load_universe(tickers_path)
        if not universe:
            print("FATAL no universe available", file=sys.stderr)
            sys.exit(1)
    else:
        save_universe(tickers_path, universe)

    print(f"Universe: {len(universe)} stocks")

    sectors, caps = fetch_sector_and_cap()
    print(f"Sector map: {len(sectors)} stocks across the market")

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
            time.sleep(0.15)
            changes = daily_changes(history, code)
            for date, row in rows.items():
                if date in changes:
                    row["r"] = round(changes[date], 2)
            all_dates.update(dates)
            per_stock[code] = {
                "rows": rows,
                "closes": dict(history),
                "template": template_metrics(history),
                "chg": changes,
            }
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
        # RS is a rank within the universe, so every stock's raw performance on
        # this date has to be collected before any single row can be scored.
        raws = sorted(
            m["rs_raw"]
            for s in per_stock.values()
            for m in [s["template"].get(date)]
            if m and m["rs_raw"] is not None
        )

        def rs_percentile(raw):
            if raw is None or not raws:
                return None
            below = sum(1 for v in raws if v < raw)
            return round(below / len(raws) * 99)

        rows = []
        for code, stock in per_stock.items():
            row = stock["rows"].get(date)
            if not row:
                continue
            row = {"c": code, **row}
            metrics = stock["template"].get(date)
            if metrics:
                rs = rs_percentile(metrics["rs_raw"])
                checks = template_checks(metrics, rs)
                row["t"] = {
                    "n": sum(checks),
                    "k": [int(c) for c in checks],
                    "rs": rs,
                    "lo": round(metrics["above_low"], 1),
                    "hi": round(metrics["below_high"], 1),
                    "sl": round(metrics["slope"], 2),
                }
            rows.append(row)
            if row["f"]:
                charted.add(code)
        rows.sort(key=lambda r: (-r["f"], -r["s"], r["c"]))
        snapshots[date] = rows

    output = {
        "generated_at": datetime.now(KST).isoformat(),
        "universe_size": len(universe),
        "dates": snapshot_dates,
        "names": {code: universe[code] for code in per_stock},
        "sectors": {code: sectors[code] for code in per_stock if code in sectors},
        "caps": {code: caps[code] for code in per_stock if code in caps},
        "snapshots": snapshots,
        "chart_dates": chart_dates,
        "series": {
            code: [per_stock[code]["closes"].get(d) for d in chart_dates]
            for code in sorted(charted)
        },
        "index": fetch_index(index_symbol, index_label, index_note),
        "market": {date: market_day(date, per_stock, sectors, caps) for date in snapshot_dates},
    }
    changed = write_if_changed(signals_path, output, separators=(",", ":"))

    latest = snapshot_dates[-1]
    short_n = len(snapshots[latest])
    full_n = sum(1 for r in snapshots[latest] if r["f"])
    missing_sector = [c for c in per_stock if c not in sectors]
    verb = "Saved" if changed else "Unchanged —"
    print(f"\n{verb} {len(snapshot_dates)} snapshot dates in {signals_path}")
    print(f"Latest {latest}: {short_n} short-aligned, {full_n} fully aligned")
    print(f"Chart series: {len(output['series'])} stocks x {len(chart_dates)} days")
    if missing_sector:
        print(f"No sector for: {missing_sector}", file=sys.stderr)
    if failures:
        print(f"Failed/skipped tickers: {failures}", file=sys.stderr)
