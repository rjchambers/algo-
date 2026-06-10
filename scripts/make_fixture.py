"""Generate the deterministic synthetic fixture committed under tests/fixtures.

SYNTHETIC DATA — for harness/signal mechanics validation only, never for edge
claims. Regime-switching GBM hourly candles plus an AR(1) funding process that
leans with recent returns (funding gets rich after run-ups, mimicking crowded
positioning). Seeded: re-running this script reproduces the file byte-for-byte.

Usage: python scripts/make_fixture.py [--bars 4380] [--out tests/fixtures/btc_synth_1h.csv]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
HOURS_PER_YEAR = 24 * 365


def make_synthetic(bars: int, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Regime-switching drift: bull / chop / bear blocks of ~3 weeks.
    block = 24 * 21
    n_blocks = bars // block + 1
    annual_drifts = rng.choice([1.5, 0.0, -1.0], size=n_blocks, p=[0.35, 0.40, 0.25])
    drift_hourly = np.repeat(annual_drifts, block)[:bars] / HOURS_PER_YEAR
    vol_hourly = 0.60 / np.sqrt(HOURS_PER_YEAR)

    log_returns = drift_hourly + vol_hourly * rng.standard_normal(bars)
    close = 50_000.0 * np.exp(np.cumsum(log_returns))
    open_ = np.concatenate([[50_000.0], close[:-1]])
    spread = np.abs(rng.standard_normal(bars)) * vol_hourly * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.lognormal(mean=4.0, sigma=0.5, size=bars)

    # Funding: AR(1) around a small positive base, pushed by trailing 24h return.
    trail = pd.Series(log_returns).rolling(24).sum().fillna(0.0).to_numpy()
    funding = np.zeros(bars)
    base = 0.125e-4  # ~11% annualized, typical calm-market hourly funding
    for i in range(1, bars):
        shock = rng.standard_normal() * 0.3e-4
        funding[i] = 0.97 * funding[i - 1] + 0.03 * (base + 6e-4 * trail[i]) + shock * 0.03
    index = pd.date_range("2025-01-01", periods=bars, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "funding_rate": funding,
        },
        index=pd.Index(index, name="ts"),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=int, default=4380)  # ~6 months of 1h bars
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures/btc_synth_1h.csv"))
    args = parser.parse_args()

    df = make_synthetic(args.bars)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, float_format="%.8f")
    print(f"wrote {len(df)} bars to {args.out}")
