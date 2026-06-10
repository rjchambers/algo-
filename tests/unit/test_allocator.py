import numpy as np
import pandas as pd
import pytest

from hl_trader.allocator.allocator import AllocatorParams, allocate


def make_close(n=600, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    return pd.Series(100 * np.exp(np.cumsum(rng.standard_normal(n) * 0.005)), index=idx)


def const_signal(index, value):
    return pd.Series(value, index=index)


def test_weighted_combination():
    close = make_close()
    params = AllocatorParams(
        weights={"a": 3.0, "b": 1.0}, target_annual_vol=1e9, max_leverage=1.0, vol_span_bars=24
    )
    # a long, b short, 3:1 weights -> combined +0.5, leverage capped at 1.
    t = allocate(
        {"a": const_signal(close.index, 1.0), "b": const_signal(close.index, -1.0)},
        close,
        params,
    )
    assert t.iloc[-1] == pytest.approx(0.5)


def test_vol_targeting_scales_down_in_high_vol():
    close = make_close()
    sig = {"a": const_signal(close.index, 1.0)}
    calm = allocate(
        close=close,
        signal_targets=sig,
        params=AllocatorParams(target_annual_vol=0.20, vol_span_bars=24, max_leverage=10.0),
    )
    # Same prices with 5x the volatility -> ~1/5 the exposure.
    vol_close = close.iloc[0] * (close / close.iloc[0]) ** 5
    wild = allocate(
        close=vol_close,
        signal_targets=sig,
        params=AllocatorParams(target_annual_vol=0.20, vol_span_bars=24, max_leverage=10.0),
    )
    assert wild.iloc[-1] < calm.iloc[-1] * 0.4


def test_leverage_cap():
    close = make_close()
    params = AllocatorParams(target_annual_vol=10.0, max_leverage=2.0, vol_span_bars=24)
    t = allocate({"a": const_signal(close.index, 1.0)}, close, params)
    assert t.max() <= 2.0 + 1e-9


def test_warmup_flat_and_unknown_weight_rejected():
    close = make_close()
    t = allocate({"a": const_signal(close.index, 1.0)}, close, AllocatorParams(vol_span_bars=24))
    assert (t.iloc[:10] == 0.0).all()  # vol not yet defined -> no exposure
    with pytest.raises(ValueError, match="unknown signals"):
        allocate(
            {"a": const_signal(close.index, 1.0)}, close, AllocatorParams(weights={"nope": 1.0})
        )
