"""Broad-universe multi-stream system: does breadth lift the Sharpe?

Runs the trend (long-bias TSMOM) and market-neutral cross-sectional-momentum
streams across the full liquid universe fetched by fetch_universe.py, then blends
them by inverse vol. Compares the broad result to a 3-asset baseline so you can see
the effect of breadth directly. Honest: full-sample + held-out 12mo, real costs.

Usage:
    .venv/bin/python scripts/broad_system.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import ENGINE  # noqa: E402

from hl_trader.allocator.allocator import AllocatorParams, allocate  # noqa: E402
from hl_trader.backtest.engine import run_backtest  # noqa: E402
from hl_trader.backtest.metrics import compute_metrics  # noqa: E402
from hl_trader.logging_setup import configure_logging  # noqa: E402

UNIV = ROOT / "data_cache" / "real_universe"
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


def to_returns(eq, idx):
    """Normalised return stream on the union index; flat before an asset lists."""
    e = eq.reindex(idx)
    e = e.ffill()
    e = e / e.dropna().iloc[0]
    return e.pct_change().fillna(0.0)


def run_universe(dfs):
    idx = None
    for a in dfs:
        idx = dfs[a].index if idx is None else idx.union(dfs[a].index)
    idx = idx.sort_values()
    split = idx[-1] - pd.DateOffset(months=12)

    # TREND: equal-weight average of per-sleeve return streams
    trend_rets = [to_returns(sleeve_eq(dfs[a], longbias(dfs[a])), idx) for a in dfs]
    trend_ret = sum(trend_rets) / len(trend_rets)
    trend = (1 + trend_ret).cumprod() * ENGINE.initial_cash

    # XSMOM: demeaned 14d momentum across available assets each bar (market-neutral)
    closes = pd.DataFrame({a: dfs[a]["close"].reindex(idx).ffill() for a in dfs})
    mom = closes.pct_change(14 * DAY)
    demeaned = mom.sub(mom.mean(axis=1), axis=0)
    gross = demeaned.abs().sum(axis=1).replace(0, np.nan)
    weights = demeaned.div(gross, axis=0).clip(-1, 1)
    xs_rets = []
    for a in dfs:
        df_a = dfs[a].reindex(idx).ffill().dropna()
        tgt = weights[a].reindex(df_a.index).fillna(0.0)
        xs_rets.append(to_returns(run_backtest(df_a, tgt, ENGINE).equity, idx))
    xs_ret = sum(xs_rets) / len(xs_rets)
    xsmom = (1 + xs_ret).cumprod() * ENGINE.initial_cash

    # inverse-vol blend
    va, vb = trend_ret.std(), xs_ret.std()
    wa, wb = (1 / va) / (1 / va + 1 / vb), (1 / vb) / (1 / va + 1 / vb)
    blend = (1 + wa * trend_ret + wb * xs_ret).cumprod() * ENGINE.initial_cash
    corr = trend_ret.corr(xs_ret)
    return {"trend": trend, "xsmom": xsmom, "blend": blend, "split": split,
            "corr": corr, "w": (wa, wb), "idx": idx}


def main():
    configure_logging("ERROR")
    if not UNIV.exists() or not list(UNIV.glob("*.parquet")):
        print("no universe data — run scripts/fetch_universe.py first"); return
    dfs = {p.stem.replace("_1h", ""): pd.read_parquet(p) for p in sorted(UNIV.glob("*.parquet"))}
    print(f"Universe ({len(dfs)} assets): {', '.join(dfs)}")
    r = run_universe(dfs)
    print(f"window {r['idx'][0].date()}..{r['idx'][-1].date()}  "
          f"corr(trend,xsmom)={r['corr']:+.2f}  blend w: trend={r['w'][0]:.0%} xsmom={r['w'][1]:.0%}\n")
    print(f"{'stream':<22} {'FULL_tot':>9} {'sharpe':>7} {'maxDD':>8} | {'OOS_tot':>9} {'OOS_sh':>7}")
    print("-" * 72)
    for label, key in (("TREND (broad)", "trend"), ("XSMOM (broad)", "xsmom"),
                       ("BLEND (broad)", "blend")):
        eq = r[key]
        mf, mo = metrics(eq), metrics(eq.loc[r["split"]:])
        print(f"{label:<22} {mf.total_return:>9.1%} {mf.sharpe:>7.2f} {mf.max_drawdown:>8.1%} | "
              f"{mo.total_return:>9.1%} {mo.sharpe:>7.2f}")
    print("\nCompare to the 3-asset run (multi_strategy.py): more breadth should make the")
    print("cross-sectional stream stronger and the trend basket steadier. This is the")
    print("honest lever for higher Sharpe — more uncorrelated streams, more markets.")


if __name__ == "__main__":
    main()
