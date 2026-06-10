"""Classic published technical strategies, encoded with NO look-ahead.

Every function maps an OHLCV(+funding) frame to a target exposure in [-1, 1]
using only data up to and including each bar (rolling/ewm). The backtest engine
adds the t+1 execution delay, so these are look-ahead-free end to end. Plain
pandas/numpy indicators (no TA-lib) per the project's dependency decision.

These are CANDIDATES to be tested honestly, not blessed strategies. On 1h data,
"50/200-day" crossovers use day-equivalent bar counts (50d = 1200h, 200d = 4800h).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HOUR = 1
DAY = 24


# -- indicators -------------------------------------------------------------

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, min_periods=span, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    tr = pd.concat([(h - l), (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def median_price(df: pd.DataFrame) -> pd.Series:
    return (df["high"] + df["low"]) / 2


def awesome_osc(df: pd.DataFrame, fast: int = 5, slow: int = 34) -> pd.Series:
    """Bill Williams Awesome Oscillator: SMA(median,5) - SMA(median,34)."""
    m = median_price(df)
    return m.rolling(fast).mean() - m.rolling(slow).mean()


def accelerator_osc(df: pd.DataFrame, sig: int = 5) -> pd.Series:
    """Bill Williams Accelerator Oscillator: AO - SMA(AO, 5)."""
    ao = awesome_osc(df)
    return ao - ao.rolling(sig).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Average Directional Index (trend strength, non-directional)."""
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff()
    down = -l.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, min_periods=n, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, min_periods=n, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()


def stoch(df: pd.DataFrame, n: int = 14, d: int = 3) -> pd.Series:
    """Stochastic %K (0-100)."""
    low_n = df["low"].rolling(n).min()
    high_n = df["high"].rolling(n).max()
    k = 100 * (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan)
    return k.rolling(d).mean()


def _hold(entry_long: pd.Series, exit_long: pd.Series,
          entry_short: pd.Series | None = None, exit_short: pd.Series | None = None,
          index=None) -> pd.Series:
    """State machine: enter/exit long (and optionally short) on boolean events."""
    el, xl = entry_long.to_numpy(), exit_long.to_numpy()
    es = entry_short.to_numpy() if entry_short is not None else np.zeros(len(el), bool)
    xs = exit_short.to_numpy() if exit_short is not None else np.ones(len(el), bool)
    pos = np.zeros(len(el))
    cur = 0.0
    for i in range(len(el)):
        if cur == 0.0:
            if el[i]:
                cur = 1.0
            elif es[i]:
                cur = -1.0
        elif cur > 0 and xl[i]:
            cur = -1.0 if (entry_short is not None and es[i]) else 0.0
        elif cur < 0 and xs[i]:
            cur = 1.0 if el[i] else 0.0
        pos[i] = cur
    return pd.Series(pos, index=index)


# -- strategies (df -> target in [-1, 1]) -----------------------------------

def golden_cross(df: pd.DataFrame, fast: int = 50 * DAY, slow: int = 200 * DAY) -> pd.Series:
    """Classic 50/200-day SMA cross. Long above, short below (death cross)."""
    c = df["close"]
    f, s = c.rolling(fast).mean(), c.rolling(slow).mean()
    return np.sign(f - s).fillna(0.0)


def golden_cross_long(df: pd.DataFrame, fast: int = 50 * DAY, slow: int = 200 * DAY) -> pd.Series:
    """Golden cross, long/flat only (no shorting)."""
    c = df["close"]
    f, s = c.rolling(fast).mean(), c.rolling(slow).mean()
    return (f > s).astype(float).where(f.notna() & s.notna(), 0.0)


def ema_crossover(df: pd.DataFrame, fast: int = 20 * HOUR, slow: int = 50 * HOUR) -> pd.Series:
    f, s = ema(df["close"], fast), ema(df["close"], slow)
    return np.sign(f - s).fillna(0.0)


def macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.Series:
    line = ema(df["close"], fast) - ema(df["close"], slow)
    signal = line.ewm(span=sig, min_periods=sig, adjust=False).mean()
    return np.sign(line - signal).fillna(0.0)


def rsi_meanrev(df: pd.DataFrame, n: int = 14, low: float = 30, high: float = 70,
                mid: float = 50) -> pd.Series:
    """Buy oversold, sell overbought; exit at the midline (classic 30/70)."""
    r = rsi(df["close"], n)
    return _hold(
        entry_long=r < low, exit_long=r >= mid,
        entry_short=r > high, exit_short=r <= mid, index=df.index,
    ).fillna(0.0)


