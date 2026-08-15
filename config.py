import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

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
