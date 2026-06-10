"""Pull HL commodity-perp candles (GOLD/SILVER/OIL) and show why they can't be
validated yet — concretely, with the data.

These HIP-3 builder-dex perps are real and tradeable, but launched only months
ago. This script pulls their full available 1h history from Hyperliquid, prints
how little there is, and runs buy&hold + golden_cross on it so you can SEE that
the window is a single regime (one number, no out-of-sample). It deliberately
does NOT produce a "verdict" — there isn't enough data for one.

Usage:
    .venv/bin/python scripts/commodity_probe.py
"""

import time

import numpy as np
import pandas as pd

from hl_trader.allocator.allocator import AllocatorParams, allocate
from hl_trader.backtest.engine import EngineParams, run_backtest
from hl_trader.backtest.metrics import compute_metrics
from hl_trader.config import load_settings
from hl_trader.exchange.hyperliquid_client import HyperliquidInfoClient
from hl_trader.logging_setup import configure_logging
from hl_trader.signals.classic import golden_cross

# Builder-dex commodity perps (coin string is "dex:NAME" for candleSnapshot).
COINS = ["xyz:GOLD", "xyz:SILVER", "xyz:BRENTOIL", "km:USOIL", "km:GOLD", "km:SILVER"]
DAY = 24


def fetch_candles(client, coin, start_ms, end_ms):
    rows = client.candles_all(coin, "1h", start_ms, end_ms)
    if not rows:
        return None
    idx = pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True)
    df = pd.DataFrame(
        {"open": [float(r["o"]) for r in rows], "high": [float(r["h"]) for r in rows],
         "low": [float(r["l"]) for r in rows], "close": [float(r["c"]) for r in rows],
         "volume": [float(r["v"]) for r in rows]},
        index=idx,
    )
    return df[~df.index.duplicated(keep="first")].sort_index()


def main():
    configure_logging("ERROR")
    client = HyperliquidInfoClient(load_settings(network="mainnet").api_url)
    now = int(time.time() * 1000)
    start = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1000)

    print("HL COMMODITY PERPS — available history (HIP-3 builder dexs)\n")
    print("*** WARNING: a few months of 1h data is ONE market regime. Any backtest")
    print("    number below is illustrative only — NOT evidence of edge. No OOS is")
    print("    even possible at this length. Do not size capital from this. ***\n")
    print(f"{'coin':<16} {'bars':>6} {'months':>7} {'first':>12} "
          f"{'bh_ret':>8} {'gc_ret':>8}")
    for coin in COINS:
        df = fetch_candles(client, coin, start, now)
        if df is None or len(df) < 200:
            print(f"{coin:<16} {'(no/low data)':>6}")
            continue
        months = len(df) / (30 * DAY)
        bh = df["close"].iloc[-1] / df["close"].iloc[0] - 1
        # golden_cross needs 200d of history; on <7mo the slow MA never warms, so
        # it is mostly flat — itself a demonstration that the window is too short.
        sized = allocate({"s": golden_cross(df)}, df["close"],
                         AllocatorParams(weights={"s": 1.0}))
        res = run_backtest(df, sized, EngineParams(max_drawdown_kill=0.25))
        gc = compute_metrics(res.equity, res.trades, res.account.fees_paid).total_return
        if np.isnan(gc):
            gc = 0.0
        print(f"{coin:<16} {len(df):>6} {months:>7.1f} {str(df.index[0].date()):>12} "
              f"{bh:>8.1%} {gc:>8.1%}")
    print("\nTakeaway: 50/200-DAY trend-following can't even form on <7 months of"
          " data\n(the 200-day MA never warms). These need 1-2+ years before any"
          " honest test.")


if __name__ == "__main__":
    main()
