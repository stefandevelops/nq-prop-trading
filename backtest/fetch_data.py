"""Download CME Globex NQ/MNQ data from Databento and load it into a Nautilus catalog.

Always prints Databento's cost quote first; nothing is downloaded without --yes.

Examples:
    python backtest/fetch_data.py --start 2025-01-02 --end 2025-02-01            # quote only
    python backtest/fetch_data.py --start 2025-01-02 --end 2025-02-01 --yes      # download + load
    python backtest/fetch_data.py --symbol MNQ.v.0 --start 2025-01-02 --end 2025-02-01 --yes
    python backtest/fetch_data.py --load-only --symbol NQ.v.0 --schema tbbo      # reload saved DBN files
"""

import argparse
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from nautilus_trader.adapters.databento.loaders import DatabentoDataLoader
from nautilus_trader.model.data import OrderBookDepth10, QuoteTick, TradeTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.persistence.catalog import ParquetDataCatalog

BACKTEST_DIR = Path(__file__).resolve().parent
REPO_DIR = BACKTEST_DIR.parent
DATA_DIR = BACKTEST_DIR / "data"
DEFAULT_CATALOG = DATA_DIR / "catalog"
DATASET = "GLBX.MDP3"
VENUE = "GLBX"
PRICE_PRECISION = 2
SCHEMAS = ["tbbo", "trades", "mbp-1", "mbp-10"]
MANIFEST = "_loaded_files.json"


def load_api_key() -> str | None:
    key = os.environ.get("DATABENTO_API_KEY")
    if key:
        return key.strip()
    for env_file in (REPO_DIR / ".env", BACKTEST_DIR / ".env"):
        if not env_file.exists():
            continue
        for line in env_file.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip().removeprefix("export ").strip() == "DATABENTO_API_KEY":
                return value.strip().strip("'\"")
    return None


def stype_for(symbol: str) -> str:
    if re.fullmatch(r"[A-Z0-9]+\.[cvn]\.\d+", symbol):
        return "continuous"
    if symbol.endswith((".FUT", ".OPT")):
        return "parent"
    return "raw_symbol"


def default_instrument_id(symbol: str) -> InstrumentId:
    root = symbol.split(".")[0] if stype_for(symbol) == "continuous" else symbol
    return InstrumentId.from_str(f"{root}.{VENUE}")


def dbn_dir(symbol: str, schema: str) -> Path:
    return DATA_DIR / "dbn" / symbol / schema


def download_days(start: date, end: date):
    d = start
    while d < end:
        if d.weekday() != 5:  # CME Globex is closed all of Saturday (UTC)
            yield d
        d += timedelta(days=1)


