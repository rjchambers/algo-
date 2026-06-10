# Hyperliquid Multi-Signal Trading System — Task Plan

> Scope of this document: **Phases 0–2.** Later phases are intentionally
> not planned in detail (do not build orchestration ahead of proven edge — spec §6).
> Items are checkable. Mark `[x]` only when proven (test passed / log shown).
>
> **Status 2026-06-10:** Phase 0 code-complete (live gate blocked on B0);
> Phase 1 complete and gate-proven; Phase 2 signals/allocator implemented and
> unit-tested, real-data validation blocked on B0. 43 tests passing offline.

---

## Confirmed decisions (from kickoff Q&A 2026-05-31)

| Decision | Choice | Notes |
|---|---|---|
| Python | ~~3.10.20~~ **3.11.15** (env drifted; see lessons.md) | venv; `requires-python >=3.11`, exact pins in requirements.txt |
| Exchange SDK | `hyperliquid-python-sdk` (pinned, used from Phase 3) | Phases 0–2 read-only Info via thin requests client; `ccxt` for historical ingestion |
| Backtest data source | **Binance OHLCV via `ccxt`** | deep history as price proxy; model **Hyperliquid** fees/funding/slippage |
| TA library | ~~`pandas-ta`~~ **plain pandas/numpy** | dropped: forced `numpy<2` for indicators we write in 3 lines (lessons.md) |
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
- [x] Create venv on Python 3.11; `requirements.txt` + `requirements-dev.txt` (pinned)
- [x] `pyproject.toml` (project metadata, pytest config, ruff config; ruff-format replaces black)
- [x] `.gitignore` covering `.env`, `*.key`, keystores, `logs/`, `.venv/`, data caches
- [x] `.env.example` with every required var documented (no real values)
- [x] `pre-commit` config with `detect-secrets` (+ `.secrets.baseline`) + ruff/ruff-format
- [x] `README.md` (setup, safety model, phase status)

### 0.2 Config & secrets
- [x] `config.py` module: typed settings loader (pydantic-settings) reading env + `.env` (test: `test_config.py`)
- [x] Separate testnet vs mainnet base URLs; **default to testnet** (proven: `test_defaults_to_testnet`)
- [x] Agent (API) wallet key loaded from env only; key-shape validation; naming + README forbid master key
- [x] Fail loudly with clear message if required secrets missing (`require_trading_credentials`)

### 0.3 Logging & observability
- [x] `structlog` JSON logging configured; bindable context fields (asset, loop_id)
- [x] Secret redaction in log processors (proven: `test_logging_redaction.py` — fields, hex keys, nesting)
- [x] Log to console + rotating file under `logs/` (gitignored)

### 0.4 Hyperliquid connectivity (read-only)
- [x] Thin `exchange/hyperliquid_client.py` — requests-based Info client (SDK reserved for Phase 3 signing)
- [x] REST Info: `meta`, `allMids`, `l2Book`, `clearinghouseState`, `fundingHistory`, `candleSnapshot`
- [ ] WebSocket subscribe to trades/l2book/candles — **deferred until B0**: untestable here even mocked-end-to-end; REST covers Phase 1–2 needs
- [x] Rate-budget awareness: weight accounting (1200/min) + meta snapshot caching (proven: `test_client.py`)
- [x] Paginated history backfill (`funding_history_all`, `candles_all`) honoring the 500-element
      cap, with stuck-cursor guard (proven: `test_client.py` pagination tests, 2026-06-10)
- [ ] **Verify live** against testnet once B0 cleared (`scripts/check_testnet.py` ready to run)

### 0.5 Tests (Phase 0)
- [x] Unit tests: config loader, redaction, client request shaping + rate budget (13 tests)
- [x] Connectivity test marked `@pytest.mark.live` (skipped unless `--run-live`)
- [x] `.venv/bin/pytest` green — 43 passed, 1 skipped (live)

**Phase 0 review (2026-06-10):** Code-complete and unit-proven. Gate NOT fully
passed: live testnet fetch blocked on B0 (env returns 403 for HL hosts). WS
client deliberately deferred rather than committed untested. Run
`scripts/check_testnet.py` + `pytest --run-live` immediately after allowlisting.

