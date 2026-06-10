# Lessons (reviewed at start of each session)

- **2026-06-10 — Environment drift is real.** The kickoff plan pinned Python
  3.10.20; this session's container has 3.11.15. Pin a *minimum* (`>=3.11`) in
  pyproject and record the exact tested version in requirements.txt comments
  instead of assuming the env is stable across sessions.
- **2026-06-10 — Build offline-first.** Blocker B0 (network allowlist) also
  blocks Binance and the HL S3 archive, not just HL API hosts. Everything
  network-facing must be injectable/stubable and covered by offline tests, with
  thin live-verification scripts kept separate (`check_testnet.py`,
  `pytest --run-live`). This kept all 43 tests green without any network.
- **2026-06-10 — Dropped `pandas-ta`.** It forces `numpy<2` for two indicators
  we can write in three lines of pandas. Fewer pinned-back deps, and we get
  numpy 2.x / pandas 3.x. Revisit only if a signal genuinely needs a complex
  indicator.
- **2026-06-10 (evening) — B0 cleared, but a new data wall (B1).** HL hosts now
  return 200 (live gate passed). However all CEX *REST* hosts are geo-blocked
  (`api.binance.com` → 451) or off-allowlist, and HL `candleSnapshot` only keeps
  ~7 months of 1h candles. The save: Binance's *static* archive
  `data.binance.vision` is reachable with deep history (2017+) — same data, no
  REST. Lesson: when an API is blocked, look for the vendor's bulk/archive host
  before giving up on the data.
- **2026-06-10 (evening) — Binance archive switched epoch ms→µs in 2025.** A
  multi-year concat contains both units; detecting the unit from the first row
  silently mis-parsed 2025+ rows to year ~58000, which the date-range slice then
  dropped — truncating BTC at 2024-12-31 and looking like "less history exists."
  Fix: detect per element (µs > 1e14) and normalise. Lesson: validate the *last*
  row's date, not just that the load "worked."
- **2026-06-10 (evening) — HL /info burst-limits paginated pulls (429).** ~52
  funding pages back-to-back tripped a 429 even inside our weight budget. Added
  exponential backoff + `Retry-After` in the client. Weight accounting ≠ server
  rate limit.
- **2026-06-10 (evening) — THE BIG ONE: the first two edges have no edge.** On 3y
  real BTC/ETH, TSMOM and funding-MR (and both funding-MR variants) all KILL on
  held-out + walk-forward + sensitivity. Funding-MR loses *because* it shorts
  rich-funding (crowded-long) regimes — i.e. it fades the trend in a bull market.
  Vol-targeting/kill-switch behaved correctly but can't fix negative expectancy.
  Lesson: a clean thesis + passing unit tests says nothing about edge; only honest
  out-of-sample data does. Do NOT respond by tuning these until a backtest looks
  good — that's the overfitting trap. Next edge starts from a fresh, pre-registered
  hypothesis tested on identical splits.
- **2026-06-10 — Synthetic fixture discipline.** The committed fixture is
  seeded synthetic data; every artifact that touches it (script output, README)
  must say loudly that results on it are mechanics checks, not edge evidence.
  On the synthetic run both single strategies hit the 25% kill switch while the
  vol-targeted combination didn't — a good sanity demo that the risk layering
  works, and a reminder that single-signal books are fragile.
