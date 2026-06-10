import json

import pytest

from hl_trader.exchange.hyperliquid_client import (
    WEIGHT_BUDGET_PER_MINUTE,
    HyperliquidInfoClient,
    RateBudgetExceeded,
)


class StubResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class StubSession:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {}
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return StubResponse(self.payload)


def make_client(payload=None, clock=None):
    session = StubSession(payload)
    client = HyperliquidInfoClient(
        "https://api.hyperliquid-testnet.xyz",
        session=session,
        clock=clock or (lambda: 0.0),
    )
    return client, session


def test_request_shaping_funding_history():
    client, session = make_client([])
    client.funding_history("BTC", start_ms=1000, end_ms=2000)
    body = session.calls[0]["json"]
    assert body == {"type": "fundingHistory", "coin": "BTC", "startTime": 1000, "endTime": 2000}
    assert session.calls[0]["url"].endswith("/info")


def test_request_shaping_candle_snapshot():
    client, session = make_client([])
    client.candle_snapshot("ETH", "1h", 1, 2)
    body = session.calls[0]["json"]
    assert body["type"] == "candleSnapshot"
    assert body["req"] == {"coin": "ETH", "interval": "1h", "startTime": 1, "endTime": 2}
    json.dumps(body)  # payload must be JSON-serializable


def test_meta_cached_within_ttl():
    client, session = make_client({"universe": []})
    client.meta()
    client.meta()
    assert len(session.calls) == 1


def test_weight_budget_enforced():
    client, _ = make_client({})
    n_allowed = WEIGHT_BUDGET_PER_MINUTE // 2  # allMids weighs 2
    for _ in range(n_allowed):
        client.all_mids()
    with pytest.raises(RateBudgetExceeded):
        client.all_mids()


def test_weight_window_expires():
    now = {"t": 0.0}
    client, _ = make_client({}, clock=lambda: now["t"])
    for _ in range(WEIGHT_BUDGET_PER_MINUTE // 2):
        client.all_mids()
    now["t"] = 61.0
    client.all_mids()  # must not raise after the window rolls
    assert client.weight_used() == 2
