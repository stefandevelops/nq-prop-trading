"""Print today's NQ auction levels and setup notes before the New York open.

    .venv-nautilus/bin/python backtest/premarket_levels.py
    .venv-nautilus/bin/python backtest/premarket_levels.py --max-cost 0.50

Downloads the last ~5 weeks of NQ 1-minute bars from Databento (a few cents of credit; the quote is printed
first and the script stops if it is above --max-cost). Levels: prior RTH high/low, value area high/low and
POC (from 1-minute bars), overnight high/low, plus the median initial balance and 15-minute opening range
sizes, which set realistic stops for the IB and ORB setups.
"""
import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))
from common import CONTRACTS, cost_per_contract, load_config  # noqa: E402
from fetch_bars import load_env  # noqa: E402
from research_setups import value_area  # noqa: E402

ET = "America/New_York"


def fetch(max_cost: float, days: int) -> pd.DataFrame:
    load_env()
    client = db.Historical()
    end = pd.Timestamp(client.metadata.get_dataset_range(dataset="GLBX.MDP3")["end"])
    req = dict(dataset="GLBX.MDP3", symbols=["NQ.v.0"], stype_in="continuous", schema="ohlcv-1m",
               start=(end - timedelta(days=days)).isoformat(), end=end.isoformat())
    cost = client.metadata.get_cost(**req)
    print(f"Databento quote: ${cost:.3f} for {days} days of NQ 1-minute bars (data available to {end.tz_convert(ET):%Y-%m-%d %H:%M} ET)")
    if cost > max_cost:
        sys.exit(f"Above --max-cost ${max_cost:.2f}; nothing downloaded.")
    df = client.timeseries.get_range(**req).to_df(price_type="float")
    df.index = df.index.tz_convert(ET)
    return df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v", "instrument_id": "inst"})


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--max-cost", type=float, default=0.25, help="refuse to download if the quote is above this ($)")
    p.add_argument("--days", type=int, default=35, help="calendar days of history (for the median IB / opening range sizes)")
    args = p.parse_args()
    cfg = load_config()
    bars = fetch(args.max_cost, args.days)
    contract = bars.inst.iloc[-1]
    bars = bars[bars.inst == contract]  # ignore the old contract around a roll
    mins = bars.index.hour * 60 + bars.index.minute
    rth = bars[(mins >= 570) & (mins < 960) & (bars.index.dayofweek < 5)]
    days = [g for _, g in rth.groupby(rth.index.date) if len(g) >= 380]
    if not days:
        sys.exit("No complete RTH session in the downloaded data.")
    prev = days[-1]
    last = bars.index[-1]
    now_et = pd.Timestamp.now(tz=ET)
    on = bars[bars.index > prev.index[-1]]
    poc, vah, val = value_area(prev.h.values, prev.l.values, prev.v.values)
    ib = [g[(g.index.hour * 60 + g.index.minute) < 630] for g in days[-20:]]
    orr = [g[(g.index.hour * 60 + g.index.minute) < 585] for g in days[-20:]]
    ib_med = float(np.median([g.h.max() - g.l.min() for g in ib]))
    or_med = float(np.median([g.h.max() - g.l.min() for g in orr]))
    price = bars.c.iloc[-1]

    levels = [("PDH  prior day high", prev.h.max()), ("VAH  prior value area high", vah), ("POC  prior point of control", poc),
              ("VAL  prior value area low", val), ("PDL  prior day low", prev.l.min()), ("Prior RTH close", prev.c.iloc[-1])]
    if len(on):
        levels += [("ONH  overnight high", on.h.max()), ("ONL  overnight low", on.l.min())]
    levels.sort(key=lambda x: -x[1])

    print(f"\nNQ levels for {now_et:%A %d %b %Y}  (prior session {prev.index[0]:%a %d %b}, last bar {last:%H:%M} ET)\n")
    shown_price = False
    for name, lv in levels:
        if not shown_price and price > lv:
            print(f"  {'>> last price':30s} {price:10.2f}")
            shown_price = True
        print(f"  {name:30s} {lv:10.2f}   {lv - price:+8.2f} pts")
    if not shown_price:
        print(f"  {'>> last price':30s} {price:10.2f}")

    where = "ABOVE prior value" if price > vah else "BELOW prior value" if price < val else "INSIDE prior value"
    print(f"\nContext: price is {where} (value area {vah - val:.0f} pts wide).")
    if price > vah or price < val:
        print("  Opening outside value: if the open holds out there, expect a trend day and favour the IB/ORB breakout in that direction.")
        print("  If price gets back inside value and holds for 15+ minutes, a rotation toward the POC/opposite edge is possible (discretionary only).")
    else:
        print("  Opening inside value: balance is more likely. Breakouts need acceptance; reversals at VAH/VAL/PDH/PDL need clear absorption.")

    pv, cost = CONTRACTS["MNQ"].point_value, cost_per_contract(cfg, "MNQ")
    risk = cfg["plan"]["risk_per_trade"]
    print(f"\nRange sizes (median of last {len(ib)} sessions): 15-min opening range {or_med:.0f} pts, initial balance (first hour) {ib_med:.0f} pts.")
    print(f"  IB breakout stop: 30 pts inside the IB edge. ORB 15m stop: far side of the range, so about {or_med:.0f} pts.")
    print(f"\nMNQ size at ${risk:.0f} risk (incl. ${cost:.2f} costs per contract):")
    for stop in (30, 50, 80, round(or_med)):
        q = int(risk // (stop * pv + cost))
        print(f"  {stop:4d} pt stop -> {q} MNQ" + ("   (too wide: skip or use the range midpoint)" if q < 1 else ""))
    print("\nTimes: RTH open 9:30 ET (14:30 UK), opening range done 9:45, IB done 10:30 (15:30 UK), no new IB/ORB entries after 13:00 ET.")

    out = ROOT / "signals" / "levels.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({
        "date": f"{now_et:%Y-%m-%d}", "last_bar_et": f"{last:%Y-%m-%d %H:%M}", "last_price": round(float(price), 2),
        "context": where, "levels": {name.split("  ")[0]: round(float(lv), 2) for name, lv in levels},
        "median_opening_range_15m": round(or_med), "median_initial_balance": round(ib_med),
    }, indent=2))
    print(f"\nSaved for the screen agent: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
