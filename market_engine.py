import os
import requests
from datetime import datetime, timezone
import config

# ==========================================
# LOCAL INDICATOR CALCULATIONS
# ==========================================
def calculate_atr_1h(bars, period=14):
    """Calculates ATR based on True Range across OHLC bars."""
    if len(bars) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(bars)):
        high = float(bars[i]["high"])
        low = float(bars[i]["low"])
        prev_close = float(bars[i-1]["close"])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return None
    
    recent_tr = true_ranges[-period:]
    return sum(recent_tr) / period

def calculate_4h_50_ema(bars):
    """Resamples 1h data into 4h bars and computes the 50 EMA."""
    closes_1h = [float(b["close"]) for b in bars]
    closes_4h = []
    
    # Group every 4 1-hour closes
    for i in range(3, len(closes_1h), 4):
        closes_4h.append(closes_1h[i])
        
    if len(closes_4h) < config.EMA_PERIOD:
        # Fallback if less than 200 hours of data exists
        return sum(closes_1h[-50:]) / min(len(closes_1h), 50)
    
    k = 2.0 / (config.EMA_PERIOD + 1)
    ema = sum(closes_4h[:config.EMA_PERIOD]) / float(config.EMA_PERIOD)
    
    for price in closes_4h[config.EMA_PERIOD:]:
        ema = (price * k) + (ema * (1.0 - k))
    return ema

def calculate_1h_rsi(bars, period=14):
    """Standard 14-period Relative Strength Index."""
    closes = [float(b["close"]) for b in bars]
    if len(closes) < period + 1:
        return 50.0
        
    gains = []
    losses = []
    for i in range(len(closes) - period, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))
            
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    if avg_loss == 0:
        return 100.0
        
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

# ==========================================
# MAIN DATA FETCHING & LOGIC ROUTING
# ==========================================
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

    # 1. Fetch Real-Time Live Price (Direct Ticker)
    price_url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={config.TWELVE_DATA_API_KEY}"
    try:
        p_res = requests.get(price_url, timeout=10).json()
        if "price" not in p_res:
            print(f"Price API error for {symbol}: {p_res}")
            return None, decimals, "BUY", None, "LOW"
        current_price = round(float(p_res["price"]), decimals)
    except Exception as e:
        print(f"Price Fetch Error ({symbol}): {e}")
        return None, decimals, "BUY", None, "LOW"

    # 2. Fetch Historical Time Series Data (For Indicator Math Only)
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1h&outputsize=220&apikey={config.TWELVE_DATA_API_KEY}"
    try:
        res = requests.get(url, timeout=10).json()
        if "values" not in res or len(res["values"]) == 0:
            print(f"Time series error for {symbol}: {res}")
            return None, decimals, "BUY", None, "LOW"
        
        # Twelve Data returns newest records first -> Reverse to oldest -> newest
        bars = list(reversed(res["values"]))
    except Exception as e:
        print(f"Time Series Fetch Error ({symbol}): {e}")
        return None, decimals, "BUY", None, "LOW"

    # 3. Compute Strategy Indicators Locally
    atr = calculate_atr_1h(bars, period=config.ATR_PERIOD)
    if atr is None or atr == 0:
        atr = current_price * 0.003
        
    ema_4h_50 = calculate_4h_50_ema(bars)
    rsi_1h = calculate_1h_rsi(bars, period=config.RSI_PERIOD)

    # 4. Apply Trading Rules Using Exact Real-Time Price
    if current_price > ema_4h_50:
        signal_type = "BUY"
        if rsi_1h > config.RSI_OVERBOUGHT:
            conviction = "AVOID_OVERBOUGHT"
        elif rsi_1h >= 50.0:
            conviction = "HIGH"
        else:
            conviction = "STANDARD"
    else:
        signal_type = "SELL"
        if rsi_1h < config.RSI_OVERSOLD:
            conviction = "AVOID_OVERSOLD"
        elif rsi_1h < 50.0:
            conviction = "HIGH"
        else:
            conviction = "STANDARD"

    return current_price, decimals, signal_type, atr, conviction

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
