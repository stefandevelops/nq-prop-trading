"""Monte Carlo simulation of a prop firm challenge.

Simulates thousands of challenge attempts trade by trade, applying the firm's
drawdown rules and your own daily stop / profit goal, and reports how often
you pass, fail, or run out of time.

Examples:
  python3 montecarlo.py
  python3 montecarlo.py --win-rate 0.55 --rr 1.5 --risk 150
  python3 montecarlo.py --sweep risk
  python3 montecarlo.py --sweep rr
"""
import argparse
import random
import statistics

from common import CONTRACTS, drawdown_threshold, load_config, size_position, trade_outcomes


def run_once(cfg, plan, loss, win, gross_win, rng):
    start = cfg["starting_balance"]
    target_balance = start + cfg["profit_target"]
    intraday = cfg["drawdown_type"] == "intraday_trailing"
    dll = cfg.get("daily_loss_limit")
    consistency = cfg.get("consistency_pct")
    balance = hwm = start
    best_day = 0.0
    trades = 0

    for day in range(1, plan["max_days"] + 1):
        threshold = drawdown_threshold(cfg, hwm)
        day_pnl = 0.0
        losses = 0
        for _ in range(plan["max_trades_per_day"]):
            if rng.random() < plan["win_rate"]:
                if intraday:
                    # Trails the open-profit peak at the target, before exit costs.
                    hwm = max(hwm, balance + gross_win)
                    threshold = drawdown_threshold(cfg, hwm)
                pnl = win
            else:
                pnl = loss
                losses += 1
            balance += pnl
            day_pnl += pnl
            trades += 1

            if balance <= threshold:
                return "fail", day, trades
            if dll and day_pnl <= -dll:
                if cfg.get("daily_loss_limit_hard_fail"):
                    return "fail", day, trades
                break
            if losses >= plan["max_losses_per_day"]:
                break
            if plan["daily_loss_stop"] and day_pnl <= -plan["daily_loss_stop"]:
                break
            if plan["daily_profit_goal"] and day_pnl >= plan["daily_profit_goal"]:
                break

        if not intraday:
            hwm = max(hwm, balance)
        best_day = max(best_day, day_pnl)
        profit = balance - start
        if (
            balance >= target_balance
            and day >= cfg.get("min_trading_days", 0)
            and (consistency is None or best_day <= consistency * profit)
        ):
            return "pass", day, trades

    return "timeout", plan["max_days"], trades


def simulate(cfg, plan, sims, seed):
    contracts = size_position(cfg, plan["contract"], plan["risk_per_trade"], plan["stop_points"])
    if contracts == 0:
        return None
    loss, win, gross_win = trade_outcomes(cfg, plan["contract"], contracts, plan["stop_points"], plan["reward_risk"])
    rng = random.Random(seed)
    results = {"pass": [], "fail": [], "timeout": []}
    trade_counts = []
    for _ in range(sims):
        outcome, days, trades = run_once(cfg, plan, loss, win, gross_win, rng)
        results[outcome].append(days)
        if outcome == "pass":
            trade_counts.append(trades)
    return {
        "contracts": contracts,
        "loss": loss,
        "win": win,
        "results": results,
        "trades_to_pass": trade_counts,
        "sims": sims,
    }


def pct(part, whole):
    return f"{100 * part / whole:5.1f}%"


def print_report(cfg, plan, r):
    sims = r["sims"]
    loss, win = r["loss"], r["win"]
    w = plan["win_rate"]
    ev = w * win + (1 - w) * loss
    breakeven = -loss / (win - loss)
    passed, failed, timeout = (r["results"][k] for k in ("pass", "fail", "timeout"))
    pass_rate = len(passed) / sims

    print(f"\n{cfg['firm']} {cfg['account']}: target +${cfg['profit_target']:,}, "
          f"max drawdown ${cfg['max_drawdown']:,} ({cfg['drawdown_type']})")
    print(f"Plan: {r['contracts']} {plan['contract']} x {plan['stop_points']:g} pt stop, "
          f"{plan['reward_risk']:g}R target, {w:.0%} win rate")
    print(f"      max {plan['max_trades_per_day']} trades / {plan['max_losses_per_day']} losses per day, "
          f"daily stop ${plan['daily_loss_stop'] or 0:,.0f}, daily goal ${plan['daily_profit_goal'] or 0:,.0f}, "
          f"{plan['max_days']} day limit")
    print(f"\nPer trade after costs: win +${win:,.0f}, loss -${-loss:,.0f}")
    print(f"Expectancy: ${ev:,.2f} per trade   breakeven win rate: {breakeven:.1%}")
    if ev <= 0:
        print("  -> Negative expectancy: this plan loses money on average no matter how you manage risk.")

    print(f"\nResults over {sims:,} simulated challenges:")
    print(f"  Pass      {pct(len(passed), sims)}")
    print(f"  Fail      {pct(len(failed), sims)}")
    print(f"  Timed out {pct(len(timeout), sims)}  (still alive after {plan['max_days']} days)")
    if passed:
        q = statistics.quantiles(passed, n=4) if len(passed) > 1 else [passed[0]] * 3
        print(f"\n  Trading days to pass: median {statistics.median(passed):.0f}  "
              f"(middle half {q[0]:.0f}-{q[2]:.0f})")
        print(f"  Trades to pass: median {statistics.median(r['trades_to_pass']):.0f}")
    if failed:
        print(f"  Failures happen at median day {statistics.median(failed):.0f}")
    fee = cfg.get("challenge_fee")
    if fee and pass_rate > 0:
        print(f"\n  Expected fees per passed challenge: ${fee / pass_rate:,.0f} "
              f"(~{1 / pass_rate:.1f} attempts at ${fee:,})")
    if cfg["drawdown_type"] == "intraday_trailing":
        print("\n  Note: intraday trailing ignores open-profit peaks on losing trades, so real results may be slightly worse.")
    print()


