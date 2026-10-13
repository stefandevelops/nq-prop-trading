"""Backtest the Absorption Reversal strategy on a Nautilus catalog and export journal-ready trades.

Examples:
    python backtest/run_backtest.py --sample                                  # synthetic pipeline test
    python backtest/run_backtest.py --start 2025-01-02 --end 2025-01-31       # real data in backtest/data/catalog
    python backtest/run_backtest.py --news-file backtest/news_days.txt --set min_aggressor_share=0.65
"""

import argparse
import csv
import json
import re
import sys
import warnings
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, PerContractFeeModel
from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import AccountType, AssetClass, BookType, OmsType
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from fetch_data import DEFAULT_CATALOG, REPO_DIR
from make_sample_data import SAMPLE_CATALOG
from strategies.absorption import AbsorptionConfig, AbsorptionStrategy, et_ns

sys.path.insert(0, str(REPO_DIR))
from common import CONTRACTS, cost_per_contract, load_config  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"
JOURNAL_COLUMNS = ["date", "time", "setup", "side", "contract", "qty", "entry", "stop", "exit",
                   "mfe", "mae", "rules", "notes", "stopEstimated"]
SYNTHETIC_BANNER = "SYNTHETIC DATA - pipeline test only, results are meaningless"

warnings.filterwarnings("ignore", message="Timestamp.utcnow is deprecated")


def make_instrument(instrument_id: InstrumentId, contract: str) -> FuturesContract:
    # The traded contract's multiplier is applied to whatever price series is in the catalog:
    # MNQ on NQ prices is a close proxy (same index, MNQ just has thinner books).
    spec = CONTRACTS[contract]
    ts = pd.Timestamp("2000-01-01", tz="UTC").value
    return FuturesContract(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        asset_class=AssetClass.INDEX,
        currency=USD,
        price_precision=2,
        price_increment=Price.from_str(f"{spec.tick_size:.2f}"),
        multiplier=Quantity.from_int(int(spec.point_value)),
        lot_size=Quantity.from_int(1),
        underlying=contract,
        activation_ns=ts,
        expiration_ns=pd.Timestamp("2100-01-01", tz="UTC").value,
        ts_event=ts,
        ts_init=ts,
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
        exchange="XCME",
    )


def read_news_file(path: Path | None) -> tuple[str, ...]:
    if not path:
        return ()
    events = []
    for line in path.read_text().splitlines():
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}))?", line)
        if m and not line.lstrip().startswith("#"):
            events.append(f"{m[1]} {m[2]}" if m[2] else m[1])
    return tuple(events)


def parse_overrides(items: list[str]) -> dict:
    out = {}
    for item in items:
        key, _, raw = item.partition("=")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


def session_dates(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def session_date(t: pd.Timestamp) -> date:
    """CME trading date: Globex trading from 18:00 ET belongs to the next day's session."""
    return (t.tz_convert("America/New_York") + pd.Timedelta(hours=6)).date()


def ts(ns: int) -> pd.Timestamp:
    return pd.Timestamp(ns, tz="UTC")


def run(args) -> tuple[list[dict], dict]:
    cfg = load_config()
    plan = cfg["plan"]
    catalog = ParquetDataCatalog(str(args.catalog))
    iid = InstrumentId.from_str(args.instrument_id)
    first = catalog.query_first_timestamp(TradeTick, str(iid))
    last = catalog.query_last_timestamp(TradeTick, str(iid))
    if first is None:
        sys.exit(f"No trade data for {iid} in {args.catalog}. Run fetch_data.py or make_sample_data.py first.")
    start = args.start or session_date(first)
    end = args.end or session_date(last)

    c = cfg["costs"][args.contract]
    strategy_config = AbsorptionConfig(**{
        "instrument_id": iid,
        "contract": args.contract,
        "point_value": CONTRACTS[args.contract].point_value,
        "tick_size": CONTRACTS[args.contract].tick_size,
        "risk_usd": args.risk or plan["risk_per_trade"],
        "cost_per_contract": cost_per_contract(cfg, args.contract),
        "max_contracts": cfg["max_contracts"][args.contract],
        "max_stop_pts": min(25.0, plan["stop_points"]),
        "max_trades_per_day": plan["max_trades_per_day"],
        "max_losses_per_day": plan["max_losses_per_day"],
        "daily_loss_stop": plan["daily_loss_stop"],
        "daily_profit_goal": plan["daily_profit_goal"],
        "news_events": read_news_file(args.news_file),
        **parse_overrides(args.set),
    })

    engine = BacktestEngine(BacktestEngineConfig(
        trader_id=TraderId("BACKTESTER-001"),
        logging=LoggingConfig(log_level=args.log_level),
    ))
    engine.add_venue(
        venue=Venue(iid.venue.value),
        oms_type=OmsType.NETTING,
        account_type=AccountType.MARGIN,
        base_currency=USD,
        starting_balances=[Money(cfg["starting_balance"], USD)],
        # Fills happen at the touch (spread included). The 1-tick slippage from challenge.json is
        # charged in the reported $ figures instead, exactly as the journal does, so it is not double counted.
        fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0),
        fee_model=PerContractFeeModel(Money(c["commission_rt"] / 2, USD)),
        book_type=BookType.L1_MBP,
    )
    engine.add_instrument(make_instrument(iid, args.contract))
    strategy = AbsorptionStrategy(strategy_config)
    engine.add_strategy(strategy)

    print(f"Backtesting {iid} as {args.contract}, {start} to {end}")
    for d in session_dates(start, end):
        lo, hi = et_ns(d - timedelta(days=1), "18:00"), et_ns(d, "18:00") - 1
        trades = catalog.query(TradeTick, identifiers=[str(iid)], start=ts(lo), end=ts(hi))
        if not trades:
            continue
        q_lo = et_ns(d, strategy_config.rth_open) - 5 * 60 * 10**9
        q_hi = et_ns(d, strategy_config.flatten_time) + 5 * 60 * 10**9
        quotes = catalog.query(QuoteTick, identifiers=[str(iid)], start=ts(q_lo), end=ts(q_hi))
        engine.add_data(trades + quotes)
        engine.run(streaming=True)
        engine.clear_data()
        print(f"  {d}: {len(trades):,} trades, {len(quotes):,} quotes, {len(strategy.trades)} strategy trades so far")
    engine.end()
    engine.dispose()
    return strategy.trades, {"start": start, "end": end, "cfg": cfg}


