"""Deep daily history from Yahoo Finance's chart API (no key required).

Used to validate strategies across ASSET CLASSES — commodities (gold, silver,
oil), equity indices (S&P 500, Nasdaq), and crypto — which have decades of daily
history and, crucially, low cross-correlations. Hyperliquid lists 24/7 perps for
these (crypto + HIP-3 commodity/index perps), so a strategy validated on this deep
multi-asset history can be deployed on one venue; this loader supplies the history
the HL perps themselves are too young to provide.

Network access goes through an injectable ``fetch`` callable so parsing is testable
offline.
"""

import io
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

# Friendly name -> Yahoo symbol, grouped by asset class.
MACRO_UNIVERSE = {
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "WTIOIL": "CL=F",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

Fetch = Callable[[str], bytes]


def http_fetch(url: str) -> bytes:
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
    resp.raise_for_status()
    return resp.content


def parse_chart(blob: bytes) -> pd.DataFrame:
    """Parse a Yahoo v8 chart JSON payload into a UTC-daily OHLCV frame."""
    import json

    data = json.loads(blob)
    res = data["chart"]["result"][0]
    ts = pd.to_datetime(res["timestamp"], unit="s", utc=True)
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {"open": q["open"], "high": q["high"], "low": q["low"],
         "close": q["close"], "volume": q["volume"]},
        index=ts,
    )
    df = df.dropna(subset=["close"])
    # normalise to date granularity (drop intraday tz noise); keep one row per day
    df.index = df.index.normalize()
    return df[~df.index.duplicated(keep="last")].sort_index()


class YahooLoader:
    def __init__(self, cache_dir: Path, fetch: Fetch = http_fetch):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._fetch = fetch

    def load(self, name: str, symbol: str | None = None, start: str = "2012-01-01",
             refresh: bool = False) -> pd.DataFrame:
        symbol = symbol or MACRO_UNIVERSE.get(name, name)
        path = self.cache_dir / f"{name}_1d.parquet"
        if path.exists() and not refresh:
            return pd.read_parquet(path)
        # explicit period1/period2 forces true DAILY bars (range=max coarsens to monthly)
        p1 = int(pd.Timestamp(start, tz="UTC").timestamp())
        p2 = int(pd.Timestamp.now(tz="UTC").timestamp())
        url = CHART_URL.format(symbol=symbol) + f"?period1={p1}&period2={p2}&interval=1d"
        df = parse_chart(self._fetch(url))
        df.to_parquet(path)
        return df