def print_sweep(cfg, plan, kind, sims, seed):
    win_rates = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    if kind == "risk":
        cols = [100, 150, 200, 300, 400, 600]
        key, label, fmt = "risk_per_trade", "Risk per trade ($)", lambda v: f"${v}"
    else:
        cols = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
        key, label, fmt = "reward_risk", "Reward:risk", lambda v: f"{v:g}R"

    fixed = "reward:risk " + f"{plan['reward_risk']:g}R" if kind == "risk" else f"risk ${plan['risk_per_trade']:,.0f}"
    print(f"\nPass rate by win rate (rows) and {label.lower()} (columns)")
    print(f"{plan['contract']}, {plan['stop_points']:g} pt stop, {fixed}, {sims:,} sims per cell\n")
    print("  Win rate " + "".join(f"{fmt(c):>9}" for c in cols))
    for wr in win_rates:
        row = f"  {wr:>7.0%}  "
        for c in cols:
            r = simulate(cfg, {**plan, "win_rate": wr, key: c}, sims, seed)
            row += f"{'too small':>9}" if r is None else f"{100 * len(r['results']['pass']) / sims:8.0f}%"
        print(row)
    print("\n'too small' = risk is less than 1 contract at this stop.\n")


def main():
    cfg = load_config()
    plan = dict(cfg["plan"])

    p = argparse.ArgumentParser(description="Monte Carlo pass/fail odds for a prop firm challenge.")
    p.add_argument("--contract", choices=sorted(CONTRACTS))
    p.add_argument("--win-rate", type=float, help="e.g. 0.6")
    p.add_argument("--rr", type=float, help="Reward:risk multiple, e.g. 1.5")
    p.add_argument("--risk", type=float, help="$ risk per trade")
    p.add_argument("--stop", type=float, help="Stop distance in points")
    p.add_argument("--trades-per-day", type=int)
    p.add_argument("--max-losses", type=int, help="Stop trading after this many losses in a day")
    p.add_argument("--daily-stop", type=float, help="Your personal daily loss stop in $ (0 = none)")
    p.add_argument("--daily-goal", type=float, help="Stop for the day after this much profit (0 = none)")
    p.add_argument("--days", type=int, help="Max trading days to simulate")
    p.add_argument("--sims", type=int, default=10000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--sweep", choices=["risk", "rr"], help="Print a pass-rate grid instead of a single report")
    args = p.parse_args()

    overrides = {
        "contract": args.contract,
        "win_rate": args.win_rate,
        "reward_risk": args.rr,
        "risk_per_trade": args.risk,
        "stop_points": args.stop,
        "max_trades_per_day": args.trades_per_day,
        "max_losses_per_day": args.max_losses,
        "daily_loss_stop": args.daily_stop,
        "daily_profit_goal": args.daily_goal,
        "max_days": args.days,
    }
    plan.update({k: v for k, v in overrides.items() if v is not None})

    if args.sweep:
        print_sweep(cfg, plan, args.sweep, min(args.sims, 2000), args.seed)
        return

    r = simulate(cfg, plan, args.sims, args.seed)
    if r is None:
        p.error(f"${plan['risk_per_trade']:,.0f} risk doesn't cover 1 {plan['contract']} at a {plan['stop_points']:g} pt stop.")
    print_report(cfg, plan, r)


if __name__ == "__main__":
    main()
