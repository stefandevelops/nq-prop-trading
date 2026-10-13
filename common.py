import json
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("challenge.json")


@dataclass(frozen=True)
class Contract:
    symbol: str
    point_value: float
    tick_size: float

    @property
    def tick_value(self) -> float:
        return self.point_value * self.tick_size


CONTRACTS = {
    "NQ": Contract("NQ", point_value=20.0, tick_size=0.25),
    "MNQ": Contract("MNQ", point_value=2.0, tick_size=0.25),
}


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def cost_per_contract(cfg: dict, symbol: str) -> float:
    """Round-turn commission plus slippage, in dollars, for one contract."""
    c = cfg["costs"][symbol]
    return c["commission_rt"] + c["slippage_ticks"] * CONTRACTS[symbol].tick_value


def size_position(cfg: dict, symbol: str, risk_dollars: float, stop_points: float) -> int:
    """Largest contract count whose stop-out loss (including costs) stays within risk_dollars."""
    spec = CONTRACTS[symbol]
    loss_per_contract = stop_points * spec.point_value + cost_per_contract(cfg, symbol)
    contracts = int(risk_dollars // loss_per_contract)
    return max(0, min(contracts, cfg["max_contracts"][symbol]))


def trade_outcomes(cfg: dict, symbol: str, contracts: int, stop_points: float, reward_risk: float):
    """Net dollar result of a losing and a winning trade, plus the gross winner before costs."""
    spec = CONTRACTS[symbol]
    costs = contracts * cost_per_contract(cfg, symbol)
    gross_loss = contracts * stop_points * spec.point_value
    gross_win = gross_loss * reward_risk
    return -(gross_loss + costs), gross_win - costs, gross_win


def drawdown_threshold(cfg: dict, high_water_mark: float) -> float:
    """Account balance at or below which the account is failed."""
    start = cfg["starting_balance"]
    dd = cfg["max_drawdown"]
    if cfg["drawdown_type"] == "static":
        return start - dd
    threshold = high_water_mark - dd
    lock = cfg.get("trail_lock_balance")
    if lock is not None:
        threshold = min(threshold, lock)
    return threshold
