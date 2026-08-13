import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY")

FX_ROTATION = [
    {"name": "EUR/USD", "symbol": "EUR/USD", "type": "FX"},
    {"name": "GBP/USD", "symbol": "GBP/USD", "type": "FX"},
    {"name": "USD/JPY", "symbol": "USD/JPY", "type": "FX"},
    {"name": "AUD/USD", "symbol": "AUD/USD", "type": "FX"},
    {"name": "USD/CAD", "symbol": "USD/CAD", "type": "FX"},
    {"name": "USD/CHF", "symbol": "USD/CHF", "type": "FX"}
]

CRYPTO_ROTATION = [
    {"name": "BTC/USD", "symbol": "BTC/USD", "type": "CRYPTO"},
    {"name": "ETH/USD", "symbol": "ETH/USD", "type": "CRYPTO"}
]
