"""Historical data loading with on-disk parquet cache.

Sources:
- OHLCV: Binance via ccxt (deep history; used as price proxy per plan decision).
- Funding: Binance USD-M perp funding history via ccxt as proxy; Hyperliquid's
  own ``fundingHistory`` endpoint should replace/augment this once the network
  allowlist (blocker B0) is cleared, because HL funding diverges from CEX funding.

All frames are UTC-indexed, sorted, gap-checked. Network access is only
attempted on cache miss; tests run entirely from committed fixtures.
"""

from pathlib import Path

import pandas as pd

from hl_trader.logging_setup import get_logger

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# Plan decision: Binance spot symbols proxy HL perps (deep history).
SYMBOL_MAP = {"BTC": "BTC/USDT", "ETH": "ETH/USDT"}
FUNDING_SYMBOL_MAP = {"BTC": "BTC/USDT:USDT", "ETH": "ETH/USDT:USDT"}

_TIMEFRAME_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class DataGapError(ValueError):
    pass


def check_gaps(df: pd.DataFrame, timeframe: str, max_missing_frac: float = 0.01) -> None:
    """Raise if the index has duplicate bars or too many missing bars."""
    if df.index.has_duplicates:
        raise DataGapError("duplicate timestamps in candle index")
    if not df.index.is_monotonic_increasing:
        raise DataGapError("candle index not sorted")
    step = pd.Timedelta(milliseconds=_TIMEFRAME_MS[timeframe])
    expected = (df.index[-1] - df.index[0]) // step + 1
    missing_frac = 1 - len(df) / expected
    if missing_frac > max_missing_frac:
        raise DataGapError(
            f"{missing_frac:.2%} of expected {timeframe} bars missing (> {max_missing_frac:.0%})"
        )


def _normalize(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="first")]
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    check_gaps(df, timeframe)
    return df


class OhlcvLoader:
    def __init__(self, cache_dir: Path, exchange=None):
        """``exchange`` is a ccxt exchange instance; lazily created if None."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._exchange = exchange
        self._log = get_logger("data.loader")

    def _get_exchange(self):
        if self._exchange is None:
            import ccxt

            self._exchange = ccxt.binance({"enableRateLimit": True})
        return self._exchange

    def _cache_path(self, asset: str, timeframe: str, kind: str = "ohlcv") -> Path:
        return self.cache_dir / f"{kind}_{asset}_{timeframe}.parquet"

    def load_ohlcv(
        self, asset: str, timeframe: str, start: str, end: str, refresh: bool = False
    ) -> pd.DataFrame:
        path = self._cache_path(asset, timeframe)
        if path.exists() and not refresh:
            df = pd.read_parquet(path)
        else:
            df = self._fetch_ohlcv(asset, timeframe, start, end)
            df.to_parquet(path)
        df = _normalize(df, timeframe)
        return df.loc[start:end]

    def _fetch_ohlcv(self, asset: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
        ex = self._get_exchange()
        symbol = SYMBOL_MAP[asset]
        since = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
        rows: list[list] = []
        while since < end_ms:
            batch = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            since = batch[-1][0] + _TIMEFRAME_MS[timeframe]
        self._log.info("fetched_ohlcv", asset=asset, timeframe=timeframe, bars=len(rows))
        df = pd.DataFrame(rows, columns=["ts", *OHLCV_COLUMNS])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df.set_index("ts")

    def load_funding(self, asset: str, start: str, end: str, refresh: bool = False) -> pd.Series:
        """Hourly funding-rate series (rate per hour, HL convention).

        Binance pays 8-hourly; we forward-fill each 8h print across its hours
        and divide by 8 so magnitudes are per-hour, matching HL accrual.
        """
        path = self._cache_path(asset, "1h", kind="funding")
        if path.exists() and not refresh:
            df = pd.read_parquet(path)
        else:
            df = self._fetch_funding(asset, start, end)
            df.to_parquet(path)
        s = df["funding_rate"]
        if s.index.tz is None:
            s.index = s.index.tz_localize("UTC")
        hourly = s.resample("1h").ffill() / 8.0
        return hourly.loc[start:end].rename("funding_rate")

    def _fetch_funding(self, asset: str, start: str, end: str) -> pd.DataFrame:
        ex = self._get_exchange()
        symbol = FUNDING_SYMBOL_MAP[asset]
        since = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
        end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
        rows: list[dict] = []
        while since < end_ms:
            batch = ex.fetch_funding_rate_history(symbol, since=since, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            since = batch[-1]["timestamp"] + 1
        self._log.info("fetched_funding", asset=asset, points=len(rows))
        df = pd.DataFrame(
            {
                "ts": pd.to_datetime([r["timestamp"] for r in rows], unit="ms", utc=True),
                "funding_rate": [float(r["fundingRate"]) for r in rows],
            }
        )
        return df.set_index("ts")


def load_fixture(path: Path) -> pd.DataFrame:
    """Load a committed CSV fixture (UTC index, OHLCV + optional funding_rate)."""
    df = pd.read_csv(path, parse_dates=["ts"], index_col="ts")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()
