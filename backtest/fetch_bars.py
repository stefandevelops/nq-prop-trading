"""Download NQ 1-minute OHLCV bars from Databento (cheap history for auction/level research).

    .venv-nautilus/bin/python backtest/fetch_bars.py                      # quote only
    .venv-nautilus/bin/python backtest/fetch_bars.py --yes                # download 2024-07-01 to 2026-07-01

Needs DATABENTO_API_KEY in .env. Bars carry volume but no aggressor side, so order-flow filters
can only be tested on the tick months (fetch_data.py).
"""
import argparse
import os
from pathlib import Path

import databento as db

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "backtest" / "data" / "ohlcv"


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--symbol", default="NQ.v.0")
    p.add_argument("--start", default="2024-07-01")
    p.add_argument("--end", default="2026-07-01")
    p.add_argument("--yes", action="store_true", help="download (otherwise only print the quote)")
    args = p.parse_args()
    load_env()
    client = db.Historical()
    req = dict(dataset="GLBX.MDP3", symbols=[args.symbol], stype_in="continuous", schema="ohlcv-1m", start=args.start, end=args.end)
    cost = client.metadata.get_cost(**req)
    size = client.metadata.get_billable_size(**req)
    print(f"{args.symbol} ohlcv-1m {args.start} to {args.end}: ${cost:.2f}, {size / 1e6:.1f} MB")
    out = OUT_DIR / f"{args.symbol}_ohlcv-1m_{args.start}_{args.end}.dbn.zst"
    if out.exists():
        print(f"Already downloaded: {out.relative_to(ROOT)}")
        return
    if not args.yes:
        print("Quote only. Re-run with --yes to download.")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client.timeseries.get_range(**req, path=str(out))
    print(f"Saved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
