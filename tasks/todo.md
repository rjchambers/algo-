# Hyperliquid Multi-Signal Trading System — Task Plan

> Scope of this document: **Phases 0–2.** Later phases are intentionally
> not planned in detail (do not build orchestration ahead of proven edge — spec §6).
> Items are checkable. Mark `[x]` only when proven (test passed / log shown).
>
> **Status 2026-06-10 (evening):** Phase 0 gate **PASSED live** (B0 cleared —
> `check_testnet.py` + `pytest --run-live` green). Phase 1 complete and
> gate-proven. Phase 2 signals/allocator implemented, unit-tested, and now
> **validated on 3y of real BTC/ETH data (§2.6)** — result: **all four
> candidate strategies KILLED** (no edge survives held-out + walk-forward +
> sensitivity). 60 tests passing offline. No capital should be deployed: there
> is no proven edge yet.

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

## ✅ Resolved / ⚠️ Active blockers

- **B0 — Network allowlist — RESOLVED 2026-06-10.** `api.hyperliquid.xyz` and
  `api.hyperliquid-testnet.xyz` now return 200. Phase 0 gate passed live
  (`check_testnet.py`: 208 assets, live mids/funding; `pytest --run-live` green).
- **B1 — No deep-history CEX feed (NEW, partial).** All CEX *REST* hosts are
  geo-blocked (`api.binance.com` → 451) or outside the allowlist (Kraken/OKX/
  Bybit/… → network error), and HL's own `candleSnapshot` only retains ~7 months
  of 1h candles. Worked around for crypto majors via the reachable **Binance
  Vision static archive** (`data.binance.vision`, 2017→now) for OHLCV/funding/OI,
  plus live HL `fundingHistory` (2023-05→now). Still unresolved for **commodities**
  (HL HIP-3 perps GOLD/SILVER/OIL on builder dexs `xyz`/`flx`/`km`/…): they
  launched Dec-2025/Mar-2026 (~3–5.5 months of candles) and have no reachable
  deep-history source, so they are **not validatable yet**.

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

### 2.6 Real-data validation — **DONE 2026-06-10 (B0 cleared; see B1 workaround)**
- [x] Pull 3y 1h OHLCV + funding + OI for BTC, ETH (Binance Vision archive, since
      `api.binance.com` is geo-blocked) + real HL funding via `funding_history_all`
      (2023-06-01 → 2026-05-31, 26,303 hourly bars/asset, 100% HL-funding coverage).
      Consolidated fixtures committed under `tests/fixtures/real/`.
- [x] Re-run both signals + combined with default params (no pre-split tuning)
- [x] `funding_mr` variant A — **OI confirmation** (`FundingMROIConfirmed`): fade a
      funding extreme only when open-interest percentile also confirms crowding
- [x] `funding_mr` variant B — **HL-vs-CEX funding spread**: (HL − Binance) funding
      as the percentile input
- [x] Walk-forward (anchored grid-search train → untouched test) + held-out last 12mo
- [x] Sensitivity: ±50% on lookback/window/percentile params
- [x] Decision: **KILL all four** on both assets (numbers below)

**Phase 2 review (2026-06-10) — VERDICT: KILL ALL. No edge proven; deploy nothing.**

Evaluated as-traded (vol-targeted through the allocator, HL costs, 25% DD kill).
Promote gate (all must hold): held-out 12mo Sharpe > 0.5 AND OOS total > 0 AND
walk-forward Sharpe > 0 AND ±50% sensitivity median Sharpe > 0 AND ≥60% of the
sensitivity grid positive. Full numbers in `output/phase2_validation/summary.json`.

