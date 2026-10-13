"""Value area rotation ("80% rule") research on 1-minute NQ bars built from the Databento tick files.

    .venv-nautilus/bin/python backtest/research_va_rotation.py
    .venv-nautilus/bin/python backtest/research_va_rotation.py --oos      # also print the out-of-sample month

Idea (Dalton): the RTH session opens outside the prior day's value area, then price gets back inside and is
accepted there. Acceptance means the market rejects the new prices, so it tends to rotate through value to the
opposite edge. Variants differ in how acceptance is defined, how the stop is placed and whether order flow
(aggressor delta) must agree. Rules are chosen on Jul-Aug 2026 and checked once on Sep 2026.

Fills: entry at the close of the signal bar; if stop and target are both inside one bar the stop counts first.
$ figures size MNQ to the plan risk and charge commission + 1 tick slippage like the journal.
"""
import argparse
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backtest"))
from build_dashboard import load_ticks, value_area  # noqa: E402
from common import CONTRACTS, cost_per_contract, load_config  # noqa: E402

CACHE = ROOT / "backtest" / "data" / "research"
ET = "America/New_York"
IS_END = "2026-08-31"


def load_data() -> tuple[pd.DataFrame, dict]:
    bars_path, va_path = CACHE / "bars_1m.parquet", CACHE / "value_areas.json"
    if bars_path.exists() and va_path.exists():
        return pd.read_parquet(bars_path), json.loads(va_path.read_text())
    bars, profiles, _ = load_ticks()
    vas = {d: dict(zip(("poc", "vah", "val"), value_area(p))) for d, p in profiles.items()}
    CACHE.mkdir(parents=True, exist_ok=True)
    bars.to_parquet(bars_path)
    va_path.write_text(json.dumps(vas))
    return bars, vas


@dataclass(frozen=True)
class Variant:
    accept: str          # "30mN": N consecutive 30-min periods close inside value; "1mN": N consecutive 1-min closes inside
    entry: str           # "close": at the acceptance bar's close; "retest": limit order back at the re-entered edge
    buffer: float        # stop distance in points beyond the re-entered value edge
    delta: bool          # require aggressor delta since the open to agree with the rotation
    target: str          # "opp": opposite value edge; "poc": prior POC
    max_stop: float = 100.0
    retest_inside: float = 3.0  # retest limit sits this many points inside the edge
    entry_end: int = 13 * 60    # no entries after this ET minute

    def name(self) -> str:
        return (f"accept={self.accept:4s} entry={self.entry:6s} stop=edge+{self.buffer:<2g} "
                f"delta={'Y' if self.delta else 'N'} target={self.target}")


def sessions(bars: pd.DataFrame, vas: dict) -> list[dict]:
    rth = bars[(bars.index.hour * 60 + bars.index.minute >= 570) & (bars.index.hour * 60 + bars.index.minute < 960)]
    days = sorted({d.isoformat() for d in rth.index.date})
    out = []
    for prev, day in zip(days, days[1:]):
        b = rth[rth.index.date == pd.Timestamp(day).date()]
        pb = rth[rth.index.date == pd.Timestamp(prev).date()]
        if len(b) < 300 or prev not in vas or b.inst.iloc[0] != pb.inst.iloc[-1]:
            continue
        out.append({"date": day, "bars": b, **vas[prev]})
    return out


def find_trade(s: dict, v: Variant) -> dict | None:
    b, vah, val = s["bars"], s["vah"], s["val"]
    o = b.o.iloc[0]
    if val <= o <= vah:
        return None
    side = -1 if o > vah else 1               # opened above value -> rotate down (short)
    edge = vah if side == -1 else val
    target = (val if side == -1 else vah) if v.target == "opp" else s["poc"]
    mins = b.index.hour * 60 + b.index.minute
    inside = (b.c <= vah) & (b.c >= val)
    n = int(v.accept.split("m")[1])
    acc_i = None
    if v.accept.startswith("30m"):
        closes = b.c.resample("30min", origin="start_day", offset="9h30min").last()
        ins = ((closes <= vah) & (closes >= val)).tolist()
        for k in range(n - 1, len(ins)):
            if all(ins[k - n + 1: k + 1]):
                ts = closes.index[k] + pd.Timedelta(minutes=29)
                acc_i = b.index.get_loc(ts) if ts in b.index else None
                break
    else:
        run = 0
        for i, ok in enumerate(inside):
            run = run + 1 if ok else 0
            if run >= n:
                acc_i = i
                break
    if acc_i is None or mins[acc_i] >= v.entry_end:
        return None
    if v.delta:
        d = (b.buy.iloc[: acc_i + 1] - b.sell.iloc[: acc_i + 1]).sum()
        if d * side <= 0:
            return None
    stop = edge - side * v.buffer

    if v.entry == "close":
        entry_i, entry = acc_i, b.c.iloc[acc_i]
        first_bar = entry_i + 1
    else:
        entry, entry_i = edge + side * v.retest_inside, None
        for j in range(acc_i + 1, len(b)):
            if mins[j] >= v.entry_end or ((b.l.iloc[j] <= target) if side == -1 else (b.h.iloc[j] >= target)):
                return None
            if (b.h.iloc[j] >= entry) if side == -1 else (b.l.iloc[j] <= entry):
                entry_i = j
                break
        if entry_i is None:
            return None
        first_bar = entry_i  # the fill bar may also take out the stop
    if (target - entry) * side <= 0:
        return None
    risk = (entry - stop) * side
    if risk <= 2 or risk > v.max_stop:
        return None
    exit_px, reason, mfe, mae = b.c.iloc[-1], "close", 0.0, 0.0
    for i in range(first_bar, len(b)):
        hi, lo = b.h.iloc[i], b.l.iloc[i]
        fav, adv = ((hi - entry) if side == 1 else (entry - lo)), ((entry - lo) if side == 1 else (hi - entry))
        mae = max(mae, adv)
        if (lo <= stop) if side == 1 else (hi >= stop):
            exit_px, reason = stop, "stop"
            break
        mfe = max(mfe, fav)
        if (hi >= target) if side == 1 else (lo <= target):
            exit_px, reason = target, "target"
            break
    return {"date": s["date"], "time": b.index[entry_i].strftime("%H:%M"), "side": side, "entry": entry, "stop": stop,
            "target": target, "exit": exit_px, "reason": reason, "risk": risk, "R": (exit_px - entry) * side / risk,
            "planned_R": (target - entry) * side / risk, "mfe": mfe, "mae": mae}


