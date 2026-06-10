"""Read-only Hyperliquid Info API client.

Thin wrapper over the public ``POST /info`` endpoint with:
- request-weight accounting against Hyperliquid's published REST budget,
- short-TTL caching of slow-moving snapshots (``meta``),
- injectable session for offline/mocked tests.

Trading (Exchange endpoint, signed actions) is Phase 3 and will go through
``hyperliquid-python-sdk``; nothing in this module can place orders.
"""

import time
from typing import Any

import requests

from hl_trader.logging_setup import get_logger

# Hyperliquid REST rate limit: 1200 weight/minute per IP. Info request weights
# per docs: most info requests weight 2; l2Book/allMids weight 2; candleSnapshot 4.
WEIGHT_BUDGET_PER_MINUTE = 1200
_DEFAULT_WEIGHTS = {
    "meta": 2,
    "metaAndAssetCtxs": 2,
    "allMids": 2,
    "l2Book": 2,
    "clearinghouseState": 2,
    "fundingHistory": 2,
    "candleSnapshot": 4,
}

META_CACHE_TTL_S = 300.0


class RateBudgetExceeded(RuntimeError):
    pass


class HyperliquidInfoClient:
    def __init__(
        self,
        base_url: str,
        session: requests.Session | None = None,
        timeout_s: float = 10.0,
        clock=time.monotonic,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout_s = timeout_s
        self._clock = clock
        self._weight_window: list[tuple[float, int]] = []  # (timestamp, weight)
        self._meta_cache: tuple[float, dict] | None = None
        self._log = get_logger("hl.info", base_url=self.base_url)

    # -- rate budget -------------------------------------------------------
    def _spend_weight(self, request_type: str) -> None:
        weight = _DEFAULT_WEIGHTS.get(request_type, 20)
        now = self._clock()
        self._weight_window = [(t, w) for t, w in self._weight_window if now - t < 60.0]
        used = sum(w for _, w in self._weight_window)
        if used + weight > WEIGHT_BUDGET_PER_MINUTE:
            raise RateBudgetExceeded(
                f"Refusing '{request_type}': would exceed {WEIGHT_BUDGET_PER_MINUTE} "
                f"weight/min (used {used} in window)."
            )
        self._weight_window.append((now, weight))

    def weight_used(self) -> int:
        now = self._clock()
        return sum(w for t, w in self._weight_window if now - t < 60.0)

    # -- core --------------------------------------------------------------
    def _info(self, payload: dict[str, Any]) -> Any:
        request_type = payload["type"]
        self._spend_weight(request_type)
        resp = self.session.post(f"{self.base_url}/info", json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        self._log.debug("info_request", request_type=request_type, status=resp.status_code)
        return resp.json()

    # -- public read-only endpoints -----------------------------------------
    def meta(self) -> dict:
        """Perp universe metadata. Cached for META_CACHE_TTL_S."""
        now = self._clock()
        if self._meta_cache is not None and now - self._meta_cache[0] < META_CACHE_TTL_S:
            return self._meta_cache[1]
        result = self._info({"type": "meta"})
        self._meta_cache = (now, result)
        return result

    def all_mids(self) -> dict[str, str]:
        return self._info({"type": "allMids"})

    def l2_book(self, coin: str) -> dict:
        return self._info({"type": "l2Book", "coin": coin})

    def clearinghouse_state(self, address: str) -> dict:
        return self._info({"type": "clearinghouseState", "user": address})

    def funding_history(self, coin: str, start_ms: int, end_ms: int | None = None) -> list[dict]:
        payload: dict[str, Any] = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
        if end_ms is not None:
            payload["endTime"] = end_ms
        return self._info(payload)

    def candle_snapshot(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
        req = {"coin": coin, "interval": interval, "startTime": start_ms, "endTime": end_ms}
        return self._info({"type": "candleSnapshot", "req": req})
