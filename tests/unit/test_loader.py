from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hl_trader.data.loader import DataGapError, check_gaps, load_fixture

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_fixture_loads_utc_sorted(synth_df):
    assert str(synth_df.index.tz) == "UTC"
    assert synth_df.index.is_monotonic_increasing
    assert set(["open", "high", "low", "close", "volume", "funding_rate"]) <= set(synth_df.columns)
    check_gaps(synth_df, "1h")  # committed fixture must be gap-free


def test_fixture_is_deterministic(synth_df):
    import sys

    sys.path.insert(0, str(FIXTURES.parent.parent / "scripts"))
    from make_fixture import make_synthetic

    regenerated = make_synthetic(len(synth_df))
    np.testing.assert_allclose(
        regenerated["close"].to_numpy(), synth_df["close"].to_numpy(), rtol=1e-6
    )


def test_check_gaps_rejects_gappy_data(synth_df):
    gappy = pd.concat([synth_df.iloc[:100], synth_df.iloc[200:300]])
    with pytest.raises(DataGapError, match="missing"):
        check_gaps(gappy, "1h")


def test_check_gaps_rejects_duplicates(synth_df):
    dup = pd.concat([synth_df.iloc[:50], synth_df.iloc[49:100]])
    with pytest.raises(DataGapError, match="duplicate"):
        check_gaps(dup, "1h")


def test_load_fixture_roundtrip(tmp_path):
    idx = pd.date_range("2025-01-01", periods=3, freq="1h", tz="UTC")
    df = pd.DataFrame({"open": [1.0, 2, 3], "close": [1.0, 2, 3]}, index=pd.Index(idx, name="ts"))
    p = tmp_path / "x.csv"
    df.to_csv(p)
    loaded = load_fixture(p)
    assert str(loaded.index.tz) == "UTC"
    assert len(loaded) == 3
