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
- **2026-06-10 — Synthetic fixture discipline.** The committed fixture is
  seeded synthetic data; every artifact that touches it (script output, README)
  must say loudly that results on it are mechanics checks, not edge evidence.
  On the synthetic run both single strategies hit the 25% kill switch while the
  vol-targeted combination didn't — a good sanity demo that the risk layering
  works, and a reminder that single-signal books are fragile.
