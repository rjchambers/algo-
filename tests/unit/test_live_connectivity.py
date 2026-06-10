"""Live testnet connectivity (Phase 0 gate). Skipped until blocker B0 clears.

Run with: .venv/bin/pytest tests/unit/test_live_connectivity.py --run-live
"""

import pytest

from hl_trader.config import load_settings
from hl_trader.exchange.hyperliquid_client import HyperliquidInfoClient

pytestmark = pytest.mark.live


def test_testnet_meta_and_mids():
    settings = load_settings(_env_file=None)  # defaults to testnet
    client = HyperliquidInfoClient(settings.api_url)
    meta = client.meta()
    assert any(a["name"] == "BTC" for a in meta["universe"])
    mids = client.all_mids()
    assert float(mids["BTC"]) > 0
