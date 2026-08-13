import requests
import time
from datetime import datetime, timezone
import config

def get_precision_and_price(raw_price_str):
    try:
        price_val = float(raw_price_str)
        decimals = len(str(raw_price_str).split('.')[1]) if '.' in str(raw_price_str) else 2
        return price_val, min(max(decimals, 2), 5)
    except:
        return float(raw_price_str), 5

def fetch_live_market_data(item):
    symbol = item["symbol"]
    try:
        url_ts = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1h&outputsize=30&apikey={config.TWELVE_DATA_API_KEY}"
        res = requests.get(url_ts, timeout=6)
        if res.status_code == 429:
            time.sleep(5)
            res = requests.get(url_ts, timeout=6)

        res_ts = res.json()
        if "values" in res_ts and len(res_ts["values"]) >= 20:
            values = res_ts["values"]
            raw_p = values[0]["close"]
            price, decimals = get_precision_and_price(raw_p)

            # ATR Calculation
            tr_list = [max(float(values[i]["high"]) - float(values[i]["low"]), 
                          abs(float(values[i]["high"]) - float(values[i+1]["close"])), 
                          abs(float(values[i]["low"]) - float(values[i+1]["close"]))) for i in range(14)]
            atr = sum(tr_list) / 14.0

            # Trend & RSI Calculations
            closes = [float(v["close"]) for v in values[:20]]
            ma_short = sum(closes[:5]) / 5.0
            ma_long = sum(closes[:20]) / 20.0
            trend = "BUY" if ma_short >= ma_long else "SELL"

            gains = [max(float(values[i]["close"]) - float(values[i+1]["close"]), 0) for i in range(14)]
            losses = [abs(min(float(values[i]["close"]) - float(values[i+1]["close"]), 0)) for i in range(14)]
            avg_gain = sum(gains) / 14.0
            avg_loss = sum(losses) / 14.0
            rs = (avg_gain / avg_loss) if avg_loss != 0 else 1
            rsi = 100 - (100 / (1 + rs))

            conviction = "🔥 High Conviction" if ((trend == "BUY" and rsi >= 50) or (trend == "SELL" and rsi < 50)) else "⚡ Standard Setup"
            return price, decimals, trend, atr, conviction
    except Exception as e:
        print(f"Market Engine Error: {e}")

    defaults = {
        "EUR/USD": (1.08520, 5, 0.0015), "GBP/USD": (1.27450, 5, 0.0020), 
        "USD/JPY": (154.250, 3, 0.350), "AUD/USD": (0.65420, 5, 0.0012), 
        "USD/CAD": (1.36450, 5, 0.0015), "USD/CHF": (0.88450, 5, 0.0014),
        "BTC/USD": (65000.00, 2, 450.0), "ETH/USD": (1920.00, 2, 25.0)
    }
    p, d, default_atr = defaults.get(symbol, (1.00000, 5, 0.0015))
    return p, d, "BUY", default_atr, "⚡ Standard Setup"

def get_market_session(is_crypto):
    if is_crypto: return "CRYPTO 24/7 MARKET"
    hour = datetime.now(timezone.utc).hour
    if 0 <= hour < 7: return "ASIAN SESSION"
    elif 7 <= hour < 13: return "LONDON SESSION"
    elif 13 <= hour < 21: return "NEW YORK SESSION"
    else: return "OVERNIGHT SESSION"
