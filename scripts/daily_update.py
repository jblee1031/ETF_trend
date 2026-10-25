"""One-command daily update: collect Korea data, verify, push, confirm live.

Exists so the scheduled task runs a single fixed command. The old task issued a
dozen different shell commands, each needing its own permission rule — and the
commit message carried the date, so a new rule was needed every day and the
unattended run stalled on the prompt.

Usage: python scripts/daily_update.py [--skip-live]

Prints a compact machine-readable summary; exit code 0 = nothing to do or
success, 1 = failed before pushing, 2 = pushed but the live site lagged.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import krx_alignment as ka  # noqa: E402

MARKETS = ["kospi200", "kosdaq150"]
DATA_FILES = ["data/prices.json",
              "data/kospi200_signals.json", "data/kosdaq150_signals.json",
              "data/kospi200_sectors.json", "data/kosdaq150_sectors.json",
              "data/index_daily.json",
              "data/kospi200_turnover.json", "data/kosdaq150_turnover.json"]
LIVE = "https://jblee1031.github.io/ETF_trend/data/"
COLLECTORS = ["fetch_prices.py", "fetch_kospi200.py", "fetch_kosdaq150.py",
              "fetch_index_daily.py"]
BELLWETHER = "005930"  # Samsung Electronics, for "is there a newer trading day"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def git(*args, check=True):
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and done.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def published_date(market):
    with (ROOT / f"data/{market}_signals.json").open(encoding="utf-8") as f:
        return json.load(f)["dates"][-1]


def collect(log_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with log_path.open("w", encoding="utf-8") as log:
        for script in COLLECTORS:
            done = subprocess.run([sys.executable, "-u", f"scripts/{script}"],
                                  cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            if done.returncode:
                return script
    return None


def verify(trading_day):
    """Returns (ok, problems, stats)."""
    problems = []
    stats = {}

    with (ROOT / "data/prices.json").open(encoding="utf-8") as f:
        prices = json.load(f)
    etf_dates = {t["history"][-1]["date"] for t in prices["tickers"].values()}
    if etf_dates != {trading_day}:
        problems.append(f"ETF latest dates {sorted(etf_dates)} != {trading_day}")
    stats["etf_tickers"] = len(prices["tickers"])

    for market, floor in zip(MARKETS, (150, 100)):
        with (ROOT / f"data/{market}_signals.json").open(encoding="utf-8") as f:
            d = json.load(f)
        last, prev = d["dates"][-1], d["dates"][-2]
        rows, before = d["snapshots"][last], d["snapshots"][prev]
        market_day = d["market"][last]
        closes = d["index"]["closes"]

        if last != trading_day:
            problems.append(f"{market} latest {last} != {trading_day}")
        if len(d["dates"]) != 40:
            problems.append(f"{market} has {len(d['dates'])} snapshot dates, expected 40")
        if d["universe_size"] < floor:
            problems.append(f"{market} universe only {d['universe_size']}")
        if not len(d["names"]) == len(d["sectors"]) == len(d["caps"]):
            problems.append(f"{market} names/sectors/caps mismatch: "
                            f"{len(d['names'])}/{len(d['sectors'])}/{len(d['caps'])}")
        extreme = [(c, v) for day in d["dates"]
                   for c, v in d["market"][day]["gainers"] + d["market"][day]["losers"]
                   if abs(v) > 30.01]
        if extreme:
            problems.append(f"{market} daily moves beyond ±30%: {extreme[:3]}")

        stats[market] = {
            "short": len(rows), "short_prev": len(before),
            "full": sum(1 for r in rows if r["f"]),
            "full_prev": sum(1 for r in before if r["f"]),
            "mv8": sum(1 for r in rows if r.get("t", {}).get("n") == 8),
            "adv": market_day["adv"], "dec": market_day["dec"], "flat": market_day["flat"],
            "median": market_day["median"],
            "index": round(closes[-1], 2),
            "index_chg": round((closes[-1] / closes[-2] - 1) * 100, 2),
            "best": market_day["sectors"][0], "worst": market_day["sectors"][-1],
            "universe": d["universe_size"],
        }
    return not problems, problems, stats


def commit_and_push(trading_day):
    git("add", *DATA_FILES)
    if not git("diff", "--cached", "--quiet", check=False).returncode:
        return None  # nothing staged
    git("commit", "-q", "-m",
        f"chore: update Korea data ({trading_day}, scheduled local run)\n\n"
        "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>")
    for attempt in range(3):
        git("fetch", "-q", "origin")
        if git("pull", "-q", "--rebase", "--autostash", "origin", "main", check=False).returncode == 0 \
                and git("push", "origin", "main", check=False).returncode == 0:
            return git("rev-parse", "--short", "HEAD").stdout.strip()
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("push failed after 3 attempts")


def live_is_current(trading_day):
    for name, key in (("prices.json", "etf"), ("kospi200_signals.json", None),
                      ("kosdaq150_signals.json", None)):
        try:
            with urllib.request.urlopen(f"{LIVE}{name}?n={time.time()}", timeout=15) as resp:
                d = json.load(resp)
        except Exception:  # noqa: BLE001
            return False
        latest = (max(t["history"][-1]["date"] for t in d["tickers"].values())
                  if key == "etf" else d["dates"][-1])
        if latest != trading_day:
            return False
    return True


def main():
    skip_live = "--skip-live" in sys.argv
    git("fetch", "-q", "origin")
    git("pull", "-q", "--rebase", "--autostash", "origin", "main")

    trading_day = ka.fetch_history(BELLWETHER)[-1]["date"]
    current = min(published_date(m) for m in MARKETS)
    if trading_day <= current:
        print(f"RESULT: up-to-date | trading_day={trading_day} | published={current}")
        return 0

    log_path = Path(tempfile.gettempdir()) / "etf_daily_update.log"
    print(f"collecting {trading_day} (published {current}); log: {log_path}", flush=True)
    failed = collect(log_path)
    if failed:
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
        print(f"RESULT: failed | step={failed}")
        print("\n".join(tail))
        return 1

    warnings = [l for l in log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                if l.startswith("WARN")]
    ok, problems, stats = verify(trading_day)
    if not ok:
        print(f"RESULT: failed | step=verify | not pushed")
        for p in problems:
            print(f"  PROBLEM {p}")
        return 1

    commit = commit_and_push(trading_day)
    for w in warnings:
        print(f"  WARN {w[5:].strip()}")
    print(f"RESULT: {'pushed' if commit else 'no-change'} | trading_day={trading_day} "
          f"| commit={commit or '-'} | etf_tickers={stats['etf_tickers']}")
    for market in MARKETS:
        s = stats[market]
        print(f"  {market} universe={s['universe']} short={s['short']} (prev {s['short_prev']}) "
              f"full={s['full']} (prev {s['full_prev']}) mv8={s['mv8']} "
              f"adv={s['adv']} dec={s['dec']} flat={s['flat']} median={s['median']} "
              f"index={s['index']} ({s['index_chg']:+}%) best={s['best']} worst={s['worst']}")

    if skip_live or not commit:
        return 0
    for _ in range(18):
        if live_is_current(trading_day):
            print("LIVE: ok")
            return 0
        time.sleep(30)
    print("LIVE: still lagging after 9 minutes (GitHub Pages deploy is slow)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
