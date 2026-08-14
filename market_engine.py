import os
import requests
import config

def fetch_live_market_data(item):
    symbol = item["symbol"]
    decimals = item["decimals"]
    
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=15min&outputsize=30&apikey={config.TWELVE_DATA_API_KEY}"
    
    try:
        res = requests.get(url, timeout=12).json()
        
        if "values" in res and len(res["values"]) > 0:
            values = res["values"]
            current_price = float(values[0]["close"])
            
            # Calculate 14-period True Range / ATR
            tr_list = []
            closes = [float(v["close"]) for v in values]
            
            for i in range(len(values) - 1):
                high = float(values[i]["high"])
                low = float(values[i]["low"])
                prev_close = float(values[i+1]["close"])
                tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                tr_list.append(tr)
                
            atr = sum(tr_list[:14]) / 14 if len(tr_list) >= 14 else tr_list[0]
            
            # Trend confirmation (20-period SMA)
            sma_20 = sum(closes[:20]) / 20 if len(closes) >= 20 else current_price
            signal_type = "BUY" if current_price >= sma_20 else "SELL"
            
            return current_price, decimals, signal_type, atr, "High"
        else:
            error_msg = res.get("message", "No values returned from Twelve Data")
            print(f"[Twelve Data Error] Symbol: {symbol} | Response: {error_msg}")
            
    except Exception as e:
        print(f"[Market Engine Exception] Symbol: {symbol} | Error: {e}")

    # Return None safely if request failed so main script can handle cleanly
    return None, decimals, "BUY", None, "Medium"

def get_market_session(is_crypto=False):
    if is_crypto:
        return "24/7 CRYPTO MARKET"
    return "GLOBAL MARKET SESSION"
