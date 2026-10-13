"""Position sizer for NQ / MNQ, sized against the prop firm drawdown.

Examples:
  python3 sizer.py --stop 20
  python3 sizer.py --entry 21450 --stop-price 21428 --risk 150
  python3 sizer.py --stop 30 --balance 51200 --hwm 51600
"""
import argparse
import math

from common import (
    CONTRACTS,
    cost_per_contract,
    drawdown_threshold,
    load_config,
    size_position,
    trade_outcomes,
)


def main():
    cfg = load_config()
    plan = cfg["plan"]
    start = cfg["starting_balance"]

    p = argparse.ArgumentParser(description="Size an NQ/MNQ trade against your prop firm drawdown.")
    p.add_argument("--stop", type=float, help="Stop distance in points")
    p.add_argument("--entry", type=float, help="Entry price (use with --stop-price)")
    p.add_argument("--stop-price", type=float, help="Stop price (use with --entry)")
    p.add_argument("--risk", type=float, default=plan["risk_per_trade"], help="Max $ risk for this trade")
    p.add_argument("--rr", type=float, default=plan["reward_risk"], help="Reward:risk multiple for the target")
    p.add_argument("--balance", type=float, default=start, help="Current account balance")
    p.add_argument("--hwm", type=float, help="Highest balance used by the trailing drawdown (defaults to --balance)")
    args = p.parse_args()

    if args.entry is not None and args.stop_price is not None:
        stop_points = abs(args.entry - args.stop_price)
        side = "long" if args.stop_price < args.entry else "short"
    elif args.stop is not None:
        stop_points = args.stop
        side = None
    else:
        stop_points = plan["stop_points"]
        side = None
    if stop_points <= 0:
        p.error("Stop distance must be greater than zero.")

    hwm = max(args.hwm if args.hwm is not None else args.balance, args.balance)
    threshold = drawdown_threshold(cfg, hwm)
    room = args.balance - threshold
    to_target = start + cfg["profit_target"] - args.balance

    print(f"\n{cfg['firm']} {cfg['account']}  |  drawdown: {cfg['drawdown_type']}")
    print(f"Balance ${args.balance:,.0f}   fail level ${threshold:,.0f}   room ${room:,.0f}   to target ${to_target:,.0f}")
    print(f"Stop {stop_points:g} pts   max risk ${args.risk:,.0f}   target {args.rr:g}R")
    if room <= 0:
        print("\nAccount is at or below the fail level.")
        return

    for symbol in ("MNQ", "NQ"):
        spec = CONTRACTS[symbol]
        n = size_position(cfg, symbol, args.risk, stop_points)
        print(f"\n  {symbol} (${spec.point_value:g}/pt, costs ${cost_per_contract(cfg, symbol):.2f}/contract round turn)")
        if n == 0:
            one = stop_points * spec.point_value + cost_per_contract(cfg, symbol)
            print(f"    Not even 1 contract fits: 1 contract risks ${one:,.0f}.")
            continue
        loss, win, _ = trade_outcomes(cfg, symbol, n, stop_points, args.rr)
        losses_to_fail = math.ceil(room / -loss)
        print(f"    Contracts: {n}" + ("  (firm max)" if n == cfg["max_contracts"][symbol] else ""))
        print(f"    If stopped: -${-loss:,.0f}  ({-loss / cfg['max_drawdown']:.0%} of max drawdown, {-loss / room:.0%} of room left)")
        print(f"    If target:  +${win:,.0f}  ({stop_points * args.rr:g} pts)")
        print(f"    Consecutive losses until fail: {losses_to_fail}")
        if args.entry is not None and side:
            sign = 1 if side == "long" else -1
            print(f"    {side.upper()}  entry {args.entry:g}  stop {args.stop_price:g}  target {args.entry + sign * stop_points * args.rr:g}")
        if cfg.get("daily_loss_limit") and -loss > cfg["daily_loss_limit"]:
            print("    WARNING: a single loss exceeds the firm's daily loss limit.")
        if -loss > 0.15 * cfg["max_drawdown"]:
            print("    WARNING: risking more than 15% of the max drawdown on one trade.")
    print()


if __name__ == "__main__":
    main()
