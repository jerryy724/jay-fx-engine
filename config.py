import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ==========================================
# TWELVE DATA API KEYS (with fallback)
# ==========================================
# Primary key. Add a second key as a GitHub Actions secret named
# TWELVE_DATA_API_KEY_2 to get automatic fallback when the primary
# key hits its rate limit (this happens most often on weekends).
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")
TWELVE_DATA_API_KEY_2 = os.getenv("TWELVE_DATA_API_KEY_2")

# Every module should use data_client.twelvedata_get(...) instead of
# calling requests.get() directly — it walks this list until one key works.
TWELVE_DATA_KEYS = [k for k in [TWELVE_DATA_API_KEY, TWELVE_DATA_API_KEY_2] if k]

FX_ROTATION = [
    {"name": "EUR/USD", "symbol": "EUR/USD", "type": "FX", "default_direction": "BUY"},
    {"name": "GBP/USD", "symbol": "GBP/USD", "type": "FX", "default_direction": "SELL"},
    {"name": "USD/JPY", "symbol": "USD/JPY", "type": "FX", "default_direction": "BUY"},
    {"name": "AUD/USD", "symbol": "AUD/USD", "type": "FX", "default_direction": "SELL"},
    {"name": "USD/CAD", "symbol": "USD/CAD", "type": "FX", "default_direction": "BUY"},
    {"name": "USD/CHF", "symbol": "USD/CHF", "type": "FX", "default_direction": "SELL"}
]

CRYPTO_ROTATION = [
    {"name": "BTC/USD", "symbol": "BTC/USD", "type": "CRYPTO", "default_direction": "SELL"},
    {"name": "ETH/USD", "symbol": "ETH/USD", "type": "CRYPTO", "default_direction": "BUY"}
]

# ==========================================
# STRATEGY PARAMETERS
# ==========================================
ATR_PERIOD = 14
EMA_PERIOD = 50
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# If True, a signal where RSI is extended past the overbought/oversold
# threshold (trend and momentum agree, but momentum is stretched) is
# skipped instead of posted as a Standard Setup. Off by default so your
# posting cadence doesn't change — flip to True if you want the engine
# to hold back the riskiest setups automatically.
SKIP_EXTENDED_RSI_SETUPS = False

# ==========================================
# CHANNEL QUIET HOURS (UTC)
# ==========================================
QUIET_HOUR_START = 22  # channel closes for new signals at 22:00 UTC
QUIET_HOUR_END = 24    # channel reopens at 00:00 UTC
