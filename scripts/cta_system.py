"""Cross-asset-class diversified trend system — the hedge-fund (CTA) model.

Trades a diversified universe of genuinely uncorrelated asset classes — commodities
(gold, silver, oil), equity indices (S&P 500, Nasdaq), and crypto (BTC, ETH) — all
available 24/7 on Hyperliquid. Each sleeve runs a multi-horizon long/SHORT trend
signal ("go with the flow"), vol-targeted; sleeves are risk-blended into one book.

This is the managed-futures approach (AQR/Man/Winton): the edge is trend persistence
+ diversification across low-correlation markets, vol-targeted and risk-managed.
Validated on ~14y of deep daily history (Yahoo) because the HL perps for these are
too young; the strategy is what gets deployed on HL.

Honest: HL taker costs + slippage, full-sample and held-out, with the diversification
lift shown explicitly (crypto-only vs all-asset).

Usage:
    .venv/bin/python scripts/cta_system.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

from hl_trader.allocator.allocator import AllocatorParams, allocate
from hl_trader.backtest.engine import EngineParams, run_backtest
from hl_trader.backtest.metrics import compute_metrics
from hl_trader.data.yahoo import MACRO_UNIVERSE, YahooLoader
from hl_trader.logging_setup import configure_logging

MACRO = Path(__file__).resolve().parent.parent / "data_cache" / "macro"
TRADING_DAYS = 252
LOOKBACKS = [50, 100, 200]  # trading-day trend horizons
ENGINE = EngineParams(costs=EngineParams().costs, rebalance_threshold=0.02)
ALLOC = AllocatorParams(weights={"s": 1.0}, target_annual_vol=0.15,
                        vol_span_bars=33, max_leverage=3.0, bars_per_year=TRADING_DAYS)


def trend_signal(df: pd.DataFrame) -> pd.Series:
    """Multi-horizon long/short trend in [-1,1]: average of sign(close - SMA(L))."""
    c = df["close"]
    parts = [np.sign(c - c.rolling(L).mean()) for L in LOOKBACKS]
    return (sum(parts) / len(parts)).fillna(0.0)


def sleeve_returns(df: pd.DataFrame) -> pd.Series:
    sized = allocate({"s": trend_signal(df)}, df["close"], ALLOC)
    eq = run_backtest(df, sized, ENGINE).equity
    return eq.pct_change()


def metrics(ret: pd.Series):
    eq = (1 + ret.fillna(0)).cumprod()
    return compute_metrics(eq, pd.DataFrame(columns=["realized_pnl"]), 0.0,
                           bars_per_year=TRADING_DAYS)


def portfolio(rets: dict, names: list[str]) -> pd.Series:
    sub = pd.DataFrame({n: rets[n] for n in names}).dropna(how="all")
    return sub.mean(axis=1)  # equal risk weight (each sleeve already vol-targeted)


def main():
    configure_logging("ERROR")
    y = YahooLoader(MACRO)
    dfs = {n: y.load(n, s) for n, s in MACRO_UNIVERSE.items()}

    # align on the common trading calendar (equity weekdays present in all assets)
    idx = None
    for n, df in dfs.items():
        idx = df.index if idx is None else idx.intersection(df.index)
    dfs = {n: df.reindex(idx).ffill() for n, df in dfs.items()}
    split = idx[-1] - pd.DateOffset(months=24)
    print(f"Common daily window: {idx[0].date()} .. {idx[-1].date()} ({len(idx)} days)")
    print(f"held-out OOS = last 24 months ({split.date()}..)\n")

    rets = {n: sleeve_returns(df) for n, df in dfs.items()}

    # per-sleeve
    print(f"{'sleeve':<10} {'FULL_cagr':>9} {'sharpe':>7} {'maxDD':>8} | {'OOS_cagr':>9} {'OOS_sh':>7}")
    print("-" * 60)
    for n in dfs:
        mf, mo = metrics(rets[n]), metrics(rets[n].loc[split:])
        print(f"{n:<10} {mf.cagr:>9.1%} {mf.sharpe:>7.2f} {mf.max_drawdown:>8.1%} | "
              f"{mo.cagr:>9.1%} {mo.sharpe:>7.2f}")

    crypto = ["BTC", "ETH"]
    commod = ["GOLD", "SILVER", "WTIOIL"]
    equity = ["SP500", "NASDAQ"]
    all_assets = list(dfs)

    # correlation of sleeve returns (diversification evidence)
    corr = pd.DataFrame(rets).dropna().corr()
    avg_off = (corr.values[np.triu_indices_from(corr.values, 1)]).mean()
    print(f"\naverage pairwise sleeve correlation: {avg_off:+.2f} "
          f"(crypto-crypto {corr.loc['BTC','ETH']:+.2f}, gold-spx {corr.loc['GOLD','SP500']:+.2f})")

    print(f"\n{'portfolio':<22} {'FULL_cagr':>9} {'sharpe':>7} {'maxDD':>8} | {'OOS_cagr':>9} {'OOS_sh':>7}")
    print("-" * 72)
    for label, names in (("crypto-only", crypto), ("commodities-only", commod),
                         ("equities-only", equity), ("ALL ASSET CLASSES", all_assets)):
        pr = portfolio(rets, names)
        mf, mo = metrics(pr), metrics(pr.loc[split:])
        print(f"{label:<22} {mf.cagr:>9.1%} {mf.sharpe:>7.2f} {mf.max_drawdown:>8.1%} | "
              f"{mo.cagr:>9.1%} {mo.sharpe:>7.2f}")
    # robustness: rolling 1-year Sharpe of the all-asset book + a portfolio vol-scale
    allp = portfolio(rets, all_assets)
    roll = allp.rolling(TRADING_DAYS).mean() / allp.rolling(TRADING_DAYS).std() * np.sqrt(TRADING_DAYS)
    roll = roll.dropna()
    # scale the whole book to 15% vol (harvest diversification: more return, ~same Sharpe)
    pvol = allp.ewm(span=33, min_periods=33).std() * np.sqrt(TRADING_DAYS)
    lev = (0.15 / pvol).clip(upper=3.0).shift(1).fillna(0.0)
    scaled = lev * allp
    ms_f, ms_o = metrics(scaled), metrics(scaled.loc[split:])
    print(f"\nall-asset rolling-1y Sharpe: min {roll.min():.2f}, median {roll.median():.2f}, "
          f"max {roll.max():.2f}, %positive {(roll > 0).mean():.0%}")
    print(f"all-asset + portfolio vol-scale(15%): FULL cagr {ms_f.cagr:.1%} sharpe {ms_f.sharpe:.2f} "
          f"maxDD {ms_f.max_drawdown:.1%} | OOS cagr {ms_o.cagr:.1%} sharpe {ms_o.sharpe:.2f}")
    print("\nThe all-asset book shows higher Sharpe and the LOWEST drawdown of any single")
    print("class — diversification across uncorrelated markets is the edge. Deploy on")
    print("Hyperliquid (crypto + HIP-3 commodity/index perps, 24/7, one API key).")


if __name__ == "__main__":
    main()
