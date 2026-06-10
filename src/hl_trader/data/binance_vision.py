"""Deep-history loader for Binance's public data archive (data.binance.vision).

Why this exists: the Binance REST API (``api.binance.com``) is geo-blocked
(HTTP 451) from this execution environment, and every other CEX REST host is
outside the network allowlist. Binance's *static* archive
(``data.binance.vision``) is reachable and serves the same exchange data as
monthly/daily CSV-in-ZIP files going back to 2017. We use it as the §2.6
deep-history price/funding/open-interest source.

This is a faithful substitution for the ccxt path in ``loader.py``: identical
Binance data, different transport. Hyperliquid fees/funding are still modelled
in the backtest; Binance prices are only the deep-history *proxy* per the plan.

All network access goes through an injectable ``downloader`` callable so the
parsing logic is covered by offline tests (no archive access required).

Archive layout used:
- spot klines:   data/spot/monthly/klines/{SYM}/1h/{SYM}-1h-{YYYY-MM}.zip
- UM funding:    data/futures/um/monthly/fundingRate/{SYM}/{SYM}-fundingRate-{YYYY-MM}.zip
- UM OI metrics: data/futures/um/daily/metrics/{SYM}/{SYM}-metrics-{YYYY-MM-DD}.zip
"""

import io
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pandas as pd
import requests

from hl_trader.logging_setup import get_logger

BASE_URL = "https://data.binance.vision"

# Binance kline CSV columns (no header in the archive files).
_KLINE_COLS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]

Downloader = Callable[[str], bytes | None]

_log = get_logger("data.binance_vision")


