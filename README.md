# Delta Exchange 20-EMA Retest Bot

Trades BTCUSD perpetual futures on Delta India based on a 20-EMA retest on
the 15m timeframe, with swing-based stop-loss, fixed R:R target, and a
structure-based trailing stop reviewed every 10 minutes.

## Strategy rules (as implemented)

- **Trend**: last `TREND_CONFIRM_BARS` (default 3) closed 15m candles all
  close above the 20 EMA (uptrend) or all below it (downtrend).
- **Retest entry**: the next closed candle's low touches/pierces the EMA
  but closes back above it (uptrend) -> enter **long** at that close.
  Mirror image for downtrend -> **short**. Entry fires on the retest
  candle's own close — it does not wait for a breakout confirmation on the
  following candle. Adjust `detect_retest_signal` in `strategy.py` if you
  want that extra confirmation instead.
- **Stop-loss**: just beyond the retest candle's low/high (small buffer).
- **Target**: `RR_TARGET` (default 3) times the initial risk (1:3 R:R).
- **Position size**: risk `RISK_PCT` (default 2%) of account equity per
  trade, sized from the SL distance.
- **Trailing**: every `REVIEW_INTERVAL_SECONDS` (default 600s/10min):
  once profit reaches `BREAKEVEN_TRIGGER_R` (default 0.5R), SL moves to
  breakeven. After that, SL trails behind the latest confirmed swing
  low/high (a 2-bar fractal pivot), only ever tightening, never loosening.
- Only one open position at a time.

## Known limitations / before you go live

1. **Field names not verified live.** This bot was written in a sandbox
   with no network access to delta.exchange, so exact JSON field names for
   `get_products()` / `get_all_wallet_balances()` responses (product_id,
   tick_size, contract_value, settling asset symbol) are based on
   documentation and community examples, not a live call. **Run
   `python selfcheck.py` first** (with real keys, `DRY_RUN=true` is fine)
   and compare its output against the field names used in `delta_api.py`
   and `bot.py`. Fix any mismatches before disabling `DRY_RUN`.
2. **No true OCO/bracket order.** SL and target are placed as two
   independent orders, not an exchange-native bracket, so there's a small
   race-condition window where both could fill (e.g. on a fast gap). The
   bot cancels the leftover order once it detects the position is flat,
   polling every `POLL_INTERVAL_SECONDS` (60s default), but this isn't
   instant. Consider migrating to `place_bracket_order` once you've
   confirmed its exact request schema from Delta's dashboard/support
   (the docs site wasn't reachable from the sandbox that wrote this code).
3. **Always test with `DRY_RUN=true` first**, and ideally point
   `DELTA_BASE_URL` at Delta's testnet before ever using live keys:
   `https://cdn-ind.testnet.deltaex.org`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your real API key/secret directly on the server —
# never paste them into a chat session.
```

Run the field-name check:
```bash
python selfcheck.py
```

Dry run (no real orders):
```bash
python bot.py
```
Watch `bot.log` / stdout across a few full 15m cycles and confirm the
signals, sizing, and trailing look right before flipping `DRY_RUN=false`.

## Deploying on the droplet (168.144.120.73)

This has to be done from the droplet console or an SSH session you open
yourself — it can't be done from this chat.

```bash
sudo mkdir -p /opt/delta-ema-bot
sudo useradd -r -s /usr/sbin/nologin deltabot 2>/dev/null || true
# copy this project's files into /opt/delta-ema-bot (scp, git clone, or paste)
cd /opt/delta-ema-bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit .env with real keys, chmod 600 .env
sudo chown -R deltabot:deltabot /opt/delta-ema-bot

sudo cp deploy/delta-ema-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now delta-ema-bot
sudo systemctl status delta-ema-bot
journalctl -u delta-ema-bot -f
```
