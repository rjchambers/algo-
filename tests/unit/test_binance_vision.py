"""Offline tests for the Binance Vision archive loader.

A fake downloader returns in-memory ZIP blobs, so parsing/alignment is covered
without any network access (lessons.md: build offline-first).
"""

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from hl_trader.data.binance_vision import BinanceVisionLoader


def _zip(name: str, csv_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, csv_text)
    return buf.getvalue()


def _kline_csv(start_ms: int, n: int, price: float = 100.0) -> str:
    rows = []
    for i in range(n):
        t = start_ms + i * 3_600_000
        rows.append(f"{t},{price},{price + 1},{price - 1},{price + 0.5},10,"
                    f"{t + 3_599_999},1000,5,5,500,0")
    return "\n".join(rows) + "\n"


class FakeArchive:
    """Serves klines for 2024-01 and 2024-02, funding + metrics for 2024-01."""

    def __init__(self):
        jan = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
        feb = int(pd.Timestamp("2024-02-01", tz="UTC").timestamp() * 1000)
        self.store = {
            "BTCUSDT-1h-2024-01.zip": _zip("BTCUSDT-1h-2024-01.csv", _kline_csv(jan, 744, 100)),
            "BTCUSDT-1h-2024-02.zip": _zip("BTCUSDT-1h-2024-02.csv", _kline_csv(feb, 696, 200)),
            "BTCUSDT-fundingRate-2024-01.zip": _zip(
                "BTCUSDT-fundingRate-2024-01.csv",
                "calc_time,funding_interval_hours,last_funding_rate\n"
                f"{jan},8,0.0008\n{jan + 8 * 3_600_000},8,0.0016\n",
            ),
            "BTCUSDT-metrics-2024-01-01.zip": _zip(
                "BTCUSDT-metrics-2024-01-01.csv",
                "create_time,symbol,sum_open_interest,sum_open_interest_value\n"
                "2024-01-01 00:00:00,BTCUSDT,70000,7000000\n"
                "2024-01-01 00:05:00,BTCUSDT,70500,7050000\n"
                "2024-01-01 01:00:00,BTCUSDT,71000,7100000\n",
            ),
        }

    def __call__(self, url: str):
        return self.store.get(url.rsplit("/", 1)[1])  # None on miss == 404


def test_load_ohlcv_concatenates_months(tmp_path):
    v = BinanceVisionLoader(tmp_path, downloader=FakeArchive())
    df = v.load_ohlcv("BTCUSDT", "2024-01-01", "2024-02-29")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None
    assert df.index.is_monotonic_increasing and not df.index.has_duplicates
    assert len(df) == 744 + 696
    # February price block differs from January (real values parsed, not NaN)
    assert df["open"].iloc[0] == 100.0
    assert df["open"].iloc[-1] == 200.0
    assert not df.isna().any().any()


def test_ohlcv_caches_and_slices(tmp_path):
    arch = FakeArchive()
    v = BinanceVisionLoader(tmp_path, downloader=arch)
    v.load_ohlcv("BTCUSDT", "2024-01-01", "2024-02-29")
    assert (tmp_path / "ohlcv_1h_BTCUSDT.parquet").exists()  # cache key includes interval
    # second loader hits cache (broken downloader proves no network needed)
    v2 = BinanceVisionLoader(tmp_path, downloader=lambda url: (_ for _ in ()).throw(AssertionError))
    sliced = v2.load_ohlcv("BTCUSDT", "2024-01-10", "2024-01-12")
    assert sliced.index[0] >= pd.Timestamp("2024-01-10", tz="UTC")
    assert sliced.index[-1] <= pd.Timestamp("2024-01-12 23:59", tz="UTC")


def test_funding_resampled_to_hourly_magnitude(tmp_path):
    v = BinanceVisionLoader(tmp_path, downloader=FakeArchive())
    s = v.load_funding("BTCUSDT", "2024-01-01", "2024-01-01 12:00")
    assert s.name == "funding_rate"
    # first 8h print 0.0008 spread to hourly /8 == 0.0001
    assert s.iloc[0] == pytest.approx(0.0001)
    assert s.iloc[8] == pytest.approx(0.0002)  # second print 0.0016/8


def test_open_interest_resampled_hourly(tmp_path):
    v = BinanceVisionLoader(tmp_path, downloader=FakeArchive())
    oi = v.load_open_interest("BTCUSDT", "2024-01-01", "2024-01-01 02:00")
    assert oi.name == "open_interest"
    # 00:00 hour takes the last 5-min print before 01:00 (70500), 01:00 -> 71000
    assert oi.loc["2024-01-01 00:00"] == 70500
    assert oi.loc["2024-01-01 01:00"] == 71000


def test_missing_month_skipped_not_fatal(tmp_path):
    # request a range whose later month has no file; the present month still loads
    v = BinanceVisionLoader(tmp_path, downloader=FakeArchive())
    df = v.load_ohlcv("BTCUSDT", "2024-01-01", "2024-03-31")
    assert len(df) == 744 + 696  # March absent, Jan+Feb returned


def test_mixed_ms_and_microsecond_timestamps_parsed(tmp_path):
    # Binance switched archive epochs ms -> microseconds in 2025; a multi-year
    # concatenation contains BOTH, so each row's unit must be detected per element.
    dec_ms = int(pd.Timestamp("2024-12-01", tz="UTC").timestamp() * 1000)
    jan_us = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1_000_000)
    dec = "\n".join(f"{dec_ms + i * 3_600_000},10,11,9,10.5,1,0,1,1,1,1,0" for i in range(3))
    jan = "\n".join(f"{jan_us + i * 3_600_000_000},20,21,19,20.5,1,0,1,1,1,1,0" for i in range(3))

    def arch(url):
        return _zip("x.csv", (dec if "2024-12" in url else jan) + "\n")

    v = BinanceVisionLoader(tmp_path, downloader=arch)
    df = v.load_ohlcv("BTCUSDT", "2024-12-01", "2025-01-31")
    # both eras land in their true year, sorted, no far-future garbage
    assert df.index[0] == pd.Timestamp("2024-12-01 00:00", tz="UTC")
    assert df.index[-1] == pd.Timestamp("2025-01-01 02:00", tz="UTC")
    assert df.index.year.max() == 2025
    assert np.isclose(df["close"].iloc[0], 10.5)
    assert np.isclose(df["close"].iloc[-1], 20.5)
