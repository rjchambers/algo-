# hl-trader — Hyperliquid multi-signal trading system

Phased build of an automated trading system for Hyperliquid perps.
Current status: **Phases 0–1 complete and gate-proven; Phase 2 signals validated
on 3y of real BTC/ETH data — all candidate edges KILLED (no proven edge yet).**
Live connectivity verified. **No capital should be deployed.** See
`tasks/todo.md` for the §2.6 numbers and the honest path-to-real-money roadmap.

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
├── exchange/hyperliquid_client.py  # read-only Info client, rate-budgeted, 429-backoff
├── data/loader.py             # ccxt OHLCV/funding + parquet cache + gap checks
├── data/binance_vision.py     # deep-history archive loader (OHLCV/funding/OI)
├── backtest/                  # engine, costs, portfolio, metrics
├── signals/                   # tsmom, funding_mr (+ OI-confirmed variant)
└── allocator/                 # the single deterministic risk sizer
scripts/                       # check_testnet, run_backtest, fetch_real_data, validate_phase2
tests/                         # unit suite + synthetic + real (tests/fixtures/real) fixtures
tasks/                         # todo.md (phase gates), lessons.md
```

## Real-data validation (§2.6)

```bash
.venv/bin/python scripts/fetch_real_data.py    # build tests/fixtures/real/{BTC,ETH}_1h.parquet
.venv/bin/python scripts/validate_phase2.py    # baseline + walk-forward + sensitivity + decisions
```

Data sources: deep OHLCV/funding/open-interest from the **Binance Vision archive**
(`data.binance.vision`, used because `api.binance.com` is geo-blocked here) plus
live Hyperliquid funding. Verdict (2026-06-10): **all four candidate strategies
killed** on 3y of real BTC/ETH — see `tasks/todo.md` Phase 2 review and
`output/phase2_validation/summary.json`.

## Known constraints

- **B0 (network) — resolved.** HL hosts reachable; live gate passed.
- **B1 (deep history):** CEX REST hosts are geo-blocked/off-allowlist and HL keeps
  only ~7mo of candles, so deep history for crypto majors comes from the Binance
  Vision archive. **Commodities** (GOLD/SILVER/OIL on HL HIP-3 builder dexs) and
  HYPE have too little history to validate and no reachable deep-history source.
- The legacy fixture (`tests/fixtures/btc_synth_1h.csv`) is **synthetic** (mechanics
  only). No strategy goes near real money before a *proven* real-data edge, Phase 3
  execution code, and a testnet paper-trading period.
