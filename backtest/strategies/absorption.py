"""Absorption Reversal at Key Levels (PLAYBOOK.md) as a NautilusTrader strategy.

A mechanical approximation of a discretionary order-flow read, built from trade ticks
(aggressor side) and optionally top-of-book sizes:

1. Key levels: prior-day RTH high/low (+ value area high/low/POC), overnight high/low,
   developing RTH VWAP, initial balance high/low, round numbers.
2. Absorption: within a short window price pushes into a level with heavy, one-sided
   aggressive volume, yet the window extreme stays within a small tolerance of the level,
   has stopped extending for a while, and was tested more than once.
3. Shift: price trades back through the level and short-term delta flips to the other side.
4. Management: stop beyond the absorption extreme (max 25 pts), half off at 1R with stop to
   breakeven, rest at 2R or VWAP, 10-minute time stop, entries 9:35-11:30 ET, daily rules.

All prices are in index points; times are America/New_York.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import AggressorSide, OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.trading.strategy import Strategy

NY = ZoneInfo("America/New_York")
NS = 1_000_000_000
SETUP_NAME = "Absorption reversal"


class AbsorptionConfig(StrategyConfig, frozen=True):
    instrument_id: InstrumentId

    # --- Contract and sizing (defaults: MNQ, numbers from challenge.json) ---
    contract: str = "MNQ"
    point_value: float = 2.0            # $ per point per contract (MNQ 2, NQ 20)
    tick_size: float = 0.25
    risk_usd: float = 200.0             # fixed $ risk per trade
    cost_per_contract: float = 1.80     # round-turn commission + slippage $, included in sizing like sizer.py
    max_contracts: int = 50

    # --- Key levels ---
    use_prior_day_hl: bool = True
    # Defaults trade structural levels only: round numbers, VWAP and POC as entry levels lost money
    # both in-sample (Jul-Aug 2026) and out-of-sample (Sep 2026). VWAP is still used as a target.
    use_value_area: bool = True         # prior-day RTH value area high/low
    use_poc: bool = False               # prior-day RTH point of control (needs use_value_area)
    value_area_pct: float = 0.70
    use_overnight_hl: bool = True       # Globex 18:00-09:30 high/low, active from the RTH open
    use_vwap: bool = False              # developing VWAP anchored at the RTH open, as an entry level
    use_initial_balance: bool = True    # 9:30-10:30 high/low, active after 10:30
    round_number_step: float = 0.0      # e.g. 100 adds round-number levels; 0 disables
    level_tolerance_pts: float = 3.0    # "at the level": extreme within this distance short of the level
    max_penetration_pts: float = 3.0    # extreme may poke at most this far through the level

    # --- Absorption detection ---
    absorption_window_secs: int = 60    # lookback for aggression and stall
    avg_volume_lookback_mins: int = 30  # baseline for "heavy" volume
    min_volume_multiple: float = 1.2    # window volume must be >= this x the average volume per window
    min_window_volume: int = 0          # optional absolute floor in contracts of the traded instrument
    min_aggressor_share: float = 0.50   # share of window volume hitting into the level; on real NQ 60s windows are near 50/50 (p90 ~57%)
    min_absorbed_ratio: float = 0.02    # aggressive volume traded within push_zone_pts of the extreme, as a fraction of
                                        # average window volume (NQ is thin per price: p90 ~0.02-0.03 in Jul 2026)
    max_extreme_distance_pts: float = 5.0  # price must still be this close to the extreme when the setup arms
    min_pushes: int = 2                 # separate tests of the extreme within the window
    push_zone_pts: float = 1.0          # within this of the extreme counts as a test
    push_reset_pts: float = 1.5         # pullback needed between two tests
    min_stall_secs: int = 5             # extreme must be at least this old: aggression is no longer extending price
    min_passive_size: int = 0           # >0: average passive size at the extreme while being hit (needs quotes; proxy for "liquidity holds")
    max_level_tests: int = 3            # skip a level once it has been tested more often than this today
    level_test_gap_secs: int = 300      # touches closer together than this are one test

    # --- Entry trigger (the shift) ---
    trigger_timeout_secs: int = 120     # absorption must turn into a shift within this time
    shift_pts: float = 1.0              # price must trade this far back through the level/extreme
    shift_window_secs: int = 15         # delta over this window must flip to the entry side
    break_pts: float = 2.0              # price beyond the extreme by more than this = level broke, cancel

    # --- Risk and targets ---
    stop_buffer_pts: float = 3.0        # stop distance beyond the absorption extreme
    min_stop_pts: float = 6.0           # tighter logical stops are widened to this (noise floor)
    max_stop_pts: float = 25.0          # wider stops: skip the trade
    min_room_r: float = 1.5             # open space to the next level/VWAP in R; 0 disables
    t1_r: float = 1.0
    t1_fraction: float = 0.5            # share closed at T1, rest gets a breakeven stop
    t2_r: float = 2.0
    t2_use_vwap: bool = True            # take the rest at VWAP if it is between T1 and T2
    time_stop_mins: int = 10            # exit if T1 not reached within this time
    max_hold_mins: int = 30             # hard exit for the runner after T1
    exit_on_opposite_absorption: bool = True
    mfe_horizon_mins: int = 60          # keep measuring MFE after exit until the original stop or this horizon

    # --- Session (ET) ---
    entry_start: str = "09:35"
    entry_end: str = "11:30"
    flatten_time: str = "12:00"
    rth_open: str = "09:30"
    rth_close: str = "16:00"
    ib_end: str = "10:30"
    globex_open: str = "18:00"

    # --- News: "YYYY-MM-DD" skips the day, "YYYY-MM-DD HH:MM" (ET) blocks a window around it ---
    news_events: tuple[str, ...] = ()
    news_before_mins: int = 5
    news_after_mins: int = 15

    # --- Daily rules ---
    max_trades_per_day: int = 4
    max_losses_per_day: int = 2
    daily_loss_stop: float = 400.0
    daily_profit_goal: float = 500.0
    giveback_rule: bool = True          # stop once up 2R and 1R of it has been given back


class RollingFlow:
    """Trades in a sliding time window with running buy/sell volume and O(1) window high/low."""

    def __init__(self, window_secs: int):
        self.window_ns = window_secs * NS
        self.trades: deque = deque()  # (ts, price, size, is_buy, passive_size)
        self.buy = 0
        self.sell = 0
        self._max: deque = deque()    # (ts, price); front is the earliest occurrence of the window high
        self._min: deque = deque()

    def add(self, ts: int, price: float, size: int, is_buy: bool, passive: int) -> None:
        self.trades.append((ts, price, size, is_buy, passive))
        if is_buy:
            self.buy += size
        else:
            self.sell += size
        while self._max and self._max[-1][1] < price:
            self._max.pop()
        self._max.append((ts, price))
        while self._min and self._min[-1][1] > price:
            self._min.pop()
        self._min.append((ts, price))
        cutoff = ts - self.window_ns
        while self.trades[0][0] < cutoff:
            _, _, s, b, _ = self.trades.popleft()
            if b:
                self.buy -= s
            else:
                self.sell -= s
        while self._max[0][0] < cutoff:
            self._max.popleft()
        while self._min[0][0] < cutoff:
            self._min.popleft()

    @property
    def volume(self) -> int:
        return self.buy + self.sell

    def high(self) -> tuple[float, int]:
        return self._max[0][1], self._max[0][0]

    def low(self) -> tuple[float, int]:
        return self._min[0][1], self._min[0][0]


@dataclass
class Setup:
    side: int          # +1 long, -1 short
    label: str
    level: float
    extreme: float
    armed_ts: int
    notes: str


@dataclass
class Trade:
    side: int
    label: str
    notes: str
    stop: float
    entry_ts: int
    entry: float = 0.0
    risk: float = 0.0
    qty: int = 0
    t1_done: bool = False
    exit_reason: str | None = None
    mfe: float = 0.0
    mae: float = 0.0
    mfe_until: int = 0
    record: dict = field(default_factory=dict)


def value_area(profile: dict[float, int], pct: float) -> tuple[float, float, float]:
    prices = sorted(profile)
    vols = [profile[p] for p in prices]
    poc = max(range(len(prices)), key=vols.__getitem__)
    lo = hi = poc
    acc, target = vols[poc], sum(vols) * pct
    while acc < target and (lo > 0 or hi < len(prices) - 1):
        up = vols[hi + 1] if hi + 1 < len(prices) else -1
        dn = vols[lo - 1] if lo > 0 else -1
        if up >= dn:
            hi += 1
            acc += up
        else:
            lo -= 1
            acc += dn
    return prices[hi], prices[lo], prices[poc]


def et_ns(d: date, hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return int(datetime(d.year, d.month, d.day, h, m, tzinfo=NY).timestamp()) * NS


class AbsorptionStrategy(Strategy):
    def __init__(self, config: AbsorptionConfig):
        super().__init__(config)
        c = config
        self.trades: list[dict] = []
        self._flow = RollingFlow(c.absorption_window_secs)
        self._shift = RollingFlow(c.shift_window_secs)
        self._minutes: deque = deque(maxlen=c.avg_volume_lookback_mins)
        self._minute = -1
        self._minute_vol = 0
        self._ask_size = 0
        self._bid_size = 0
        self._skip_days: set[date] = set()
        self._news: list[int] = []
        for ev in c.news_events:
            ev = ev.strip()
            if len(ev) == 10:
                self._skip_days.add(date.fromisoformat(ev))
            else:
                dt = datetime.fromisoformat(ev).replace(tzinfo=NY)
                self._news.append(int(dt.timestamp()) * NS)
        self._news.sort()
        self._prior: dict[str, float] = {}
        self._session_end = 0
        self._tracking: list[Trade] = []
        self._trade: Trade | None = None
        self._setup: Setup | None = None
        self._pending: Trade | None = None
        self._stop_order = None
        self._entry_order_id = None
        self._t1_order_id = None
        self._closing = False
        self._reset_session_state()

    # ---------------------------------------------------------------- lifecycle

    def on_start(self) -> None:
        self.instrument = self.cache.instrument(self.config.instrument_id)
        if self.instrument is None:
            self.log.error(f"Instrument {self.config.instrument_id} not found")
            self.stop()
            return
        self.subscribe_trade_ticks(self.config.instrument_id)
        if self.config.min_passive_size > 0:
            self.subscribe_quote_ticks(self.config.instrument_id)

    def on_stop(self) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        self.close_all_positions(self.config.instrument_id)

    def _reset_session_state(self) -> None:
        self._on_hi = self._on_lo = None
        self._rth_hi = self._rth_lo = None
        self._ib_hi = self._ib_lo = None
        self._vwap_pv = 0.0
        self._vwap_v = 0
        self._profile: dict[float, int] = {}
        self._tests: dict[str, int] = {}
        self._last_touch: dict[str, int] = {}
        self._cooldown: dict[str, int] = {}
        self._next_eval = 0
        self._day_trades = 0
        self._day_losses = 0
        self._day_pnl = 0.0
        self._day_peak = 0.0
        self._day_done = False
        self._setup = None

    def _new_session(self, ts: int) -> None:
        c = self.config
        if self._rth_hi is not None:
            self._prior = {"PDH": self._rth_hi, "PDL": self._rth_lo}
            if c.use_value_area and self._profile:
                self._prior["VAH"], self._prior["VAL"], self._prior["POC"] = value_area(self._profile, c.value_area_pct)
        et = datetime.fromtimestamp(ts / NS, NY)
        d = et.date()
        if et.time() >= time.fromisoformat(c.globex_open):
            d += timedelta(days=1)
        self._reset_session_state()
        self._date = d
        self._rth_open_ns = et_ns(d, c.rth_open)
        self._rth_close_ns = et_ns(d, c.rth_close)
        self._ib_end_ns = et_ns(d, c.ib_end)
        self._entry_start_ns = et_ns(d, c.entry_start)
        self._entry_end_ns = et_ns(d, c.entry_end)
        self._flatten_ns = et_ns(d, c.flatten_time)
        self._session_end = et_ns(d, c.globex_open)
        before, after = c.news_before_mins * 60 * NS, c.news_after_mins * 60 * NS
        self._news_windows = [(n - before, n + after) for n in self._news if self._session_end - 86400 * NS <= n < self._session_end]
        self._day_done = d in self._skip_days

    # ---------------------------------------------------------------- data

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self._bid_size = int(tick.bid_size.as_double())
        self._ask_size = int(tick.ask_size.as_double())

    def on_trade_tick(self, tick: TradeTick) -> None:
        ts = tick.ts_event
        if ts >= self._session_end:
            self._new_session(ts)
        price = tick.price.as_double()
        size = int(tick.size.as_double())
        is_buy = tick.aggressor_side == AggressorSide.BUYER
        self._update_stats(ts, price, size)
        self._flow.add(ts, price, size, is_buy, self._ask_size if is_buy else self._bid_size)
        self._shift.add(ts, price, size, is_buy, 0)

        if self._tracking:
            self._track_mfe(ts, price)
        if self._trade is not None and not self._closing:
            self._manage(ts, price)
        if ts >= self._next_eval:
            self._next_eval = ts + NS
            self._evaluate(ts, price)
        if self._setup is not None:
            self._check_trigger(ts, price)

    def _update_stats(self, ts: int, price: float, size: int) -> None:
        minute = ts // (60 * NS)
        if minute != self._minute:
            if self._minute >= 0:
                self._minutes.append(self._minute_vol)
            self._minute, self._minute_vol = minute, 0
        self._minute_vol += size

        if ts < self._rth_open_ns:
            self._on_hi = price if self._on_hi is None else max(self._on_hi, price)
            self._on_lo = price if self._on_lo is None else min(self._on_lo, price)
        elif ts < self._rth_close_ns:
            self._rth_hi = price if self._rth_hi is None else max(self._rth_hi, price)
            self._rth_lo = price if self._rth_lo is None else min(self._rth_lo, price)
            self._vwap_pv += price * size
            self._vwap_v += size
            self._profile[price] = self._profile.get(price, 0) + size
            if ts < self._ib_end_ns:
                self._ib_hi = price if self._ib_hi is None else max(self._ib_hi, price)
                self._ib_lo = price if self._ib_lo is None else min(self._ib_lo, price)

    @property
    def _vwap(self) -> float | None:
        return self._vwap_pv / self._vwap_v if self._vwap_v else None

    def _levels(self, ts: int, price: float) -> dict[str, float]:
        c = self.config
        lv: dict[str, float] = {}
        if c.use_prior_day_hl and "PDH" in self._prior:
            lv["PDH"], lv["PDL"] = self._prior["PDH"], self._prior["PDL"]
        if c.use_value_area and "POC" in self._prior:
            lv.update({k: self._prior[k] for k in (("VAH", "VAL", "POC") if c.use_poc else ("VAH", "VAL"))})
        if c.use_overnight_hl and ts >= self._rth_open_ns and self._on_hi is not None:
            lv["ONH"], lv["ONL"] = self._on_hi, self._on_lo
        if c.use_vwap and self._vwap is not None:
            lv["VWAP"] = self._vwap
        if c.use_initial_balance and ts >= self._ib_end_ns and self._ib_hi is not None:
            lv["IBH"], lv["IBL"] = self._ib_hi, self._ib_lo
        if c.round_number_step > 0:
            base = (price // c.round_number_step) * c.round_number_step
            lv[f"R{base:.0f}"] = base
            lv[f"R{base + c.round_number_step:.0f}"] = base + c.round_number_step
        return lv

    # ---------------------------------------------------------------- detection

    def _can_enter(self, ts: int) -> bool:
        return (
            not self._day_done
            and self._trade is None
            and self._pending is None
            and self._entry_start_ns <= ts < self._entry_end_ns
            and self._day_trades < self.config.max_trades_per_day
            and not self._in_news(ts)
        )

    def _in_news(self, ts: int) -> bool:
        return any(a <= ts < b for a, b in self._news_windows)

    def _evaluate(self, ts: int, price: float) -> None:
        c = self.config
        if not (self._rth_open_ns <= ts < self._flatten_ns):
            return
        levels = self._levels(ts, price)
        for label, level in levels.items():
            if abs(price - level) <= c.level_tolerance_pts:
                if ts - self._last_touch.get(label, -10**20) > c.level_test_gap_secs * NS:
                    self._tests[label] = self._tests.get(label, 0) + 1
                self._last_touch[label] = ts

        if self._trade is not None:
            if c.exit_on_opposite_absorption and not self._closing:
                found = self._find_absorption(ts, levels, only_side=-self._trade.side)
                if found:
                    self._close(f"opposite absorption at {found.label}")
            return
        if self._setup is None and self._can_enter(ts):
            self._setup = self._find_absorption(ts, levels)

    def _find_absorption(self, ts: int, levels: dict[str, float], only_side: int = 0) -> Setup | None:
        c = self.config
        flow = self._flow
        if not flow.trades:
            return None
        avg = sum(self._minutes) / len(self._minutes) * c.absorption_window_secs / 60 if self._minutes else 0
        vol = flow.volume
        if vol < max(c.min_window_volume, c.min_volume_multiple * avg, 1):
            return None
        for label, level in levels.items():
            if self._tests.get(label, 0) > c.max_level_tests or self._cooldown.get(label, 0) > ts:
                continue
            for side in (-1, 1):
                if only_side and side != only_side:
                    continue
                # short: buyers hit into resistance; long: sellers hit into support
                ext, ext_ts = flow.high() if side == -1 else flow.low()
                beyond = (ext - level) * -side
                if not (-c.level_tolerance_pts <= beyond <= c.max_penetration_pts):
                    continue
                aggr = flow.buy if side == -1 else flow.sell
                if aggr / vol < c.min_aggressor_share:
                    continue
                if ts - ext_ts < c.min_stall_secs * NS:
                    continue
                if (ext - flow.trades[-1][1]) * -side > c.max_extreme_distance_pts:
                    continue
                pushes, passive, absorbed = self._pushes(ext, side)
                if pushes < c.min_pushes or absorbed < c.min_absorbed_ratio * avg:
                    continue
                if c.min_passive_size > 0 and passive < c.min_passive_size:
                    continue
                notes = (f"{label} {level:.2f}; {'buyers' if side == -1 else 'sellers'} {aggr / vol:.0%} of {vol} lots "
                         f"(x{vol / avg:.1f} avg); {absorbed} absorbed at extreme; {pushes} pushes"
                         if avg else f"{label} {level:.2f}")
                return Setup(side, label, level, ext, ts, notes)
        return None

    def _pushes(self, ext: float, side: int) -> tuple[int, float, int]:
        """Tests of the extreme, average passive size there, and aggressive volume absorbed there."""
        c = self.config
        pushes, in_zone, passive, absorbed = 0, False, [], 0
        for _, p, size, is_buy, psize in self._flow.trades:
            dist = (ext - p) * -side  # >= 0, distance back from the extreme
            if dist <= c.push_zone_pts:
                if not in_zone:
                    pushes += 1
                    in_zone = True
                if is_buy == (side == -1):
                    passive.append(psize)
                    absorbed += size
            elif dist >= c.push_reset_pts:
                in_zone = False
        return pushes, (sum(passive) / len(passive) if passive else 0.0), absorbed

    def _check_trigger(self, ts: int, price: float) -> None:
        c = self.config
        s = self._setup
        if not self._can_enter(ts) or ts - s.armed_ts > c.trigger_timeout_secs * NS:
            self._disarm(ts)
            return
        beyond = (price - s.extreme) * -s.side
        if beyond > c.break_pts:
            self._disarm(ts)
            return
        if beyond > 0:
            s.extreme = price
        trigger = min(s.level, s.extreme) - c.shift_pts if s.side == -1 else max(s.level, s.extreme) + c.shift_pts
        flipped = self._shift.sell > self._shift.buy if s.side == -1 else self._shift.buy > self._shift.sell
        if (price - trigger) * s.side >= 0 and flipped:
            self._setup = None
            self._cooldown[s.label] = ts + c.absorption_window_secs * NS
            self._enter(ts, price, s)

    def _disarm(self, ts: int) -> None:
        self._cooldown[self._setup.label] = ts + self.config.absorption_window_secs * NS
        self._setup = None

    # ---------------------------------------------------------------- orders

    def _enter(self, ts: int, price: float, s: Setup) -> None:
        c = self.config
        stop = s.extreme - s.side * c.stop_buffer_pts
        stop_pts = (price - stop) * s.side
        if stop_pts < c.min_stop_pts:
            stop, stop_pts = price - s.side * c.min_stop_pts, c.min_stop_pts
        if stop_pts > c.max_stop_pts:
            self.log.info(f"Skip {s.label}: stop {stop_pts:.2f} pts > max")
            return
        if c.min_room_r > 0:
            room = [(lv - price) * s.side for k, lv in self._levels(ts, price).items()
                    if not k.startswith("R") and k != s.label]
            room = [r for r in room if r > c.tick_size]
            if room and min(room) < c.min_room_r * stop_pts:
                self.log.info(f"Skip {s.label}: only {min(room):.2f} pts of room")
                return
        qty = min(int(c.risk_usd // (stop_pts * c.point_value + c.cost_per_contract)), c.max_contracts)
        if qty < 1:
            return
        stop = round(stop / c.tick_size) * c.tick_size
        self._pending = Trade(side=s.side, label=s.label, notes=s.notes, stop=stop, entry_ts=ts)
        order = self.order_factory.market(
            self.config.instrument_id,
            OrderSide.BUY if s.side == 1 else OrderSide.SELL,
            self.instrument.make_qty(qty),
        )
        self._entry_order_id = order.client_order_id
        self.submit_order(order)

    def _open_positions(self) -> list:
        return self.cache.positions_open(instrument_id=self.config.instrument_id, strategy_id=self.id)

    def _activate_trade(self) -> None:
        # Market orders can fill in several pieces against the top-of-book size; protect the full position.
        t, self._pending = self._pending, None
        positions = self._open_positions()
        if t is None or not positions:
            return
        position = positions[0]
        t.entry = position.avg_px_open
        t.qty = int(position.quantity.as_double())
        t.risk = abs(t.entry - t.stop)
        self._trade = t
        self._closing = False
        self._stop_order = self.order_factory.stop_market(
            self.config.instrument_id,
            OrderSide.SELL if t.side == 1 else OrderSide.BUY,
            position.quantity,
            trigger_price=self.instrument.make_price(t.stop),
            reduce_only=True,
        )
        self.submit_order(self._stop_order)

    def _manage(self, ts: int, price: float) -> None:
        c = self.config
        t = self._trade
        fav = (price - t.entry) * t.side
        t.mfe = max(t.mfe, fav)
        t.mae = max(t.mae, -fav)
        if not t.t1_done and fav >= c.t1_r * t.risk:
            t.t1_done = True
            n = int(t.qty * c.t1_fraction)
            if 1 <= n < t.qty:
                order = self.order_factory.market(
                    c.instrument_id, OrderSide.SELL if t.side == 1 else OrderSide.BUY,
                    self.instrument.make_qty(n), reduce_only=True,
                )
                self._t1_order_id = order.client_order_id
                self.submit_order(order)
            else:
                self._stop_to_breakeven(t.qty)
            return
        if t.t1_done:
            target, name = t.entry + t.side * c.t2_r * t.risk, "T2"
            vwap = self._vwap
            if c.t2_use_vwap and vwap is not None and c.t1_r * t.risk < (vwap - t.entry) * t.side < c.t2_r * t.risk:
                target, name = vwap, "VWAP"
            if (price - target) * t.side >= 0:
                self._close(name)
                return
        held = ts - t.entry_ts
        if not t.t1_done and held >= c.time_stop_mins * 60 * NS:
            self._close("time stop")
        elif t.t1_done and held >= c.max_hold_mins * 60 * NS:
            self._close("max hold")
        elif ts >= self._flatten_ns:
            self._close("flatten")
        elif self._in_news(ts):
            self._close("news")

    def _stop_to_breakeven(self, qty: int) -> None:
        t = self._trade
        if self._stop_order is None or not self._stop_order.is_open:
            return
        be = round(t.entry / self.config.tick_size) * self.config.tick_size
        self.modify_order(self._stop_order, quantity=self.instrument.make_qty(qty), trigger_price=self.instrument.make_price(be))

    def _close(self, reason: str) -> None:
        self._trade.exit_reason = reason
        self._closing = True
        for position in self._open_positions():
            self.close_position(position)

    def on_order_filled(self, event) -> None:
        if not self.cache.order(event.client_order_id).is_closed:
            return
        if event.client_order_id == self._entry_order_id:
            self._entry_order_id = None
            self._activate_trade()
        elif event.client_order_id == self._t1_order_id and self._trade is not None:
            self._t1_order_id = None
            positions = self._open_positions()
            if positions:
                self._stop_to_breakeven(int(positions[0].quantity.as_double()))

    def on_order_rejected(self, event) -> None:
        if self._pending is not None and event.client_order_id == self._entry_order_id:
            self.log.warning(f"Entry rejected ({event.reason})")
            self._pending = None
        elif self._stop_order is not None and event.client_order_id == self._stop_order.client_order_id and self._trade:
            self.log.warning(f"Stop rejected ({event.reason}); exiting at market")
            self._close("stop rejected")

    def on_position_closed(self, event) -> None:
        self.cancel_all_orders(self.config.instrument_id)
        t = self._trade
        self._trade = None
        self._stop_order = None
        self._t1_order_id = None
        self._closing = False
        if t is None:
            return
        c = self.config
        exit_px = event.avg_px_close
        qty = int(event.peak_qty.as_double())
        pts = (exit_px - t.entry) * t.side
        net = pts * c.point_value * qty - c.cost_per_contract * qty
        reason = t.exit_reason or ("breakeven stop" if t.t1_done else "stop")
        entry_et = datetime.fromtimestamp(t.entry_ts / NS, NY)
        t.record = {
            "date": entry_et.strftime("%Y-%m-%d"),
            "time": entry_et.strftime("%H:%M"),
            "setup": SETUP_NAME,
            "side": "Long" if t.side == 1 else "Short",
            "contract": c.contract,
            "qty": qty,
            "entry": round(t.entry, 2),
            "stop": round(t.stop, 2),
            "exit": round(exit_px, 2),
            "mfe": t.mfe,
            "mae": t.mae,
            "rules": True,
            "notes": f"{t.notes}; exit: {reason}",
            "stopEstimated": False,
            "exit_reason": reason,
            "net_usd": round(net, 2),
            "r": pts / t.risk if t.risk else 0.0,
            "risk_pts": t.risk,
        }
        self.trades.append(t.record)
        t.mfe_until = t.entry_ts + c.mfe_horizon_mins * 60 * NS
        self._tracking.append(t)

        self._day_trades += 1
        self._day_losses += net < 0
        self._day_pnl += net
        self._day_peak = max(self._day_peak, self._day_pnl)
        if (
            self._day_losses >= c.max_losses_per_day
            or self._day_pnl <= -c.daily_loss_stop
            or self._day_pnl >= c.daily_profit_goal
            or (c.giveback_rule and self._day_peak >= 2 * c.risk_usd and self._day_pnl <= self._day_peak - c.risk_usd)
        ):
            self._day_done = True

    def _track_mfe(self, ts: int, price: float) -> None:
        keep = []
        for t in self._tracking:
            t.mfe = max(t.mfe, (price - t.entry) * t.side)
            t.record["mfe"] = t.mfe
            if (price - t.stop) * t.side > 0 and ts < t.mfe_until:
                keep.append(t)
        self._tracking = keep
