"""Compare IQ Capital 50K Daily Loss ($49) vs Position Loss ($39) for the breakout playbook.

Strategy: IB acceptance breakout (simple: 2 five-minute closes, entry at close, stop 30 pts inside
the IB, target IB edge + 0.5 IB) plus ORB 15m (far-side stop, 2R, 2 attempts), combined with at most
3 trades and 2 losers a day. Both setups passed the design + holdout checks (PLAYBOOK.md section 15).

Rolling-start challenges: a challenge starts on every session and trades the real following sessions.

  Daily Loss:    $2,000 EOD trailing drawdown (locks at $50,000), $1,000 soft daily loss = stop for the day.
  Position Loss: $3,000 EOD trailing drawdown (assumed to lock at $50,000 too), no daily limit,
                 a position losing $500 or more incl. costs is a soft breach; the 3rd breach fails.

Cost per pass = (fee + $19 extension if the window is longer than 21 days) / pass rate.

Usage:  .venv-nautilus/bin/python backtest/compare_accounts.py [--stop-slip 4]
"""

from __future__ import annotations

import argparse
import copy

from research_setups import (CONTRACTS, DESIGN_END, ORB, IBBreak, build_sessions, combine, cost_per_contract, load_bars,
                             load_config, usd)

EXTENSION_FEE = 19


def accounts(cfg: dict) -> dict:
    daily = copy.deepcopy(cfg)
    daily.update(challenge_fee=49, max_drawdown=2000, daily_loss_limit=1000, position_loss_limit=None, max_breaches=None)
    pos = copy.deepcopy(cfg)
    pos.update(challenge_fee=39, max_drawdown=3000, daily_loss_limit=None, position_loss_limit=500, max_breaches=3)
    return {"Daily Loss ($49)": daily, "Position Loss ($39)": pos}


def trade_usd(t: dict, risk_usd: float, acct: dict, stop_slip: float) -> float:
    """P&L in $, with stop_slip extra points of slippage on stop-outs (fast markets)."""
    x = usd(t, risk_usd, acct)
    if x and stop_slip and t["reason"] == "stop":
        pv, cost = CONTRACTS["MNQ"].point_value, cost_per_contract(acct, "MNQ")
        qty = min(int(risk_usd // (t["risk"] * pv + cost)), acct["max_contracts"]["MNQ"])
        x -= stop_slip * pv * qty
    return x


def rolling(dates: list[str], trades: list[dict], risk_usd: float, acct: dict, max_days: int, stop_slip: float = 0.0) -> dict:
    start, dd, lock = acct["starting_balance"], acct["max_drawdown"], acct["trail_lock_balance"]
    target = start + acct["profit_target"]
    dll, pll, max_br = acct["daily_loss_limit"], acct["position_loss_limit"], acct["max_breaches"]
    by_day: dict[str, list] = {}
    for t in trades:
        by_day.setdefault(t["date"], []).append(trade_usd(t, risk_usd, acct, stop_slip))
    res = {"pass": 0, "fail": 0, "timeout": 0, "days": [], "breach_fails": 0}
    for k in range(len(dates) - max_days + 1):
        bal, hwm, outcome, breaches = start, start, "timeout", 0
        for j, d in enumerate(dates[k:k + max_days], 1):
            thr = min(hwm - dd, lock)
            day = 0.0
            for x in by_day.get(d, []):
                bal += x
                day += x
                if pll and x <= -pll:
                    breaches += 1
                    if breaches >= max_br:
                        outcome = "fail"
                        res["breach_fails"] += 1
                        break
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
    res["n"] = res["pass"] + res["fail"] + res["timeout"]
    return res


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--stop-slip", type=float, default=0.0, help="extra points of slippage on every stop-out (default 0)")
    args = p.parse_args()
    cfg = load_config()
    print("Loading bars and building sessions...")
    sessions = build_sessions(load_bars())
    setups = [IBBreak(2, "close", 30.0, 0.5, False), ORB(15, "opp", 2.0, 2)]
    periods = {
        "Design Jul 2024-Dec 2025": [s for s in sessions if s["date"] <= DESIGN_END],
        "Holdout Jan-Sep 2026": [s for s in sessions if s["date"] > DESIGN_END],
    }
    accts = accounts(cfg)
    for name, ss in periods.items():
        trades = combine([t for v in setups for s in ss for t in v.trades(s)])
        dates = [s["date"] for s in ss]
        print(f"\n== {name}: {len(trades)} trades over {len(ss)} sessions, {args.stop_slip:g} pts extra slippage on stops")
        print(f"  {'window':>6s} {'risk':>5s}  {'account':20s} {'pass':>5s} {'fail':>5s} {'timeout':>7s} {'breach-fail':>11s} {'median days':>11s} {'$ per pass':>10s}")
        for days in (21, 42):
            for risk in (250, 350, 450, 500):
                for an, a in accts.items():
                    r = rolling(dates, trades, risk, a, days, args.stop_slip)
                    if not r["n"]:
                        continue
                    p = r["pass"] / r["n"]
                    fee = a["challenge_fee"] + (EXTENSION_FEE if days > 21 else 0)
                    med = sorted(r["days"])[len(r["days"]) // 2] if r["days"] else None
                    cost = f"${fee / p:,.0f}" if p else "never"
                    print(f"  {days:4d}d ${risk:4d}  {an:20s} {p:5.0%} {r['fail'] / r['n']:5.0%} {r['timeout'] / r['n']:7.0%} "
                          f"{r['breach_fails'] / r['n']:11.0%} {str(med or '-'):>11s} {cost:>10s}")


if __name__ == "__main__":
    main()