| Asset | Strategy | OOS total | OOS Sharpe | WF Sharpe | Sens median | Verdict |
|---|---|---|---|---|---|---|
| BTC | tsmom            | −7.6%  | −0.42 | −0.29 | −0.75 | KILL |
| BTC | funding_mr       | −20.0% | −2.23 | −0.96 | −1.84 | KILL |
| BTC | funding_mr_oi    | −21.1% | −2.69 | —     | −0.99 | KILL |
| BTC | funding_mr_spread| −0.4%  |  0.00 | −1.28 |  0.07 | KILL |
| ETH | tsmom            | +0.6%  |  0.12 |  0.75 |  0.38 | KILL (OOS<0.5) |
| ETH | funding_mr       | −12.1% | −1.51 | −0.47 | −0.50 | KILL |
| ETH | funding_mr_oi    | −8.6%  | −1.24 | —     | −0.88 | KILL |
| ETH | funding_mr_spread| −9.2%  | −0.98 | −0.79 | −1.32 | KILL |

Findings:
1. **Funding mean-reversion (and both variants) loses everywhere.** As written it
   *shorts* crowded-long (rich-funding) regimes — i.e. it systematically fades the
   trend during a 2023→2025 bull run, the textbook way to bleed. OI confirmation
   and the HL-vs-CEX spread did not rescue it. The carry it collects is dwarfed by
   adverse price moves. The thesis as implemented is wrong-signed in trends.
2. **TSMOM is the only signal with any pulse**, and only on ETH (WF Sharpe 0.75,
   67% of the sensitivity grid positive) — but its held-out OOS Sharpe is 0.12 and
   it is dead on BTC. No robust, cross-asset, out-of-sample edge → KILL.
3. **Combined book** is negative on both (−13.8% BTC, −5.5% ETH OOS): the allocator
   correctly cut drawdowns vs. single signals, but you can't vol-target your way
   out of negative-expectancy inputs.

Decision: do **not** promote any signal to Phase 3. Risk machinery (vol target,
kill switch, no-look-ahead) is validated and behaves correctly; the *edges* are
not there. Next research must start from a real, tested hypothesis — not by
tuning these until a backtest looks good (that is the overfitting trap §6 warns of).

**Exploratory follow-up (`scripts/explore_strategies.py`) — leads only, NOT validated:**
Tested buy&hold (the real benchmark), long-only trend, Donchian breakout, and
funding-carry-gated-by-trend on the same fixtures. Findings:
- **The held-out 12mo was a crypto downturn** (raw buy&hold BTC −29.6%, ETH −20.6%),
  so every long-biased strategy lost OOS. One 12-month hold-out is regime-specific;
  real validation needs multiple regimes (longer history / multiple held-out slices).
- **Nothing robustly beats holding.** Faint OOS pulses (carry-with-trend +2.6% BTC,
  Donchian +4.2% ETH) don't replicate across both assets or survive full-sample.
- **Kill switch never re-enters** (permanent flatten): costs ~5pp on vol-targeted
  BTC buy&hold here and sidelines for good — add a re-entry rule before deployment.
  (The larger raw-172% vs vol-targeted-44% gap is vol-targeting capping exposure by
  design, not a bug.)
None promoted. Real leads to validate next: proper multi-regime trend-following and
market-neutral funding carry — pre-registered, on BTC/ETH/SOL, gates as above.

**Classic-TA battery (`scripts/battery_backtest.py`, `signals/classic.py`) — leads only:**
Tested 17 published strategies (golden/death cross ±ADX, EMA crossover/bounce, MACD,
RSI/Bollinger/Stochastic mean-reversion, Bollinger breakout, Supertrend, multi-TF
momentum, Bill Williams Awesome/Accelerator oscillators) plus pre-specified
convergence combinations, all as-traded vs buy&hold on BTC/ETH.
- **Every oscillator and mean-reversion strategy loses after costs** (Accelerator
  Osc worst: ~770 trades, fees dominate) — matches the published literature.
- **Only `golden_cross` / `golden_cross_adx` beat buy&hold OOS on both assets**
  (positive through the downturn, ~half the drawdown). Indicator "convergence"
  combos mostly cut turnover/DD, not added alpha. No strategy cleared the
  cross-asset lead bar.
