"""Build dashboard/data.js for dashboard.html from the Databento tick files and backtest results.

    .venv-nautilus/bin/python backtest/build_dashboard.py

Per trading day it exports 1-minute NQ bars (08:30-12:30 ET) with aggressor delta and session VWAP,
the key levels the strategy uses, tape statistics, and every backtest run in backtest/results.
"""
import csv
import json
import sys
from pathlib import Path

import databento as db
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DBN_DIR = ROOT / "backtest" / "data" / "dbn" / "NQ.v.0" / "tbbo"
RESULTS = ROOT / "backtest" / "results"
OUT = ROOT / "dashboard" / "data.js"
ET = "America/New_York"

RUN_LABELS = {
    "insample_structural": "Jul-Aug - structural levels (in-sample)",
    "oos_sept_structural": "Sep - structural levels (out-of-sample)",
    "oos_sept_alllevels": "Sep - all levels (out-of-sample)",
}

sys.path.insert(0, str(ROOT))
from common import load_config  # noqa: E402


def load_ticks() -> tuple[pd.DataFrame, dict]:
    """1-minute bars for all hours, plus per-ET-date RTH price/volume profiles and tape stats."""
    bars, profiles, tape = [], {}, {}
    for path in sorted(DBN_DIR.glob("*.dbn.zst")):
        df = db.DBNStore.from_file(path).to_df(price_type="float")
        if df.empty:
            continue
        df = df[df.side.isin(["A", "B"])][["ts_event", "side", "price", "size", "instrument_id"]]
        df["size"] = df["size"].astype("int64")
        df["ts"] = df.ts_event.dt.tz_convert(ET)
        df["buy"] = df["size"].where(df.side == "B", 0)
        df["sell"] = df["size"].where(df.side == "A", 0)
        g = df.set_index("ts").groupby(pd.Grouper(freq="1min"))
        b = g.agg(o=("price", "first"), h=("price", "max"), l=("price", "min"), c=("price", "last"),
                  v=("size", "sum"), buy=("buy", "sum"), sell=("sell", "sum"), inst=("instrument_id", "last")).dropna()
        bars.append(b)

        mins = df.ts.dt.hour * 60 + df.ts.dt.minute
        rth = df[(mins >= 570) & (mins < 960)]
        for day, part in rth.groupby(rth.ts.dt.date):
            key = day.isoformat()
            prof = part.groupby("price")["size"].sum()
            profiles[key] = profiles.get(key, pd.Series(dtype=float)).add(prof, fill_value=0)
            t = tape.setdefault(key, {"trades": 0, "buy": 0, "sell": 0, "maxTrade": 0})
            t["trades"] += len(part)
            t["buy"] += int(part.buy.sum())
            t["sell"] += int(part.sell.sum())
            t["maxTrade"] = max(t["maxTrade"], int(part["size"].max()))
        print(f"  {path.name}: {len(df):,} trades", flush=True)
    allbars = pd.concat(bars)
    allbars = allbars[~allbars.index.duplicated(keep="last")].sort_index()
    return allbars, profiles, tape


def value_area(profile: pd.Series, share: float = 0.70) -> tuple[float, float, float]:
    prices = profile.sort_index()
    poc_i = int(prices.values.argmax())
    lo = hi = poc_i
    target = prices.sum() * share
    acc = prices.iloc[poc_i]
    while acc < target and (lo > 0 or hi < len(prices) - 1):
        down = prices.iloc[lo - 1] if lo > 0 else -1
        up = prices.iloc[hi + 1] if hi < len(prices) - 1 else -1
        if up >= down:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += down
    return float(prices.index[poc_i]), float(prices.index[hi]), float(prices.index[lo])


