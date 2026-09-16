import os
from dotenv import load_dotenv

load_dotenv()


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


def _float(name, default):
    return float(os.environ.get(name, default))


def _int(name, default):
    return int(os.environ.get(name, default))


API_KEY = os.environ.get("DELTA_API_KEY", "")
API_SECRET = os.environ.get("DELTA_API_SECRET", "")
BASE_URL = os.environ.get("DELTA_BASE_URL", "https://api.india.delta.exchange")

SYMBOL = os.environ.get("SYMBOL", "BTCUSD")
RESOLUTION = os.environ.get("RESOLUTION", "15m")
EMA_PERIOD = _int("EMA_PERIOD", 20)
TREND_CONFIRM_BARS = _int("TREND_CONFIRM_BARS", 3)
PIVOT_LOOKBACK = _int("PIVOT_LOOKBACK", 2)

ATR_PERIOD = _int("ATR_PERIOD", 14)
WICK_MAX_PCT = _float("WICK_MAX_PCT", 0.20)
MIN_RANGE_ATR_MULT = _float("MIN_RANGE_ATR_MULT", 0.5)

RISK_PCT = _float("RISK_PCT", 0.02)
RR_TARGET = _float("RR_TARGET", 3)
BREAKEVEN_TRIGGER_R = _float("BREAKEVEN_TRIGGER_R", 0.5)
LEVERAGE = _int("LEVERAGE", 3)

REVIEW_INTERVAL_SECONDS = _int("REVIEW_INTERVAL_SECONDS", 600)
POLL_INTERVAL_SECONDS = _int("POLL_INTERVAL_SECONDS", 60)

DRY_RUN = _bool("DRY_RUN", True)

STATE_FILE = os.environ.get("STATE_FILE", "state.json")
LOG_FILE = os.environ.get("LOG_FILE", "bot.log")

RESOLUTION_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "1d": 86400,
}
