import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

import config


@dataclass
class Trade:
    side: str
    product_id: int
    size: int
    entry: float
    initial_sl: float
    current_sl: float
    target: float
    sl_order_id: Optional[int]
    tp_order_id: Optional[int]
    breakeven_done: bool
    retest_candle_time: int


def load() -> Optional[Trade]:
    if not os.path.exists(config.STATE_FILE):
        return None
    with open(config.STATE_FILE) as f:
        data = json.load(f)
    return Trade(**data) if data else None


def save(trade: Optional[Trade]):
    with open(config.STATE_FILE, "w") as f:
        json.dump(asdict(trade) if trade else None, f, indent=2)


def clear():
    save(None)
