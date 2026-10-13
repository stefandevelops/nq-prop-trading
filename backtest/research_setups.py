"""Three auction-theory setups on 2+ years of NQ 1-minute bars, chosen on one period and checked on another.

    .venv-nautilus/bin/python backtest/research_setups.py              # design period only
    .venv-nautilus/bin/python backtest/research_setups.py --holdout    # + the holdout check and challenge test (run once)

Setups (PLAYBOOK.md wording):
  A  Value area rotation ("80% rule"): open outside the prior RTH value area, get accepted back inside,
     ride to the opposite value edge.
  B  Failed auction: price probes beyond the prior day / overnight high or low, finds no follow-through
     and closes back inside; target VWAP, the prior POC or a fixed 2R.
  C  Initial balance breakout with acceptance: after 10:30, consecutive 5-minute closes beyond the IB;
     enter at the close or on the retest, target an IB-range extension.

Data: Databento GLBX.MDP3 NQ.v.0 ohlcv-1m from 2024-07-01 (fetch_bars.py), then 1-minute bars built from
the tick files for Jul-Sep 2026. Bars have no aggressor side, so these tests cover auction structure only;
the order-flow trigger is your discretionary filter on top.

Fills: market entries at the signal bar's close, limit entries when a bar trades through the price.
If one bar touches both stop and target the stop counts. $ results size MNQ to a fixed $ risk and charge
commission + 1 tick slippage like the journal. Exits by 15:55 ET.
"""
import argparse
import csv
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

import databento as db
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from common import CONTRACTS, cost_per_contract, load_config  # noqa: E402

OHLCV = ROOT / "backtest" / "data" / "ohlcv" / "NQ.v.0_ohlcv-1m_2024-07-01_2026-07-01.dbn.zst"
TICK_BARS = ROOT / "backtest" / "data" / "research" / "bars_1m.parquet"
RESULTS = ROOT / "backtest" / "results"
ET = "America/New_York"
DESIGN_END = "2025-12-31"
MIN_TRADES = 30
MAX_STOP = 100.0
RTH_OPEN, IB_END, RTH_CLOSE, LAST_EXIT = 570, 630, 960, 955


# ----------------------------------------------------------------------------- data

def load_bars() -> pd.DataFrame:
    df = db.DBNStore.from_file(OHLCV).to_df(price_type="float")
    df = df.rename(columns={"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v", "instrument_id": "inst"})
    df.index = df.index.tz_convert(ET)
    df = df[["o", "h", "l", "c", "v", "inst"]]
    if TICK_BARS.exists():
        tb = pd.read_parquet(TICK_BARS)[["o", "h", "l", "c", "v", "inst"]]
        df = pd.concat([df[df.index < tb.index.min()], tb])
    return df.sort_index()


def value_area(h: np.ndarray, l: np.ndarray, v: np.ndarray, share: float = 0.70) -> tuple[float, float, float]:
    """Volume profile from 1-minute bars (each bar's volume spread evenly over its range, 1-point bins)."""
    base = np.floor(l.min())
    prof = np.zeros(int(np.ceil(h.max()) - base) + 2)
    for hi, lo, vol in zip(h, l, v):
        a, b = int(np.floor(lo) - base), int(np.floor(hi) - base) + 1
        prof[a:b] += vol / (b - a)
    poc = int(prof.argmax())
    lo = hi = poc
    acc, target = prof[poc], prof.sum() * share
    while acc < target and (lo > 0 or hi < len(prof) - 1):
        up = prof[hi + 1] if hi < len(prof) - 1 else -1
        dn = prof[lo - 1] if lo > 0 else -1
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    return base + poc + 0.5, base + hi + 1, base + lo


