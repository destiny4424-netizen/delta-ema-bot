"""
Backtest the 20-EMA retest strategy (strategy.py) against historical 15m
OHLC data supplied as a CSV — no network access required.

CSV: a header row containing some form of a time/date column (unix seconds,
milliseconds, or an ISO/parseable datetime string) plus open, high, low,
close columns (case-insensitive, any order; volume ignored if present).

Usage:
    python backtest.py path/to/candles.csv [--equity 100000] [--fee-bps 10]
    python backtest.py --live --days 180 [--equity 100000] [--fee-bps 10]

--live pulls real history straight from Delta's public candle endpoint
(no API key needed — it's a public market-data call, auth=False). This
only works where the machine actually has internet access to
api.india.delta.exchange (e.g. the droplet), not from a network-restricted
sandbox.

Simplifications (read before trusting the numbers):
- No live tick data, so intrabar SL/TP resolution is approximate: if a bar's
  low reaches SL AND its high reaches target in the same bar, SL is assumed
  to fill first (worst case). Real fills may differ.
- The "review every 10 min" trailing rule collapses to "review on every new
  15m bar close" here, since that's the finest granularity 15m data gives.
- fee_bps is a round-trip cost in basis points of notional, deducted from
  each trade's R (default 10bps = 0.1%, i.e. ~0.05% per side taker fee).
- No funding-rate cost is modeled for perpetuals held across funding times.
"""
import argparse
import csv
import statistics
import sys
import time
from datetime import datetime, timezone

import config
import strategy


def _parse_time(raw: str) -> int:
    raw = raw.strip()
    try:
        val = float(raw)
        if val > 10_000_000_000:  # milliseconds
            val /= 1000
        return int(val)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Could not parse time value: {raw!r}")


def load_csv(path: str):
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower(): c for c in reader.fieldnames}
        time_col = next((cols[k] for k in ("time", "date", "datetime", "timestamp") if k in cols), None)
        if time_col is None or not all(k in cols for k in ("open", "high", "low", "close")):
            raise ValueError(f"CSV must have time/date + open/high/low/close columns; got {reader.fieldnames}")
        raw = []
        for row in reader:
            raw.append({
                "time": _parse_time(row[time_col]),
                "open": row[cols["open"]],
                "high": row[cols["high"]],
                "low": row[cols["low"]],
                "close": row[cols["close"]],
            })
    return strategy.parse_candles(raw)


def fetch_live(days: int):
    import delta_api

    client = delta_api.make_client()
    step = config.RESOLUTION_SECONDS[config.RESOLUTION]
    now = int(time.time())
    range_start = now - days * 86400
    chunk_bars = 1000  # stay well under typical per-request candle caps
    chunk_span = chunk_bars * step

    all_raw = {}
    end = now
    while end > range_start:
        start = max(range_start, end - chunk_span)
        resp = client.get_candles(symbol=config.SYMBOL, resolution=config.RESOLUTION, start=start, end=end, auth=False)
        batch = resp.get("result", resp) if isinstance(resp, dict) else resp
        if not batch:
            break
        for c in batch:
            all_raw[int(c["time"])] = c
        end = start - step
        time.sleep(0.3)  # be polite to the public endpoint

    raw = sorted(all_raw.values(), key=lambda c: int(c["time"]))
    print(f"Fetched {len(raw)} candles spanning ~{days} days for {config.SYMBOL} {config.RESOLUTION}")
    return strategy.parse_candles(raw)