def summarize(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0}
    nets = [t["net_usd"] for t in trades]
    rs = [t["r"] for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    equity = peak = max_dd = 0.0
    streak = worst = 0
    for x in nets:
        equity += x
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        streak = streak + 1 if x < 0 else 0
        worst = max(worst, streak)
    exits: dict[str, int] = {}
    for t in trades:
        exits[t["exit_reason"]] = exits.get(t["exit_reason"], 0) + 1
    return {
        "trades": n,
        "days_traded": len({t["date"] for t in trades}),
        "win_rate": len(wins) / n,
        "expectancy_r": sum(rs) / n,
        "expectancy_usd": sum(nets) / n,
        "net_usd": sum(nets),
        "profit_factor": sum(wins) / -sum(losses) if losses else float("inf"),
        "max_drawdown_usd": max_dd,
        "worst_losing_streak": worst,
        "reached": {k: sum(t["mfe"] >= k * t["risk_pts"] for t in trades) / n for k in (1, 2, 3)},
        "avg_stop_pts": sum(t["risk_pts"] for t in trades) / n,
        "avg_qty": sum(t["qty"] for t in trades) / n,
        "exits": exits,
    }


def format_summary(s: dict, header: str) -> str:
    lines = [header, ""]
    if not s["trades"]:
        return "\n".join(lines + ["No trades."])
    lines += [
        f"Trades:               {s['trades']} on {s['days_traded']} days",
        f"Win rate:             {s['win_rate']:.1%}",
        f"Expectancy:           {s['expectancy_r']:+.2f}R per trade (gross), ${s['expectancy_usd']:+.2f} per trade (net)",
        f"Net P&L:              ${s['net_usd']:+,.2f}",
        f"Profit factor:        {s['profit_factor']:.2f}",
        f"Max drawdown:         ${s['max_drawdown_usd']:,.2f} (closed-trade equity)",
        f"Worst losing streak:  {s['worst_losing_streak']}",
        f"Price reached 1R/2R/3R before the original stop: "
        + " / ".join(f"{s['reached'][k]:.0%}" for k in (1, 2, 3)),
        f"Average stop:         {s['avg_stop_pts']:.2f} pts, average size {s['avg_qty']:.1f} contracts",
        "Exits:                " + ", ".join(f"{k} {v}" for k, v in sorted(s["exits"].items(), key=lambda kv: -kv[1])),
        "",
        "$ figures are net of commission + slippage per challenge.json (same formula as the journal).",
        "R is gross price movement / initial stop distance, as the journal computes it.",
    ]
    return "\n".join(lines)


def write_csv(path: Path, trades: list[dict], synthetic: bool) -> None:
    def tick(x: float) -> float:
        return round(round(x / 0.25) * 0.25, 2)

    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(JOURNAL_COLUMNS)
        for t in trades:
            row = {**t, "mfe": tick(t["mfe"]), "mae": tick(t["mae"]), "rules": "true", "stopEstimated": "false",
                   "notes": ("SYNTHETIC - " if synthetic else "Backtest - ") + t["notes"]}
            w.writerow([row[k] for k in JOURNAL_COLUMNS])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sample", action="store_true", help="use the synthetic sample catalog (pipeline test)")
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--instrument-id", default="NQ.GLBX", help="price series in the catalog")
    p.add_argument("--contract", choices=list(CONTRACTS), default=None, help="contract to trade (default: plan contract)")
    p.add_argument("--start", type=date.fromisoformat, help="first session date (ET), default: catalog start")
    p.add_argument("--end", type=date.fromisoformat, help="last session date (ET, inclusive), default: catalog end")
    p.add_argument("--risk", type=float, help="$ risk per trade (default: challenge.json plan)")
    p.add_argument("--news-file", type=Path, help="lines of 'YYYY-MM-DD' (skip day) or 'YYYY-MM-DD HH:MM' (ET blackout)")
    p.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE", help="override any AbsorptionConfig field")
    p.add_argument("--log-level", default="ERROR")
    args = p.parse_args()
    if args.sample:
        args.catalog = SAMPLE_CATALOG
    args.contract = args.contract or load_config()["plan"]["contract"]

    trades, meta = run(args)
    s = summarize(trades)
    tag = "SYNTHETIC_" if args.sample else ""
    stem = f"{tag}absorption_{args.contract}_{meta['start']}_{meta['end']}"
    RESULTS_DIR.mkdir(exist_ok=True)
    csv_path = RESULTS_DIR / f"{stem}_trades.csv"
    txt_path = RESULTS_DIR / f"{stem}_summary.txt"
    header = f"Absorption Reversal backtest, {args.contract}, {meta['start']} to {meta['end']}"
    if args.sample:
        header = f"*** {SYNTHETIC_BANNER} ***\n{header}"
    text = format_summary(s, header)
    write_csv(csv_path, trades, args.sample)
    txt_path.write_text(text + "\n")
    print()
    print(text)
    print(f"\nTrades CSV (journal format): {csv_path}\nSummary: {txt_path}")


if __name__ == "__main__":
    main()