def build_sessions(bars: pd.DataFrame) -> list[dict]:
    mins = bars.index.hour * 60 + bars.index.minute
    is_rth = (mins >= RTH_OPEN) & (mins < RTH_CLOSE) & (bars.index.dayofweek < 5)
    rth = bars[is_rth]
    groups = {d: g for d, g in rth.groupby(rth.index.date)}
    dates = sorted(groups)
    sessions, ib_hist = [], []
    for prev, day in zip(dates, dates[1:]):
        b, pb = groups[day], groups[prev]
        if len(b) < 380 or len(pb) < 380:  # skip half days and the session after them
            continue
        if b.inst.iloc[0] != pb.inst.iloc[-1]:  # roll: prior levels belong to another contract
            continue
        on = bars[(bars.index > pb.index[-1]) & (bars.index < b.index[0])]
        on = on[on.inst == b.inst.iloc[0]]
        poc, vah, val = value_area(pb.h.values, pb.l.values, pb.v.values)
        t = (b.index.hour * 60 + b.index.minute).values
        tp = (b.h.values + b.l.values + b.c.values) / 3
        vwap = np.cumsum(tp * b.v.values) / np.maximum(np.cumsum(b.v.values), 1)
        ib = t < IB_END
        ibh, ibl = b.h.values[ib].max(), b.l.values[ib].min()
        s = {
            "date": day.isoformat(), "t": t, "o": b.o.values, "h": b.h.values, "l": b.l.values, "c": b.c.values,
            "vwap": vwap, "open": b.o.values[0], "pdh": pb.h.max(), "pdl": pb.l.min(), "poc": poc, "vah": vah, "val": val,
            "onh": on.h.max() if len(on) else None, "onl": on.l.min() if len(on) else None,
            "ibh": ibh, "ibl": ibl, "ib_med": float(np.median(ib_hist[-20:])) if len(ib_hist) >= 10 else None,
        }
        ib_hist.append(ibh - ibl)
        sessions.append(s)
    return sessions


# ----------------------------------------------------------------------------- simulation

def walk(s: dict, i0: int, side: int, entry: float, stop: float, target: float, fill_bar: bool) -> tuple:
    """Bar-by-bar exit. fill_bar: the entry bar itself (limit fill) may still hit the stop."""
    h, l, c, t = s["h"], s["l"], s["c"], s["t"]
    mfe = mae = 0.0
    for i in range(i0 if fill_bar else i0 + 1, len(h)):
        fav = (h[i] - entry) if side == 1 else (entry - l[i])
        adv = (entry - l[i]) if side == 1 else (h[i] - entry)
        mae = max(mae, adv)
        if adv >= (entry - stop) * side:
            return i, stop, "stop", mfe, mae
        if not (fill_bar and i == i0):
            mfe = max(mfe, fav)
            if fav >= (target - entry) * side:
                return i, target, "target", mfe, mae
        if t[i] >= LAST_EXIT:
            return i, c[i], "close", mfe, mae
    return len(h) - 1, c[-1], "close", mfe, mae


def make_trade(s, setup, note, i_entry, side, entry, stop, target, fill_bar=False, max_stop=MAX_STOP) -> dict | None:
    risk = (entry - stop) * side
    if risk < 4 or risk > max_stop or (target - entry) * side <= 0:
        return None
    i_exit, exit_px, reason, mfe, mae = walk(s, i_entry, side, entry, stop, target, fill_bar)
    return {"date": s["date"], "setup": setup, "note": note, "i": i_entry, "i_exit": i_exit, "t": int(s["t"][i_entry]),
            "t_exit": int(s["t"][i_exit]), "side": side, "entry": entry, "stop": stop, "target": target, "exit": exit_px,
            "reason": reason, "risk": risk, "R": (exit_px - entry) * side / risk, "planned": (target - entry) * side / risk,
            "mfe": mfe, "mae": mae}


# ----------------------------------------------------------------------------- setups

@dataclass(frozen=True)
class VA:
    accept: str      # "30m1" / "30m2": consecutive 30-min closes inside value; "1m15": 15 consecutive 1-min closes
    buffer: float    # stop beyond the re-entered edge
    target: str      # "opp" opposite edge, "poc"
    setup = "A Value area rotation"

    def label(self):
        return f"A accept={self.accept} stop=edge+{self.buffer:g} target={self.target}"

    def trades(self, s):
        vah, val, o, c, t = s["vah"], s["val"], s["open"], s["c"], s["t"]
        if val <= o <= vah:
            return []
        side = -1 if o > vah else 1
        edge = vah if side == -1 else val
        target = (val if side == -1 else vah) if self.target == "opp" else s["poc"]
        inside = (c <= vah) & (c >= val)
        n = int(self.accept.split("m")[1])
        acc = None
        if self.accept.startswith("30m"):
            ends = np.where((t - RTH_OPEN) % 30 == 29)[0]
            run = 0
            for i in ends:
                run = run + 1 if inside[i] else 0
                if run >= n:
                    acc = i
                    break
        else:
            run = 0
            for i in range(len(c)):
                run = run + 1 if inside[i] else 0
                if run >= n:
                    acc = i
                    break
        if acc is None or t[acc] >= 13 * 60:
            return []
        tr = make_trade(s, self.setup, f"opened {'above VAH' if side == -1 else 'below VAL'}, accepted back inside",
                        acc, side, c[acc], edge - side * self.buffer, target)
        return [tr] if tr else []


