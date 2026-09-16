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
    """
    ema = ema_series(candles, config.EMA_PERIOD)
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
