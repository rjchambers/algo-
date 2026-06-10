"""Fast broad-universe fetch: OHLCV + Binance funding only (no open interest).

The trend and cross-sectional-momentum streams need price (and optionally funding),
not open interest — so we skip the slow daily OI downloads and pull a large liquid
universe quickly from the Binance Vision archive. Writes per-asset hourly frames to
data_cache/real_universe/ (gitignored; regenerable). Assets with no archive data or
too-short history are skipped.

Usage:
    .venv/bin/python scripts/fetch_universe.py [--start 2023-06-01] [--end 2026-06-01]
"""

import argparse
from pathlib import Path

import pandas as pd

from hl_trader.data.binance_vision import BinanceVisionLoader
from hl_trader.data.loader import check_gaps
from hl_trader.logging_setup import configure_logging, get_logger

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data_cache" / "real_universe"

# Liquid perps with Binance Vision spot history and Hyperliquid listings.
UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC",
    "DOT", "ATOM", "NEAR", "FIL", "APT", "ARB", "INJ", "AAVE", "UNI", "SUI",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-06-01")
    ap.add_argument("--end", default="2026-06-01")
    args = ap.parse_args()
    configure_logging("ERROR")
    log = get_logger("fetch_universe")
    OUT.mkdir(parents=True, exist_ok=True)
    v = BinanceVisionLoader(ROOT / "data_cache" / "vision")

    ok, skipped = [], []
    for asset in UNIVERSE:
        sym = f"{asset}USDT"
        try:
            ohlcv = v.load_ohlcv(sym, args.start, args.end)
            funding = v.load_funding(sym, args.start, args.end)
            df = ohlcv.copy()
            df["funding_rate"] = funding.reindex(df.index).ffill()
            df = df.dropna()
            if len(df) < 24 * 180:  # need >=~6 months
                skipped.append((asset, f"only {len(df)} bars"))
                continue
            check_gaps(df, "1h", max_missing_frac=0.05)
            df.to_parquet(OUT / f"{asset}_1h.parquet")
            ok.append(asset)
            log.info("fetched", asset=asset, bars=len(df),
                     first=str(df.index[0].date()), last=str(df.index[-1].date()))
        except Exception as e:  # noqa: BLE001
            skipped.append((asset, str(e)[:60]))
    print(f"fetched {len(ok)}: {', '.join(ok)}")
    if skipped:
        print("skipped:", "; ".join(f"{a} ({why})" for a, why in skipped))


if __name__ == "__main__":
    main()
