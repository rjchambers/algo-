"""Phase 0 gate proof: read-only live connectivity to Hyperliquid testnet.

Run once blocker B0 (network allowlist) is cleared:
    .venv/bin/python scripts/check_testnet.py [--mainnet]

Read-only: uses only the public Info endpoint; no key required, no orders.
"""

import argparse
import sys
import time

from hl_trader.config import load_settings
from hl_trader.exchange.hyperliquid_client import HyperliquidInfoClient
from hl_trader.logging_setup import configure_logging, get_logger


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mainnet", action="store_true")
    args = parser.parse_args()

    settings = load_settings(network="mainnet" if args.mainnet else "testnet")
    configure_logging(settings.log_level, settings.log_dir)
    log = get_logger("check_testnet", network=settings.network.value)

    client = HyperliquidInfoClient(settings.api_url)

    meta = client.meta()
    universe = [a["name"] for a in meta["universe"][:10]]
    log.info("meta_ok", n_assets=len(meta["universe"]), first_assets=universe)

    mids = client.all_mids()
    log.info("mids_ok", btc_mid=mids.get("BTC"), eth_mid=mids.get("ETH"))

    now_ms = int(time.time() * 1000)
    funding = client.funding_history("BTC", start_ms=now_ms - 24 * 3_600_000)
    log.info("funding_ok", points_24h=len(funding))

    if settings.account_address:
        state = client.clearinghouse_state(settings.account_address)
        log.info("account_ok", margin_summary=state.get("marginSummary"))
    else:
        log.info("account_skipped", reason="HL_TRADER_ACCOUNT_ADDRESS not set")

    log.info("phase0_gate", status="PASS", weight_used=client.weight_used())
    return 0


if __name__ == "__main__":
    sys.exit(main())
