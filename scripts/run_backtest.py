"""Run the Phase 2 strategies through the backtest harness and print metrics.

By default runs on the committed synthetic fixture (mechanics check, NOT an
edge claim). Point --data at a real-data CSV/parquet produced by the loader
once network access is allowlisted.

Usage:
    .venv/bin/python scripts/run_backtest.py
    .venv/bin/python scripts/run_backtest.py --data path/to/real.csv --out output/
"""

import argparse
from pathlib import Path

from hl_trader.allocator.allocator import AllocatorParams, allocate
from hl_trader.backtest.engine import EngineParams, run_backtest
from hl_trader.backtest.metrics import compute_metrics
from hl_trader.data.loader import load_fixture
from hl_trader.logging_setup import configure_logging
from hl_trader.signals.funding_mr import FundingMeanReversion
from hl_trader.signals.momentum import TimeSeriesMomentum

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "btc_synth_1h.csv"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=FIXTURE)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    configure_logging("WARNING")
    df = load_fixture(args.data)
    is_synth = args.data == FIXTURE

    signals = [TimeSeriesMomentum(), FundingMeanReversion()]
    targets = {s.name: s.target(df) for s in signals}

    engine_params = EngineParams(max_drawdown_kill=0.25)
    alloc_params = AllocatorParams(weights={"tsmom": 1.0, "funding_mr": 1.0})

    runs = {name: t for name, t in targets.items()}
    runs["combined"] = allocate(targets, df["close"], alloc_params)

    print(f"data: {args.data} ({len(df)} bars, {df.index[0]} .. {df.index[-1]})")
    if is_synth:
        print("*** SYNTHETIC fixture: mechanics check only — not evidence of edge ***")
    header = (
        f"{'strategy':<12} {'total':>8} {'cagr':>8} {'sharpe':>7} {'maxDD':>7} "
        f"{'winrate':>8} {'trades':>7} {'turnover':>9} {'fees':>10}"
    )
    print(header)
    print("-" * len(header))
    for name, target in runs.items():
        result = run_backtest(df, target, engine_params)
        m = compute_metrics(result.equity, result.trades, result.account.fees_paid)
        print(
            f"{name:<12} {m.total_return:>8.2%} {m.cagr:>8.2%} {m.sharpe:>7.2f} "
            f"{m.max_drawdown:>7.2%} {m.win_rate:>8.2%} {m.n_closing_trades:>7d} "
            f"{m.turnover:>9.1f} {m.fees_paid:>10.2f}" + ("  [KILLED]" if result.killed else "")
        )
        if args.out:
            result.to_csv(args.out / name)
    if args.out:
        print(f"equity curves + trade logs written under {args.out}/")


if __name__ == "__main__":
    main()
