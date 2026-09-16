"""
One-off diagnostic: prints the real distribution of wick_pct (wick as % of
candle range) and range/ATR ratio across live BTCUSD 15m history, so
WICK_MAX_PCT and MIN_RANGE_ATR_MULT in .env can be set from actual data
instead of guesswork.

Usage: python diagnose_candles.py [--days 180]
"""
import argparse
import statistics

import backtest
import config
import strategy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=180)
    args = ap.parse_args()

    candles = backtest.fetch_live(args.days)
    atr = strategy.atr_series(candles, config.ATR_PERIOD)

    wick_pcts = []
    range_atr_ratios = []
    for c, a in zip(candles, atr):
        rng = c.high - c.low
        if rng <= 0:
            continue
        upper = c.high - max(c.open, c.close)
        lower = min(c.open, c.close) - c.low
        wick_pcts.append((upper + lower) / rng)
        if a is not None and a > 0:
            range_atr_ratios.append(rng / a)

    def pct(data, p):
        data = sorted(data)
        idx = int(len(data) * p)
        return data[min(idx, len(data) - 1)]

    print(f"\n{len(candles)} candles analyzed\n")
    print("wick_pct distribution (wick as % of candle range):")
    print(f"  median: {statistics.median(wick_pcts):.2f}")
    for p in (0.25, 0.5, 0.6, 0.7, 0.8, 0.9):
        print(f"  {int(p*100)}th percentile: {pct(wick_pcts, p):.2f}")

    print("\nrange/ATR distribution (candle range vs recent volatility):")
    print(f"  median: {statistics.median(range_atr_ratios):.2f}")
    for p in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        print(f"  {int(p*100)}th percentile: {pct(range_atr_ratios, p):.2f}")

    print(
        f"\nCurrent config: WICK_MAX_PCT={config.WICK_MAX_PCT}, "
        f"MIN_RANGE_ATR_MULT={config.MIN_RANGE_ATR_MULT}\n"
        "Pick WICK_MAX_PCT around the 60-70th percentile of wick_pct (keeps the\n"
        "cleanest ~30-40% of candles) and MIN_RANGE_ATR_MULT around the\n"
        "20-30th percentile of range/ATR (drops only the smallest, noisiest bars)."
    )


if __name__ == "__main__":
    main()
