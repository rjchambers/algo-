"""Time-series momentum with a slow regime filter.

Long when the lookback return is positive AND price is above the slow moving
average; short when both point down; flat when they disagree. The regime
filter cuts the chop-bleed that kills naive TSMOM at hourly frequency.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hl_trader.signals.base import Signal


@dataclass
class TimeSeriesMomentum(Signal):
    lookback_bars: int = 168  # 1 week of 1h bars
    regime_bars: int = 1440  # ~60 days of 1h bars
    name: str = "tsmom"

    def target(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        mom = np.sign(close.pct_change(self.lookback_bars))
        regime = np.sign(close - close.rolling(self.regime_bars).mean())
        agree = mom == regime
        raw = mom.where(agree, 0.0).fillna(0.0)
        return self._validate(raw, df)
