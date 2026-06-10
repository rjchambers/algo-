import json

import pytest
import requests

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
    def __init__(self, payload=None, pages=None):
        self.payload = payload if payload is not None else {}
        self.pages = list(pages) if pages is not None else None
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if self.pages is not None:
            return StubResponse(self.pages.pop(0) if self.pages else [])
        return StubResponse(self.payload)


def make_client(payload=None, clock=None, pages=None):
    session = StubSession(payload, pages=pages)
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


def test_funding_history_paginates_past_500_cap():
    page1 = [{"time": i, "fundingRate": "0.0001"} for i in range(500)]
    page2 = [{"time": 500 + i, "fundingRate": "0.0001"} for i in range(3)]
    client, session = make_client(pages=[page1, page2])
    items = client.funding_history_all("BTC", start_ms=0, end_ms=10_000)
    assert len(items) == 503
    assert [c["json"]["startTime"] for c in session.calls] == [0, 500]
    assert all(c["json"]["type"] == "fundingHistory" for c in session.calls)


def test_pagination_short_page_stops():
    page = [{"time": i} for i in range(10)]  # < 500: range exhausted in one page
    client, session = make_client(pages=[page])
    items = client.funding_history_all("BTC", start_ms=0, end_ms=10_000)
    assert len(items) == 10
    assert len(session.calls) == 1


def test_pagination_filters_items_beyond_end():
    page = [{"time": i} for i in range(500)]
    client, _ = make_client(pages=[page])
    items = client.funding_history_all("BTC", start_ms=0, end_ms=100)
    assert len(items) == 100
    assert items[-1]["time"] == 99


def test_pagination_stuck_cursor_terminates():
    # Misbehaving endpoint returns the identical full page forever; the cursor
    # guard must break out instead of looping.
    page = [{"time": i} for i in range(500)]
    client, session = make_client(pages=[page, page, page])
    items = client.funding_history_all("BTC", start_ms=0, end_ms=10_000)
    assert len(session.calls) == 2  # first page + one repeat, then guard trips
    assert len(items) == 1000


def test_candles_all_paginates_on_open_time():
    page1 = [{"t": i, "T": i + 1, "c": "100"} for i in range(500)]
    page2 = [{"t": 500, "T": 501, "c": "100"}]
    client, session = make_client(pages=[page1, page2])
    items = client.candles_all("ETH", "1h", start_ms=0, end_ms=10_000)
    assert len(items) == 501
    assert session.calls[1]["json"]["req"]["startTime"] == 500


def test_weight_window_expires():
    now = {"t": 0.0}
    client, _ = make_client({}, clock=lambda: now["t"])
    for _ in range(WEIGHT_BUDGET_PER_MINUTE // 2):
        client.all_mids()
    now["t"] = 61.0
    client.all_mids()  # must not raise after the window rolls
    assert client.weight_used() == 2


class CodedResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        return self.responses.pop(0)


def test_retries_on_429_then_succeeds():
    import requests as _rq  # noqa: F401  (ensure requests imported for HTTPError)

    session = SequenceSession([
        CodedResponse(429),
        CodedResponse(429),
        CodedResponse(200, {"ok": True}),
    ])
    slept = []
    client = HyperliquidInfoClient(
        "https://api.hyperliquid-testnet.xyz", session=session,
        clock=lambda: 0.0, backoff_base_s=0.1, sleep=slept.append,
    )
    assert client.all_mids() == {"ok": True}
    assert len(session.calls) == 3
    assert slept == [0.1, 0.2]  # exponential backoff between attempts


def test_honours_retry_after_header():
    session = SequenceSession([
        CodedResponse(429, headers={"Retry-After": "5"}),
        CodedResponse(200, {"ok": True}),
    ])
    slept = []
    client = HyperliquidInfoClient(
        "https://api.hyperliquid-testnet.xyz", session=session,
        clock=lambda: 0.0, sleep=slept.append,
    )
    client.all_mids()
    assert slept == [5.0]


def test_gives_up_after_max_retries():
    session = SequenceSession([CodedResponse(429) for _ in range(4)])
    client = HyperliquidInfoClient(
        "https://api.hyperliquid-testnet.xyz", session=session,
        clock=lambda: 0.0, max_retries=3, backoff_base_s=0.0, sleep=lambda _: None,
    )
    with pytest.raises(requests.HTTPError):
        client.all_mids()
    assert len(session.calls) == 4  # initial + 3 retries
