from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", help="run tests hitting live APIs")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="needs --run-live and network allowlist (blocker B0)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def synth_df() -> pd.DataFrame:
    from hl_trader.data.loader import load_fixture

    return load_fixture(FIXTURES / "btc_synth_1h.csv")
