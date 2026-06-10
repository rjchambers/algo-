"""Full §2.6-style validation of the trend-following lead (golden/death cross).

The battery flagged trend-following as the one classic with cross-asset OOS value.
This subjects it to the same discipline as the Phase 2 signals: held-out 12mo,
walk-forward (grid-search train -> untouched test), and +/-50% sensitivity on the
MA lengths. Promote bar identical to §2.6.

Usage:
    .venv/bin/python scripts/validate_trend.py [BTC ETH SOL]
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import DATA, ENGINE, PROMOTE, eval_target  # noqa: E402

from hl_trader.allocator.allocator import AllocatorParams, allocate  # noqa: E402
from hl_trader.backtest.engine import run_backtest  # noqa: E402
from hl_trader.backtest.metrics import compute_metrics  # noqa: E402
from hl_trader.logging_setup import configure_logging  # noqa: E402

DAY = 24


def cross_target(df: pd.DataFrame, fast: int, slow: int) -> pd.Series:
    c = df["close"]
    return np.sign(c.rolling(fast).mean() - c.rolling(slow).mean()).fillna(0.0)


GRID = [(f * DAY, s * DAY) for f in (25, 50, 75) for s in (100, 200, 300) if f < s]


def walk_forward(df, train_months=12, test_months=3):
    start, end = df.index[0], df.index[-1]
    cursor = start + pd.DateOffset(months=train_months)
    oos = []
    while cursor < end:
        train = df.loc[start:cursor]
        test_end = min(cursor + pd.DateOffset(months=test_months), end)
        if len(df.loc[cursor:test_end]) < 24:
            break
        best, best_sh = GRID[0], -np.inf
        for f, s in GRID:
            m = eval_target(train, cross_target(train, f, s))
            if pd.notna(m.sharpe) and m.sharpe > best_sh:
                best, best_sh = (f, s), m.sharpe
        full = cross_target(df.loc[start:test_end], *best)
        sized = allocate({"s": full}, df.loc[start:test_end, "close"],
                         AllocatorParams(weights={"s": 1.0}))
        res = run_backtest(df.loc[start:test_end], sized, ENGINE)
        oos.append(res.equity.loc[cursor:test_end].pct_change().dropna())
        cursor = test_end
    if not oos:
        return None
    rets = pd.concat(oos)
    eq = (1 + rets).cumprod() * ENGINE.initial_cash
    return compute_metrics(eq, pd.DataFrame(columns=["realized_pnl"]), 0.0)


def sensitivity(df):
    sh = []
    for f in (25, 50, 75):
        for s in (100, 200, 300):
            if f >= s:
                continue
            m = eval_target(df, cross_target(df, f * DAY, s * DAY))
            if pd.notna(m.sharpe):
                sh.append(m.sharpe)
    s = pd.Series(sh)
    return {"n": len(s), "min": s.min(), "median": s.median(), "max": s.max(),
            "frac_positive": (s > 0).mean()}


def main():
    configure_logging("ERROR")
    assets = sys.argv[1:] or ["BTC", "ETH"]
    print("TREND-FOLLOWING (50/200 golden/death cross) — full validation\n")
    print(f"{'asset':<6} {'full_sh':>8} {'oos_tot':>9} {'oos_sh':>7} {'wf_tot':>9} "
          f"{'wf_sh':>7} {'sens_med':>9} {'sens+':>6} {'verdict':>9}")
    for asset in assets:
        path = DATA / f"{asset}_1h.parquet"
        if not path.exists():
            print(f"{asset:<6} (missing fixture)"); continue
        df = pd.read_parquet(path)
        split = df.index[-1] - pd.DateOffset(months=12)
        full = eval_target(df, cross_target(df, 50 * DAY, 200 * DAY))
        oos = eval_target(df.loc[split:], cross_target(df.loc[split:], 50 * DAY, 200 * DAY))
        wf = walk_forward(df)
        sens = sensitivity(df.loc[split:])
        ok = (pd.notna(oos.sharpe) and oos.sharpe > PROMOTE["oos_sharpe"]
              and oos.total_return > 0 and wf is not None and wf.sharpe > 0
              and sens["median"] > 0 and sens["frac_positive"] >= PROMOTE["sens_frac_positive"])
        verdict = "PROMOTE" if ok else "KILL"
        wf_tot = wf.total_return if wf else float("nan")
        wf_sh = wf.sharpe if wf else float("nan")
        print(f"{asset:<6} {full.sharpe:>8.2f} {oos.total_return:>9.1%} {oos.sharpe:>7.2f} "
              f"{wf_tot:>9.1%} {wf_sh:>7.2f} {sens['median']:>9.2f} "
              f"{sens['frac_positive']:>6.0%} {verdict:>9}")
    print("\nPromote bar: OOS Sharpe>0.5 AND OOS total>0 AND WF Sharpe>0 AND "
          "sens median>0 AND >=60% of sensitivity grid positive.")


if __name__ == "__main__":
    main()
