"""How to maximise the pass rate: risk per trade vs time, using IQ Capital's repeatable $19 extensions.

Same strategy as compare_accounts.py (IB acceptance + ORB 15m, max 3 trades, stop after 2 losers),
4 pts extra slippage on stop-outs. Two tests:

  1. Real rolling challenges on Jul 2024 - Sep 2026 with windows of 21 to 105 sessions.
  2. No deadline: day-block bootstrap (5-session blocks of real days) for up to 250 sessions,
     with the edge cut by 0, 0.1R and 0.17R per trade (0.17R removes the whole measured edge).

Cost per pass = (fee + $19 x extensions used) / pass rate, where each 30 calendar days is about 21 sessions.

Usage:  .venv-nautilus/bin/python backtest/pass_planner.py
"""

from __future__ import annotations

import numpy as np

from compare_accounts import accounts, trade_usd
from research_setups import ORB, IBBreak, build_sessions, combine, load_bars, load_config

EXTENSION_FEE = 19
SESSIONS_PER_MONTH = 21
STOP_SLIP = 4.0
RISKS = (150, 200, 250, 350, 450)


def simulate(days: list[list], acct: dict, pnl=None) -> tuple[str, int]:
    """Run one challenge over a sequence of days. Each day is a list of trade P&Ls, or of trades priced by
    pnl(trade, profit_so_far) when a balance-dependent risk schedule is used. Returns (outcome, sessions used)."""
    start, dd, lock = acct["starting_balance"], acct["max_drawdown"], acct["trail_lock_balance"]
    target = start + acct["profit_target"]
    dll, pll, max_br = acct["daily_loss_limit"], acct["position_loss_limit"], acct["max_breaches"]
    bal, hwm, breaches = start, start, 0
    for j, day_trades in enumerate(days, 1):
        thr = min(hwm - dd, lock)
        day = 0.0
        for x in day_trades:
            if pnl:
                x = pnl(x, bal - start)
            bal += x
            day += x
            if pll and x <= -pll:
                breaches += 1
                if breaches >= max_br:
                    return "fail", j
            if bal <= thr:
                return "fail", j
            if dll and day <= -dll:
                break
        hwm = max(hwm, bal)
        if bal >= target:
            return "pass", j
    return "timeout", len(days)


def cost(acct: dict, sessions: int) -> float:
    return acct["challenge_fee"] + EXTENSION_FEE * ((sessions - 1) // SESSIONS_PER_MONTH)


def summarise(results: list[tuple[str, int]], acct: dict) -> str:
    n = len(results)
    p = sum(o == "pass" for o, _ in results) / n
    f = sum(o == "fail" for o, _ in results) / n
    spend = sum(cost(acct, s) for _, s in results) / n
    passed = sorted(s for o, s in results if o == "pass")
    med = passed[len(passed) // 2] if passed else 0
    per_pass = f"${spend / p:,.0f}" if p else "never"
    return f"pass {p:4.0%}  fail {f:4.0%}  timeout {1 - p - f:4.0%}  median {med:3d} sessions to pass  {per_pass:>7s} per pass"


def main():
    cfg = load_config()
    print("Loading bars and building sessions...")
    sessions = build_sessions(load_bars())
    setups = [IBBreak(2, "close", 30.0, 0.5, False), ORB(15, "opp", 2.0, 2)]
    trades = combine([t for v in setups for s in sessions for t in v.trades(s)])
    dates = [s["date"] for s in sessions]
    accts = accounts(cfg)
    rng = np.random.default_rng(7)

    print(f"\n{len(trades)} trades over {len(dates)} sessions ({dates[0]} to {dates[-1]}), {STOP_SLIP:g} pts extra slippage on stops")
    for an, a in accts.items():
        for risk in RISKS:
            by_day = {d: [] for d in dates}
            for t in trades:
                by_day[t["date"]].append(trade_usd(t, risk, a, STOP_SLIP))
            seq = [by_day[d] for d in dates]
            print(f"\n== {an}, ${risk} risk per trade")
            for window in (21, 42, 63, 105):
                res = [simulate(seq[k:k + window], a) for k in range(len(seq) - window + 1)]
                print(f"  real, {window:3d}-session window:  {summarise(res, a)}")
            risk_r = risk
            for haircut in (0.0, 0.10, 0.17):
                res = []
                for _ in range(4000):
                    blocks = rng.integers(0, len(seq) - 5, size=50)
                    days = [[x - haircut * risk_r if x else x for x in seq[b + i]] for b in blocks for i in range(5)]
                    res.append(simulate(days, a))
                print(f"  no deadline, edge -{haircut:.2f}R:   {summarise(res, a)}")

    # Balance-dependent risk schedules, fixed in advance (not tuned): profit so far -> $ risk.
    schedules = {
        "flat $350": lambda p: 350,
        "$450, $250 while below start": lambda p: 450 if p >= 0 else 250,
        "$250 until +$1,000, then $450": lambda p: 250 if p < 1000 else 450,
        "$450 until +$1,500, then $250": lambda p: 450 if p < 1500 else 250,
    }
    a = accts["Position Loss ($39)"]
    by_day = {d: [] for d in dates}
    for t in trades:
        by_day[t["date"]].append(t)
    seq = [by_day[d] for d in dates]
    for name, sched in schedules.items():
        print(f"\n== Position Loss, risk schedule: {name}")
        for haircut in (0.0, 0.10):
            def pnl(t, profit, sched=sched, haircut=haircut):
                r = sched(profit)
                x = trade_usd(t, r, a, STOP_SLIP)
                return x - haircut * r if x else x
            if haircut == 0.0:
                for window in (42, 63, 105):
                    res = [simulate(seq[k:k + window], a, pnl) for k in range(len(seq) - window + 1)]
                    print(f"  real, {window:3d}-session window:  {summarise(res, a)}")
            res = []
            for _ in range(4000):
                blocks = rng.integers(0, len(seq) - 5, size=50)
                res.append(simulate([seq[b + i] for b in blocks for i in range(5)], a, pnl))
            print(f"  no deadline, edge -{haircut:.2f}R:   {summarise(res, a)}")


if __name__ == "__main__":
    main()