@dataclass(frozen=True)
class FailedAuction:
    max_mins: int        # probe must fail (close back inside) within this many minutes
    buffer: float        # stop beyond the probe extreme
    target: str          # "vwap", "poc" or "2R"
    balance_only: bool   # only when the session opened inside the prior day's range
    min_probe: float = 3.0
    max_probe: float = 60.0
    setup = "B Failed auction"

    def label(self):
        return (f"B fail<={self.max_mins}m stop=ext+{self.buffer:g} target={self.target:4s} "
                f"balance_only={'Y' if self.balance_only else 'N'}")

    def trades(self, s):
        o, h, l, c, t = s["open"], s["h"], s["l"], s["c"], s["t"]
        if self.balance_only and not (s["pdl"] <= o <= s["pdh"]):
            return []
        levels = [(n, lv, -1) for n, lv in (("PDH", s["pdh"]), ("ONH", s["onh"])) if lv is not None and lv > o]
        levels += [(n, lv, 1) for n, lv in (("PDL", s["pdl"]), ("ONL", s["onl"])) if lv is not None and lv < o]
        out = []
        for name, lv, side in levels:
            probe, ext = None, None
            for i in range(len(c)):
                if t[i] < RTH_OPEN + 5:
                    continue
                if t[i] >= 12 * 60:
                    break
                beyond = (h[i] - lv) if side == -1 else (lv - l[i])
                if probe is None:
                    if beyond >= self.min_probe:
                        probe, ext = i, (h[i] if side == -1 else l[i])
                    else:
                        continue
                ext = max(ext, h[i]) if side == -1 else min(ext, l[i])
                if (ext - lv) * -side > self.max_probe or i - probe > self.max_mins:
                    break
                if (c[i] - lv) * side > 0:  # closed back inside
                    entry, stop = c[i], ext - side * self.buffer
                    if self.target == "2R":
                        target = entry + 2 * (entry - stop)
                    else:
                        target = s["vwap"][i] if self.target == "vwap" else s["poc"]
                        if (target - entry) * side < (entry - stop) * side:  # need at least 1R of room
                            break
                    tr = make_trade(s, self.setup, f"{name} {lv:.2f} probe {abs(ext - lv):.1f} pts failed", i, side, entry, stop, target)
                    if tr:
                        out.append(tr)
                    break
        return out


@dataclass(frozen=True)
class IBBreak:
    k: int               # consecutive 5-min closes beyond the IB
    entry: str           # "close" or "retest" (limit 2 pts beyond the IB edge)
    buffer: float        # stop back inside the IB
    ext: float           # target = IB edge + ext x IB range
    narrow_only: bool    # IB narrower than its 20-session median
    setup = "C IB breakout"

    def label(self):
        return (f"C k={self.k} entry={self.entry:6s} stop=edge-{self.buffer:g} target=IB+{self.ext:g}x "
                f"narrow_only={'Y' if self.narrow_only else 'N'}")

    def trades(self, s):
        ibh, ibl, h, l, c, t = s["ibh"], s["ibl"], s["h"], s["l"], s["c"], s["t"]
        rng = ibh - ibl
        if self.narrow_only and (s["ib_med"] is None or rng >= s["ib_med"]):
            return []
        ends = np.where(((t - RTH_OPEN) % 5 == 4) & (t >= IB_END))[0]
        up = dn = 0
        for i in ends:
            if t[i] >= 13 * 60:
                return []
            up = up + 1 if c[i] > ibh else 0
            dn = dn + 1 if c[i] < ibl else 0
            if up >= self.k or dn >= self.k:
                side = 1 if up >= self.k else -1
                edge = ibh if side == 1 else ibl
                stop, target = edge - side * self.buffer, edge + side * self.ext * rng
                note = f"accepted {'above IBH' if side == 1 else 'below IBL'} {edge:.2f}, IB {rng:.0f} pts"
                if self.entry == "close":
                    tr = make_trade(s, self.setup, note, i, side, c[i], stop, target)
                    return [tr] if tr else []
                px = edge + side * 2
                for j in range(i + 1, len(c)):
                    if t[j] >= 13 * 60 or ((h[j] >= target) if side == 1 else (l[j] <= target)):
                        return []
                    if (l[j] <= px) if side == 1 else (h[j] >= px):
                        tr = make_trade(s, self.setup, note + ", retest", j, side, px, stop, target, fill_bar=True)
                        return [tr] if tr else []
                return []
        return []