---

## Phase 1 — Backtest harness

**Goal:** deterministic event-driven backtester with realistic fees + slippage.
**Gate:** reproduces a known trivial strategy's PnL correctly + covered by tests.

### 1.1 Data layer
- [x] `data/loader.py`: OHLCV + funding via `ccxt` (Binance) with on-disk parquet cache
      _(code + offline tests; live fetch path unexercised until B0 — loader is cache/fixture-first)_
- [x] Deterministic, timezone-aware, gap-checked candles (`check_gaps`; proven: `test_loader.py`); symbol map documented in module
- [x] Fixture dataset committed — **deviation:** synthetic seeded data (`scripts/make_fixture.py`),
      not a real slice, since all data hosts are blocked (B0). Regeneration is byte-deterministic
      (proven: `test_fixture_is_deterministic`). Swap in a real slice when network opens.

### 1.2 Cost model (Hyperliquid-faithful)
- [x] `backtest/costs.py`: taker/maker fees, slippage (fills never at mid), hourly funding accrual
      with HL sign convention (long pays positive funding; proven: `test_costs.py`)
- [x] Config-driven params; HL base-tier source documented in module docstring (taker 4.5bps / maker 1.5bps)

### 1.3 Event-driven engine
- [x] `backtest/engine.py`: bar-by-bar loop; no look-ahead enforced INSIDE the engine
      (decision at close t → fill at open t+1)
- [x] `backtest/portfolio.py`: cash, position, avg entry, equity curve, realized/unrealized PnL
- [x] Order types: market + protective stop (intrabar trigger); partial-fill-aware Trade record
- [x] Deterministic given same inputs (proven: `test_determinism_identical_runs`)
- [x] Risk controls: max-drawdown kill switch (flatten + stay flat; proven in tests)

### 1.4 Metrics & reporting
- [x] `backtest/metrics.py`: total/CAGR, Sharpe, max DD, win rate, expectancy, turnover, fees paid
      (hand-computed cases proven: `test_metrics.py`)
- [x] Equity curve + trade log CSV output (`BacktestResult.to_csv`, `run_backtest.py --out`)

### 1.5 Validation (the gate)
- [x] **Buy-and-hold** sanity: matches hand-computed return exactly (no-cost case)
- [x] **Always-long with fees**: reproduces analytic PnL incl. fee + slippage; funding accrual analytic case
- [x] No-look-ahead test: signal on a price spike captures nothing; one bar earlier captures it fully
- [x] Determinism test: identical runs → identical equity curve + trade log
- [x] All tests green: `43 passed, 1 skipped` (live) in 0.6s

**Phase 1 review (2026-06-10):** Gate PASSED on offline evidence — every checked
item has a named test. Caveat carried forward: cost model validated against
documented HL schedule, not live fills; recalibrate slippage from real fills in
Phase 3 paper trading.

---

## Phase 2 — Signals & allocator

**Goal:** first two candidate edges as code, combined by the single deterministic allocator.
**Edge thesis (from 2026-06-10 session):** (a) funding-extreme mean reversion — fade
crowded positioning when hourly funding hits rolling-percentile extremes; (b) time-series
momentum gated by a slow regime filter. Anti-correlated bleed profiles; combined book
vol-targeted. HL on-chain positioning/liquidation data is the Phase 3+ signal candidate.

**Gate:** signals + allocator unit-proven (done) **and** validated on real data with
walk-forward + held-out recent period (blocked on B0).

### 2.1 Signal framework
- [x] `signals/base.py`: Signal ABC — target exposure in [-1,1] at t from data ≤ t only;
      engine adds the execution delay so no-look-ahead holds end to end
- [x] Bounded-output validation in base class (proven: `test_bounded`)

### 2.2 Time-series momentum (`signals/momentum.py`)
- [x] Lookback-return sign gated by slow-MA regime agreement; flat on disagreement
      (proven: `test_signals.py::TestMomentum` — trends, disagreement, warmup)

### 2.3 Funding mean reversion (`signals/funding_mr.py`)
- [x] Rolling percentile rank of hourly funding; enter beyond `enter_pct`, hysteresis
      exit at `exit_pct` (proven: `TestFundingMR` — fade rich funding, long deep negative, warmup)

