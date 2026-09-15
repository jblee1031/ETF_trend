"""Build moving-average alignment signals for the KOSPI 200 constituents.

Universe source: Naver Finance's KOSPI 200 constituent list, 10 per page.
Everything after that is shared with the KOSDAQ 150 dashboard — see
krx_alignment.py for the pipeline and the output format.

Outputs: data/kospi200_tickers.json, data/kospi200_signals.json
"""
import re
import time

import requests

import krx_alignment as ka

LIST_URL = "https://finance.naver.com/sise/entryJongmok.naver"
ROW_RE = re.compile(r'code=(\w{6})" target="_parent">([^<]+)</a>')


def fetch_universe(max_pages=40):
    stocks = {}
    for page in range(1, max_pages + 1):
        resp = requests.get(LIST_URL, params={"page": page}, headers=ka.HEADERS, timeout=10)
        resp.raise_for_status()
        rows = ROW_RE.findall(resp.content.decode("euc-kr", errors="replace"))
        if not rows:
            break
        for code, name in rows:
            stocks.setdefault(code, name.strip())
        time.sleep(0.15)
    return stocks


if __name__ == "__main__":
    ka.build("kospi200", fetch_universe, min_universe=100,
             index_symbol="KPI200", index_label="코스피200")