def simulate(candles, fee_bps: float):
    """Walk-forward bar replay. Returns list of trade dicts."""
    trades = []
    position = None  # dict: side, entry, sl, initial_sl, target, breakeven_done, entry_idx

    min_history = config.EMA_PERIOD + config.TREND_CONFIRM_BARS + 1
    for i in range(min_history, len(candles)):
        window = candles[: i + 1]  # candles[0..i], i.e. up to and including this closed bar
        bar = candles[i]

        if position is not None:
            side = position["side"]
            risk = abs(position["entry"] - position["initial_sl"])

            hit_sl = bar.low <= position["sl"] if side == "long" else bar.high >= position["sl"]
            hit_tp = bar.high >= position["target"] if side == "long" else bar.low <= position["target"]

            exit_price = None
            if hit_sl and hit_tp:
                exit_price = position["sl"]  # conservative: assume SL fills first
            elif hit_sl:
                exit_price = position["sl"]
            elif hit_tp:
                exit_price = position["target"]

            if exit_price is not None:
                raw_r = (exit_price - position["entry"]) / risk if side == "long" else (position["entry"] - exit_price) / risk
                r_after_fees = raw_r - (fee_bps / 10000) * (position["entry"] / risk)
                trades.append({
                    "side": side,
                    "entry_time": candles[position["entry_idx"]].time,
                    "exit_time": bar.time,
                    "entry": position["entry"],
                    "exit": exit_price,
                    "r_multiple": r_after_fees,
                    "bars_held": i - position["entry_idx"],
                })
                position = None
                continue

            # trailing review (collapsed to "every closed bar" — see module docstring)
            profit_r = (bar.close - position["entry"]) / risk if side == "long" else (position["entry"] - bar.close) / risk
            if not position["breakeven_done"] and profit_r >= config.BREAKEVEN_TRIGGER_R:
                position["sl"] = position["entry"]
                position["breakeven_done"] = True
            elif position["breakeven_done"]:
                if side == "long":
                    pivot = strategy.latest_confirmed_pivot_low(window, config.PIVOT_LOOKBACK)
                    if pivot is not None and pivot > position["sl"]:
                        position["sl"] = pivot
                else:
                    pivot = strategy.latest_confirmed_pivot_high(window, config.PIVOT_LOOKBACK)
                    if pivot is not None and pivot < position["sl"]:
                        position["sl"] = pivot
            continue

        signal = strategy.detect_retest_signal(window)
        if signal:
            position = {
                "side": signal.side,
                "entry": signal.entry,
                "sl": signal.stop_loss,
                "initial_sl": signal.stop_loss,
                "target": signal.target,
                "breakeven_done": False,
                "entry_idx": i,
            }

    return trades


def summarize(trades, starting_equity: float):
    if not trades:
        print("No trades triggered on this data with current config thresholds.")
        return

    r_values = [t["r_multiple"] for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]

    equity = starting_equity
    peak = equity
    max_dd_pct = 0.0
    equity_curve = [equity]
    for t in trades:
        equity *= (1 + config.RISK_PCT * t["r_multiple"])
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0
        max_dd_pct = max(max_dd_pct, dd)
        equity_curve.append(equity)

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    print(f"Trades:        {len(trades)}")
    print(f"Win rate:      {len(wins) / len(trades):.1%}")
    print(f"Avg R:         {statistics.mean(r_values):+.2f}")
    print(f"Total R:       {sum(r_values):+.2f}")
    print(f"Profit factor: {(gross_win / gross_loss) if gross_loss else float('inf'):.2f}")
    print(f"Max drawdown:  {max_dd_pct:.1%}  (at {config.RISK_PCT:.0%} risk/trade)")
    print(f"Equity: {starting_equity:,.2f} -> {equity:,.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", nargs="?", default=None)
    ap.add_argument("--live", action="store_true", help="fetch real history from Delta's public API instead of a CSV")
    ap.add_argument("--days", type=int, default=180, help="days of history to fetch with --live")
    ap.add_argument("--equity", type=float, default=100000)
    ap.add_argument("--fee-bps", type=float, default=10.0)
    ap.add_argument("--trades-csv", default=None, help="optional path to write per-trade log")
    args = ap.parse_args()

    if args.live:
        candles = fetch_live(args.days)
    elif args.csv_path:
        candles = load_csv(args.csv_path)
        print(f"Loaded {len(candles)} candles from {args.csv_path}")
    else:
        ap.error("provide a csv_path or pass --live")

    if len(candles) < 200:
        print("WARNING: fewer than 200 bars — results won't be statistically meaningful.", file=sys.stderr)

    trades = simulate(candles, args.fee_bps)
    summarize(trades, args.equity)

    if args.trades_csv and trades:
        with open(args.trades_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
            w.writeheader()
            w.writerows(trades)
        print(f"\nPer-trade log written to {args.trades_csv}")


if __name__ == "__main__":
    main()