- **Full validation of the trend lead (`scripts/validate_trend.py`): KILL.** Golden
  cross — BTC OOS Sharpe 0.37 (<0.5); ETH OOS 0.56 but walk-forward −0.91 (tuned
  params lose −31% OOS). Beats buy&hold and hedges drawdowns, but is NOT a robust
  promotable standalone edge. Best use is as an anticorrelated overlay, not alpha.

**Multi-timeframe leveraged system (`scripts/mtf_system.py`) — KILL.** Confluence
of 1m/5m/15m/1h/4h trend signals (real 3y BTC 1m data, 105k 15m bars), leveraged
long/short flips, SL/TP. Every config lost 40-50% (hit the 50% kill switch) with
~$30k/$100k in taker fees. Lower timeframes + leverage amplify costs and losses;
no edge to amplify. (3-asset re-confirmation of the trend lead also KILL on
BTC/ETH/SOL — walk-forward fails on ETH/SOL.)

**Overall after testing §2.6 signals + 17 classic strategies + oscillators +
combinations + a leveraged multi-timeframe system, with full walk-forward/
sensitivity, on BTC/ETH/SOL: NO promotable edge found.** This is the honest
state; the next edge needs a genuinely different data source or structural
insight (e.g. HL-native positioning/liquidation flow, cross-sectional structure,
or a non-price signal), not more TA on OHLCV at any timeframe. Evidence:
`output/phase2_validation/{battery_BTC_ETH_SOL,trend_validation,mtf_system_BTC}.txt`.

**Commodities (GOLD/SILVER/OIL/WTICRUDE) — confirmed tradeable on HL HIP-3 builder
dexs** (`xyz:GOLD`, `xyz:SILVER`, `xyz:BRENTOIL`, `km:USOIL`, …) but with only
~3–5.5 months of candle history and no reachable deep-history source → backtests
on them are single-regime noise, not validatable (see `scripts/commodity_probe.py`).

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

- **OQ1:** Provisioning the **testnet agent wallet key** — needed before Phase 3
  paper trading. You (the human) must create the agent wallet in the Hyperliquid
  UI and place its key in `.env`; the assistant cannot and should not create it.
  _(Still open — gates Phase 3.)_
- **OQ3 — ANSWERED:** §2.6 used **3y** (2023-06 → 2026-05), the common window
  bounded by HL funding/OI start. Deeper Binance price history exists (2017+) but
  funding/OI and HL-spread inputs don't, and identical splits across signals
  matter more than raw length.
- **OQ4 (new):** Research direction now that the first two edges are dead — see
  "Path to real money" below. Needs a human decision on which hypotheses to pursue.

---

## Path to real money (honest roadmap — nothing here is "deploy tonight")

The system is **not ready for capital** and won't be after one more session: there
is no proven edge, and no order-placement code exists yet. Sequenced, gated:

1. **Find a real edge first (Phase 2 redo).** All current signals are killed.
   Candidate next hypotheses (each must clear the §2.6 gates on BTC/ETH/SOL before
   anything else): (a) **trend-following done properly** — TSMOM showed the only
   pulse; test longer-horizon breakout/Donchian with the regime filter, costs
   honestly modelled; (b) **funding carry** (the *opposite* sign of what we built:
   earn funding with a trend/vol filter rather than fade it); (c) **cross-sectional
   momentum** across the liquid majors. Pre-register params; no fitting to the
   held-out year.
2. **Phase 3 execution (read→write).** Only after an edge promotes: signed Exchange
   client via `hyperliquid-python-sdk`, order diffing/reconciliation, idempotent
   cancels, position/leverage caps enforced server-side. Requires OQ1 (agent key).
3. **Testnet paper trading.** Run the promoted strategy live on **testnet** for a
   sustained period; reconcile fills/funding vs. backtest; recalibrate slippage.
4. **Tiny real size.** Only then, mainnet with minimal capital and hard caps, for
   a probationary period, monitored.

Commodities (GOLD/SILVER/OIL on HL HIP-3 dexs) are deferred behind B1: too little
history to validate. HYPE likewise has only ~7mo of HL candles (no Binance archive).

---

## Notes / lessons
- See `tasks/lessons.md` (reviewed at start of each session).