def build_days(bars: pd.DataFrame, profiles: dict, tape: dict) -> list[dict]:
    mins = bars.index.hour * 60 + bars.index.minute
    rth_mask = (mins >= 570) & (mins < 960) & (bars.index.dayofweek < 5)
    rth_days = sorted({d.isoformat() for d in bars.index[rth_mask].date})
    days = []
    for i, day in enumerate(rth_days):
        d = pd.Timestamp(day, tz=ET)
        rth = bars[(bars.index >= d + pd.Timedelta(minutes=570)) & (bars.index < d + pd.Timedelta(minutes=960))]
        if len(rth) < 60:
            continue
        levels = []
        if i > 0:
            prev = pd.Timestamp(rth_days[i - 1], tz=ET)
            prth = bars[(bars.index >= prev + pd.Timedelta(minutes=570)) & (bars.index < prev + pd.Timedelta(minutes=960))]
            rolled = len(prth) and prth.inst.iloc[-1] != rth.inst.iloc[0]
            if len(prth) and not rolled:
                levels += [("PDH", prth.h.max(), "structural"), ("PDL", prth.l.min(), "structural")]
                if rth_days[i - 1] in profiles:
                    poc, vah, val = value_area(profiles[rth_days[i - 1]])
                    levels += [("PD VAH", vah, "structural"), ("PD VAL", val, "structural"), ("PD POC", poc, "context")]
            on = bars[(bars.index >= prev + pd.Timedelta(hours=18)) & (bars.index < d + pd.Timedelta(minutes=570))]
            if len(on) and on.inst.iloc[-1] == rth.inst.iloc[0]:
                levels += [("ONH", on.h.max(), "structural"), ("ONL", on.l.min(), "structural")]
        ib = rth[rth.index < d + pd.Timedelta(minutes=630)]
        levels += [("IBH", ib.h.max(), "structural"), ("IBL", ib.l.min(), "structural")]

        tp = (rth.h + rth.l + rth.c) / 3
        vwap = (tp * rth.v).cumsum() / rth.v.cumsum()
        view = bars[(bars.index >= d + pd.Timedelta(minutes=510)) & (bars.index < d + pd.Timedelta(minutes=750))]
        view = view[view.inst == rth.inst.iloc[0]]
        vw = vwap.reindex(view.index)
        days.append({
            "date": day,
            "contract": int(rth.inst.iloc[0]),
            "rth": {"o": float(rth.o.iloc[0]), "h": float(rth.h.max()), "l": float(rth.l.min()), "c": float(rth.c.iloc[-1]),
                    "v": int(rth.v.sum())},
            "levels": [{"name": n, "price": round(float(p), 2), "kind": k} for n, p, k in levels],
            "tape": tape.get(day),
            "bars": {
                "t": [int(ts.hour * 60 + ts.minute) for ts in view.index],
                "o": view.o.round(2).tolist(), "h": view.h.round(2).tolist(),
                "l": view.l.round(2).tolist(), "c": view.c.round(2).tolist(),
                "v": view.v.astype(int).tolist(), "d": (view.buy - view.sell).astype(int).tolist(),
                "vwap": [None if pd.isna(x) else round(float(x), 2) for x in vw],
            },
        })
    return days


def approx_exit_minute(day: dict | None, entry_min: int, exit_px: float) -> int | None:
    if not day:
        return None
    b = day["bars"]
    for t, h, l in zip(b["t"], b["h"], b["l"]):
        if t > entry_min and l - 0.25 <= exit_px <= h + 0.25:
            return t
    return None


def load_runs(days_by_date: dict) -> list[dict]:
    runs = []
    for path in sorted(RESULTS.glob("*_trades.csv")):
        # setups_* come from 1-minute-bar research spanning 2024-2026; the dashboard only has tick days for Jul-Sep 2026.
        if path.name.startswith(("SYNTHETIC", "setups_")):
            continue
        rid = path.name.removesuffix("_trades.csv")
        trades = []
        with open(path) as f:
            for r in csv.DictReader(f):
                hh, mm = map(int, r["time"].split(":"))
                entry_min = hh * 60 + mm
                t = {k: r[k] for k in ("date", "time", "side", "contract", "notes")}
                t.update({k: float(r[k]) if r[k] not in ("", None) else None for k in ("qty", "entry", "stop", "exit", "mfe", "mae")})
                t["entryMin"] = entry_min
                t["exitMin"] = approx_exit_minute(days_by_date.get(r["date"]), entry_min, t["exit"])
                trades.append(t)
        summary = path.with_name(f"{rid}_summary.txt")
        runs.append({"id": rid, "label": RUN_LABELS.get(rid, rid.replace("_", " ")), "trades": trades,
                     "summary": summary.read_text() if summary.exists() else ""})
    return runs


def main():
    if not DBN_DIR.exists():
        sys.exit(f"No tick data in {DBN_DIR}. Run backtest/fetch_data.py first.")
    print("Reading tick files...")
    bars, profiles, tape = load_ticks()
    days = build_days(bars, profiles, tape)
    runs = load_runs({d["date"]: d for d in days})
    data = {"generated": pd.Timestamp.now(tz=ET).strftime("%Y-%m-%d %H:%M ET"), "symbol": "NQ.v.0",
            "rules": load_config(), "days": days, "runs": runs}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("window.DASHBOARD_DATA = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(days)} days, {sum(len(r['trades']) for r in runs)} trades in {len(runs)} runs, "
          f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