def bollinger_meanrev(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.Series:
    c = df["close"]
    mid = c.rolling(n).mean()
    sd = c.rolling(n).std()
    upper, lower = mid + k * sd, mid - k * sd
    return _hold(
        entry_long=c < lower, exit_long=c >= mid,
        entry_short=c > upper, exit_short=c <= mid, index=df.index,
    ).fillna(0.0)


def bollinger_breakout(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.Series:
    c = df["close"]
    mid = c.rolling(n).mean()
    sd = c.rolling(n).std()
    upper, lower = mid + k * sd, mid - k * sd
    return _hold(
        entry_long=c > upper, exit_long=c <= mid,
        entry_short=c < lower, exit_short=c >= mid, index=df.index,
    ).fillna(0.0)


def ema_bounce(df: pd.DataFrame, ema_n: int = 50, trend_n: int = 200) -> pd.Series:
    """Pullback-to-rising-EMA bounce, long-only, trend-gated.

    In an uptrend (close > EMA200), buy when price reclaims a rising EMA50 from
    below; exit when it closes back under EMA50.
    """
    c = df["close"]
    e, t = ema(c, ema_n), ema(c, trend_n)
    uptrend = c > t
    rising = e > e.shift(1)
    reclaim = (c > e) & (c.shift(1) <= e.shift(1))
    return _hold(
        entry_long=uptrend & rising & reclaim, exit_long=c < e, index=df.index,
    ).fillna(0.0)


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.Series:
    """ATR-band trend follower (long when trend up, short when down)."""
    c = df["close"]
    hl2 = (df["high"] + df["low"]) / 2
    a = atr(df, n)
    upper = (hl2 + mult * a).to_numpy()
    lower = (hl2 - mult * a).to_numpy()
    close = c.to_numpy()
    n_bars = len(close)
    fu = np.full(n_bars, np.nan)
    fl = np.full(n_bars, np.nan)
    dirn = np.zeros(n_bars)  # 1 up, -1 down
    for i in range(1, n_bars):
        if np.isnan(upper[i]):
            continue
        fu[i] = upper[i] if (np.isnan(fu[i - 1]) or upper[i] < fu[i - 1]
                             or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (np.isnan(fl[i - 1]) or lower[i] > fl[i - 1]
                             or close[i - 1] < fl[i - 1]) else fl[i - 1]
        prev = dirn[i - 1] if dirn[i - 1] != 0 else 1
        if close[i] > fu[i]:
            dirn[i] = 1
        elif close[i] < fl[i]:
            dirn[i] = -1
        else:
            dirn[i] = prev
    return pd.Series(dirn, index=df.index)


def mtf_momentum(df: pd.DataFrame, regime: int = 200 * DAY) -> pd.Series:
    """Multi-timeframe momentum convergence (look-ahead-free via bar windows).

    Agreement of short (1d), medium (4d), long (7d) momentum signs, gated by a
    slow regime MA. Long only when all agree up and price is above regime;
    short only when all agree down and below regime; else flat.
    """
    c = df["close"]
    m1 = np.sign(c.pct_change(1 * DAY))
    m4 = np.sign(c.pct_change(4 * DAY))
    m7 = np.sign(c.pct_change(7 * DAY))
    above = c > c.rolling(regime).mean()
    long = (m1 > 0) & (m4 > 0) & (m7 > 0) & above
    short = (m1 < 0) & (m4 < 0) & (m7 < 0) & (~above)
    out = pd.Series(0.0, index=c.index)
    out[long] = 1.0
    out[short] = -1.0
    return out.where(c.rolling(regime).mean().notna(), 0.0)


def awesome_oscillator(df: pd.DataFrame) -> pd.Series:
    """AO momentum: long when AO > 0, short when AO < 0."""
    return np.sign(awesome_osc(df)).fillna(0.0)


def accelerator_oscillator(df: pd.DataFrame) -> pd.Series:
    """AC momentum: long when AC > 0, short when AC < 0."""
    return np.sign(accelerator_osc(df)).fillna(0.0)


def stoch_meanrev(df: pd.DataFrame, n: int = 14, low: float = 20, high: float = 80,
                  mid: float = 50) -> pd.Series:
    k = stoch(df, n)
    return _hold(entry_long=k < low, exit_long=k >= mid,
                 entry_short=k > high, exit_short=k <= mid, index=df.index).fillna(0.0)


# -- convergence combinations (pre-specified; built around the trend result) --

def trend_ao_confirmed(df: pd.DataFrame) -> pd.Series:
    """Golden-cross trend taken only when the Awesome Oscillator agrees."""
    cross = golden_cross(df)
    ao = np.sign(awesome_osc(df)).fillna(0.0)
    return cross.where(cross == ao, 0.0)


def golden_cross_adx(df: pd.DataFrame, thresh: float = 25.0) -> pd.Series:
    """Golden-cross trend taken only in a strong trend (ADX > threshold)."""
    cross = golden_cross(df)
    strong = (adx(df) > thresh).fillna(False)
    return cross.where(strong, 0.0)


def triple_trend_confirm(df: pd.DataFrame) -> pd.Series:
    """Take a side only when 50/200 cross, Awesome Osc, AND Accelerator Osc agree."""
    cross = golden_cross(df)
    ao = np.sign(awesome_osc(df)).fillna(0.0)
    ac = np.sign(accelerator_osc(df)).fillna(0.0)
    agree = (cross == ao) & (cross == ac) & (cross != 0)
    return cross.where(agree, 0.0)


def mtf_supertrend(df: pd.DataFrame) -> pd.Series:
    """Long/short only when multi-timeframe momentum and Supertrend agree."""
    m = mtf_momentum(df)
    st = supertrend(df)
    return m.where(m == st, 0.0)


STRATEGIES = {
    # single indicators
    "golden_cross": golden_cross,
    "golden_cross_long": golden_cross_long,
    "ema_crossover": ema_crossover,
    "macd": macd,
    "rsi_meanrev": rsi_meanrev,
    "bollinger_meanrev": bollinger_meanrev,
    "bollinger_breakout": bollinger_breakout,
    "ema_bounce": ema_bounce,
    "supertrend": supertrend,
    "mtf_momentum": mtf_momentum,
    "awesome_oscillator": awesome_oscillator,
    "accelerator_oscillator": accelerator_oscillator,
    "stoch_meanrev": stoch_meanrev,
    # convergence combinations
    "trend_ao_confirmed": trend_ao_confirmed,
    "golden_cross_adx": golden_cross_adx,
    "triple_trend_confirm": triple_trend_confirm,
    "mtf_supertrend": mtf_supertrend,
}
