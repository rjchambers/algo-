"""Deterministic bar-by-bar backtest engine.

No-look-ahead contract: ``target[t]`` is the exposure decided at the CLOSE of
bar ``t`` (computed only from data up to t). The engine executes that decision
at the OPEN of bar ``t+1``. This shift happens inside the engine so a strategy
cannot accidentally trade on the bar that produced its signal.

Costs: taker fees + slippage on every fill (see costs.py), hourly funding
accrual if the data has a ``funding_rate`` column.

Risk controls handled here (they need the live equity curve):
- protective stop: close the position if the intrabar extreme moves
  ``stop_frac`` against the average entry price;
- kill switch: if equity drawdown from its peak exceeds
  ``max_drawdown_kill``, flatten and stay flat for the rest of the run.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from hl_trader.backtest.costs import CostParams, fill_price, funding_payment, taker_fee
from hl_trader.backtest.portfolio import Account


@dataclass
class EngineParams:
    initial_cash: float = 100_000.0
    costs: CostParams = CostParams()
    rebalance_threshold: float = 0.02  # skip trades smaller than this fraction of equity
    stop_frac: float | None = None  # e.g. 0.05 = close if price moves 5% against entry
    take_profit_frac: float | None = None  # e.g. 0.10 = close if price moves 10% in favour
    max_drawdown_kill: float | None = None  # e.g. 0.25 = flatten for good at -25% equity DD


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    account: Account
    killed: bool

    def to_csv(self, out_dir) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.equity.rename("equity").to_csv(out_dir / "equity_curve.csv")
        self.trades.to_csv(out_dir / "trades.csv", index=False)


def run_backtest(
    df: pd.DataFrame, target: pd.Series, params: EngineParams | None = None
) -> BacktestResult:
    """Run the event loop over ``df`` (OHLCV + optional funding_rate).

    ``target`` is desired exposure as a signed fraction of equity, indexed like
    ``df``. NaN means "no decision: hold current position".
    """
    params = params or EngineParams()
    if not df.index.equals(target.index):
        raise ValueError("target index must match data index")

    # The no-look-ahead shift: decision at close of t fills at open of t+1.
    exec_target = target.shift(1)

    has_funding = "funding_rate" in df.columns
    acct = Account(cash=params.initial_cash)
    equity_values = np.empty(len(df))
    peak_equity = params.initial_cash
    killed = False
    prev_close_equity = params.initial_cash

    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    fundings = df["funding_rate"].to_numpy() if has_funding else None
    targets = exec_target.to_numpy()
    index = df.index

    for i in range(len(df)):
        ts, o, c = index[i], opens[i], closes[i]

        # 1) Execute the previous bar's decision at this bar's open.
        t = targets[i]
        if not killed and not np.isnan(t):
            desired_units = t * prev_close_equity / o
            trade_units = desired_units - acct.units
            if abs(trade_units) * o / max(prev_close_equity, 1e-9) >= params.rebalance_threshold:
                px = fill_price(o, trade_units, params.costs)
                fee = taker_fee(trade_units * px, params.costs)
                acct.apply_fill(ts, trade_units, px, fee, "rebalance")

        # 2) Protective stop on intrabar extremes.
        if params.stop_frac is not None and acct.units != 0:
            if acct.units > 0:
                stop_px = acct.avg_entry * (1 - params.stop_frac)
                if lows[i] <= stop_px:
                    px = fill_price(stop_px, -acct.units, params.costs)
                    fee = taker_fee(acct.units * px, params.costs)
                    acct.apply_fill(ts, -acct.units, px, fee, "stop")
            else:
                stop_px = acct.avg_entry * (1 + params.stop_frac)
                if highs[i] >= stop_px:
                    px = fill_price(stop_px, -acct.units, params.costs)
                    fee = taker_fee(acct.units * px, params.costs)
                    acct.apply_fill(ts, -acct.units, px, fee, "stop")

        # 2b) Take-profit on intrabar extremes. Stop is checked first, so when a
        # bar's range spans both levels we conservatively assume the stop hit.
        if params.take_profit_frac is not None and acct.units != 0:
            if acct.units > 0:
                tp_px = acct.avg_entry * (1 + params.take_profit_frac)
                if highs[i] >= tp_px:
                    px = fill_price(tp_px, -acct.units, params.costs)
                    fee = taker_fee(acct.units * px, params.costs)
                    acct.apply_fill(ts, -acct.units, px, fee, "take_profit")
            else:
                tp_px = acct.avg_entry * (1 - params.take_profit_frac)
                if lows[i] <= tp_px:
                    px = fill_price(tp_px, -acct.units, params.costs)
                    fee = taker_fee(acct.units * px, params.costs)
                    acct.apply_fill(ts, -acct.units, px, fee, "take_profit")

        # 3) Hourly funding accrual, marked at the bar close.
        if fundings is not None and acct.units != 0 and not np.isnan(fundings[i]):
            acct.cash += funding_payment(acct.units, c, fundings[i])

        # 4) Mark equity at close; kill switch check.
        equity = acct.equity(c)
        peak_equity = max(peak_equity, equity)
        if (
            params.max_drawdown_kill is not None
            and not killed
            and equity < peak_equity * (1 - params.max_drawdown_kill)
        ):
            if acct.units != 0:
                px = fill_price(c, -acct.units, params.costs)
                fee = taker_fee(acct.units * px, params.costs)
                acct.apply_fill(ts, -acct.units, px, fee, "kill_switch")
                equity = acct.equity(c)
            killed = True

        equity_values[i] = equity
        prev_close_equity = equity

    equity_series = pd.Series(equity_values, index=index, name="equity")
    trades_df = pd.DataFrame([vars(t) for t in acct.trades])
    return BacktestResult(equity=equity_series, trades=trades_df, account=acct, killed=killed)
