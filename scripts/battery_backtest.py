"""Backtest the classic-strategy battery on real data, honestly.

Each strategy is evaluated as-traded (vol-targeted through the allocator, HL
costs, 25% DD kill) on full sample and the held-out last 12 months, alongside
the buy&hold benchmark. A strategy is flagged as a LEAD only if, on EVERY asset,
its held-out Sharpe > 0.5 and it beats buy&hold's held-out total return. Leads
are still just candidates for full §2.6 walk-forward + sensitivity validation —
this script does not promote anything.

Usage:
    .venv/bin/python scripts/battery_backtest.py [BTC ETH SOL]
"""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_phase2 import DATA, eval_target  # noqa: E402

from hl_trader.logging_setup import configure_logging  # noqa: E402
from hl_trader.signals.classic import STRATEGIES  # noqa: E402

HEADER = (f"{'strategy':<20} {'full_tot':>9} {'full_sh':>8} {'oos_tot':>9} "
          f"{'oos_sh':>7} {'oos_DD':>8} {'trades':>7}")


def buy_hold(df):
    return pd.Series(1.0, index=df.index)


def main():
    configure_logging("ERROR")
    assets = [a for a in (sys.argv[1:] or ["BTC", "ETH"])]
    print("CLASSIC STRATEGY BATTERY — honest as-traded backtest (vs buy&hold).")
    print("Leads must clear OOS Sharpe>0.5 AND beat buy&hold OOS on EVERY asset.\n")

    # collect per-asset OOS results for the cross-asset lead test
    oos_sharpe: dict[str, dict[str, float]] = {a: {} for a in assets}
    oos_total: dict[str, dict[str, float]] = {a: {} for a in assets}
    bh_oos: dict[str, float] = {}

    all_strats = {"buy_hold": buy_hold, **STRATEGIES}
    for asset in assets:
        path = DATA / f"{asset}_1h.parquet"
        if not path.exists():
            print(f"!! missing {path}\n"); continue
        df = pd.read_parquet(path)
        split = df.index[-1] - pd.DateOffset(months=12)
        oos_df = df.loc[split:]
        raw_bh = oos_df["close"].iloc[-1] / oos_df["close"].iloc[0] - 1
        print(f"== {asset}  ({len(df)} bars; raw buy&hold last-12mo {raw_bh:+.1%}) ==")
        print(HEADER)
        for name, fn in all_strats.items():
            full = eval_target(df, fn(df))
            oos = eval_target(oos_df, fn(oos_df))
            print(f"{name:<20} {full.total_return:>9.1%} {full.sharpe:>8.2f} "
                  f"{oos.total_return:>9.1%} {oos.sharpe:>7.2f} {oos.max_drawdown:>8.1%} "
                  f"{oos.n_closing_trades:>7d}")
            oos_sharpe[asset][name] = oos.sharpe
            oos_total[asset][name] = oos.total_return
            if name == "buy_hold":
                bh_oos[asset] = oos.total_return
        print()

    # cross-asset lead test
    print("=" * 70)
    print("CROSS-ASSET LEADS (OOS Sharpe>0.5 AND beats buy&hold OOS on ALL assets):")
    done = [a for a in assets if (DATA / f"{a}_1h.parquet").exists()]
    leads = []
    for name in STRATEGIES:
        ok = all(
            pd.notna(oos_sharpe[a].get(name)) and oos_sharpe[a][name] > 0.5
            and oos_total[a][name] > bh_oos[a]
            for a in done
        )
        if ok:
            leads.append(name)
    if leads:
        for name in leads:
            detail = ", ".join(f"{a}: Sh={oos_sharpe[a][name]:.2f} tot={oos_total[a][name]:+.1%}"
                               for a in done)
            print(f"  LEAD: {name}  ({detail})")
    else:
        print("  none. No classic strategy robustly beats holding out-of-sample.")
    print("\n(Leads are candidates only — still require full §2.6 walk-forward + sensitivity.)")


if __name__ == "__main__":
    main()
