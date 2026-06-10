"""Offline tests for the Yahoo daily loader (injected fetch, no network)."""

import json

import pandas as pd

from hl_trader.data.yahoo import YahooLoader, parse_chart


def _payload():
    ts = [int(pd.Timestamp(d, tz="UTC").timestamp()) for d in ("2024-01-02", "2024-01-03", "2024-01-04")]
    return json.dumps({
        "chart": {"result": [{
            "timestamp": ts,
            "indicators": {"quote": [{
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, None],  # trailing NaN should be dropped
                "volume": [1000, 1100, 1200],
            }]},
        }]}
    }).encode()


def test_parse_chart_builds_daily_ohlcv():
    df = parse_chart(_payload())
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None
    assert len(df) == 2  # the NaN-close row is dropped
    assert df["close"].iloc[0] == 100.5
    assert (df.index == df.index.normalize()).all()


def test_loader_caches(tmp_path):
    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        return _payload()

    y = YahooLoader(tmp_path, fetch=fake_fetch)
    df1 = y.load("GOLD", "GC=F")
    assert (tmp_path / "GOLD_1d.parquet").exists()
    assert calls["n"] == 1
    # second load hits cache (no extra fetch)
    df2 = y.load("GOLD", "GC=F")
    assert calls["n"] == 1
    # parquet round-trip may change datetime resolution (ns->ms); compare values
    assert df1.shape == df2.shape
    assert (df1.to_numpy() == df2.to_numpy()).all()
    assert list(df1.index.date) == list(df2.index.date)


def test_loader_passes_daily_interval_and_period(tmp_path):
    seen = {}

    def fake_fetch(url):
        seen["url"] = url
        return _payload()

    YahooLoader(tmp_path, fetch=fake_fetch).load("WTIOIL", "CL=F", start="2015-01-01")
    assert "interval=1d" in seen["url"]
    assert "period1=" in seen["url"] and "period2=" in seen["url"]
