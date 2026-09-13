"""Build moving-average alignment signals for the KOSDAQ 150 constituents.

Universe source: the holdings of KODEX 코스닥150 (229200), read from the
FnGuide/Naver ETF page. KRX's own constituent endpoint now requires a login,
and Naver only publishes a constituent list for the KOSPI 200, so the
full-replication ETF's holdings stand in for the index membership. The holdings
come back as names only, so each is resolved to a ticker through Naver's
autocomplete endpoint.

Everything after that is shared with the KOSPI 200 dashboard — see
krx_alignment.py for the pipeline and the output format.

Outputs: data/kosdaq150_tickers.json, data/kosdaq150_signals.json
"""
import json
import re
import sys
import time
import urllib.parse

import requests

import krx_alignment as ka

ETF_CODE = "229200"
HOLDINGS_URL = f"https://navercomp.wisereport.co.kr/v2/ETF/index.aspx?cmp_cd={ETF_CODE}"
AUTOCOMPLETE_URL = "https://ac.stock.naver.com/ac"
CU_DATA_RE = re.compile(r"var CU_data = (\{.*?\});", re.S)
NON_STOCK = {"원화현금"}


def fetch_holdings():
    """Constituent names from the ETF's published creation-unit basket."""
    resp = requests.get(HOLDINGS_URL, headers=ka.HEADERS, timeout=15)
    resp.raise_for_status()
    match = CU_DATA_RE.search(resp.text)
    if not match:
        raise RuntimeError("could not find CU_data in the ETF page")
    rows = json.loads(match.group(1))["grid_data"]
    return [r["STK_NM_KOR"] for r in rows if r["STK_NM_KOR"] not in NON_STOCK]


def resolve_code(name):
    url = f"{AUTOCOMPLETE_URL}?q={urllib.parse.quote(name)}&target=stock"
    data = ka.get_json(url, headers={**ka.HEADERS, "Referer": "https://finance.naver.com/"})
    for item in (data or {}).get("items", []):
        if item.get("name") == name and item.get("typeCode") == "KOSDAQ":
            return item["code"]
    return None


def fetch_universe():
    names = fetch_holdings()
    stocks = {}
    unresolved = []
    for name in names:
        code = resolve_code(name)
        if code:
            stocks[code] = name
        else:
            unresolved.append(name)
        time.sleep(0.1)
    if unresolved:
        print(f"WARN could not resolve tickers for: {unresolved}", file=sys.stderr)
    return stocks


if __name__ == "__main__":
    ka.build("kosdaq150", fetch_universe, min_universe=100)
