import os
import requests
import config

def fetch_live_market_data(item):
    symbol = item["symbol"]
    decimals = item["decimals"]
    
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize=30&apikey={config.TWELVE_DATA_API_KEY}"
    
    try:
        res = requests.get(url, timeout=10).json()
        if "values" not in res:
            print(f"Error fetching data for {symbol}: {res.get('message', 'Unknown Error')}")
            return None, decimals, "BUY", 0.001, "Medium"

        values = res["values"]
        current_price = float(values[0]["close"])
        
        # Calculate 14-period ATR for dynamic volatility estimation
        tr_list = []
        closes = [float(v["close"]) for v in values]
        
        for i in range(len(values) - 1):
            high = float(values[i]["high"])
            low = float(values[i]["low"])
            prev_close = float(values[i+1]["close"])
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            tr_list.append(tr)
            
        atr = sum(tr_list[:14]) / 14 if len(tr_list) >= 14 else tr_list[0]
        
        # Trend Filter: 20-period SMA
        sma_20 = sum(closes[:20]) / 20 if len(closes) >= 20 else current_price
        
        if current_price >= sma_20:
            signal_type = "BUY"
            conviction = "High"
        else:
            signal_type = "SELL"
            conviction = "High"

        return current_price, decimals, signal_type, atr, conviction

    except Exception as e:
        print(f"Market Engine Exception ({symbol}): {e}")
        return None, decimals, "BUY", 0.001, "Medium"

def get_market_session(is_crypto=False):
    if is_crypto:
        return "24/7 CRYPTO MARKET"
    return "GLOBAL MARKET SESSION"
