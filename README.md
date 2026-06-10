# hl-trader — Hyperliquid multi-signal trading system

Phased build of an automated trading system for Hyperliquid perps.
Current status: **Phase 0 (scaffold) and Phase 1 (backtest harness) complete;
Phase 2 (signals + allocator) implemented, awaiting real-data validation**
(see `tasks/todo.md` for gates and evidence).

## Safety model

- **Testnet by default.** Mainnet requires `HL_TRADER_NETWORK=mainnet` explicitly.
- **Agent wallet only.** The only key this system ever touches is a Hyperliquid
  *agent* (API) wallet key, which cannot withdraw funds. The master/withdrawal
  key must never leave the Hyperliquid UI. `.env` is gitignored; pre-commit runs
  `detect-secrets`; the structlog pipeline redacts key-shaped strings and
  secret-named fields before anything reaches a sink.
- **Phases 0–2 are read-only.** No code path places orders yet (Phase 3).
- **Risk discipline lives in code:** the allocator vol-targets exposure and caps
  leverage; the engine enforces protective stops and a max-drawdown kill switch.

## Setup

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip install -e .
cp .env.example .env   # fill in only what the current phase needs
```

## Run

```bash
.venv/bin/pytest                              # full offline suite
.venv/bin/python scripts/run_backtest.py      # strategies on the synthetic fixture
.venv/bin/python scripts/check_testnet.py     # Phase 0 live gate (needs network allowlist)
.venv/bin/pytest --run-live                   # includes live connectivity tests
```

`scripts/run_backtest.py --data <file> --out output/` runs on real data once the
loader has been pointed at allowlisted endpoints, and writes equity curves and
trade logs for inspection.

## Layout

```
src/hl_trader/
├── config.py                  # typed env settings, testnet default
├── logging_setup.py           # structlog JSON + secret redaction
├── exchange/hyperliquid_client.py  # read-only Info client, rate-budgeted
├── data/loader.py             # ccxt OHLCV/funding + parquet cache + gap checks
├── backtest/                  # engine, costs, portfolio, metrics
├── signals/                   # tsmom, funding_mr (Phase 2)
└── allocator/                 # the single deterministic risk sizer
scripts/                       # check_testnet, run_backtest, make_fixture
tests/                         # unit suite + committed synthetic fixture
tasks/                         # todo.md (phase gates), lessons.md
```

## Known constraints

- **Blocker B0:** this dev environment cannot reach `api.hyperliquid.xyz`,
  Binance, or the HL S3 archive (403 from network policy). Everything network-
  facing is built and unit-tested against recorded/stubbed responses; live
  verification scripts are ready to run the moment hosts are allowlisted.
- The committed fixture (`tests/fixtures/btc_synth_1h.csv`) is **synthetic**
  (seeded, regenerable via `scripts/make_fixture.py`). It validates mechanics,
  never edge. No strategy goes near real money before real-data backtests,
  walk-forward validation, and a testnet paper-trading period.
