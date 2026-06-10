"""Stacking uncorrelated return streams to lift portfolio Sharpe.

Demonstrates the core design principle: a market-NEUTRAL cross-sectional momentum
stream (long the strongest asset, short the weakest) is largely uncorrelated to the
directional trend stream, so risk-blending the two should raise Sharpe even if the
new stream is individually modest.

Streams:
- TREND  : long-bias TSMOM basket (the proven sleeve).
- XSMOM  : cross-sectional momentum — each asset's exposure = its demeaned lookback
           return across the universe, so the book is ~market-neutral.

Blend: inverse-volatility (risk-parity) weights on the two streams. Reports each
stream's Sharpe, their correlation, and the blend — honestly, full + held-out.

Usage:
    .venv/bin/python scripts/multi_strategy.py [BTC ETH SOL BNB]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import DATA, ENGINE  # noqa: E402

from hl_trader.allocator.allocator import AllocatorParams, allocate  # noqa: E402
from hl_trader.backtest.engine import run_backtest  # noqa: E402
from hl_trader.backtest.metrics import compute_metrics  # noqa: E402
from hl_trader.logging_setup import configure_logging  # noqa: E402

DAY = 24
HOURS_YR = 24 * 365


def longbias(df, lookback=30 * DAY, regime=200 * DAY):
    c = df["close"]
    mom = c.pct_change(lookback)
    above = c > c.rolling(regime).mean()
    t = pd.Series(0.0, index=c.index)
    t[(mom > 0) & above] = 1.0
    t[(mom > 0) & ~above] = 0.5
    return t


def sleeve_eq(df, target):
    sized = allocate({"s": target}, df["close"], AllocatorParams(weights={"s": 1.0}))
    return run_backtest(df, sized, ENGINE).equity


def metrics(eq):
    return compute_metrics(eq, pd.DataFrame(columns=["realized_pnl"]), 0.0, bars_per_year=HOURS_YR)


def norm_eq(eq, idx):
    e = eq.reindex(idx).ffill()
    return e / e.iloc[0]


def xs_targets(dfs, idx, lookback=14 * DAY):
    """Cross-sectional momentum: demeaned lookback return per asset (market-neutral)."""
    rets = pd.DataFrame({a: dfs[a]["close"].reindex(idx).ffill().pct_change(lookback)
                         for a in dfs})
    demeaned = rets.sub(rets.mean(axis=1), axis=0)
    # scale so the cross-section has unit gross exposure each bar
    gross = demeaned.abs().sum(axis=1).replace(0, np.nan)
    scaled = demeaned.div(gross, axis=0).fillna(0.0).clip(-1, 1)
    return scaled


def main():
    configure_logging("ERROR")
    assets = [a for a in (sys.argv[1:] or ["BTC", "ETH", "SOL"])
              if (DATA / f"{a}_1h.parquet").exists()]
    dfs = {a: pd.read_parquet(DATA / f"{a}_1h.parquet") for a in assets}
    idx = None
    for a in assets:
        idx = dfs[a].index if idx is None else idx.intersection(dfs[a].index)
    split = idx[-1] - pd.DateOffset(months=12)

    # TREND stream
    trend_norm = [norm_eq(sleeve_eq(dfs[a], longbias(dfs[a])), idx) for a in assets]
    trend = sum(trend_norm) / len(trend_norm) * ENGINE.initial_cash

    # XSMOM stream (market-neutral): each asset's demeaned-momentum exposure
    xs = xs_targets(dfs, idx)
    xs_norm = []
    for a in assets:
        df_a = dfs[a].reindex(idx).ffill().dropna()
        tgt = xs[a].reindex(df_a.index).fillna(0.0)
        xs_norm.append(norm_eq(run_backtest(df_a, tgt, ENGINE).equity, idx))
    xsmom = sum(xs_norm) / len(xs_norm) * ENGINE.initial_cash

    # inverse-vol blend of the two streams
    def blend(a_eq, b_eq):
        ra, rb = a_eq.pct_change().fillna(0), b_eq.pct_change().fillna(0)
        va, vb = ra.std(), rb.std()
        wa, wb = (1 / va) / (1 / va + 1 / vb), (1 / vb) / (1 / va + 1 / vb)
        return (1 + wa * ra + wb * rb).cumprod() * ENGINE.initial_cash, (wa, wb)

    combo, (wa, wb) = blend(trend, xsmom)
    corr = trend.pct_change().corr(xsmom.pct_change())

    print(f"Universe: {', '.join(assets)}   window {idx[0].date()}..{idx[-1].date()}")
    print(f"stream correlation (trend vs xs-mom): {corr:+.2f}   blend weights "
          f"trend={wa:.0%} xsmom={wb:.0%}\n")
    print(f"{'stream':<22} {'FULL_tot':>9} {'sharpe':>7} {'maxDD':>8} | {'OOS_tot':>9} {'OOS_sh':>7}")
    print("-" * 72)
    for label, eq in (("TREND (long-bias)", trend), ("XSMOM (mkt-neutral)", xsmom),
                      ("BLEND (risk-parity)", combo)):
        mf, mo = metrics(eq), metrics(eq.loc[split:])
        print(f"{label:<22} {mf.total_return:>9.1%} {mf.sharpe:>7.2f} {mf.max_drawdown:>8.1%} | "
              f"{mo.total_return:>9.1%} {mo.sharpe:>7.2f}")
    print("\nIf the blend's Sharpe exceeds the trend stream's and correlation is low, the")
    print("stacking principle is working. More uncorrelated streams (carry, defensive)")
    print("and more assets push it further. Honest target ~Sharpe 1; this is the path.")


if __name__ == "__main__":
    main()