def load_dbn_to_catalog(files: list[Path], catalog_path: Path, instrument_id: InstrumentId) -> int:
    """Convert DBN files to Nautilus ticks and append them to the catalog. Returns ticks written."""
    catalog_path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(catalog_path))
    manifest_path = catalog_path / MANIFEST
    loaded = set(json.loads(manifest_path.read_text())) if manifest_path.exists() else set()
    loader = DatabentoDataLoader()
    written = 0
    for path in sorted(files):
        key = f"{instrument_id}|{path.parent.name}|{path.name}"
        if key in loaded:
            continue
        data = loader.from_dbn_file(
            path,
            instrument_id=instrument_id,
            price_precision=PRICE_PRECISION,
            include_trades=True,
        )
        trades = [x for x in data if isinstance(x, TradeTick)]
        quotes = [x for x in data if isinstance(x, QuoteTick)]
        depth = [x for x in data if isinstance(x, OrderBookDepth10)]
        quotes += [x.to_quote_tick() for x in depth]
        quotes.sort(key=lambda q: q.ts_init)
        for batch in (trades, quotes, depth):
            if batch:
                catalog.write_data(batch)
                written += len(batch)
        loaded.add(key)
        manifest_path.write_text(json.dumps(sorted(loaded), indent=1))
        print(f"  loaded {path.name}: {len(trades):,} trades, {len(quotes):,} quotes" + (f", {len(depth):,} depth" if depth else ""))
    return written


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=date.fromisoformat, help="first UTC date, YYYY-MM-DD")
    p.add_argument("--end", type=date.fromisoformat, help="end UTC date (exclusive), YYYY-MM-DD")
    p.add_argument("--symbol", default="NQ.v.0",
                   help="NQ.v.0 = front month by volume (recommended), NQ.c.0 = by calendar, or a raw contract like NQH5")
    p.add_argument("--schema", nargs="+", choices=SCHEMAS, default=["tbbo"],
                   help="tbbo (default): every trade + the best bid/ask just before it. trades: trades only. "
                        "mbp-1: every top-of-book change (much larger). mbp-10: 10-level depth (largest).")
    p.add_argument("--instrument-id", help="Nautilus instrument ID to store the data under (default e.g. NQ.GLBX)")
    p.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    p.add_argument("--yes", action="store_true", help="actually download (costs money) after showing the quote")
    p.add_argument("--load-only", action="store_true", help="skip Databento; load already downloaded DBN files")
    args = p.parse_args(argv)
    if not args.load_only:
        if not (args.start and args.end):
            p.error("--start and --end are required unless --load-only")
        if args.end <= args.start:
            p.error("--end must be after --start")
    if stype_for(args.symbol) == "parent":
        p.error("parent symbols (e.g. NQ.FUT) mix every expiry and spread; use NQ.v.0 or a single contract")
    return args


def main(argv=None) -> None:
    args = parse_args(argv)
    instrument_id = InstrumentId.from_str(args.instrument_id) if args.instrument_id else default_instrument_id(args.symbol)

    if not args.load_only:
        key = load_api_key()
        if not key:
            sys.exit("DATABENTO_API_KEY not found. Set it in your shell or in Trading/.env (see backtest/README.md).")
        import databento as db

        client = db.Historical(key)
        stype_in = stype_for(args.symbol)
        query = dict(dataset=DATASET, symbols=[args.symbol], stype_in=stype_in,
                     start=args.start.isoformat(), end=args.end.isoformat())
        print(f"Databento quote for {args.symbol} ({stype_in}), {args.start} to {args.end} (end exclusive):")
        total = 0.0
        for schema in args.schema:
            cost = client.metadata.get_cost(schema=schema, **query)
            size = client.metadata.get_billable_size(schema=schema, **query)
            total += cost
            print(f"  {schema:7s} {size / 1e9:8.2f} GB   ${cost:,.2f}")
        print(f"  total   ${total:,.2f}  (usage-based list price; plan credits/subscriptions may change what you pay)")
        if not args.yes:
            print("Nothing downloaded. Re-run with --yes to download.")
            return

        for schema in args.schema:
            out_dir = dbn_dir(args.symbol, schema)
            out_dir.mkdir(parents=True, exist_ok=True)
            for day in download_days(args.start, args.end):
                path = out_dir / f"{day.isoformat()}.dbn.zst"
                if path.exists():
                    continue
                print(f"  downloading {schema} {day}")
                part = path.with_suffix(".part")
                client.timeseries.get_range(schema=schema, path=part, **{**query, "start": day.isoformat(),
                                                                          "end": (day + timedelta(days=1)).isoformat()})
                part.rename(path)

    print(f"Loading into catalog {args.catalog} as {instrument_id}")
    total = 0
    for schema in args.schema:
        files = sorted(dbn_dir(args.symbol, schema).glob("*.dbn.zst"))
        if args.start:
            files = [f for f in files if args.start.isoformat() <= f.name[:10] < (args.end or date.max).isoformat()]
        total += load_dbn_to_catalog(files, args.catalog, instrument_id)
    print(f"Done. {total:,} new ticks written.")


if __name__ == "__main__":
    main()