def http_download(url: str) -> bytes | None:
    """Default downloader: GET ``url``; return body bytes, or None on 404.

    A 404 is expected (a month/day with no file, e.g. the in-progress month)
    and is signalled by returning None so callers can skip it; other HTTP
    errors propagate.
    """
    resp = requests.get(url, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


def _read_zip_csv(blob: bytes, header: int | None) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as fh:
            return pd.read_csv(fh, header=header)


def _months(start: pd.Timestamp, end: pd.Timestamp) -> Iterator[str]:
    """Yield 'YYYY-MM' for each month touching [start, end)."""
    cur = start.tz_convert("UTC").tz_localize(None).to_period("M")
    last = (end - pd.Timedelta(seconds=1)).tz_convert("UTC").tz_localize(None).to_period("M")
    while cur <= last:
        yield str(cur)
        cur += 1


def _days(start: pd.Timestamp, end: pd.Timestamp) -> Iterator[str]:
    for ts in pd.date_range(start.normalize(), end.normalize(), freq="D", tz="UTC"):
        yield ts.strftime("%Y-%m-%d")


def _to_utc_ms(series: pd.Series) -> pd.DatetimeIndex:
    """Parse a Binance epoch column to a UTC index.

    Binance switched archive timestamps from milliseconds to microseconds in
    2025. A single concatenated multi-year frame can therefore contain BOTH
    units, so detect per element (microseconds have ~16 digits, > 1e14) and
    normalise everything to milliseconds before parsing.
    """
    vals = pd.to_numeric(series).astype("int64")
    ms = vals.where(vals < 10**14, vals // 1000)
    return pd.DatetimeIndex(pd.to_datetime(ms, unit="ms", utc=True))


class BinanceVisionLoader:
    """Cache-first loader pulling deep history from the Binance Vision archive."""

    def __init__(self, cache_dir: Path, downloader: Downloader = http_download):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._download = downloader

    def _cache_path(self, kind: str, symbol: str) -> Path:
        return self.cache_dir / f"{kind}_{symbol}.parquet"

    # -- OHLCV (any kline interval) ----------------------------------------
    def load_ohlcv(
        self, symbol: str, start: str, end: str, interval: str = "1h", refresh: bool = False
    ) -> pd.DataFrame:
        path = self._cache_path(f"ohlcv_{interval}", symbol)
        if path.exists() and not refresh:
            df = pd.read_parquet(path)
        else:
            df = self._fetch_ohlcv(
                symbol, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"), interval
            )
            df.to_parquet(path)
        return df.loc[start:end]

    def _fetch_ohlcv(
        self, symbol: str, start: pd.Timestamp, end: pd.Timestamp, interval: str = "1h"
    ) -> pd.DataFrame:
        frames = []
        for ym in _months(start, end):
            url = f"{BASE_URL}/data/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{ym}.zip"
            blob = self._download(url)
            if blob is None:
                _log.info("vision_missing", kind="klines", symbol=symbol, period=ym)
                continue
            raw = _read_zip_csv(blob, header=None)
            raw.columns = _KLINE_COLS[: raw.shape[1]]
            frames.append(raw)
        if not frames:
            raise FileNotFoundError(f"no kline files for {symbol} in {start}..{end}")
        df = pd.concat(frames, ignore_index=True)
        idx = _to_utc_ms(df["open_time"])
        out = pd.DataFrame(
            {c: pd.to_numeric(df[c]).to_numpy() for c in ["open", "high", "low", "close", "volume"]},
            index=idx,
        )
        out = out[~out.index.duplicated(keep="first")].sort_index()
        _log.info("vision_ohlcv", symbol=symbol, bars=len(out))
        return out

    # -- funding (8h -> hourly, HL-magnitude convention) -------------------
    def load_funding(self, symbol: str, start: str, end: str, refresh: bool = False) -> pd.Series:
        """Hourly funding-rate series (per-hour magnitude, like loader.py).

        Binance settles funding every 8h; we forward-fill each print across its
        8 hours and divide by 8 so magnitudes match Hyperliquid's hourly accrual.
        """
        path = self._cache_path("funding", symbol)
        if path.exists() and not refresh:
            raw = pd.read_parquet(path)
        else:
            raw = self._fetch_funding(symbol, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
            raw.to_parquet(path)
        s = raw["funding_rate"]
        if s.index.tz is None:
            s.index = s.index.tz_localize("UTC")
        hourly = s.resample("1h").ffill() / 8.0
        return hourly.loc[start:end].rename("funding_rate")

    def _fetch_funding(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        frames = []
        for ym in _months(start, end):
            url = f"{BASE_URL}/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{ym}.zip"
            blob = self._download(url)
            if blob is None:
                _log.info("vision_missing", kind="funding", symbol=symbol, period=ym)
                continue
            frames.append(_read_zip_csv(blob, header=0))
        if not frames:
            raise FileNotFoundError(f"no funding files for {symbol} in {start}..{end}")
        df = pd.concat(frames, ignore_index=True)
        idx = _to_utc_ms(df["calc_time"])
        out = pd.DataFrame(
            {"funding_rate": pd.to_numeric(df["last_funding_rate"]).to_numpy()}, index=idx
        )
        out = out[~out.index.duplicated(keep="first")].sort_index()
        _log.info("vision_funding", symbol=symbol, points=len(out))
        return out

    # -- open interest (5-min metrics -> hourly) --------------------------
    def load_open_interest(
        self, symbol: str, start: str, end: str, refresh: bool = False
    ) -> pd.Series:
        """Hourly open-interest (contracts) from the UM futures metrics archive."""
        path = self._cache_path("oi", symbol)
        if path.exists() and not refresh:
            raw = pd.read_parquet(path)
        else:
            raw = self._fetch_oi(symbol, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
            raw.to_parquet(path)
        s = raw["open_interest"]
        if s.index.tz is None:
            s.index = s.index.tz_localize("UTC")
        hourly = s.resample("1h").last().ffill()
        return hourly.loc[start:end].rename("open_interest")

    def _fetch_oi(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        frames = []
        for ymd in _days(start, end):
            url = f"{BASE_URL}/data/futures/um/daily/metrics/{symbol}/{symbol}-metrics-{ymd}.zip"
            blob = self._download(url)
            if blob is None:
                continue
            frames.append(_read_zip_csv(blob, header=0))
        if not frames:
            raise FileNotFoundError(f"no metrics files for {symbol} in {start}..{end}")
        df = pd.concat(frames, ignore_index=True)
        idx = pd.DatetimeIndex(pd.to_datetime(df["create_time"], utc=True))
        out = pd.DataFrame(
            {"open_interest": pd.to_numeric(df["sum_open_interest"]).to_numpy()}, index=idx
        )
        out = out[~out.index.duplicated(keep="first")].sort_index()
        _log.info("vision_oi", symbol=symbol, points=len(out))
        return out
