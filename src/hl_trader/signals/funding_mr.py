"""Funding-extreme mean reversion.

When the hourly funding rate is at an extreme percentile of its rolling
window, positioning is crowded: rich positive funding -> crowded longs ->
go short (and collect funding while in the trade); deeply negative funding ->
crowded shorts -> go long. Hysteresis: enter beyond ``enter_pct``, hold until
funding falls back inside ``exit_pct``, then flat.

Requires a ``funding_rate`` column (hourly rate, HL convention).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hl_trader.signals.base import Signal


@dataclass
class FundingMeanReversion(Signal):
    window_bars: int = 720  # 30 days of hourly funding
    enter_pct: float = 0.95
    exit_pct: float = 0.70
    name: str = "funding_mr"

    def target(self, df: pd.DataFrame) -> pd.Series:
        if "funding_rate" not in df.columns:
            raise ValueError("funding_mr requires a funding_rate column")
        f = df["funding_rate"]
        # Rolling percentile rank of the current funding print within its window.
        rank = f.rolling(self.window_bars).rank(pct=True)

        pos = np.zeros(len(f))
        ranks = rank.to_numpy()
        for i in range(1, len(f)):
            r = ranks[i]
            if np.isnan(r):
                pos[i] = 0.0
                continue
            prev = pos[i - 1]
            if r >= self.enter_pct:
                pos[i] = -1.0  # crowded longs paying rich funding: fade them
            elif r <= 1 - self.enter_pct:
                pos[i] = 1.0
            elif prev < 0 and r >= self.exit_pct:
                pos[i] = prev  # still elevated: hold the short
            elif prev > 0 and r <= 1 - self.exit_pct:
                pos[i] = prev
            else:
                pos[i] = 0.0
        return self._validate(pd.Series(pos, index=df.index), df)
