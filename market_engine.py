import os
import json
import time
import requests
from datetime import datetime, timezone

TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
CACHE_FILE = "atr_cache.json"

def get_cached_atr(symbol):
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
            if symbol in cache:
                data = cache[symbol]
                # Cache ATR for 2 hours (7200 seconds) to save API credits
                if time.time() - data['timestamp'] < 7200:
                    return data['atr']
        except Exception:
            pass
    return None

def save_cached_atr(symbol, atr):
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                cache = json.load(f)
        except Exception:
            pass
    cache[symbol] = {'atr': atr, 'timestamp': time.time()}
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass

def fetch_live_market_data(item):
    symbol = item["symbol"]
    
    if item.get("type") == "CRYPTO" or "XAU" in symbol:
        decimals = 2
    elif "JPY" in symbol:
        decimals = 3
    else:
        decimals = 5

    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]

    if is_weekend and item.get("type") != "CRYPTO":
        symbol = "BTC/USD"
        decimals = 2

    # 1. Fetch Live Price strictly from API (Costs 1 Credit)
    price_url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVE_DATA_API_KEY}"
    try:
        p_res = requests.get(price_url, timeout=10).json()
        if "price" not in p_res:
            print(f"Price API error for {symbol}: {p_res}")
            return None, decimals, "BUY", None, "LOW"
        price = round(float(p_res["price"]), decimals)
    except Exception as e:
        print(f"Price Fetch Error ({symbol}): {e}")
        return None, decimals, "BUY", None, "LOW"

    # 2. Fetch 14-period ATR (Checks Cache First!)
    atr = get_cached_atr(symbol)
    if atr is None:
        atr_url = f"https://api.twelvedata.com/atr?symbol={symbol}&interval=15min&time_period=14&apikey={TWELVE_DATA_API_KEY}"
        try:
            a_res = requests.get(atr_url, timeout=10).json()
            if "values" in a_res and len(a_res["values"]) > 0:
                atr = float(a_res["values"][0]["atr"])
                save_cached_atr(symbol, atr)
            else:
                atr = price * 0.003
        except Exception as e:
            print(f"ATR Fetch Error ({symbol}): {e}")
            atr = price * 0.003
    
    signal_type = item.get("default_direction", "SELL")
    conviction = "HIGH"

    return price, decimals, signal_type, atr, conviction

def get_market_session(is_crypto=False):
    if is_crypto:
        return "24/7 CRYPTO MARKET"
    
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 8:
        return "ASIAN SESSION"
    elif 8 <= hour < 13:
        return "LONDON SESSION"
    else:
        return "NEW YORK SESSION"
