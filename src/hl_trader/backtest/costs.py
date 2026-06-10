"""Hyperliquid-faithful trading cost model.

Fee schedule source: Hyperliquid docs ("Fees"), base tier for perps:
taker 0.045%, maker 0.015%. Volume tiers and staking discounts lower these;
we model the conservative base tier. Slippage is a fixed-bps penalty on top
of the fill price (fills never happen at mid). Funding accrues hourly; a
positive rate means longs pay shorts (HL convention).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostParams:
    taker_fee_bps: float = 4.5
    maker_fee_bps: float = 1.5
    slippage_bps: float = 2.0

    @property
    def taker_fee_rate(self) -> float:
        return self.taker_fee_bps / 10_000

    @property
    def maker_fee_rate(self) -> float:
        return self.maker_fee_bps / 10_000

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000


def fill_price(reference_price: float, trade_units: float, params: CostParams) -> float:
    """Execution price after slippage: buys fill above reference, sells below."""
    if trade_units > 0:
        return reference_price * (1 + params.slippage_rate)
    if trade_units < 0:
        return reference_price * (1 - params.slippage_rate)
    return reference_price


def taker_fee(notional: float, params: CostParams) -> float:
    return abs(notional) * params.taker_fee_rate


def funding_payment(position_units: float, mark_price: float, hourly_rate: float) -> float:
    """Cash flow from one hour of funding. Negative = position pays.

    Long position with positive funding pays; short with positive funding receives.
    """
    return -position_units * mark_price * hourly_rate
