from dataclasses import dataclass
from typing import List, Optional

import config


@dataclass
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float


def parse_candles(raw: List[dict]) -> List[Candle]:
    """Delta returns candles newest-first; normalize to oldest-first."""
    candles = [
        Candle(
            time=int(c["time"]),
            open=float(c["open"]),
            high=float(c["high"]),
            low=float(c["low"]),
            close=float(c["close"]),
        )
        for c in raw
    ]
    candles.sort(key=lambda c: c.time)
    return candles


def ema_series(candles: List[Candle], period: int) -> List[Optional[float]]:
    """EMA aligned index-for-index with candles. First `period-1` entries are None."""
    closes = [c.close for c in candles]
    out: List[Optional[float]] = [None] * len(closes)
    if len(closes) < period:
        return out
    k = 2 / (period + 1)
    sma = sum(closes[:period]) / period
    out[period - 1] = sma
    prev = sma
    for i in range(period, len(closes)):
        prev = closes[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def atr_series(candles: List[Candle], period: int) -> List[Optional[float]]:
    """Wilder's ATR aligned index-for-index with candles. First `period` entries are None."""
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n <= period:
        return out
    trs = []
    for i in range(1, n):
        c, prev = candles[i], candles[i - 1]
        tr = max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        trs.append(tr)
    atr = sum(trs[:period]) / period
    out[period] = atr
    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i + 1] = atr
    return out


def candle_quality_ok(candle: Candle, atr_value: Optional[float]) -> bool:
    """Rejects candles with excessive wicks (chop/indecision) or that are too
    small relative to recent volatility (insignificant, low-conviction bars)."""
    rng = candle.high - candle.low
    if rng <= 0:
        return False
    upper = candle.high - max(candle.open, candle.close)
    lower = min(candle.open, candle.close) - candle.low
    wick_pct = (upper + lower) / rng
    if wick_pct > config.WICK_MAX_PCT:
        return False
    if atr_value is not None and rng < config.MIN_RANGE_ATR_MULT * atr_value:
        return False
    return True


@dataclass
class Signal:
    side: str  # "long" or "short"
    entry: float
    stop_loss: float
    target: float
    retest_candle_time: int


def detect_retest_signal(candles: List[Candle]) -> Optional[Signal]:
    """
    Trend-continuation retest of the EMA on the most recently CLOSED candle.

    Long: prior TREND_CONFIRM_BARS candles closed above EMA (uptrend intact),
    then the latest closed candle's low touches/pierces the EMA but closes
    back above it (rejection) -> enter long on that close.
    Short is the mirror image.

    To cut down on false signals from choppy/indecisive price action, the
    retest candle AND all trend-confirmation candles must pass
    candle_quality_ok: wicks no more than WICK_MAX_PCT of the candle's
    range, and a range at least MIN_RANGE_ATR_MULT x the current ATR (not
    a tiny, insignificant bar).
    """
    ema = ema_series(candles, config.EMA_PERIOD)
    atr = atr_series(candles, config.ATR_PERIOD)
    n = len(candles)
    need = config.TREND_CONFIRM_BARS + 1
    if n < need or ema[-1] is None:
        return None

    retest = candles[-1]
    retest_ema = ema[-1]
    confirm = candles[-(config.TREND_CONFIRM_BARS + 1):-1]
    confirm_ema = ema[-(config.TREND_CONFIRM_BARS + 1):-1]
    if any(e is None for e in confirm_ema):
        return None

    quality_candles = candles[-(config.TREND_CONFIRM_BARS + 1):]
    quality_atr = atr[-(config.TREND_CONFIRM_BARS + 1):]
    if not all(candle_quality_ok(c, a) for c, a in zip(quality_candles, quality_atr)):
        return None

    uptrend = all(c.close > e for c, e in zip(confirm, confirm_ema))
    downtrend = all(c.close < e for c, e in zip(confirm, confirm_ema))

    if uptrend and retest.low <= retest_ema and retest.close > retest_ema:
        buffer = retest_ema * 0.0005
        sl = retest.low - buffer
        entry = retest.close
        risk = entry - sl
        if risk <= 0:
            return None
        target = entry + config.RR_TARGET * risk
        return Signal("long", entry, sl, target, retest.time)

    if downtrend and retest.high >= retest_ema and retest.close < retest_ema:
        buffer = retest_ema * 0.0005
        sl = retest.high + buffer
        entry = retest.close
        risk = sl - entry
        if risk <= 0:
            return None
        target = entry - config.RR_TARGET * risk
        return Signal("short", entry, sl, target, retest.time)

    return None


def latest_confirmed_pivot_low(candles: List[Candle], lookback: int) -> Optional[float]:
    """Most recent fractal low: candle[i].low is the min among i-lookback..i+lookback,
    only counting pivots whose right-side window has fully closed."""
    n = len(candles)
    last_confirmable = n - 1 - lookback
    for i in range(last_confirmable, lookback - 1, -1):
        window = candles[i - lookback:i + lookback + 1]
        if candles[i].low == min(c.low for c in window):
            return candles[i].low
    return None


def latest_confirmed_pivot_high(candles: List[Candle], lookback: int) -> Optional[float]:
    n = len(candles)
    last_confirmable = n - 1 - lookback
    for i in range(last_confirmable, lookback - 1, -1):
        window = candles[i - lookback:i + lookback + 1]
        if candles[i].high == max(c.high for c in window):
            return candles[i].high
    return None
