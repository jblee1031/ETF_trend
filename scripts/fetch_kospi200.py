"""Build moving-average alignment signals for the KOSPI 200 constituents.

Universe source: the basket of KODEX 200 (069500), a full-replication tracker.
Naver's own KOSPI 200 constituent page was retired on 2026-09-17 (HTTP 410),
so this uses the same ETF-basket route as the KOSDAQ 150 dashboard.

Everything after that is shared — see krx_alignment.py for the pipeline and
the output format.

Outputs: data/kospi200_tickers.json, data/kospi200_signals.json
"""
import krx_alignment as ka


if __name__ == "__main__":
    ka.build("kospi200", lambda: ka.universe_from_etf("069500", "KOSPI"), min_universe=100,
             index_symbol="KPI200", index_label="코스피200")
