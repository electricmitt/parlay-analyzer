"""Deterministic odds / probability / EV arithmetic. No I/O, fully unit-tested."""
from __future__ import annotations

import math
from typing import Sequence


def american_to_decimal(american: int | float) -> float:
    a = float(american)
    if a == 0 or -100 < a < 100:
        raise ValueError(f"invalid American odds: {american}")
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / -a)


def decimal_to_american(dec: float) -> int:
    if dec <= 1.0:
        raise ValueError(f"invalid decimal odds: {dec}")
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100))
    return int(round(-100.0 / (dec - 1.0)))


def implied_prob(american: int | float) -> float:
    """Raw (vigged) implied probability of a price."""
    return 1.0 / american_to_decimal(american)


def prob_to_american(p: float) -> int:
    """Fair American odds for probability p."""
    p = min(max(p, 1e-6), 1 - 1e-6)
    return decimal_to_american(1.0 / p)


def no_vig_two_way(over_american: int, under_american: int) -> tuple[float, float]:
    """Remove the book margin multiplicatively (normalised implied probs)."""
    po, pu = implied_prob(over_american), implied_prob(under_american)
    s = po + pu
    return po / s, pu / s


def book_margin(over_american: int, under_american: int) -> float:
    return implied_prob(over_american) + implied_prob(under_american) - 1.0


def expected_value(p_win: float, american: int | float, stake: float = 1.0) -> float:
    """EV = P(win) * net profit if won - P(loss) * stake. Pushes are ignored here
    (handled by `expected_value_with_push`)."""
    net = (american_to_decimal(american) - 1.0) * stake
    return p_win * net - (1.0 - p_win) * stake


def expected_value_with_push(p_win: float, p_push: float, american: int | float, stake: float = 1.0) -> float:
    net = (american_to_decimal(american) - 1.0) * stake
    p_loss = max(0.0, 1.0 - p_win - p_push)
    return p_win * net - p_loss * stake


def kelly_fraction(p_win: float, american: int | float) -> float:
    """Full-Kelly fraction of bankroll; 0 when the edge is non-positive."""
    b = american_to_decimal(american) - 1.0
    f = (b * p_win - (1.0 - p_win)) / b
    return max(0.0, f)


def parlay_decimal(prices_american: Sequence[int]) -> float:
    return math.prod(american_to_decimal(a) for a in prices_american)


def profit_units(result: str, american: int, stake: float = 1.0) -> float:
    if result == "win":
        return (american_to_decimal(american) - 1.0) * stake
    if result == "loss":
        return -stake
    return 0.0  # push / void / unresolved