def dollars(t: dict, cfg: dict) -> float:
    pv, risk_usd = CONTRACTS["MNQ"].point_value, cfg["plan"]["risk_per_trade"]
    cost = cost_per_contract(cfg, "MNQ")
    qty = max(1, min(int(risk_usd // (t["risk"] * pv + cost)), cfg["max_contracts"]["MNQ"]))
    return (t["exit"] - t["entry"]) * t["side"] * pv * qty - cost * qty


def stats(trades: list[dict], cfg: dict) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    usd = [dollars(t, cfg) for t in trades]
    return {"n": n, "win": sum(t["R"] > 0 for t in trades) / n, "expR": sum(t["R"] for t in trades) / n,
            "usd": sum(usd), "hit": sum(t["reason"] == "target" for t in trades) / n,
            "planR": sum(t["planned_R"] for t in trades) / n, "stop": sum(t["risk"] for t in trades) / n}


def fmt(s: dict) -> str:
    if not s["n"]:
        return "   0 trades"
    return (f"{s['n']:4d} trades  win {s['win']:5.0%}  target hit {s['hit']:4.0%}  avg {s['expR']:+.2f}R  "
            f"(planned {s['planR']:.1f}R, stop {s['stop']:4.1f} pts)  net ${s['usd']:+,.0f}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--oos", action="store_true", help="also evaluate Sep 2026 (do this once, after choosing a variant)")
    p.add_argument("--show", help="print every trade of the variant whose name contains this text")
    args = p.parse_args()
    cfg = load_config()
    bars, vas = load_data()
    ss = sessions(bars, vas)
    ins = [s for s in ss if s["date"] <= IS_END]
    oos = [s for s in ss if s["date"] > IS_END]
    opened_out = [s for s in ins if not (s["val"] <= s["bars"].o.iloc[0] <= s["vah"])]
    print(f"In-sample sessions: {len(ins)} (Jul-Aug), opened outside prior value: {len(opened_out)}; out-of-sample: {len(oos)} (Sep)\n")

    variants = [Variant(a, en, bf, dl, tg) for a, en, bf, dl, tg in itertools.product(
        ["1m5", "1m15", "30m1", "30m2"], ["close", "retest"], [10.0, 25.0, 40.0, 60.0], [False, True], ["opp", "poc"])]
    rows = []
    for v in variants:
        tr = [t for s in ins if (t := find_trade(s, v))]
        rows.append((v, stats(tr, cfg), tr))
    rows.sort(key=lambda r: -(r[1].get("expR", -9) if r[1]["n"] >= 8 else -9))
    print("In-sample (Jul-Aug), sorted by average R (variants with fewer than 8 trades last):")
    for v, s, _ in rows:
        print(f"  {v.name()}  {fmt(s)}")
    family(rows, "in-sample")

    if args.show:
        for v, s, tr in rows:
            if args.show in v.name():
                print(f"\n{v.name()}")
                for t in tr:
                    print(f"  {t['date']} {t['time']} {'Long ' if t['side'] == 1 else 'Short'} entry {t['entry']:.2f} stop {t['stop']:.2f} "
                          f"target {t['target']:.2f} -> {t['reason']:6s} {t['R']:+.2f}R  mfe {t['mfe']:.1f} mae {t['mae']:.1f}")
                break

    if args.oos:
        print("\nOut-of-sample (Sep), same variants in the same order:")
        oos_rows = []
        for v, s_in, _ in rows:
            tr = [t for s in oos if (t := find_trade(s, v))]
            oos_rows.append((v, stats(tr, cfg), tr))
            print(f"  {v.name()}  {fmt(oos_rows[-1][1])}")
        family(oos_rows, "out-of-sample")


def family(rows: list, label: str) -> None:
    """Judge the idea by all reasonable variants together, not by the best one (which is mostly luck)."""
    rs = sorted(s["expR"] for _, s, _ in rows if s["n"] >= 5)
    if not rs:
        return
    print(f"\n  Family ({label}): {len(rs)} variants with 5+ trades, median {rs[len(rs) // 2]:+.2f}R per trade, "
          f"{sum(r > 0 for r in rs) / len(rs):.0%} of them profitable")


if __name__ == "__main__":
    main()
