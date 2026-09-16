import logging
import math
import time

from delta_rest_client import round_by_tick_size

import config
import delta_api
import state
import strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(config.LOG_FILE), logging.StreamHandler()],
)
log = logging.getLogger("bot")


def compute_size(equity: float, risk_price_distance: float, contract_value: float, tick_size: float) -> int:
    risk_amount = equity * config.RISK_PCT
    per_contract_risk = risk_price_distance * contract_value
    if per_contract_risk <= 0:
        return 0
    size = math.floor(risk_amount / per_contract_risk)
    return max(size, 0)


def open_trade(client, product, signal: strategy.Signal):
    if config.DRY_RUN:
        log.info("[DRY_RUN] Would open %s: entry=%.2f sl=%.2f target=%.2f",
                  signal.side, signal.entry, signal.stop_loss, signal.target)
        return

    equity = delta_api.get_equity(client, product["settling_asset"]["symbol"])
    risk_distance = abs(signal.entry - signal.stop_loss)
    size = compute_size(equity, risk_distance, float(product["contract_value"]), float(product["tick_size"]))
    if size < 1:
        log.warning("Computed size < 1 contract (equity=%.2f, risk_distance=%.2f); skipping trade", equity, risk_distance)
        return

    product_id = product["product_id"]
    tick = float(product["tick_size"])
    entry_side = "buy" if signal.side == "long" else "sell"
    close_side = "sell" if signal.side == "long" else "buy"

    delta_api.market_order(client, product_id, entry_side, size)
    log.info("Entered %s size=%d", signal.side, size)

    sl_price = round_by_tick_size(signal.stop_loss, tick)
    tp_price = round_by_tick_size(signal.target, tick)

    sl_resp = delta_api.stop_market_order(client, product_id, close_side, size, sl_price)
    tp_resp = delta_api.limit_order(client, product_id, close_side, size, tp_price)

    trade = state.Trade(
        side=signal.side,
        product_id=product_id,
        size=size,
        entry=signal.entry,
        initial_sl=sl_price,
        current_sl=sl_price,
        target=tp_price,
        sl_order_id=sl_resp.get("result", {}).get("id"),
        tp_order_id=tp_resp.get("result", {}).get("id"),
        breakeven_done=False,
        retest_candle_time=signal.retest_candle_time,
    )
    state.save(trade)
    log.info("Trade opened and persisted: %s", trade)


def review_trade(client, product, trade: state.Trade, candles):
    tick = float(product["tick_size"])
    close_side = "sell" if trade.side == "long" else "buy"

    if delta_api.position_size(client, trade.product_id) == 0:
        log.info("Position closed (SL or target hit). Cleaning up orphan orders.")
        delta_api.cancel(client, trade.product_id, trade.sl_order_id)
        delta_api.cancel(client, trade.product_id, trade.tp_order_id)
        state.clear()
        return

    last = candles[-1]
    current_price = last.close
    risk = abs(trade.entry - trade.initial_sl)
    if risk <= 0:
        return
    profit_r = (current_price - trade.entry) / risk if trade.side == "long" else (trade.entry - current_price) / risk

    new_sl = None
    if not trade.breakeven_done and profit_r >= config.BREAKEVEN_TRIGGER_R:
        new_sl = trade.entry
        trade.breakeven_done = True
        log.info("Breakeven trigger hit (%.2fR); moving SL to entry %.2f", profit_r, trade.entry)
    elif trade.breakeven_done:
        if trade.side == "long":
            pivot = strategy.latest_confirmed_pivot_low(candles, config.PIVOT_LOOKBACK)
            if pivot is not None and pivot > trade.current_sl:
                new_sl = pivot
        else:
            pivot = strategy.latest_confirmed_pivot_high(candles, config.PIVOT_LOOKBACK)
            if pivot is not None and pivot < trade.current_sl:
                new_sl = pivot

    if new_sl is None:
        return

    new_sl = round_by_tick_size(new_sl, tick)
    if config.DRY_RUN:
        log.info("[DRY_RUN] Would trail SL %.2f -> %.2f", trade.current_sl, new_sl)
        trade.current_sl = new_sl
        state.save(trade)
        return

    delta_api.cancel(client, trade.product_id, trade.sl_order_id)
    resp = delta_api.stop_market_order(client, trade.product_id, close_side, trade.size, new_sl)
    trade.sl_order_id = resp.get("result", {}).get("id")
    trade.current_sl = new_sl
    state.save(trade)
    log.info("SL trailed to %.2f", new_sl)


def main():
    if config.DRY_RUN:
        log.warning("Running in DRY_RUN mode: no real orders will be placed.")
    else:
        log.warning("LIVE TRADING ENABLED. Real orders will be placed with real funds.")

    client = delta_api.make_client()
    product = delta_api.get_product(client, config.SYMBOL)
    if config.LEVERAGE and not config.DRY_RUN:
        client.set_leverage(product["product_id"], config.LEVERAGE)

    last_candle_time = 0
    last_review = 0.0

    while True:
        try:
            now = int(time.time())
            raw_candles = delta_api.get_candles(client, config.SYMBOL, config.RESOLUTION, 100, now)
            candles = strategy.parse_candles(raw_candles)
            if not candles:
                time.sleep(config.POLL_INTERVAL_SECONDS)
                continue

            trade = state.load()

            if trade is None:
                latest_closed = candles[-1]
                if latest_closed.time != last_candle_time:
                    last_candle_time = latest_closed.time
                    signal = strategy.detect_retest_signal(candles)
                    if signal:
                        log.info("Signal: %s entry=%.2f sl=%.2f target=%.2f",
                                 signal.side, signal.entry, signal.stop_loss, signal.target)
                        open_trade(client, product, signal)
            else:
                if time.time() - last_review >= config.REVIEW_INTERVAL_SECONDS:
                    last_review = time.time()
                    review_trade(client, product, trade, candles)

        except Exception:
            log.exception("Error in main loop; continuing after sleep")

        time.sleep(config.POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
