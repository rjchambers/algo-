# Adaptive Multi-Strategy Systematic Trading System — Design

> A professional, asset-class-agnostic systematic trading framework: diversified
> return streams, regime-aware allocation, and capital-protective risk management.
> Built on the only things that survive honest out-of-sample testing —
> **diversification, trend persistence, carry, and disciplined risk** — not on a
> magic indicator.

## What this is (and what it honestly is not)

This is the managed-futures / CTA model, adapted to run on anything with volume and
an API (crypto perps, equity index futures, FX, commodities). It is the approach
behind funds like AQR, Man AHL, and Winton.

- **Realistic target:** portfolio Sharpe **~1.0–1.3**, max drawdown ~10–15%,
  low correlation to buy-and-hold. (A single crypto trend sleeve in our own tests
  ran Sharpe ~0.78; representative multi-market trend systems run ~1.16; AQR
  multi-strategy ~1.0.¹)
- **It is NOT** a strategy that "wins every trade" or "consistently profits on any
  pair." No such thing exists. This system has losing months and losing assets;
  its edge is *positive expectancy with controlled risk, diversified so the whole
  is steadier than any part.*
- Evidence base: see `tasks/todo.md` (Phase 2 review). On 3y real BTC/ETH/SOL,
  every single-indicator/oscillator/MTF-leveraged strategy we tested loses after
  costs; only diversified, vol-managed, long-biased trend showed robust positive
  risk-adjusted return. This design generalises that one real finding.

## The core principle: stack uncorrelated return streams

> "Combining four uncorrelated return sources roughly doubles the portfolio
> Sharpe." — the diversification "holy grail."¹

Sharpe of an equal-risk blend of *n* uncorrelated streams each with Sharpe *s* is
*s·√n*. Two streams at 0.6 → 0.85; four → 1.2. So the engineering goal is to
assemble several **genuinely uncorrelated, individually-positive** streams and
risk-weight them. The streams:

| Stream | Thesis | Status in repo |
|---|---|---|
| **Trend (TSMOM)** | momentum persists; ride it long/flat, multi-horizon | ✅ built, Sharpe ~0.78 basket |
| **Cross-sectional momentum** | long strongest / short weakest asset; market-neutral | 🔬 prototype (`multi_strategy.py`) |
| **Carry** | earn funding/roll yield, trend-gated; market-neutral form needs spot+perp | ⏳ design (Phase 3, needs spot leg) |
| **Defensive / crisis alpha** | trend is naturally long vol; add explicit tail hedge in stress regimes | ⏳ design |
| **Mean-reversion (range regimes only)** | fade extremes when regime filter says "no trend" | ⏳ design |

Streams must be **gated by regime** so we are not running a mean-reversion book in a
strong trend (that is exactly how our funding_mr signal lost).

## Architecture (layers)

```
            ┌──────────────────────────────────────────────────────┐
   DATA     │  Adapter layer: any venue with OHLCV + funding + API  │
            │  (HL perps today; add CEX/FX/futures via one adapter) │
            └──────────────────────────────────────────────────────┘
                                   │ normalised bars + funding + OI
            ┌──────────────────────────────────────────────────────┐
  REGIME    │  Regime classifier: trend / range / crisis            │
            │  (vol level, vol-of-vol, trend strength/ADX, breadth) │
            └──────────────────────────────────────────────────────┘
                                   │ regime label per asset + market
            ┌──────────────────────────────────────────────────────┐
 STRATEGIES │  Independent signal modules -> target exposure [-1,1]  │
            │  trend | xs-momentum | carry | mean-rev | defensive   │
            └──────────────────────────────────────────────────────┘
                                   │ per-stream, per-asset targets
            ┌──────────────────────────────────────────────────────┐
 ALLOCATOR  │  Risk allocation: inverse-vol/risk-parity across       │
            │  streams AND assets; correlation-aware; portfolio      │
            │  vol target; regime weights the streams                │
            └──────────────────────────────────────────────────────┘
                                   │ desired portfolio (leverage capped)
            ┌──────────────────────────────────────────────────────┐
PROTECTION  │  Self-protection: graduated de-risking on drawdown,    │
            │  per-asset & gross/net caps, volatility circuit-breaker,│
            │  funding-cost guard, stale-data/oracle-divergence halt │
            └──────────────────────────────────────────────────────┘
                                   │ final orders
            ┌──────────────────────────────────────────────────────┐
 EXECUTION  │  Maker-preferential (fees are the #1 killer), order    │
            │  diffing/reconciliation, idempotent cancels, slippage  │
            │  control, partial-fill aware                            │
            └──────────────────────────────────────────────────────┘
```