@dataclass(frozen=True)
class ORB:
    """Opening range breakout as taught by Andrea Cimitan (ORB) and Fabio Valentini (IVB): a 5-minute close
    beyond the first N minutes' range, stop at the far side or middle of the range, fixed R target,
    up to `attempts` tries per direction. 120-point stop cap = 1 MNQ at $250 risk."""
    minutes: int     # 15, 30 or 60
    stop: str        # "opp" far side of the range, "mid" range midpoint
    r: float         # target in R
    attempts: int    # tries per direction per day
    max_stop: float = 120.0
    setup = "D Opening range breakout"

    def label(self):
        return f"D ORB {self.minutes}m stop={self.stop} target={self.r:g}R attempts={self.attempts}"

    def trades(self, s):
        h, l, c, t = s["h"], s["l"], s["c"], s["t"]
        rmask = t < RTH_OPEN + self.minutes
        orh, orl = h[rmask].max(), l[rmask].min()
        mid = (orh + orl) / 2
        out, used, busy = [], {1: 0, -1: 0}, -1
        for i in np.where(((t - RTH_OPEN) % 5 == 4) & (t >= RTH_OPEN + self.minutes))[0]:
            if t[i] >= 13 * 60:
                break
            if i <= busy:
                continue
            side = 1 if c[i] > orh else -1 if c[i] < orl else 0
            if not side or used[side] >= self.attempts:
                continue
            stop = (orl if side == 1 else orh) if self.stop == "opp" else mid
            entry = c[i]
            used[side] += 1
            tr = make_trade(s, self.setup, f"{self.minutes}m range {orl:.2f}-{orh:.2f} ({orh - orl:.0f} pts), attempt {used[side]}",
                            i, side, entry, stop, entry + self.r * (entry - stop), max_stop=self.max_stop)
            if tr:
                out.append(tr)
                busy = tr["i_exit"]
        return out


def all_variants():
    va = [VA(a, b, tg) for a, b, tg in itertools.product(["30m1", "30m2", "1m15"], [25.0, 40.0], ["opp", "poc"])]
    fa = [FailedAuction(m, b, tg, bo) for m, b, tg, bo in itertools.product([10, 30], [10.0, 25.0], ["vwap", "poc", "2R"], [False, True])]
    ib = [IBBreak(k, e, b, x, n) for k, e, b, x, n in itertools.product([2, 3], ["close", "retest"], [15.0, 30.0], [0.5, 1.0], [False, True])]
    orb = [ORB(m, st, r, a) for m, st, r, a in itertools.product([15, 30, 60], ["opp", "mid"], [1.0, 2.0], [1, 2])]
    return {"A": va, "B": fa, "C": ib, "D": orb}


# ----------------------------------------------------------------------------- evaluation