### 2.4 Allocator (`allocator/allocator.py`)
- [x] Weighted signal combination, clipped to [-1,1]
- [x] Vol targeting (EWMA realized vol → leverage), hard `max_leverage` cap, flat during warmup
      (proven: `test_allocator.py`)
- [x] Kill switch placement decision: lives in engine (needs live equity), leverage discipline in allocator

### 2.5 Runner & evidence
- [x] `scripts/run_backtest.py`: per-signal + combined metrics table, CSV outputs, loud
      synthetic-data warning. Synthetic smoke run: both single signals hit the 25% kill
      switch; vol-targeted combination did not (risk layering works; NOT edge evidence)

### 2.6 Real-data validation — **blocked on B0**
- [ ] Pull 3+ years Binance 1h OHLCV + funding for BTC, ETH via loader; real HL funding via
      `funding_history_all` (paginated; HL history starts ~2023)
- [ ] Re-run both signals + combined with default params (no tuning before split discipline)
- [ ] `funding_mr` variant A — **OI confirmation**: require open-interest percentile to confirm
      crowding (via `metaAndAssetCtxs` snapshots / `activeAssetCtx` stream) before fading a
      funding extreme; compare vs. baseline on identical splits
- [ ] `funding_mr` variant B — **HL-vs-CEX funding spread**: use (HL funding − Binance funding)
      as the percentile input to isolate HL-specific crowding from market-wide carry;
      compare vs. baseline on identical splits
- [ ] Walk-forward protocol: tune only on train windows; hold out most recent 6–12 months untouched
- [ ] Sensitivity: ±50% on lookback/window/percentile params — edge must survive, not sit on a peak
- [ ] Decision: promote/kill each signal (and variant); record in Phase 2 review with numbers

**Phase 2 review section:** _(fill after real-data validation)_

---

## Repo structure (as built; config moved inside the package)

```
algo-/
├── README.md
├── pyproject.toml
├── requirements.txt / requirements-dev.txt
├── .env.example / .gitignore / .pre-commit-config.yaml / .secrets.baseline
├── src/hl_trader/
│   ├── config.py           # typed settings (pydantic-settings), testnet default
│   ├── logging_setup.py    # structlog JSON + redaction
│   ├── exchange/           # hyperliquid_client.py (read-only Info; WS + Exchange in Phase 3)
│   ├── data/               # ccxt loader + parquet cache + gap checks
│   ├── backtest/           # engine, costs, portfolio, metrics
│   ├── signals/            # base, momentum (tsmom), funding_mr
│   └── allocator/          # the single deterministic risk/allocator
│       └── (execution/ arrives in Phase 3: order diffing/reconciliation)
├── scripts/                # check_testnet.py, run_backtest.py, make_fixture.py
├── tests/
│   ├── conftest.py         # --run-live gating, fixtures
│   ├── unit/               # 43 tests
│   └── fixtures/           # btc_synth_1h.csv (synthetic, regenerable)
├── logs/                   # gitignored
└── tasks/
    ├── todo.md
    └── lessons.md
```

---

## Key technical decisions (resolved 2026-06-10)

1. **Secret-scan tool:** `detect-secrets` — adopted (`.pre-commit-config.yaml` + `.secrets.baseline`).
2. **Settings library:** `pydantic-settings` — adopted (`config.py`).
3. **Backtest timeframe(s):** 1h primary; regime context via slow rolling windows on the same 1h series (no separate 1d feed needed yet).
4. **Initial universe:** BTC (+ETH ready in symbol maps); validation universe expands with real data.
5. **Dependency manager (was OQ2):** plain `pip` + pinned `requirements.txt` — adopted.

## Open questions

- **OQ1:** Once allowlisted, do you want me to provision the **testnet agent wallet key** (you create it on Hyperliquid and put it in `.env`), or should Phase 0 connectivity rely only on public read-only Info endpoints until you're ready to share a key? _(Still open — not needed until Phase 3; everything so far is read-only.)_
- **OQ3 (new):** When B0 clears, preferred real-data depth for §2.6 — 3y (proposed) or max available?

---

## Notes / lessons
- See `tasks/lessons.md` (reviewed at start of each session).
