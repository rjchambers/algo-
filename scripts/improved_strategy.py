"""Improving the TSMOM basket's Sharpe with principled (non-overfitting) changes.

Each step is a robustness/diversification improvement, not a fit to history:
  v1  baseline   : single 30d-lookback long-bias TSMOM, equal-weight basket.
  v2  ensemble   : average MANY lookback speeds (7/14/30/60/90d) -> less timing
                   luck, smoother exposure, lower whipsaw turnover.
  v3  +portfolio : v2 then re-lever the whole basket to a target vol, harvesting
                   the diversification benefit (more return per unit risk).
  (+assets)      : add BNB when its data is ready -> more diversification.

We report full-sample, held-out 12mo, AND rolling 6-month Sharpes so you can see
the improvement is consistent across time, not a single lucky window.

Usage:
    .venv/bin/python scripts/improved_strategy.py [BTC ETH SOL BNB]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import DATA, ENGINE  # noqa: E402

from hl_trader.allocator.allocator import AllocatorParams, allocate, realized_vol  # noqa: E402
from hl_trader.backtest.engine import run_backtest  # noqa: E402
from hl_trader.backtest.metrics import compute_metrics  # noqa: E402
from hl_trader.logging_setup import configure_logging  # noqa: E402

DAY = 24
HOURS_YR = 24 * 365
LOOKBACKS = [7 * DAY, 14 * DAY, 30 * DAY, 60 * DAY, 90 * DAY]


def longbias_single(df, lookback=30 * DAY, regime=200 * DAY):
    c = df["close"]
    mom = c.pct_change(lookback)
    above = c > c.rolling(regime).mean()
    t = pd.Series(0.0, index=c.index)
    t[(mom > 0) & above] = 1.0
    t[(mom > 0) & ~above] = 0.5
    return t


def longbias_ensemble(df, regime=200 * DAY):
    """Average the long-bias signal across many lookback horizons -> [0,1]."""
    c = df["close"]
    above = c > c.rolling(regime).mean()
    parts = []
    for lb in LOOKBACKS:
        mom = c.pct_change(lb)
        t = pd.Series(0.0, index=c.index)
        t[(mom > 0) & above] = 1.0
        t[(mom > 0) & ~above] = 0.5
        parts.append(t)
    return sum(parts) / len(parts)


def sleeve_equity(df, target):
    sized = allocate({"s": target}, df["close"], AllocatorParams(weights={"s": 1.0}))
    return run_backtest(df, sized, ENGINE).equity


def basket_equity(equities: dict, idx):
    norm = [equities[a].reindex(idx).ffill() / equities[a].reindex(idx).ffill().iloc[0]
            for a in equities]
    return sum(norm) / len(norm) * ENGINE.initial_cash


def vol_scaled(eq: pd.Series, target_vol=0.15, span=30 * DAY, max_lev=2.0):
    """Re-lever a return stream to a target annual vol (portfolio-level)."""
    ret = eq.pct_change().fillna(0.0)
    vol = ret.ewm(span=span, min_periods=span).std() * np.sqrt(HOURS_YR)
    lev = (target_vol / vol).clip(upper=max_lev).shift(1).fillna(0.0)  # shift: no look-ahead
    scaled = (1 + lev * ret).cumprod() * ENGINE.initial_cash
    return scaled


def m(eq):
    return compute_metrics(eq, pd.DataFrame(columns=["realized_pnl"]), 0.0, bars_per_year=HOURS_YR)


def rolling_sharpe_6mo(eq):
    ret = eq.pct_change().dropna()
    win = 182 * DAY
    rs = ret.rolling(win).mean() / ret.rolling(win).std() * np.sqrt(HOURS_YR)
    rs = rs.dropna()
    return rs


def line(label, eq, split):
    mm, mo = m(eq), m(eq.loc[split:])
    rs = rolling_sharpe_6mo(eq)
    pos = (rs > 0).mean() if len(rs) else float("nan")
    print(f"{label:<26} {mm.total_return:>8.1%} {mm.sharpe:>7.2f} {mm.max_drawdown:>8.1%} | "
          f"{mo.total_return:>8.1%} {mo.sharpe:>7.2f} | {rs.min():>6.2f} {rs.median():>6.2f} "
          f"{rs.max():>6.2f} {pos:>6.0%}")


def main():
    configure_logging("ERROR")
    assets = [a for a in (sys.argv[1:] or ["BTC", "ETH", "SOL"])
              if (DATA / f"{a}_1h.parquet").exists()]
    dfs = {a: pd.read_parquet(DATA / f"{a}_1h.parquet") for a in assets}
    split = list(dfs.values())[0].index[-1] - pd.DateOffset(months=12)
    idx = None
    for a in assets:
        idx = dfs[a].index if idx is None else idx.intersection(dfs[a].index)

    single = {a: sleeve_equity(dfs[a], longbias_single(dfs[a])) for a in assets}
    ens = {a: sleeve_equity(dfs[a], longbias_ensemble(dfs[a])) for a in assets}
    bh = {a: sleeve_equity(dfs[a], pd.Series(1.0, index=dfs[a].index)) for a in assets}

    v1 = basket_equity(single, idx)
    v2 = basket_equity(ens, idx)
    v3 = vol_scaled(v2, target_vol=0.15)
    bench = basket_equity(bh, idx)

    print(f"Universe: {', '.join(assets)}   window {idx[0].date()}..{idx[-1].date()}\n")
    print(f"{'strategy':<26} {'FULL_tot':>8} {'sharpe':>7} {'maxDD':>8} | "
          f"{'OOS_tot':>8} {'OOS_sh':>7} | {'roll6mo Sharpe: min':>6} {'med':>6} {'max':>6} {'>0':>6}")
    print("-" * 110)
    line("buy&hold basket", bench, split)
    line("v1 single-horizon", v1, split)
    line("v2 ensemble", v2, split)
    line("v3 ensemble+volscaled", v3, split)
    print("\nFULL=3y, OOS=held-out 12mo. roll6mo = distribution of trailing-6-month")
    print("annualised Sharpe (consistency check). Each step is a robustness/diversification")
    print("improvement, not a parameter fit. Add assets (BNB+) to push Sharpe further.")


if __name__ == "__main__":
    main()
