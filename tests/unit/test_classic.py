"""Offline tests for the classic-strategy battery: bounded, aligned, no look-ahead."""

import numpy as np
import pandas as pd
import pytest

from hl_trader.signals import classic


def make_df(n=6000, seed=0):
    rng = np.random.default_rng(seed)
    ret = rng.normal(0, 0.004, n)
    close = 100 * np.exp(np.cumsum(ret))
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    high = close * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.002, n)))
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close,
         "volume": 1.0, "funding_rate": rng.normal(1e-5, 5e-5, n)},
        index=idx,
    )


@pytest.fixture(scope="module")
def df():
    return make_df()


@pytest.mark.parametrize("name", list(classic.STRATEGIES))
def test_target_is_bounded_and_aligned(df, name):
    t = classic.STRATEGIES[name](df)
    assert t.index.equals(df.index), f"{name}: index mismatch"
    assert t.between(-1.0, 1.0).all(), f"{name}: target out of [-1,1]"
    assert not t.isna().any(), f"{name}: NaN in target"


@pytest.mark.parametrize("name", list(classic.STRATEGIES))
def test_no_lookahead_prefix_stability(df, name):
    """Target at bar i must not change when future bars are appended/removed.

    Recomputing on a truncated prefix must reproduce the prefix of the full run
    (a signal that peeks ahead would differ).
    """
    fn = classic.STRATEGIES[name]
    full = fn(df)
    cut = len(df) - 500
    prefix = fn(df.iloc[:cut])
    # compare the warmed-up tail of the prefix (avoid trivial all-zero warmup)
    a = full.iloc[cut - 200 : cut].to_numpy()
    b = prefix.iloc[cut - 200 : cut].to_numpy()
    assert np.allclose(a, b, atol=1e-9), f"{name}: look-ahead — prefix differs from full"


def test_rsi_bounds(df):
    r = classic.rsi(df["close"]).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_adx_nonnegative(df):
    a = classic.adx(df).dropna()
    assert (a >= 0).all()


def test_golden_cross_directional():
    # strong uptrend -> +1; strong downtrend -> -1 once both MAs warm
    n = 6000
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    up = pd.Series(np.linspace(100, 300, n), index=idx)
    df_up = pd.DataFrame({"open": up, "high": up, "low": up, "close": up, "volume": 1.0})
    assert classic.golden_cross(df_up).iloc[-1] == 1.0
    down = pd.Series(np.linspace(300, 100, n), index=idx)
    df_dn = pd.DataFrame({"open": down, "high": down, "low": down, "close": down, "volume": 1.0})
    assert classic.golden_cross(df_dn).iloc[-1] == -1.0


def test_combination_is_subset_of_components():
    # triple_trend_confirm only takes a side when golden_cross is also nonzero
    df = make_df(seed=3)
    cross = classic.golden_cross(df)
    combo = classic.triple_trend_confirm(df)
    # wherever the combo is nonzero, the base cross must agree in sign
    nz = combo != 0
    assert (np.sign(combo[nz]) == np.sign(cross[nz])).all()