def usd(tr: dict, risk_usd: float, cfg: dict) -> float:
    pv, cost = CONTRACTS["MNQ"].point_value, cost_per_contract(cfg, "MNQ")
    qty = min(int(risk_usd // (tr["risk"] * pv + cost)), cfg["max_contracts"]["MNQ"])
    return 0.0 if qty < 1 else (tr["exit"] - tr["entry"]) * tr["side"] * pv * qty - cost * qty


def stats(trs: list[dict]) -> dict:
    n = len(trs)
    if not n:
        return {"n": 0, "expR": float("nan")}
    rs = [t["R"] for t in trs]
    return {"n": n, "win": sum(r > 0 for r in rs) / n, "expR": sum(rs) / n, "sumR": sum(rs),
            "hit": sum(t["reason"] == "target" for t in trs) / n, "stop": sum(t["risk"] for t in trs) / n,
            "planned": sum(t["planned"] for t in trs) / n}


def fmt(st: dict) -> str:
    if not st["n"]:
        return "   0 trades"
    return (f"{st['n']:4d} trades  win {st['win']:4.0%}  target {st['hit']:4.0%}  avg {st['expR']:+.2f}R  "
            f"total {st['sumR']:+6.1f}R  planned {st['planned']:.1f}R  stop {st['stop']:4.1f}")


def by_year(trs: list[dict]) -> str:
    parts = []
    for y in sorted({t["date"][:4] for t in trs}):
        st = stats([t for t in trs if t["date"][:4] == y])
        parts.append(f"{y}: {st['n']} tr {st['expR']:+.2f}R")
    return "  |  ".join(parts)


def combine(trades: list[dict], max_per_day: int = 3, max_losses: int = 2) -> list[dict]:
    """One position at a time, at most max_per_day trades and stop after max_losses losers, per day."""
    out = []
    by_day: dict[str, list] = {}
    for t in trades:
        by_day.setdefault(t["date"], []).append(t)
    for d in sorted(by_day):
        busy_until, n, losses = -1, 0, 0
        for t in sorted(by_day[d], key=lambda x: x["i"]):
            if t["i"] <= busy_until or n >= max_per_day or losses >= max_losses:
                continue
            out.append(t)
            busy_until, n, losses = t["i_exit"], n + 1, losses + (t["R"] <= 0)
    return out


def rolling_challenges(dates: list[str], trades: list[dict], risk_usd: float, cfg: dict, max_days: int) -> dict:
    """Start a real challenge on every session and trade the actual following sessions in order."""
    start_bal, target, dd, lock = cfg["starting_balance"], cfg["starting_balance"] + cfg["profit_target"], cfg["max_drawdown"], cfg["trail_lock_balance"]
    dll = cfg["daily_loss_limit"]
    by_day: dict[str, list] = {}
    for t in trades:
        by_day.setdefault(t["date"], []).append(usd(t, risk_usd, cfg))
    res = {"pass": 0, "fail": 0, "timeout": 0, "days": []}
    for k in range(len(dates) - max_days + 1):
        bal, hwm, outcome = start_bal, start_bal, "timeout"
        for j, d in enumerate(dates[k:k + max_days], 1):
            thr = min(hwm - dd, lock) if lock is not None else hwm - dd
            day = 0.0
            for x in by_day.get(d, []):
                bal += x
                day += x
                if bal <= thr:
                    outcome = "fail"
                    break
                if dll and day <= -dll:
                    break
            if outcome == "fail":
                break
            hwm = max(hwm, bal)
            if bal >= target:
                outcome = "pass"
                res["days"].append(j)
                break
        res[outcome] += 1
    n = res["pass"] + res["fail"] + res["timeout"]
    res["n"] = n
    return res


def challenge_table(dates: list[str], trades: list[dict], cfg: dict) -> None:
    for days in (21, 42):
        for r in (250, 350, 500):
            rc = rolling_challenges(dates, trades, r, cfg, days)
            if not rc["n"]:
                continue
            med = sorted(rc["days"])[len(rc["days"]) // 2] if rc["days"] else None
            print(f"  {days}-day challenges at ${r} risk: pass {rc['pass'] / rc['n']:4.0%}  fail {rc['fail'] / rc['n']:4.0%}  "
                  f"timeout {rc['timeout'] / rc['n']:4.0%}  ({rc['n']} starts{f', median {med} days to pass' if med else ''})")


def write_journal_csv(path: Path, trades: list[dict], risk_usd: float, cfg: dict) -> None:
    pv, cost = CONTRACTS["MNQ"].point_value, cost_per_contract(cfg, "MNQ")
    tick = lambda x: round(round(x / 0.25) * 0.25, 2)  # noqa: E731
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "time", "setup", "side", "contract", "qty", "entry", "stop", "exit", "mfe", "mae", "rules", "notes", "stopEstimated"])
        for t in trades:
            qty = min(int(risk_usd // (t["risk"] * pv + cost)), cfg["max_contracts"]["MNQ"])
            if qty < 1:
                continue
            w.writerow([t["date"], f"{t['t'] // 60:02d}:{t['t'] % 60:02d}", t["setup"], "Long" if t["side"] == 1 else "Short", "MNQ", qty,
                        tick(t["entry"]), tick(t["stop"]), tick(t["exit"]), tick(t["mfe"]), tick(t["mae"]), "true",
                        f"Backtest (1-min bars) - {t['note']}; exit: {t['reason']} at {t['t_exit'] // 60:02d}:{t['t_exit'] % 60:02d}", "false"])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--holdout", action="store_true", help="evaluate the chosen variants on 2026 (run once)")
    p.add_argument("--risk", type=float, default=250.0, help="$ risk per trade for the CSV export")
    args = p.parse_args()
    cfg = load_config()
    print("Loading bars and building sessions...")
    sessions = build_sessions(load_bars())
    design = [s for s in sessions if s["date"] <= DESIGN_END]
    hold = [s for s in sessions if s["date"] > DESIGN_END]
    print(f"Sessions: {len(design)} design ({design[0]['date']} to {design[-1]['date']}), {len(hold)} holdout ({hold[0]['date']} to {hold[-1]['date']})\n")

    chosen = {}
    for key, variants in all_variants().items():
        rows = []
        for v in variants:
            trs = [t for s in design for t in v.trades(s)]
            rows.append((v, stats(trs), trs))
        rows.sort(key=lambda r: -(r[1]["expR"] if r[1]["n"] >= MIN_TRADES else -9))
        print(f"== {variants[0].setup}: design period, best first (needs {MIN_TRADES}+ trades to rank)")
        for v, st, _ in rows:
            print(f"  {v.label():62s} {fmt(st)}")
        rs = sorted(st["expR"] for _, st, _ in rows if st["n"] >= MIN_TRADES)
        if rs:
            print(f"  Family: {len(rs)} variants, median {rs[len(rs) // 2]:+.2f}R, {sum(r > 0 for r in rs) / len(rs):.0%} profitable")
        # A setup qualifies only if the idea works broadly (most variants positive) and the chosen
        # variant made money in every calendar year of the design period.
        best = rows[0]
        years_ok = all(stats([t for t in best[2] if t["date"][:4] == y])["expR"] > 0 for y in {t["date"][:4] for t in best[2]})
        if best[1]["n"] >= MIN_TRADES and rs and rs[len(rs) // 2] > 0 and years_ok:
            chosen[key] = best[0]
            print(f"  Chosen: {best[0].label()}  ({by_year(best[2])})\n")
        else:
            print(f"  Rejected: family median must be positive and the best variant profitable every year ({by_year(best[2])})\n")

    design_trades = combine([t for v in chosen.values() for s in design for t in v.trades(s)])
    st = stats(design_trades)
    print(f"Combined playbook, design period: {fmt(st)}  ({st['n'] / len(design):.2f} trades per session)")
    write_journal_csv(RESULTS / "setups_design_trades.csv", design_trades, args.risk, cfg)
    challenge_table([s["date"] for s in design], design_trades, cfg)

    if not args.holdout:
        print("\nHoldout not evaluated. Re-run with --holdout once you are happy with the design-period choices.")
        return
    print("\n== HOLDOUT (Jan-Sep 2026), chosen variants")
    hold_all = []
    for key, v in chosen.items():
        trs = [t for s in hold for t in v.trades(s)]
        hold_all += trs
        print(f"  {v.label():62s} {fmt(stats(trs))}")
    for key, variants in all_variants().items():
        rs = sorted(stats([t for s in hold for t in v.trades(s)])["expR"] for v in variants)
        rs = [r for r in rs if r == r]
        if rs:
            print(f"  Family {key} on holdout: median {rs[len(rs) // 2]:+.2f}R, {sum(r > 0 for r in rs) / len(rs):.0%} of variants profitable")
    hold_trades = combine(hold_all)
    st = stats(hold_trades)
    print(f"\nCombined playbook, holdout: {fmt(st)}  ({st['n'] / len(hold):.2f} trades per session)")
    write_journal_csv(RESULTS / "setups_holdout_trades.csv", hold_trades, args.risk, cfg)
    challenge_table([s["date"] for s in hold], hold_trades, cfg)
    print(f"\nTrades CSVs (journal format, ${args.risk:.0f} risk): {RESULTS / 'setups_design_trades.csv'}, {RESULTS / 'setups_holdout_trades.csv'}")


if __name__ == "__main__":
    main()
