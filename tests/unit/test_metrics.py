import numpy as np
import pandas as pd
import pytest

from hl_trader.backtest.metrics import compute_metrics, max_drawdown


def test_max_drawdown_known_curve():
    eq = pd.Series([100.0, 120.0, 90.0, 110.0, 130.0])
    assert max_drawdown(eq) == pytest.approx((90 - 120) / 120)


def test_metrics_on_hand_computed_curve():
    idx = pd.date_range("2025-01-01", periods=5, freq="1h", tz="UTC")
    eq = pd.Series([100.0, 101.0, 102.0, 101.0, 103.0], index=idx)
    trades = pd.DataFrame(
        {
            "filled_units": [1.0, -1.0, 2.0],
            "fill_price": [100.0, 105.0, 50.0],
            "realized_pnl": [0.0, 5.0, 0.0],
        }
    )
    m = compute_metrics(eq, trades, fees_paid=1.25, bars_per_year=24 * 365)
    assert m.total_return == pytest.approx(0.03)
    assert m.n_closing_trades == 1
    assert m.win_rate == 1.0
    assert m.expectancy == pytest.approx(5.0)
    assert m.fees_paid == 1.25
    expected_turnover = (100 + 105 + 100) / np.mean(eq)
    assert m.turnover == pytest.approx(expected_turnover)


def test_metrics_no_trades():
    idx = pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC")
    eq = pd.Series([100.0, 100.0, 100.0], index=idx)
    m = compute_metrics(eq, pd.DataFrame(), fees_paid=0.0)
    assert m.total_return == 0.0
    assert m.turnover == 0.0
    assert np.isnan(m.win_rate)
