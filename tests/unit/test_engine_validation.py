"""Phase 1 gate tests: analytic PnL reproduction, no-look-ahead, determinism."""

import numpy as np
import pandas as pd
import pytest

from hl_trader.backtest.costs import CostParams
from hl_trader.backtest.engine import EngineParams, run_backtest

NO_COSTS = CostParams(taker_fee_bps=0.0, maker_fee_bps=0.0, slippage_bps=0.0)


def make_df(closes, opens=None, funding=None):
    closes = np.asarray(closes, dtype=float)
    opens = (
        np.asarray(opens, dtype=float)
        if opens is not None
        else np.concatenate([[closes[0]], closes[:-1]])
    )
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * 1.001,
            "low": np.minimum(opens, closes) * 0.999,
            "close": closes,
            "volume": 1.0,
        },
        index=idx,
    )
    if funding is not None:
        df["funding_rate"] = funding
    return df


def always_long(df):
    return pd.Series(1.0, index=df.index)


def test_buy_and_hold_matches_price_return_no_costs():
    df = make_df([100, 105, 103, 110, 120])
    params = EngineParams(initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0)
    result = run_backtest(df, always_long(df), params)
    # Decision at close of bar 0, filled at open of bar 1 (=100). Fully invested
    # from there: equity tracks close/entry exactly.
    entry = df["open"].iloc[1]
    expected_final = 10_000.0 * df["close"].iloc[-1] / entry
    assert result.equity.iloc[-1] == pytest.approx(expected_final)


def test_always_long_with_fees_matches_analytic():
    fee_bps, slip_bps = 4.5, 2.0
    df = make_df([100, 100, 100, 100])  # flat prices isolate the cost math
    params = EngineParams(
        initial_cash=10_000.0,
        costs=CostParams(taker_fee_bps=fee_bps, maker_fee_bps=0.0, slippage_bps=slip_bps),
        rebalance_threshold=0.05,
    )
    result = run_backtest(df, always_long(df), params)
    # One entry at open of bar 1: fill at 100*(1+slip), units = 10000/100,
    # fee on filled notional. No further trades (within threshold).
    fill = 100 * (1 + slip_bps / 1e4)
    units = 10_000.0 / 100.0
    fee = units * fill * fee_bps / 1e4
    expected_final = (10_000.0 - units * fill - fee) + units * 100.0  # cash + position value
    assert len(result.trades) == 1
    assert result.account.fees_paid == pytest.approx(fee)
    assert result.equity.iloc[-1] == pytest.approx(expected_final)


def test_funding_accrual_long_pays():
    rate = 1e-4
    df = make_df([100, 100, 100], funding=[rate, rate, rate])
    params = EngineParams(initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0)
    result = run_backtest(df, always_long(df), params)
    # Long 100 units from bar 1 open; pays funding on bars 1 and 2:
    # 2 * 100 units * $100 * 1e-4 = $2
    assert result.equity.iloc[-1] == pytest.approx(10_000.0 - 2.0)


def test_no_look_ahead_signal_fills_next_bar():
    # Price doubles on the last bar only. A signal that turns long at the close
    # of the spike bar must NOT capture the spike.
    df = make_df([100, 100, 100, 200])
    target = pd.Series([0.0, 0.0, 0.0, 1.0], index=df.index)
    params = EngineParams(initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0)
    result = run_backtest(df, target, params)
    assert result.equity.iloc[-1] == pytest.approx(10_000.0)  # no profit from the spike
    # Whereas turning long one bar earlier does capture it (open of spike bar = 100).
    early = pd.Series([0.0, 0.0, 1.0, 1.0], index=df.index)
    result_early = run_backtest(df, early, params)
    assert result_early.equity.iloc[-1] == pytest.approx(20_000.0)


def test_determinism_identical_runs(synth_df):
    from hl_trader.signals.momentum import TimeSeriesMomentum

    sig = TimeSeriesMomentum(lookback_bars=24, regime_bars=72)
    params = EngineParams()
    r1 = run_backtest(synth_df, sig.target(synth_df), params)
    r2 = run_backtest(synth_df, sig.target(synth_df), params)
    pd.testing.assert_series_equal(r1.equity, r2.equity)
    pd.testing.assert_frame_equal(r1.trades, r2.trades)


def test_stop_loss_triggers_at_stop_price():
    closes = [100, 100, 80, 80]
    df = make_df(closes)
    df.loc[df.index[2], "low"] = 80.0  # intrabar low breaches the 10% stop at 90
    target = pd.Series(1.0, index=df.index)
    params = EngineParams(
        initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0, stop_frac=0.10
    )
    result = run_backtest(df, target, params)
    stop_trades = result.trades[result.trades["reason"] == "stop"]
    assert len(stop_trades) >= 1
    assert stop_trades.iloc[0]["fill_price"] == pytest.approx(90.0)  # entry 100 * (1-0.10)


def test_take_profit_triggers_at_target_price():
    closes = [100, 100, 130, 130]
    df = make_df(closes)
    df.loc[df.index[2], "high"] = 130.0  # intrabar high reaches the +20% target at 120
    target = pd.Series(1.0, index=df.index)
    params = EngineParams(
        initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0, take_profit_frac=0.20
    )
    result = run_backtest(df, target, params)
    tp = result.trades[result.trades["reason"] == "take_profit"]
    assert len(tp) >= 1
    assert tp.iloc[0]["fill_price"] == pytest.approx(120.0)  # entry 100 * (1+0.20)


def test_take_profit_on_short_closes_on_drop():
    closes = [100, 100, 70, 70]
    df = make_df(closes)
    df.loc[df.index[2], "low"] = 70.0  # short profits as price falls to the -20% target (80)
    target = pd.Series(-1.0, index=df.index)
    params = EngineParams(
        initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0, take_profit_frac=0.20
    )
    result = run_backtest(df, target, params)
    tp = result.trades[result.trades["reason"] == "take_profit"]
    assert len(tp) >= 1
    assert tp.iloc[0]["fill_price"] == pytest.approx(80.0)


def test_kill_switch_flattens_and_stays_flat():
    closes = [100] + [60] * 5  # -40% crash through a 25% kill threshold
    df = make_df(closes)
    target = pd.Series(1.0, index=df.index)
    params = EngineParams(
        initial_cash=10_000.0, costs=NO_COSTS, rebalance_threshold=0.0, max_drawdown_kill=0.25
    )
    result = run_backtest(df, target, params)
    assert result.killed
    assert result.account.units == 0.0
    kill_trades = result.trades[result.trades["reason"] == "kill_switch"]
    assert len(kill_trades) == 1
    # Equity is constant after the kill bar.
    after = result.equity.iloc[2:]
    assert after.nunique() == 1
