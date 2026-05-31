# Hyperliquid Multi-Signal Trading System — Task Plan

> Scope of this document: **Phase 0 and Phase 1 only.** Later phases are intentionally
> not planned in detail (do not build orchestration ahead of proven edge — spec §6).
> Items are checkable. Mark `[x]` only when proven (test passed / log shown).

---

## Confirmed decisions (from kickoff Q&A 2026-05-31)

| Decision | Choice | Notes |
|---|---|---|
| Python | 3.10.20 (available in env) | venv; pinned exactly per spec §3 |
| Exchange SDK | `hyperliquid-python-sdk` | `ccxt` used only for historical data ingestion |
| Backtest data source | **Binance OHLCV via `ccxt`** | deep history as price proxy; model **Hyperliquid** fees/funding/slippage |
| TA library | **`pandas-ta`** | pin `numpy<2` (pandas-ta uses removed `numpy.NaN`) |
| Logging | **`structlog`** (JSON) | structured audit trail of every signal/decision/order |
| Network | User will allowlist HL hosts | see Blocker B0 below |

---

## ⚠️ Active blocker

- **B0 — Network allowlist.** `api.hyperliquid.xyz`, `api.hyperliquid-testnet.xyz`
  return `403 "Host not in allowlist"` from this web environment. GitHub + PyPI are
  reachable. The Phase 0 gate ("pull live testnet data") **cannot pass here** until
  these hosts (and `wss://api.hyperliquid.xyz/ws`) are added to the environment's
  network policy. User has agreed to allowlist. Until then, Phase 0 connectivity
  items are coded + unit-tested against recorded/mocked responses and verified live
  once unblocked.

---

## Phase 0 — Plan & scaffold

**Goal:** repo skeleton, secrets/config handling, logging, testnet read-only connectivity.
**Gate:** plan approved + live testnet account state & market data fetched read-only.

### 0.1 Repo & tooling
- [ ] Create venv on Python 3.10; `requirements.txt` + `requirements-dev.txt` (pinned)
- [ ] `pyproject.toml` (project metadata, pytest config, ruff/black config)
- [ ] `.gitignore` covering `.env`, `*.key`, keystores, `logs/`, `.venv/`, data caches
- [ ] `.env.example` with every required var documented (no real values)
- [ ] `pre-commit` config with a **secret scan** hook (e.g. `detect-secrets` or `gitleaks`) + ruff/black
- [ ] `README.md` (setup, safety model, phase status)

### 0.2 Config & secrets
- [ ] `config/` module: typed settings loader (pydantic-settings) reading env + `.env`
- [ ] Separate testnet vs mainnet base URLs; **default to testnet**
- [ ] Agent (API) wallet key loaded from env only; assert master/withdrawal key never present
- [ ] Fail loudly with clear message if required secrets missing

### 0.3 Logging & observability
- [ ] `structlog` JSON logging configured; correlation/context fields (asset, loop_id)
- [ ] Secret redaction in log processors (never log keys/signatures)
- [ ] Log to console + rotating file under `logs/` (gitignored)

### 0.4 Hyperliquid connectivity (read-only)
- [ ] Thin `exchange/hyperliquid_client.py` wrapper around the SDK Info + (later) Exchange
- [ ] REST Info: fetch `meta`, mids, account `clearinghouseState` (read-only)
- [ ] WebSocket subscribe to trades/l2book/candles for one asset; normalized event print
- [ ] Rate-budget awareness: simple weight accounting + caching of Info snapshots
- [ ] **Verify live** against testnet once B0 cleared (script: `scripts/check_testnet.py`)

### 0.5 Tests (Phase 0)
- [ ] Unit tests: config loader (missing/var present), redaction, client request shaping
- [ ] Connectivity test marked `@pytest.mark.live` (skipped until allowlisted)
- [ ] `make test` / documented pytest invocation green

**Phase 0 review section:** _(fill at phase end)_

---

## Phase 1 — Backtest harness

**Goal:** deterministic event-driven backtester with realistic fees + slippage.
**Gate:** reproduces a known trivial strategy's PnL correctly + covered by tests.

### 1.1 Data layer
- [ ] `data/loader.py`: fetch OHLCV via `ccxt` (Binance) with on-disk parquet/CSV cache
- [ ] Deterministic, timezone-aware, gap-checked candles; documented symbol mapping (BTC/USDT → BTC perp)
- [ ] Fixture dataset committed (small slice) for fast reproducible tests

### 1.2 Cost model (Hyperliquid-faithful)
- [ ] `backtest/costs.py`: taker/maker fees, slippage model (not mid fills), funding accrual
- [ ] Config-driven fee/slippage params; documented sources for HL fee schedule

### 1.3 Event-driven engine
- [ ] `backtest/engine.py`: bar-by-bar event loop, no look-ahead (signal at close → fill next bar)
- [ ] Portfolio/account model: cash, positions, equity curve, realized/unrealized PnL
- [ ] Order types needed for harness: market + stop; partial-fill aware interface
- [ ] Deterministic given same inputs (seeded; assert reproducibility in test)

### 1.4 Metrics & reporting
- [ ] `backtest/metrics.py`: total/CAGR, Sharpe, max drawdown, win rate, expectancy, turnover, fees paid
- [ ] Equity curve + trade log output (CSV/JSON) for inspection

### 1.5 Validation (the gate)
- [ ] **Buy-and-hold** sanity: engine PnL matches hand-computed return within tolerance
- [ ] **Known trivial strategy** (e.g. always-long-1-unit) reproduces analytically-derived PnL incl. fees
- [ ] No-look-ahead test: shifting signal forward changes results as expected
- [ ] Determinism test: identical runs → identical equity curve
- [ ] All Phase 1 tests green; show output/logs as proof

**Phase 1 review section:** _(fill at phase end)_

---

## Proposed repo structure

```
algo-/
├── README.md
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── config/                 # typed settings (pydantic-settings)
│   └── settings.py
├── src/hl_trader/
│   ├── exchange/           # hyperliquid_client.py (Info/Exchange wrappers, WS)
│   ├── data/               # ccxt loader + cache
│   ├── backtest/           # engine, costs, metrics, portfolio
│   ├── signals/            # (Phase 2+) TA signal producers
│   ├── allocator/          # (Phase 2+) the single deterministic risk/allocator
│   ├── execution/          # (Phase 3+) order diffing/reconciliation
│   └── logging_setup.py
├── scripts/
│   └── check_testnet.py    # read-only connectivity proof
├── tests/
│   ├── unit/
│   └── fixtures/
├── logs/                   # gitignored
└── tasks/
    ├── todo.md
    └── lessons.md
```

---

## Key technical decisions to confirm (beyond the Q&A)

1. **Secret-scan tool:** `detect-secrets` (pure-Python, easy in 3.10 venv) vs `gitleaks` (Go binary). Proposing `detect-secrets`.
2. **Settings library:** `pydantic-settings` for typed env config. OK?
3. **Backtest timeframe(s):** propose 1h primary + 1d for regime context. OK?
4. **Initial backtest universe:** BTC + ETH for Phase 1 validation (commodity-proxy markets deferred to Phase 2+). OK?

## Open questions

- **OQ1:** Once allowlisted, do you want me to provision the **testnet agent wallet key** (you create it on Hyperliquid and put it in `.env`), or should Phase 0 connectivity rely only on public read-only Info endpoints until you're ready to share a key?
- **OQ2:** Any preference on dependency manager — plain `pip` + `requirements.txt` (proposed) vs `uv`/`poetry`?

---

## Notes / lessons
- See `tasks/lessons.md` (reviewed at start of each session).
