"""Multi-timeframe confluence system with leverage + stop-loss/take-profit.

Builds trend signals on 1m / 5m / 15m / 1h / 4h from one 1-minute feed, combines
them into a weighted confluence score (higher timeframes weighted more), and
trades the 15m grid: go long/short with leverage when confluence aligns, flip
when it reverses, with SL/TP and the drawdown kill switch.

LOOK-AHEAD SAFETY: every timeframe is resampled with label='right'/closed='right'
so each bar is stamped at its CLOSE time, then forward-filled onto the 15m close
grid — a higher-TF value only becomes visible after that bar has closed. The
engine adds the usual t+1 execution delay on top.

Honest by construction: HL taker costs + slippage on every fill, and results are
shown full-sample AND on a held-out 12 months, against buy&hold. Higher leverage
and faster trading amplify costs — that is the point of measuring it.

Usage:
    .venv/bin/python scripts/mtf_system.py [--asset BTC]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from hl_trader.backtest.engine import EngineParams, run_backtest
from hl_trader.backtest.metrics import compute_metrics
from hl_trader.logging_setup import configure_logging
from hl_trader.signals.classic import ema

ROOT = Path(__file__).resolve().parent.parent
ONE_MIN = ROOT / "data_cache" / "real_1m"

TFS = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
TF_WEIGHTS = {"1m": 1.0, "5m": 1.0, "15m": 2.0, "1h": 3.0, "4h": 4.0}
BASE_TF = "15m"


def resample(df1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """OHLCV resample, bars stamped at CLOSE time (label/closed = right)."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df1m.resample(rule, label="right", closed="right").agg(agg).dropna()
    return out


def tf_trend_score(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """+1 uptrend / -1 downtrend / 0 mixed, from an EMA stack on that timeframe."""
    c = df["close"]
    ef, es = ema(c, fast), ema(c, slow)
    up = (ef > es) & (c > es)
    down = (ef < es) & (c < es)
    s = pd.Series(0.0, index=c.index)
    s[up] = 1.0
    s[down] = -1.0
    return s


def confluence(df1m: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Return the 15m base OHLCV and the weighted confluence score on its grid."""
    base = resample(df1m, TFS[BASE_TF])
    total_w = sum(TF_WEIGHTS.values())
    score = pd.Series(0.0, index=base.index)
    for tf, rule in TFS.items():
        tf_df = resample(df1m, rule)
        tf_score = tf_trend_score(tf_df)
        # forward-fill each TF's last CLOSED-bar score onto the 15m close grid
        aligned = tf_score.reindex(base.index, method="ffill").fillna(0.0)
        score = score + TF_WEIGHTS[tf] * aligned
    return base, (score / total_w)


def build_target(score: pd.Series, leverage: float, thr: float) -> pd.Series:
    """Leveraged long/short/flat: full-size flip when confluence aligns past thr."""
    t = pd.Series(0.0, index=score.index)
    t[score >= thr] = leverage
    t[score <= -thr] = -leverage
    return t


def run(base: pd.DataFrame, target: pd.Series, sl: float | None, tp: float | None) -> dict:
    params = EngineParams(
        rebalance_threshold=0.0, stop_frac=sl, take_profit_frac=tp, max_drawdown_kill=0.50
    )
    res = run_backtest(base, target, params)
    # 15m bars: ~35,040 per year
    bars_per_year = 365 * 24 * 4
    m = compute_metrics(res.equity, res.trades, res.account.fees_paid, bars_per_year=bars_per_year)
    return {"total": m.total_return, "sharpe": m.sharpe, "maxdd": m.max_drawdown,
            "trades": m.n_closing_trades, "fees": m.fees_paid, "killed": res.killed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="BTC")
    args = ap.parse_args()
    configure_logging("ERROR")

    path = ONE_MIN / f"{args.asset}USDT_1m.parquet"
    if not path.exists():
        print(f"!! missing {path} — fetch 1m data first"); return
    df1m = pd.read_parquet(path)
    print(f"{args.asset}: {len(df1m):,} 1m bars {df1m.index[0]} .. {df1m.index[-1]}\n")

    base, score = confluence(df1m)
    split = base.index[-1] - pd.DateOffset(months=12)
    bh_full = base["close"].iloc[-1] / base["close"].iloc[0] - 1
    bh_oos = base.loc[split:]["close"].iloc[-1] / base.loc[split:]["close"].iloc[0] - 1
    print(f"15m base bars: {len(base):,}   buy&hold: full {bh_full:+.1%}, last-12mo {bh_oos:+.1%}")
    print(f"confluence in [-1,1]: mean {score.mean():+.3f}, |score|>=0.5 {(score.abs()>=0.5).mean():.0%} of bars\n")

    print(f"{'config':<34} {'full_tot':>10} {'full_sh':>8} {'oos_tot':>10} {'oos_sh':>7} "
          f"{'oos_DD':>8} {'trades':>8} {'fees':>12}")
    configs = [
        ("lev1 thr0.5 no SL/TP", 1.0, 0.5, None, None),
        ("lev2 thr0.5 no SL/TP", 2.0, 0.5, None, None),
        ("lev3 thr0.5 no SL/TP", 3.0, 0.5, None, None),
        ("lev3 thr0.5 SL2% TP4%", 3.0, 0.5, 0.02, 0.04),
        ("lev3 thr0.7 SL2% TP4%", 3.0, 0.7, 0.02, 0.04),
        ("lev2 thr0.5 SL3% TP6%", 2.0, 0.5, 0.03, 0.06),
        ("lev5 thr0.7 SL1.5% TP3%", 5.0, 0.7, 0.015, 0.03),
    ]
    for name, lev, thr, sl, tp in configs:
        tgt = build_target(score, lev, thr)
        full = run(base, tgt, sl, tp)
        oos_base = base.loc[split:]
        oos = run(oos_base, build_target(score.loc[split:], lev, thr), sl, tp)
        print(f"{name:<34} {full['total']:>10.1%} {full['sharpe']:>8.2f} "
              f"{oos['total']:>10.1%} {oos['sharpe']:>7.2f} {oos['maxdd']:>8.1%} "
              f"{oos['trades']:>8d} {oos['fees']:>12,.0f}")
    print("\nNote: intraday funding omitted (small per-15m vs taker costs). Costs = HL")
    print("taker 4.5bps + 2bps slippage per fill. Leverage amplifies both edge and bleed.")


if __name__ == "__main__":
    main()
