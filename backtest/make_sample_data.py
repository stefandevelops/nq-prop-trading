"""Generate a small SYNTHETIC NQ tbbo dataset (trades + best bid/ask) to test the pipeline.

The data is a random walk with a few injected "absorption at a key level" episodes per day,
some of which reverse and some of which break. It exists only so the pipeline can run
end-to-end without a Databento key. Backtest results on it are meaningless.

    python backtest/make_sample_data.py            # writes backtest/data/sample/{dbn,catalog}
"""

import argparse
import random
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import databento_dbn as dbn
import zstandard
from nautilus_trader.model.identifiers import InstrumentId

from fetch_data import DATA_DIR, DATASET, load_dbn_to_catalog
from strategies.absorption import NY

SAMPLE_DIR = DATA_DIR / "sample"
SAMPLE_CATALOG = SAMPLE_DIR / "catalog"
SAMPLE_INSTRUMENT = InstrumentId.from_str("NQ.GLBX")
SYMBOL = "NQ.v.0"
TICK = 0.25
FIXED = 1_000_000_000
NS = 1_000_000_000


def et(d: date, h: int, m: int = 0) -> int:
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=NY).timestamp()) * NS


class TapeGenerator:
    """Tick-level random walk. Price state is the best bid in ticks; ask is one tick above."""

    def __init__(self, rng: random.Random, start_px: float):
        self.rng = rng
        self.px = round(start_px / TICK)
        self.t = 0
        self.events: list[tuple] = []

    def run(self, until: int, rate: float, buy_prob: float, size_mean: float = 2.0, move_prob: float = 0.5,
            cap_hi: int | None = None, cap_lo: int | None = None, passive: tuple[int, int] = (5, 40),
            stop_when=None) -> bool:
        """Emit trades until `until` (ns) or until stop_when(px) is true. Returns True if stopped early."""
        rng = self.rng
        while True:
            self.t += int(rng.expovariate(rate) * NS) + 1
            if self.t >= until:
                self.t = until
                return False
            is_buy = rng.random() < buy_prob
            size = 1 + int(rng.expovariate(1.0 / max(size_mean - 1, 0.1)))
            bid_sz, ask_sz = rng.randint(5, 40), rng.randint(5, 40)
            if is_buy:
                ask_sz = rng.randint(*passive)
            else:
                bid_sz = rng.randint(*passive)
            self.events.append((self.t, self.px + 1 if is_buy else self.px, size, is_buy, self.px, bid_sz, ask_sz))
            if rng.random() < move_prob:
                new = self.px + (1 if is_buy else -1)
                if cap_hi is not None:
                    new = min(new, cap_hi)
                if cap_lo is not None:
                    new = max(new, cap_lo)
                self.px = new
            if stop_when and stop_when(self.px):
                return True


def toward(p: float, d: int) -> float:
    return p if d == 1 else 1 - p


def absorption_episode(g: TapeGenerator, rng: random.Random, levels: dict[str, float]) -> None:
    candidates = [(abs(lv / TICK - g.px), lv) for lv in levels.values() if 32 <= abs(lv / TICK - g.px) <= 240]
    if not candidates:
        return
    level = round(min(candidates)[1] / TICK)
    d = 1 if level > g.px else -1  # +1: resistance above (buyers get absorbed), -1: support below
    pin = level - 1 if d == 1 else level  # aggressive prints land exactly on the level
    reached = g.run(g.t + 6 * 60 * NS, 5, toward(0.68, d), stop_when=lambda px: (px - pin) * d >= 0)
    if not reached:
        return
    cap = dict(cap_hi=pin) if d == 1 else dict(cap_lo=pin)
    for push in range(3):
        g.run(g.t + 20 * NS, 8, toward(0.85, d), size_mean=5, passive=(80, 160), **cap)
        if push < 2:
            g.run(g.t + 5 * NS, 6, toward(0.2, d), **cap)
    outcome = rng.random()
    if outcome < 0.5:  # reversal
        g.run(g.t + rng.randint(3, 6) * 60 * NS, 4, toward(0.4, d))
    elif outcome < 0.75:  # brief shift that fails, then the level breaks
        g.run(g.t + 20 * NS, 5, toward(0.3, d))
        g.run(g.t + 2 * 60 * NS, 5, toward(0.7, d), size_mean=3)
    else:  # breaks straight through
        g.run(g.t + 2 * 60 * NS, 5, toward(0.7, d), size_mean=3)


