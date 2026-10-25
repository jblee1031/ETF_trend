"""코스피·코스닥 종합지수의 일별 종가를 모은다.

증시 일정 탭이 달력 칸마다 그날 지수를 적는 데만 쓴다. 정배열 탭이 쓰는
코스피200·코스닥150 지수와는 다른 지수다(종합지수 전체).

달력은 `data/calendar.json`에 손으로 적는 일정 파일이라, 자동 수집분은
섞지 않고 `data/index_daily.json`에 따로 쓴다.
"""
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import krx_alignment as ka  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "index_daily.json"

# 네이버 차트 심볼. KPI200(코스피200)이 아니라 종합지수다.
SYMBOLS = {"k": ("KOSPI", "코스피"), "q": ("KOSDAQ", "코스닥")}


def main():
    series = {}
    labels = {}
    for key, (symbol, label) in SYMBOLS.items():
        labels[key] = label
        for row in ka.fetch_history(symbol):
            series.setdefault(row["date"], {})[key] = row["close"]

    # 한쪽 지수만 있는 날은 쓰지 않는다 (한 시장만 휴장하는 경우는 없다).
    both = {d: v for d, v in sorted(series.items()) if len(v) == len(SYMBOLS)}
    if not both:
        raise SystemExit("no trading days fetched")

    payload = {
        "generated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(),
        "labels": labels,
        "series": both,
    }
    changed = ka.write_if_changed(OUT, payload, indent=1)
    first, last = min(both), max(both)
    print(f"index_daily: {len(both)} days {first} ~ {last} "
          f"({labels['k']} {both[last]['k']}, {labels['q']} {both[last]['q']}) "
          f"{'written' if changed else 'unchanged'}")


if __name__ == "__main__":
    main()
