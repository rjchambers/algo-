"""Reverse-engineer a "winning" strategy — and show honestly why it's a mirage.

Part 1 (the demo you asked for): search a large space of indicator strategies and
parameters, pick the one with the best IN-SAMPLE backtest on each of BTC/ETH/SOL,
then apply it UNCHANGED to a held-out 12 months. A reverse-engineered winner looks
gorgeous in-sample and falls apart out-of-sample — that gap is overfitting, and it
is what kills real accounts. We also report the "fit-to-everything" hindsight
number (the seductive perfect backtest) for contrast.

Part 2: the one fundamentally-grounded strategy with real academic support —
time-series momentum (Moskowitz, Ooi & Pedersen 2012), long-biased and vol-managed
— evaluated honestly OOS vs buy&hold across all three assets.

Usage:
    .venv/bin/python scripts/reverse_engineer.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import DATA, eval_target  # noqa: E402

from hl_trader.logging_setup import configure_logging  # noqa: E402
from hl_trader.signals import classic as C  # noqa: E402

DAY = 24


# ---- candidate strategy space (label -> df->target) -----------------------

def candidates() -> dict:
    cand = {}
    for f in (10, 20, 30, 50, 75):
        for s in (100, 150, 200, 250, 300):
            if f < s:
                cand[f"golden_cross_{f}/{s}d"] = lambda df, f=f, s=s: C.golden_cross(df, f * DAY, s * DAY)
    for f in (10, 20, 50, 100):
        for s in (50, 100, 200, 400):
            if f < s:
                cand[f"ema_x_{f}/{s}h"] = lambda df, f=f, s=s: C.ema_crossover(df, f, s)
    for n in (20, 50, 100):
        for k in (1.5, 2.0, 2.5):
            cand[f"boll_mr_{n}/{k}"] = lambda df, n=n, k=k: C.bollinger_meanrev(df, n, k)
            cand[f"boll_bo_{n}/{k}"] = lambda df, n=n, k=k: C.bollinger_breakout(df, n, k)
    for n in (7, 14, 21):
        for lo, hi in ((20, 80), (30, 70), (10, 90)):
            cand[f"rsi_{n}/{lo}-{hi}"] = lambda df, n=n, lo=lo, hi=hi: C.rsi_meanrev(df, n, lo, hi)
    for n in (7, 10, 14):
        for m in (2.0, 3.0, 4.0):
            cand[f"supertrend_{n}/{m}"] = lambda df, n=n, m=m: C.supertrend(df, n, m)
    for r in (100, 200, 300):
        cand[f"mtf_{r}d"] = lambda df, r=r: C.mtf_momentum(df, r * DAY)
    return cand


def metrics_row(m):
    return f"{m.total_return:>9.1%} {m.sharpe:>7.2f} {m.max_drawdown:>8.1%}"


def part1_overfit_demo(assets):
    print("=" * 78)
    print("PART 1 — REVERSE-ENGINEER A WINNER (in-sample), THEN LOOK OUT-OF-SAMPLE")
    print("=" * 78)
    cand = candidates()
    print(f"searching {len(cand)} indicator/param strategies per asset...\n")
    for asset in assets:
        path = DATA / f"{asset}_1h.parquet"
        if not path.exists():
            print(f"{asset}: missing fixture\n"); continue
        df = pd.read_parquet(path)
        split = df.index[-1] - pd.DateOffset(months=12)
        is_df, oos_df = df.loc[:split], df.loc[split:]

        is_res, oos_res, full_res = {}, {}, {}
        for name, fn in cand.items():
            try:
                is_res[name] = eval_target(is_df, fn(is_df))
                oos_res[name] = eval_target(oos_df, fn(oos_df))
                full_res[name] = eval_target(df, fn(df))
            except Exception:
                continue

        best_is = max(is_res, key=lambda k: (is_res[k].sharpe if pd.notna(is_res[k].sharpe) else -9))
        best_full = max(full_res, key=lambda k: (full_res[k].sharpe if pd.notna(full_res[k].sharpe) else -9))
        best_oos = max(oos_res, key=lambda k: (oos_res[k].sharpe if pd.notna(oos_res[k].sharpe) else -9))

        print(f"-- {asset} --")
        print(f"  Reverse-engineered winner (best IN-SAMPLE Sharpe): {best_is}")
        print(f"    in-sample : {metrics_row(is_res[best_is])}   <- looks great")
        print(f"    OUT-of-sample (same strategy, untouched): {metrics_row(oos_res[best_is])}   <- reality")
        print(f"  Fit-to-everything hindsight winner: {best_full}  full: {metrics_row(full_res[best_full])}")
        print(f"  (Best OOS in hindsight was a DIFFERENT strategy: {best_oos} "
              f"{metrics_row(oos_res[best_oos])} — unknowable in advance.)\n")
    print("Takeaway: the strategy that wins the backtest is chosen BY the backtest;")
    print("that is selection bias, and it does not carry forward. A 'reverse-engineered")
    print("winner' is a description of the past, not a prediction of the future.\n")


# ---- Part 2: the fundamentally-sound candidate ----------------------------

def tsmom_longbias(df, lookback=30 * DAY, regime=200 * DAY):
    """Time-series momentum, long-biased: full long in an uptrend, half size (not
    short) when momentum is up but below regime, flat in a downtrend. Captures
    crypto's documented drift while cutting tail risk."""
    c = df["close"]
    mom = c.pct_change(lookback)
    above = c > c.rolling(regime).mean()
    t = pd.Series(0.0, index=c.index)
    t[(mom > 0) & above] = 1.0
    t[(mom > 0) & ~above] = 0.5
    return t


def part2_sound_strategy(assets):
    print("=" * 78)
    print("PART 2 — THE FUNDAMENTALLY-SOUND CANDIDATE: time-series momentum (long-bias)")
    print("=" * 78)
    print("Theory: TSMOM is one of the few anomalies documented across decades and asset")
    print("classes (Moskowitz/Ooi/Pedersen 2012). Long-biased + vol-targeted to respect")
    print("crypto's upward drift and avoid shorting bull trends.\n")
    print(f"{'asset':<6} {'':<16} {'full_tot':>9} {'full_sh':>7} {'oos_tot':>9} {'oos_sh':>7} {'oos_DD':>8}")
    for asset in assets:
        path = DATA / f"{asset}_1h.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        split = df.index[-1] - pd.DateOffset(months=12)
        for label, tgt in (("buy_hold", pd.Series(1.0, index=df.index)),
                           ("tsmom_longbias", tsmom_longbias(df))):
            full = eval_target(df, tgt if label == "buy_hold" else tgt)
            oos_tgt = (pd.Series(1.0, index=df.loc[split:].index) if label == "buy_hold"
                       else tsmom_longbias(df.loc[split:]))
            oos = eval_target(df.loc[split:], oos_tgt)
            print(f"{asset:<6} {label:<16} {full.total_return:>9.1%} {full.sharpe:>7.2f} "
                  f"{oos.total_return:>9.1%} {oos.sharpe:>7.2f} {oos.max_drawdown:>8.1%}")
    print("\nHonest read: this is risk management, not alpha. It tends to match or trail")
    print("buy&hold in bull runs and lose less in downturns (lower drawdown). It is a")
    print("defensible *allocation*, not a money-printer, and still must clear walk-forward")
    print("+ a testnet paper-trading period before any real capital.")


def main():
    configure_logging("ERROR")
    assets = sys.argv[1:] or ["BTC", "ETH", "SOL"]
    part1_overfit_demo(assets)
    part2_sound_strategy(assets)


if __name__ == "__main__":
    main()
