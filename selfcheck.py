"""
Run this once after filling in real API keys, BEFORE enabling live trading
(DRY_RUN=true is fine for this). Prints raw API responses so you can confirm
field names (product_id, tick_size, contract_value, settling asset symbol,
balance field) match what delta_api.py and bot.py assume. If anything here
doesn't match, fix the field names in delta_api.py before going live.
"""
import json
import time

import config
import delta_api

client = delta_api.make_client()

print("=== get_product(SYMBOL) ===")
product = delta_api.get_product(client, config.SYMBOL)
print(json.dumps(product, indent=2))

print("\n=== get_all_wallet_balances() raw ===")
print(json.dumps(client.get_all_wallet_balances(), indent=2))

print("\n=== get_candles sample (last 5 bars) ===")
candles = delta_api.get_candles(client, config.SYMBOL, config.RESOLUTION, 5, int(time.time()))
print(json.dumps(candles[:5] if isinstance(candles, list) else candles, indent=2))

print("\n=== get_position(product_id) ===")
print(json.dumps(client.get_position(product["product_id"]), indent=2))

print(
    "\nCheck above: product['product_id'], product['tick_size'], "
    "product['contract_value'], and the settling asset symbol used in "
    "get_all_wallet_balances(). Update delta_api.py/bot.py if names differ."
)
