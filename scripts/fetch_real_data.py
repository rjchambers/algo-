"""Pull the §2.6 real-data set and build one hourly frame per asset.

Sources (all real exchange data):
- price OHLCV + Binance funding + open interest: Binance Vision archive
  (``data.binance.vision``; used because api.binance.com is geo-blocked here).
- Hyperliquid's own funding: live Info ``fundingHistory`` (paginated), the
  HL-faithful series for the funding-spread variant.

Output: ``data_cache/real/{ASSET}_1h.parquet`` with columns
open, high, low, close, volume, funding_rate (Binance, per-hour),
hl_funding_rate (per-hour), open_interest. UTC-indexed, gap-checked.

Usage:
    .venv/bin/python scripts/fetch_real_data.py [--start 2023-06-01] [--end 2026-06-01]
"""

import argparse
from pathlib import Path

import pandas as pd

from hl_trader.config import load_settings
from hl_trader.data.binance_vision import BinanceVisionLoader
from hl_trader.data.loader import check_gaps
from hl_trader.exchange.hyperliquid_client import HyperliquidInfoClient
from hl_trader.logging_setup import configure_logging, get_logger

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data_cache"  # bulky raw archive cache (gitignored)
OUT = ROOT / "tests" / "fixtures" / "real"  # consolidated, committed for reproducibility

# Binance Vision spot symbols proxy HL perps (plan decision); UM futures share
# the same symbol string for funding + metrics.
VISION_SYMBOL = {"BTC": "BTCUSDT", "ETH": "ETHUSDT"}


def fetch_hl_funding(client: HyperliquidInfoClient, coin: str, start: str, end: str) -> pd.Series:
    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)
    rows = client.funding_history_all(coin, start_ms, end_ms)
    idx = pd.to_datetime([r["time"] for r in rows], unit="ms", utc=True)
    s = pd.Series([float(r["fundingRate"]) for r in rows], index=idx, name="hl_funding_rate")
    s = s[~s.index.duplicated(keep="first")].sort_index()
    # HL funds hourly; snap to the hour grid to align with Binance-derived hourly.
    return s.resample("1h").last().ffill()


def build_asset(asset: str, start: str, end: str, vision: BinanceVisionLoader,
                hl: HyperliquidInfoClient, log) -> pd.DataFrame:
    sym = VISION_SYMBOL[asset]
    ohlcv = vision.load_ohlcv(sym, start, end)
    funding = vision.load_funding(sym, start, end)
    oi = vision.load_open_interest(sym, start, end)
    hl_funding = fetch_hl_funding(hl, asset, start, end)

    df = ohlcv.copy()
    df["funding_rate"] = funding.reindex(df.index).ffill()
    df["hl_funding_rate"] = hl_funding.reindex(df.index).ffill()
    df["open_interest"] = oi.reindex(df.index).ffill()
    # Drop the warmup head where any series is still NaN.
    df = df.dropna()
    check_gaps(df, "1h", max_missing_frac=0.02)
    log.info(
        "asset_built", asset=asset, bars=len(df),
        first=str(df.index[0]), last=str(df.index[-1]),
        hl_funding_cov=f"{df['hl_funding_rate'].notna().mean():.1%}",
    )
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2023-06-01")
    parser.add_argument("--end", default="2026-06-01")
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    args = parser.parse_args()

    configure_logging("INFO")
    log = get_logger("fetch_real_data")
    OUT.mkdir(parents=True, exist_ok=True)

    vision = BinanceVisionLoader(CACHE / "vision")
    settings = load_settings(network="mainnet")
    hl = HyperliquidInfoClient(settings.api_url)

    for asset in args.assets:
        df = build_asset(asset, args.start, args.end, vision, hl, log)
        out_path = OUT / f"{asset}_1h.parquet"
        df.to_parquet(out_path)
        log.info("wrote", path=str(out_path), bars=len(df))


if __name__ == "__main__":
    main()
