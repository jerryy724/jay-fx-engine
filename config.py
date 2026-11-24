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
TWELVE_DATA_API_KEY_3 = os.getenv("TWELVE_DATA_API_KEY_3")
TWELVE_DATA_API_KEY_4 = os.getenv("TWELVE_DATA_API_KEY_4")

# Every module should use data_client.twelvedata_get(...) instead of
# calling requests.get() directly — it walks this list until one key works.
TWELVE_DATA_KEYS = [
    k for k in [
        TWELVE_DATA_API_KEY,
        TWELVE_DATA_API_KEY_2,
        TWELVE_DATA_API_KEY_3,
        TWELVE_DATA_API_KEY_4,
    ] if k
]

# Private admin chat (diagnostics, backtests, nightly reviews).
# Add the ADMIN_CHAT_ID secret in GitHub. Never the public channel.
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

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


# ==========================================
# FX v2 ENGINE SETTINGS (used by fx_engine.py and the backtest)
# ==========================================
# Spread + slippage assumption per pair, in pips (round trip, retail
# broker). These are ASSUMPTIONS. Change them to match your broker.
PAIR_SETTINGS = {
    "EUR/USD": {"pip": 0.0001, "spread_pips": 1.0, "decimals": 5},
    "GBP/USD": {"pip": 0.0001, "spread_pips": 1.4, "decimals": 5},
    "USD/JPY": {"pip": 0.01, "spread_pips": 1.2, "decimals": 3},
    "AUD/USD": {"pip": 0.0001, "spread_pips": 1.4, "decimals": 5},
    "USD/CAD": {"pip": 0.0001, "spread_pips": 1.8, "decimals": 5},
    "USD/CHF": {"pip": 0.0001, "spread_pips": 1.8, "decimals": 5},
}

FX_PAIRS = list(PAIR_SETTINGS.keys())

# Entry rules (same meaning as the Gold engine).
FX_PARAMS = {
    "trend_mode": "STRICT",   # "STRICT" or "STRUCTURE"
    "rsi_buy": 52,
    "rsi_sell": 48,
    "adx_min": 14.0,
    "momentum_min": 3,
}

# Risk caps across the whole FX book.
MAX_OPEN_PER_PAIR = 1
MAX_OPEN_TOTAL = 6
MAX_OPEN_PER_USD_SIDE = 3   # USD pairs move together, so cap one-sided USD bets