## "Go with the flow" = regime-aware trend, not prediction

The system never predicts tops/bottoms. It measures the current regime and aligns:
- **Trending up:** long via TSMOM, scaled by trend strength.
- **Trending down:** flat or short (asset-dependent; crypto skews long-bias).
- **Ranging (no trend):** trend sleeve flattens; small mean-reversion sleeve may
  fade extremes; mostly sit out — capital preservation.
- **Crisis (vol spike / correlations →1):** de-risk hard, raise cash, optionally
  tail hedge. Trend-following's "crisis alpha" comes from being short/flat into
  sustained declines.

## "Protect itself" = layered risk, graduated not binary

1. **Volatility targeting** — size so each asset/stream contributes equal risk to a
   fixed portfolio vol target (e.g. 12–15% annual). Auto-cuts size when vol rises.
2. **Graduated drawdown control** — de-lever progressively (e.g. −5% DD → 0.75x,
   −10% → 0.5x, −15% → 0.25x) instead of one hard kill, with a **re-entry rule**
   (our current kill switch has none — a documented flaw to fix).
3. **Caps** — per-asset max weight, gross & net leverage caps, correlation-adjusted
   (don't let 5 "different" longs be one big beta bet).
4. **Circuit breakers** — halt on vol-of-vol spikes, oracle/index divergence, stale
   data, or funding beyond a sane band.
5. **Cost guard** — no-trade band + maker-first execution; reject signals whose
   expected edge < expected cost (the lesson from the MTF leveraged test, which
   paid ~30% of capital in fees).

## Asset-class agnostic by construction

Every layer operates on normalised inputs (returns, vol, funding/carry, OI). To add
a market you implement one **adapter** (auth + fetch OHLCV/funding + place/cancel
order). The strategy, regime, allocator, and risk layers are unchanged. Today:
Hyperliquid perps. Tomorrow: any venue with volume and an API key.

## Honest expectations & marketing posture

What is genuinely marketable here is **process, not promises**: a diversified,
risk-managed, transparent, regime-aware system with audited out-of-sample testing
and hard capital-protection rules. Marketed honestly: "uncorrelated-to-HODL,
risk-targeted, ~Sharpe 1 objective, drawdowns capped, works on any liquid market."
Anyone marketing guaranteed or "consistent" profits is selling a blow-up.

## Build sequence (gated — no real money until proven)

1. **Stream library** — trend (done), cross-sectional momentum (prototype), then
   carry & defensive. Each must clear §2.6 gates (walk-forward, held-out, ±50%
   sensitivity) before joining the blend.
2. **Risk allocator v2** — risk-parity across streams+assets, correlation-aware,
   portfolio vol target, graduated de-risk + re-entry.
3. **Multi-venue adapter** — generalise the data/exec interface.
4. **Phase 3 execution** — signed orders (HL SDK), maker-first, reconciliation;
   requires the user-provisioned agent wallet.
5. **Testnet paper trading** — sustained run, reconcile vs backtest, recalibrate
   slippage/funding.
6. **Probationary live** — minimal capital, hard caps, monitored.

---
¹ Sources: Man Group, "A Trend Following Deep Dive"; Artur Sepp, "The Science and
Practice of Trend-following Systems"; AQR, "Uncorrelated Assets" / multi-strategy
materials. Cited in the session research log; figures are industry context, not
promises about this system.
