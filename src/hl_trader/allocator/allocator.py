"""The single deterministic allocator (spec §6: one place sizes risk).

Combines per-signal targets with fixed weights, then scales the combined
exposure with volatility targeting so realized portfolio vol tracks
``target_annual_vol``, capped at ``max_leverage``. Drawdown kill-switch lives
in the engine (it needs the live equity curve); leverage discipline lives here.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 24 * 365


@dataclass
class AllocatorParams:
    weights: dict[str, float] = field(default_factory=dict)  # signal name -> weight
    target_annual_vol: float = 0.20
    vol_span_bars: int = 240  # EWMA span for realized vol (10 days of 1h bars)
    max_leverage: float = 2.0
    bars_per_year: int = HOURS_PER_YEAR


def realized_vol(close: pd.Series, span: int, bars_per_year: int) -> pd.Series:
    returns = close.pct_change()
    return returns.ewm(span=span, min_periods=span).std() * np.sqrt(bars_per_year)


def allocate(
    signal_targets: dict[str, pd.Series], close: pd.Series, params: AllocatorParams
) -> pd.Series:
    """Combine signal targets into one engine-ready exposure series."""
    if not signal_targets:
        raise ValueError("no signal targets provided")
    unknown = set(params.weights) - set(signal_targets)
    if unknown:
        raise ValueError(f"weights reference unknown signals: {sorted(unknown)}")

    total_weight = sum(params.weights.get(name, 1.0) for name in signal_targets)
    combined = sum(s * params.weights.get(name, 1.0) for name, s in signal_targets.items()) / max(
        total_weight, 1e-12
    )
    combined = combined.clip(-1.0, 1.0)

    vol = realized_vol(close, params.vol_span_bars, params.bars_per_year)
    leverage = (params.target_annual_vol / vol).clip(upper=params.max_leverage)

    target = (combined * leverage).fillna(0.0)
    return target.clip(-params.max_leverage, params.max_leverage).rename("target")
