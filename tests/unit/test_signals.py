import numpy as np
import pandas as pd
import pytest

from hl_trader.signals.funding_mr import FundingMeanReversion
from hl_trader.signals.momentum import TimeSeriesMomentum


def make_df(closes, funding=None):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 1.0,
        },
        index=idx,
    )
    if funding is not None:
        df["funding_rate"] = funding
    return df


class TestMomentum:
    def test_long_in_uptrend_short_in_downtrend(self):
        up = make_df(np.linspace(100, 200, 50))
        sig = TimeSeriesMomentum(lookback_bars=5, regime_bars=10)
        t = sig.target(up)
        assert (t.iloc[15:] == 1.0).all()

        down = make_df(np.linspace(200, 100, 50))
        t = sig.target(down)
        assert (t.iloc[15:] == -1.0).all()

    def test_flat_when_momentum_and_regime_disagree(self):
        # Long uptrend, then a sharp short-term reversal: momentum flips short
        # before price crosses below the slow mean -> signal must go flat, not short.
        closes = np.concatenate([np.linspace(100, 200, 60), np.linspace(200, 185, 6)])
        df = make_df(closes)
        sig = TimeSeriesMomentum(lookback_bars=5, regime_bars=50)
        t = sig.target(df)
        assert t.iloc[-1] == 0.0

    def test_warmup_is_flat(self):
        df = make_df(np.linspace(100, 200, 30))
        t = TimeSeriesMomentum(lookback_bars=5, regime_bars=10).target(df)
        assert (t.iloc[:5] == 0.0).all()

    def test_bounded(self, synth_df):
        t = TimeSeriesMomentum(lookback_bars=24, regime_bars=72).target(synth_df)
        assert t.between(-1, 1).all()


class TestFundingMR:
    def test_requires_funding_column(self):
        df = make_df([100, 100])
        with pytest.raises(ValueError, match="funding_rate"):
            FundingMeanReversion().target(df)

    def test_fades_rich_funding_and_exits_on_normalization(self):
        n = 60
        funding = np.full(n, 1e-5)
        funding[40:50] = 5e-4  # extreme positive funding block
        df = make_df(np.full(n, 100.0), funding=funding)
        sig = FundingMeanReversion(window_bars=20, enter_pct=0.9, exit_pct=0.6)
        t = sig.target(df)
        assert (t.iloc[41:50] == -1.0).all()  # short while funding is extreme
        assert t.iloc[55] == 0.0  # flat again once funding normalizes

    def test_goes_long_deeply_negative_funding(self):
        n = 60
        funding = np.full(n, 1e-5)
        funding[40:50] = -5e-4
        df = make_df(np.full(n, 100.0), funding=funding)
        sig = FundingMeanReversion(window_bars=20, enter_pct=0.9, exit_pct=0.6)
        t = sig.target(df)
        assert (t.iloc[41:50] == 1.0).all()

    def test_warmup_is_flat(self):
        n = 30
        df = make_df(np.full(n, 100.0), funding=np.full(n, 1e-5))
        t = FundingMeanReversion(window_bars=20).target(df)
        assert (t.iloc[:19] == 0.0).all()
