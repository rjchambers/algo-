"""§2.6 real-data validation protocol for the Phase 2 signals.

Runs, on REAL data (Binance Vision prices/funding/OI + live Hyperliquid funding):

1. Baseline: tsmom, funding_mr, variants, and the combined book at default
   params, full-sample and on an in-sample / held-out split.
2. Walk-forward: anchored grid search on each train window, applied untouched
   to the next test window; OOS returns concatenated.
3. Sensitivity: +/-50% on each signal's key params; the edge must survive the
   whole grid, not sit on a single peak.
4. Variants: A = open-interest confirmation; B = (HL - Binance) funding spread
   as the percentile input. Compared to baseline on identical splits.
5. Decision: promote/kill each strategy against fixed thresholds.

Every strategy is evaluated *as it would be traded*: through the single
deterministic allocator (vol-targeted) with the engine's drawdown kill switch.

Usage:
    .venv/bin/python scripts/validate_phase2.py [--holdout-months 12] [--out output/phase2_validation]
"""

import argparse
import itertools
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

from hl_trader.allocator.allocator import AllocatorParams, allocate
from hl_trader.backtest.engine import EngineParams, run_backtest
from hl_trader.backtest.metrics import Metrics, compute_metrics
from hl_trader.logging_setup import configure_logging
from hl_trader.signals.funding_mr import FundingMeanReversion, FundingMROIConfirmed
from hl_trader.signals.momentum import TimeSeriesMomentum

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "fixtures" / "real"

ENGINE = EngineParams(max_drawdown_kill=0.25)

# ---------------------------------------------------------------------------
# Strategy evaluation (always through the allocator: as-traded, vol-targeted).
# ---------------------------------------------------------------------------


def eval_target(df: pd.DataFrame, raw_target: pd.Series) -> Metrics:
    """Vol-target a single raw signal and backtest it."""
    sized = allocate({"s": raw_target}, df["close"], AllocatorParams(weights={"s": 1.0}))
    res = run_backtest(df, sized, ENGINE)
    return compute_metrics(res.equity, res.trades, res.account.fees_paid)


def eval_combined(df: pd.DataFrame, targets: dict[str, pd.Series]) -> Metrics:
    sized = allocate(targets, df["close"], AllocatorParams(weights={k: 1.0 for k in targets}))
    res = run_backtest(df, sized, ENGINE)
    return compute_metrics(res.equity, res.trades, res.account.fees_paid)


def spread_df(df: pd.DataFrame) -> pd.DataFrame:
    """Variant B input: funding_rate replaced by (HL - Binance) spread."""
    out = df.copy()
    out["funding_rate"] = df["hl_funding_rate"] - df["funding_rate"]
    return out


def make_targets(df: pd.DataFrame) -> dict[str, pd.Series]:
    """All strategy raw targets on a given frame."""
    return {
        "tsmom": TimeSeriesMomentum().target(df),
        "funding_mr": FundingMeanReversion().target(df),
        "funding_mr_oi": FundingMROIConfirmed().target(df),
        "funding_mr_spread": FundingMeanReversion().target(spread_df(df)),
    }


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

HEADER = (
    f"{'strategy':<20} {'total':>9} {'cagr':>8} {'sharpe':>7} {'maxDD':>8} "
    f"{'winrate':>8} {'trades':>7} {'turnover':>9}"
)


def fmt(name: str, m: Metrics) -> str:
    return (
        f"{name:<20} {m.total_return:>9.2%} {m.cagr:>8.2%} {m.sharpe:>7.2f} "
        f"{m.max_drawdown:>8.2%} {m.win_rate:>8.2%} {m.n_closing_trades:>7d} {m.turnover:>9.1f}"
    )


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------------------
# Walk-forward (anchored grid search per window)
# ---------------------------------------------------------------------------

MOM_GRID = [
    {"lookback_bars": lb, "regime_bars": rb}
    for lb in (84, 168, 336)
    for rb in (720, 1440, 2160)
]
FMR_GRID = [
    {"window_bars": w, "enter_pct": e}
    for w in (360, 720, 1080)
    for e in (0.90, 0.95, 0.98)
]


def build(signal_cls, params, df):
    return signal_cls(**params).target(df)


