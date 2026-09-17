"""Build moving-average alignment signals for the KOSDAQ 150 constituents.

Universe source: the basket of KODEX 코스닥150 (229200), a full-replication
tracker, since the index's own constituent list isn't published openly.

Everything after that is shared with the KOSPI 200 dashboard — see
krx_alignment.py for the pipeline and the output format.

Outputs: data/kosdaq150_tickers.json, data/kosdaq150_signals.json
"""
import krx_alignment as ka


if __name__ == "__main__":
    # Naver's chart endpoint has no KOSDAQ 150 symbol; the composite is the
    # closest benchmark it serves.
    ka.build("kosdaq150", lambda: ka.universe_from_etf("229200", "KOSDAQ"), min_universe=100,
             index_symbol="KOSDAQ", index_label="코스닥 종합",
             index_note="코스닥150 지수는 데이터 소스에서 제공되지 않아 코스닥 종합지수로 대체")
