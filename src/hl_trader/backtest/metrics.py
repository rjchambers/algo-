"""Performance metrics computed from an equity curve and trade log."""

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

HOURS_PER_YEAR = 24 * 365


@dataclass(frozen=True)
class Metrics:
    total_return: float
    cagr: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    expectancy: float
    n_closing_trades: int
    turnover: float
    fees_paid: float

    def as_dict(self) -> dict:
        return asdict(self)


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((equity - peak) / peak).min())


def compute_metrics(
    equity: pd.Series,
    trades: pd.DataFrame,
    fees_paid: float,
    bars_per_year: int = HOURS_PER_YEAR,
) -> Metrics:
    returns = equity.pct_change().dropna()
    initial, final = float(equity.iloc[0]), float(equity.iloc[-1])
    total_return = final / initial - 1
    years = len(equity) / bars_per_year
    cagr = (final / initial) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    vol = float(returns.std(ddof=1))
    sharpe = float(returns.mean()) / vol * math.sqrt(bars_per_year) if vol > 0 else float("nan")

    closing = (
        trades[trades["realized_pnl"] != 0.0]
        if not trades.empty
        else pd.DataFrame(columns=["realized_pnl"])
    )
    n_closing = len(closing)
    win_rate = float((closing["realized_pnl"] > 0).mean()) if n_closing else float("nan")
    expectancy = float(closing["realized_pnl"].mean()) if n_closing else float("nan")

    traded_notional = (
        float((trades["filled_units"].abs() * trades["fill_price"]).sum())
        if not trades.empty
        else 0.0
    )
    turnover = traded_notional / float(np.mean(equity)) if len(equity) else 0.0

    return Metrics(
        total_return=total_return,
        cagr=cagr,
        sharpe=sharpe,
        max_drawdown=max_drawdown(equity),
        win_rate=win_rate,
        expectancy=expectancy,
        n_closing_trades=n_closing,
        turnover=turnover,
        fees_paid=fees_paid,
    )