def walk_forward(df: pd.DataFrame, signal_cls, grid, spread: bool = False,
                 train_months: int = 12, test_months: int = 3) -> Metrics:
    """Grid-search params on each train window; apply to the next test window.

    OOS test returns are concatenated into one equity curve and scored. The
    grid is searched only on train data; test windows are never used to pick
    params (walk-forward discipline).
    """
    src = spread_df(df) if spread else df
    start = df.index[0]
    end = df.index[-1]
    oos_returns = []
    cursor = start + pd.DateOffset(months=train_months)
    while cursor < end:
        train = src.loc[start:cursor]
        test_end = min(cursor + pd.DateOffset(months=test_months), end)
        test = src.loc[cursor:test_end]
        if len(test) < 24 or len(train) < 24:
            break
        # pick best params by in-window (train) Sharpe
        best, best_sharpe = grid[0], float("-inf")
        for params in grid:
            tgt = build(signal_cls, params, train)
            m = eval_target(train, tgt)
            if pd.notna(m.sharpe) and m.sharpe > best_sharpe:
                best, best_sharpe = params, m.sharpe
        # apply chosen params to the test window (compute target on a frame that
        # includes train history so rolling windows are warm, then slice to test)
        full = build(signal_cls, best, src.loc[start:test_end])
        sized = allocate({"s": full}, src.loc[start:test_end, "close"],
                         AllocatorParams(weights={"s": 1.0}))
        res = run_backtest(src.loc[start:test_end], sized, ENGINE)
        eq = res.equity.loc[cursor:test_end]
        oos_returns.append(eq.pct_change().dropna())
        cursor = test_end
    if not oos_returns:
        return None
    rets = pd.concat(oos_returns)
    eq = (1 + rets).cumprod() * ENGINE.initial_cash
    return compute_metrics(eq, pd.DataFrame(columns=["realized_pnl"]), 0.0)


# ---------------------------------------------------------------------------
# Sensitivity (+/-50% on key params)
# ---------------------------------------------------------------------------


def sensitivity(df_oos: pd.DataFrame, signal_cls, base_params: dict, keys: list[str],
                spread: bool = False) -> dict:
    """Vary each key by +/-50% (and the default) over a grid; report Sharpe spread."""
    src = spread_df(df_oos) if spread else df_oos
    grids = {k: sorted({max(1, int(base_params[k] * f)) if isinstance(base_params[k], int)
                        else round(base_params[k] * f, 4)
                        for f in (0.5, 1.0, 1.5)}) for k in keys}
    sharpes = []
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*[grids[k] for k in keys])]
    for combo in combos:
        params = {**base_params, **combo}
        # clamp percentile params to (0,1)
        if "enter_pct" in params:
            params["enter_pct"] = min(0.999, params["enter_pct"])
        tgt = build(signal_cls, params, src)
        m = eval_target(src, tgt)
        if pd.notna(m.sharpe):
            sharpes.append(m.sharpe)
    s = pd.Series(sharpes)
    return {"n": len(s), "min": float(s.min()), "median": float(s.median()),
            "max": float(s.max()), "frac_positive": float((s > 0).mean())}


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

PROMOTE = {"oos_sharpe": 0.5, "oos_total": 0.0, "wf_sharpe": 0.0, "sens_median": 0.0,
           "sens_frac_positive": 0.6}


def decide(oos: Metrics, wf: Metrics, sens: dict) -> tuple[str, list[str]]:
    reasons = []
    ok = True
    if not (pd.notna(oos.sharpe) and oos.sharpe > PROMOTE["oos_sharpe"]):
        ok = False; reasons.append(f"OOS Sharpe {oos.sharpe:.2f}<={PROMOTE['oos_sharpe']}")
    if not (oos.total_return > PROMOTE["oos_total"]):
        ok = False; reasons.append(f"OOS total {oos.total_return:.1%}<=0")
    if wf is None or not (pd.notna(wf.sharpe) and wf.sharpe > PROMOTE["wf_sharpe"]):
        ok = False; reasons.append(f"WF Sharpe {('n/a' if wf is None else f'{wf.sharpe:.2f}')}<=0")
    if not (sens["median"] > PROMOTE["sens_median"]):
        ok = False; reasons.append(f"sens median {sens['median']:.2f}<=0")
    if not (sens["frac_positive"] >= PROMOTE["sens_frac_positive"]):
        ok = False; reasons.append(f"sens frac+ {sens['frac_positive']:.0%}<60%")
    if ok:
        reasons.append("passed all gates")
    return ("PROMOTE" if ok else "KILL"), reasons


# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout-months", type=int, default=12)
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH"])
    parser.add_argument("--out", type=Path, default=ROOT / "output" / "phase2_validation")
    args = parser.parse_args()

    configure_logging("WARNING")
    args.out.mkdir(parents=True, exist_ok=True)
    summary: dict = {"assets": {}, "thresholds": PROMOTE}

    for asset in args.assets:
        path = DATA / f"{asset}_1h.parquet"
        if not path.exists():
            print(f"!! missing {path} — run scripts/fetch_real_data.py first")
            continue
        df = pd.read_parquet(path)
        split = df.index[-1] - pd.DateOffset(months=args.holdout_months)
        is_df, oos_df = df.loc[: split], df.loc[split:]

        section(f"{asset}: real-data window {df.index[0].date()} .. {df.index[-1].date()} "
                f"({len(df)} bars)  |  holdout = last {args.holdout_months}mo "
                f"(OOS {oos_df.index[0].date()}..{oos_df.index[-1].date()})")

        # --- Baseline (default params) ---
        targets_full = make_targets(df)
        targets_oos = make_targets(oos_df)
        print("\n-- full sample (default params) --"); print(HEADER)
        for name, t in targets_full.items():
            print(fmt(name, eval_target(df, t)))
        comb_full = eval_combined(df, {k: targets_full[k] for k in ("tsmom", "funding_mr")})
        print(fmt("combined", comb_full))

        print(f"\n-- held-out OOS last {args.holdout_months}mo (default params) --"); print(HEADER)
        oos_metrics = {}
        for name, t in targets_oos.items():
            m = eval_target(oos_df, t); oos_metrics[name] = m; print(fmt(name, m))
        comb_oos = eval_combined(oos_df, {k: targets_oos[k] for k in ("tsmom", "funding_mr")})
        oos_metrics["combined"] = comb_oos
        print(fmt("combined", comb_oos))

        # --- Walk-forward ---
        section_wf = {}
        wf = {
            "tsmom": walk_forward(df, TimeSeriesMomentum, MOM_GRID),
            "funding_mr": walk_forward(df, FundingMeanReversion, FMR_GRID),
            "funding_mr_spread": walk_forward(df, FundingMeanReversion, FMR_GRID, spread=True),
        }
        print("\n-- walk-forward (grid-search train -> apply test, concatenated OOS) --")
        print(HEADER)
        for name, m in wf.items():
            if m: print(fmt(name, m)); section_wf[name] = m

        # --- Sensitivity (+/-50% on key params), measured on the OOS window ---
        sens = {
            "tsmom": sensitivity(oos_df, TimeSeriesMomentum,
                                 {"lookback_bars": 168, "regime_bars": 1440},
                                 ["lookback_bars", "regime_bars"]),
            "funding_mr": sensitivity(oos_df, FundingMeanReversion,
                                      {"window_bars": 720, "enter_pct": 0.95},
                                      ["window_bars", "enter_pct"]),
            "funding_mr_spread": sensitivity(oos_df, FundingMeanReversion,
                                             {"window_bars": 720, "enter_pct": 0.95},
                                             ["window_bars", "enter_pct"], spread=True),
        }
        print("\n-- sensitivity +/-50% on key params (OOS Sharpe spread) --")
        print(f"{'strategy':<20} {'n':>3} {'min':>7} {'median':>7} {'max':>7} {'frac+':>7}")
        for name, s in sens.items():
            print(f"{name:<20} {s['n']:>3} {s['min']:>7.2f} {s['median']:>7.2f} "
                  f"{s['max']:>7.2f} {s['frac_positive']:>7.0%}")

        # --- Decisions ---
        section_dec = {}
        print("\n-- DECISION (promote/kill) --")
        for name in ("tsmom", "funding_mr", "funding_mr_spread"):
            verdict, reasons = decide(oos_metrics[name], wf.get(name), sens[name])
            print(f"{name:<20} {verdict:<9} {'; '.join(reasons)}")
            section_dec[name] = {"verdict": verdict, "reasons": reasons}
        # variant A (OI) judged on OOS + sensitivity vs baseline (no separate WF grid)
        sens_oi = sensitivity(oos_df, FundingMROIConfirmed,
                              {"window_bars": 720, "enter_pct": 0.95},
                              ["window_bars", "enter_pct"])
        v_oi, r_oi = decide(oos_metrics["funding_mr_oi"], wf["funding_mr"], sens_oi)
        print(f"{'funding_mr_oi':<20} {v_oi:<9} {'; '.join(r_oi)}")
        section_dec["funding_mr_oi"] = {"verdict": v_oi, "reasons": r_oi}

        summary["assets"][asset] = {
            "window": [str(df.index[0]), str(df.index[-1])],
            "bars": len(df),
            "oos": {k: m.as_dict() for k, m in oos_metrics.items()},
            "full": {k: eval_target(df, t).as_dict() for k, t in targets_full.items()},
            "walk_forward": {k: m.as_dict() for k, m in section_wf.items()},
            "sensitivity": sens,
            "decisions": section_dec,
        }

    (args.out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nwrote {args.out / 'summary.json'}")


if __name__ == "__main__":
    main()
