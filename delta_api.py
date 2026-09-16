"""
Thin helpers around delta_rest_client. Field names for product/balance
responses are based on Delta's published API shape but were NOT verified
live from this environment (the sandbox this bot was written in has no
network path to delta.exchange or api.india.delta.exchange). Run
`python selfcheck.py` once, with real API keys, BEFORE enabling live
trading, and fix any field-name mismatches it surfaces.
"""
import logging

from delta_rest_client import DeltaRestClient, OrderType

import config

log = logging.getLogger("delta_api")


def make_client() -> DeltaRestClient:
    return DeltaRestClient(
        base_url=config.BASE_URL,
        api_key=config.API_KEY,
        api_secret=config.API_SECRET,
    )


def get_product(client: DeltaRestClient, symbol: str) -> dict:
    products = client.get_products(auth=False)
    result = products.get("result", products) if isinstance(products, dict) else products
    for p in result:
        if p.get("symbol") == symbol:
            return p
    raise RuntimeError(f"Product {symbol} not found in get_products() response")


def get_equity(client: DeltaRestClient, settling_asset_symbol: str) -> float:
    balances = client.get_all_wallet_balances()
    result = balances.get("result", balances) if isinstance(balances, dict) else balances
    for b in result:
        if b.get("asset_symbol") == settling_asset_symbol:
            return float(b.get("balance", b.get("available_balance", 0)))
    raise RuntimeError(
        f"No balance entry for asset {settling_asset_symbol}; "
        "check get_all_wallet_balances() field names via selfcheck.py"
    )


def get_candles(client: DeltaRestClient, symbol: str, resolution: str, lookback_bars: int, now_ts: int):
    step = config.RESOLUTION_SECONDS[resolution]
    start = now_ts - step * (lookback_bars + 5)
    resp = client.get_candles(symbol=symbol, resolution=resolution, start=start, end=now_ts, auth=False)
    return resp.get("result", resp) if isinstance(resp, dict) else resp


def market_order(client: DeltaRestClient, product_id: int, side: str, size: int):
    return client.place_order(
        product_id=product_id,
        size=size,
        side=side,
        order_type=OrderType.MARKET,
    )


def stop_market_order(client: DeltaRestClient, product_id: int, side: str, size: int, stop_price: float):
    return client.place_stop_order(
        product_id=product_id,
        size=size,
        side=side,
        stop_price=str(stop_price),
        order_type=OrderType.MARKET,
    )


def limit_order(client: DeltaRestClient, product_id: int, side: str, size: int, price: float):
    return client.place_order(
        product_id=product_id,
        size=size,
        side=side,
        limit_price=str(price),
        order_type=OrderType.LIMIT,
        reduce_only="true",
    )


def cancel(client: DeltaRestClient, product_id: int, order_id):
    if order_id is None:
        return
    try:
        client.cancel_order(product_id, order_id)
    except Exception as e:
        log.warning("cancel_order(%s) failed: %s", order_id, e)


def position_size(client: DeltaRestClient, product_id: int) -> float:
    resp = client.get_position(product_id)
    result = resp.get("result", resp) if isinstance(resp, dict) else resp
    if isinstance(result, list):
        result = result[0] if result else {}
    return float(result.get("size", 0))
