"""Signal interface.

A signal maps market data to a desired exposure series in [-1, 1], where the
value at timestamp t may use ONLY data up to and including bar t (rolling /
expanding operations). The engine adds the execution delay (fill at t+1 open),
so a correctly implemented signal has zero look-ahead end to end.
"""

from abc import ABC, abstractmethod

import pandas as pd


class Signal(ABC):
    name: str

    @abstractmethod
    def target(self, df: pd.DataFrame) -> pd.Series:
        """Return desired exposure in [-1, 1], indexed like ``df``."""

    def _validate(self, s: pd.Series, df: pd.DataFrame) -> pd.Series:
        s = s.clip(-1.0, 1.0)
        if not s.index.equals(df.index):
            raise ValueError(f"{self.name}: target index must match data index")
        return s.rename(self.name)
