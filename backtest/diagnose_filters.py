"""Count how many absorption candidates survive each detection filter (tuning aid).

Runs the normal backtest with an instrumented copy of the detector and prints a funnel:
seconds evaluated -> heavy volume -> price at a level -> aggressor share -> stall -> pushes
-> armed -> entered. Use it on the in-sample period only.

Example:
    python backtest/diagnose_filters.py --start 2026-07-06 --end 2026-07-17 --set min_volume_multiple=1.2
"""

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

import run_backtest
from fetch_data import DEFAULT_CATALOG
from strategies.absorption import NS, AbsorptionStrategy, Setup

funnel: Counter = Counter()
share_samples: list[float] = []
zone_samples: list[float] = []
absorbed_samples: list[float] = []


def instrumented_find(self, ts, levels, only_side=0):
    c = self.config
    flow = self._flow
    if only_side or not flow.trades:
        return original_find(self, ts, levels, only_side)
    funnel["1 seconds evaluated"] += 1
    avg = sum(self._minutes) / len(self._minutes) * c.absorption_window_secs / 60 if self._minutes else 0
    vol = flow.volume
    if vol < max(c.min_window_volume, c.min_volume_multiple * avg, 1):
        return None
    funnel["2 heavy volume"] += 1
    stages = Counter()
    found = None
    for label, level in levels.items():
        if self._tests.get(label, 0) > c.max_level_tests or self._cooldown.get(label, 0) > ts:
            continue
        for side in (-1, 1):
            ext, ext_ts = flow.high() if side == -1 else flow.low()
            beyond = (ext - level) * -side
            if not (-c.level_tolerance_pts <= beyond <= c.max_penetration_pts):
                continue
            stages["3 extreme at a level"] = 1
            aggr = flow.buy if side == -1 else flow.sell
            share_samples.append(aggr / vol)
            zone = [(s, b) for _, p, s, b, _ in flow.trades if (ext - p) * -side <= c.push_zone_pts]
            zone_vol = sum(s for s, _ in zone)
            if zone_vol:
                zone_samples.append(sum(s for s, b in zone if b == (side == -1)) / zone_vol)
            if aggr / vol < c.min_aggressor_share:
                continue
            stages["4 window leans to aggressors"] = 1
            if ts - ext_ts < c.min_stall_secs * NS:
                continue
            stages["5 stalled"] = 1
            if (ext - flow.trades[-1][1]) * -side > c.max_extreme_distance_pts:
                continue
            stages["6 price still near extreme"] = 1
            pushes, passive, absorbed = self._pushes(ext, side)
            if avg:
                absorbed_samples.append(absorbed / avg)
            if pushes < c.min_pushes:
                continue
            stages["7 enough pushes"] = 1
            if absorbed < c.min_absorbed_ratio * avg:
                continue
            stages["8 heavy volume absorbed"] = 1
            if c.min_passive_size > 0 and passive < c.min_passive_size:
                continue
            found = found or Setup(side, label, level, ext, ts, f"{label} {level:.2f}")
    funnel.update(stages)
    if found:
        funnel["9 setups armed"] += 1
    return found


original_find = AbsorptionStrategy._find_absorption
AbsorptionStrategy._find_absorption = instrumented_find
original_enter = AbsorptionStrategy._enter


def counted_enter(self, ts, price, s):
    funnel["10 shift triggered"] += 1
    return original_enter(self, ts, price, s)


AbsorptionStrategy._enter = counted_enter


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=date.fromisoformat, required=True)
    p.add_argument("--end", type=date.fromisoformat, required=True)
    p.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE")
    args = p.parse_args()
    ns = argparse.Namespace(catalog=Path(DEFAULT_CATALOG), instrument_id="NQ.GLBX", contract="MNQ",
                            start=args.start, end=args.end, risk=None, news_file=None, set=args.set,
                            log_level="ERROR")
    trades, _ = run_backtest.run(ns)
    print("\nFunnel (seconds in the RTH session where at least one candidate passed the stage):")
    for k in sorted(funnel, key=lambda k: int(k.split()[0])):
        print(f"  {k:<32} {funnel[k]:>8,}")
    print(f"  {'11 trades taken':<32} {len(trades):>8,}")
    for name, samples in (("whole window", share_samples), ("at the extreme only", zone_samples)):
        if samples:
            s = sorted(samples)
            q = lambda f: s[int(f * (len(s) - 1))]
            print(f"Aggressor share into the level, {name}: median {q(0.5):.0%}, 75th {q(0.75):.0%}, 90th {q(0.9):.0%}")
    if absorbed_samples:
        s = sorted(absorbed_samples)
        q = lambda f: s[int(f * (len(s) - 1))]
        print("Absorbed volume at a stalled extreme near price, as a multiple of average window volume: "
              + ", ".join(f"p{int(f * 100)} {q(f):.2f}" for f in (0.5, 0.75, 0.9, 0.95, 0.99)))


if __name__ == "__main__":
    main()
