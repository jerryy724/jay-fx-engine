import os
import sys
import json
import requests
from datetime import datetime, timezone
import config
import market_engine
import image_generator
import news_engine
import prealerts
import tracker

def send_telegram_photo(caption, image_bio):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendPhoto"
        res = requests.post(
            url, 
            data={'chat_id': config.CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}, 
            files={'photo': image_bio}, 
            timeout=12
        )
        print(f"Telegram Photo Dispatch Status: {res.status_code}")
    except Exception as e:
        print(f"Telegram Photo Dispatch Error: {e}")

def send_telegram_msg(text):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": config.CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Text Error: {e}")

# ==========================================
# 1. HOURLY PRE-ALERT JOB
# ==========================================
def run_prealert():
    now = datetime.now(timezone.utc)
    hour = now.hour
    is_weekend = now.weekday() in [5, 6]

    rotation_list = config.CRYPTO_ROTATION if is_weekend else config.FX_ROTATION
    idx = hour % len(rotation_list)
    pair = rotation_list[idx]["name"]

    template = prealerts.PREALERT_TEMPLATES[hour % len(prealerts.PREALERT_TEMPLATES)]
    msg = template.format(pair=pair)
    send_telegram_msg(msg)

# ==========================================
# 2. STANDALONE TRACKER JOB
# ==========================================
def run_tracker_only():
    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]
    rotation_list = config.CRYPTO_ROTATION if is_weekend else config.FX_ROTATION
    
    price_map = {}
    for item in rotation_list:
        try:
            price, _, _, _, _ = market_engine.fetch_live_market_data(item)
            if price is not None:
                price_map[item["name"]] = price
        except Exception as e:
            print(f"Error fetching tracker price for {item['name']}: {e}")
            
    if price_map:
        try:
            tracker.check_open_trades(price_map)
        except Exception as e:
            print(f"Tracker Execution Error: {e}")

# ==========================================
# 3. MAIN SIGNAL DISPATCH JOB
# ==========================================
def run_signal_dispatch():
    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]

    rotation_list = config.CRYPTO_ROTATION if is_weekend else config.FX_ROTATION
    idx = now.hour % len(rotation_list)
    item = rotation_list[idx]

    # Fetch live price strictly from Twelve Data
    price, decimals, signal_type, atr, conviction = market_engine.fetch_live_market_data(item)

    if price is None or atr is None:
        error_msg = f"⚠️ *Execution Error*: Could not retrieve market data from Twelve Data for `{item['name']}`."
        print(error_msg)
        send_telegram_msg(error_msg)
        return

    pair = item["name"]
    asset_type = item["type"]
    session_name = market_engine.get_market_session(asset_type == "CRYPTO")
    date_str = now.strftime("%d %b %Y | %H:%M UTC")
    fmt = f".{decimals}f"

    # Safely evaluate existing open trades
    try:
        tracker.check_open_trades({pair: price})
    except Exception as e:
        print(f"Non-fatal tracker error: {e}")

    # Scalping parameters for rapid TP hits
    entry = price
    entry_low = entry - (0.02 * atr)
    entry_high = entry + (0.02 * atr)

    if signal_type == "BUY":
        sl = entry - (1.80 * atr)
        tp1 = entry + (0.30 * atr)
        tp2 = entry + (0.70 * atr)
        tp3 = entry + (1.20 * atr)
        tp4 = entry + (1.80 * atr)
    else:
        sl = entry + (1.80 * atr)
        tp1 = entry - (0.30 * atr)
        tp2 = entry - (0.70 * atr)
        tp3 = entry - (1.20 * atr)
        tp4 = entry - (1.80 * atr)

    # Format numeric values
    entry_low_str = f"{entry_low:{fmt}}"
    entry_high_str = f"{entry_high:{fmt}}"
    sl_str = f"{sl:{fmt}}"
    tp1_str = f"{tp1:{fmt}}"
    tp2_str = f"{tp2:{fmt}}"
    tp3_str = f"{tp3:{fmt}}"
    tp4_str = f"{tp4:{fmt}}"

    caption = (
        f"👑 *JAYFX PREMIUM SIGNALS*\n"
        f"🌐 *Session:* {session_name} | 🔥 *High Conviction*\n"
        f"🕒 *Date & Time:* {date_str}\n\n"
        f"📊 *Asset:* `{pair}`\n"
        f"📈 *Direction:* *{signal_type}*\n"
        f"🎯 *Entry Zone:* `{entry_low_str} - {entry_high_str}`\n"
        f"⚖️ *Risk:Reward Ratio:* 1:1.8 (TP4 Max)\n\n"
        f"✅ *Take Profit 1:* `{tp1_str}`\n"
        f"✅ *Take Profit 2:* `{tp2_str}`\n"
        f"✅ *Take Profit 3:* `{tp3_str}`\n"
        f"✅ *Take Profit 4:* `{tp4_str}`\n\n"
        f"🛑 *Stop Loss:* `{sl_str}`\n\n"
        f"⚠️ _Trade Responsibly. Proper risk management is required._"
    )

    image_bio = image_generator.generate_signal_card(pair, signal_type, session_text=session_name, is_update=False)
    send_telegram_photo(caption, image_bio)

    try:
        tracker.log_new_trade(pair, signal_type, entry, sl, [tp1, tp2, tp3, tp4])
    except Exception as e:
        print(f"Non-fatal trade log error: {e}")

# ==========================================
# 4. MARKET NEWS DISPATCH JOB
# ==========================================
def run_news_dispatch():
    try:
        news_engine.run_news_briefing()
    except Exception as e:
        print(f"News Briefing Error: {e}")

# ==========================================
# ENTRY POINT ROUTER
# ==========================================
if __name__ == "__main__":
    action = ""

    if len(sys.argv) > 1 and sys.argv[1].strip():
        action = sys.argv[1].lower().strip()
    else:
        action = os.getenv("ACTION_TYPE", "").lower().strip()

    print(f"Executing Action: '{action}'")

    # Full mapped dispatch routes
    if action in ["signal", "engine", "engine_trigger"]:
        run_signal_dispatch()
    elif action in ["prealert", "pre-alert"]:
        run_prealert()
    elif action in ["tracker", "watch", "order_tracker"]:
        run_tracker_only()
    elif action in ["news", "market_news"]:
        run_news_dispatch()
    else:
        print(f"Action '{action}' unmapped or empty. Defaulting to signal dispatch.")
        run_signal_dispatch()