def generate_session(g: TapeGenerator, rng: random.Random, d: date, prior: dict[str, float]) -> dict[str, float]:
    g.t = et(d - timedelta(days=1), 18)
    g.run(et(d, 9, 30), 0.3, 0.5 + rng.uniform(-0.01, 0.01))
    on = [e[1] * TICK for e in g.events]
    levels = dict(prior)
    levels["ONH"], levels["ONL"] = max(on), min(on)
    rth_start = len(g.events)

    episode_times = sorted(et(d, 9, 40) + rng.randint(0, 95 * 60) * NS for _ in range(3))
    for ep in episode_times:
        if ep > g.t:
            g.run(ep, 4, 0.5 + rng.uniform(-0.03, 0.03))
        base = (g.px * TICK // 100) * 100
        absorption_episode(g, rng, {**levels, "R0": base, "R1": base + 100})
    g.run(et(d, 11, 30), 4, 0.5 + rng.uniform(-0.03, 0.03))
    g.run(et(d, 16), 1.5, 0.5 + rng.uniform(-0.02, 0.02))
    rth = [e[1] * TICK for e in g.events[rth_start:]]
    return {"PDH": max(rth), "PDL": min(rth)}


def write_dbn(path: Path, events: list[tuple], instrument_id: int = 1) -> None:
    meta = dbn.Metadata(
        dataset=DATASET, start=events[0][0], end=events[-1][0] + 1, stype_in=dbn.SType.CONTINUOUS,
        stype_out=dbn.SType.INSTRUMENT_ID, schema=dbn.Schema.TBBO, symbols=[SYMBOL],
    )
    buf = bytearray(meta.encode())
    for ts, px, size, is_buy, bid, bid_sz, ask_sz in events:
        rec = dbn.MBP1Msg(
            publisher_id=1, instrument_id=instrument_id, ts_event=ts, ts_recv=ts + 50_000,
            price=int(px * TICK * FIXED), size=size, action=dbn.Action.TRADE,
            side=dbn.Side.BID if is_buy else dbn.Side.ASK, depth=0, flags=0x80,
            levels=dbn.BidAskPair(bid_px=int(bid * TICK * FIXED), ask_px=int((bid + 1) * TICK * FIXED),
                                  bid_sz=bid_sz, ask_sz=ask_sz, bid_ct=1, ask_ct=1),
        )
        buf += bytes(rec)
    path.write_bytes(zstandard.ZstdCompressor().compress(bytes(buf)))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=date.fromisoformat, default=date(2025, 1, 6))
    p.add_argument("--days", type=int, default=15, help="trading days to generate")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    if SAMPLE_DIR.exists():
        shutil.rmtree(SAMPLE_DIR)
    out_dir = SAMPLE_DIR / "dbn" / SYMBOL / "tbbo"
    out_dir.mkdir(parents=True)
    rng = random.Random(args.seed)
    g = TapeGenerator(rng, 21000.0)
    prior: dict[str, float] = {}
    d, made, files = args.start, 0, []
    while made < args.days:
        if d.weekday() < 5:
            g.events = []
            prior = generate_session(g, rng, d, prior)
            path = out_dir / f"{d.isoformat()}.dbn.zst"
            write_dbn(path, g.events)
            files.append(path)
            made += 1
            print(f"  SYNTHETIC {d}: {len(g.events):,} trades")
        d += timedelta(days=1)

    load_dbn_to_catalog(files, SAMPLE_CATALOG, SAMPLE_INSTRUMENT)
    print(f"SYNTHETIC sample catalog ready at {SAMPLE_CATALOG} ({SAMPLE_INSTRUMENT}). Results on it are meaningless.")


if __name__ == "__main__":
    main()
