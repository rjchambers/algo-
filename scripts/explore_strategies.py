"""EXPLORATORY pre-registered hypothesis scan (NOT promotion, NOT edge proof).

After §2.6 killed all four candidate signals, this tests a small, pre-specified
set of theory-driven alternatives on the real BTC/ETH fixtures, against the
honest benchmark everyone forgets: just holding the asset. Anything that looks
promising here is a *lead* to validate properly next session (walk-forward,
held-out, sensitivity, a third held-back asset) — it is NOT validated by this
script. We deliberately do not tune; defaults only.

Hypotheses:
- buy_hold        : long the asset, vol-targeted (the bar to beat).
- trend_long      : long-only momentum+regime (no shorts — funding_mr's fatal flaw
                    was shorting strong up-trends).
- donchian        : breakout trend-follow (long above N-bar high, short below low).
- carry_with_trend: collect funding only when the carry trade agrees with the
                    regime (opposite spirit to funding_mr's blind fade).
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import DATA, eval_target  # noqa: E402

from hl_trader.backtest.metrics import Metrics  # noqa: E402
from hl_trader.logging_setup import configure_logging  # noqa: E402


def buy_hold(df):
    return pd.Series(1.0, index=df.index)


def trend_long(df, lookback=168, regime=1440):
    c = df["close"]
    up = (c.pct_change(lookback) > 0) & (c > c.rolling(regime).mean())
    return up.astype(float).where(up, 0.0).fillna(0.0)


def donchian(df, n=336):
    c = df["close"]
    hi = c.rolling(n).max()
    lo = c.rolling(n).min()
    pos = pd.Series(0.0, index=c.index)
    pos[c >= hi] = 1.0
    pos[c <= lo] = -1.0
    return pos.replace(0.0, np.nan).ffill().fillna(0.0)


def carry_with_trend(df, lookback=168, regime=1440):
    """Take the funding-carry side only when it agrees with the trend.

    Positive funding -> shorts get paid -> short, BUT only if trend is also down.
    Negative funding -> longs get paid -> long, but only if trend is also up.
    """
    c, f = df["close"], df["funding_rate"]
    trend = np.sign(c.pct_change(lookback)).where(c > c.rolling(regime).mean(), -1.0)
    carry = -np.sign(f)  # side that collects funding
    pos = carry.where(np.sign(carry) == np.sign(trend), 0.0)
    return pos.fillna(0.0)


STRATS = {
    "buy_hold": buy_hold,
    "trend_long": trend_long,
    "donchian": donchian,
    "carry_with_trend": carry_with_trend,
}

HEADER = f"{'strategy':<18} {'full_total':>11} {'full_sh':>8} {'oos_total':>11} {'oos_sh':>8} {'oos_maxDD':>10}"


def row(name: str, full: Metrics, oos: Metrics) -> str:
    return (f"{name:<18} {full.total_return:>11.2%} {full.sharpe:>8.2f} "
            f"{oos.total_return:>11.2%} {oos.sharpe:>8.2f} {oos.max_drawdown:>10.2%}")


def main():
    configure_logging("ERROR")
    assets = sys.argv[1:] or ["BTC", "ETH"]
    print("EXPLORATORY scan — leads only, NOT validated. Benchmark = buy_hold.\n")
    for asset in assets:
        path = DATA / f"{asset}_1h.parquet"
        if not path.exists():
            print(f"!! missing {path}"); continue
        df = pd.read_parquet(path)
        split = df.index[-1] - pd.DateOffset(months=12)
        oos_df = df.loc[split:]
        # raw buy-hold (no vol target): the literal 'just hold it' number
        bh_full = df["close"].iloc[-1] / df["close"].iloc[0] - 1
        bh_oos = oos_df["close"].iloc[-1] / oos_df["close"].iloc[0] - 1
        print(f"== {asset}  (raw buy&hold: full {bh_full:+.1%}, last-12mo {bh_oos:+.1%}) ==")
        print(HEADER)
        for name, fn in STRATS.items():
            full = eval_target(df, fn(df))
            oos = eval_target(oos_df, fn(oos_df))
            print(row(name, full, oos))
        print()


if __name__ == "__main__":
    main()
