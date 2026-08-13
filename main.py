import os
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
        requests.post(url, data={'chat_id': config.CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}, files={'photo': image_bio}, timeout=10)
    except Exception as e:
        print(f"Telegram Photo Error: {e}")

def send_telegram_msg(text):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": config.CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

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

def run_signal_dispatch():
    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]

    rotation_list = config.CRYPTO_ROTATION if is_weekend else config.FX_ROTATION
    idx = now.hour % len(rotation_list)
    item = rotation_list[idx]

    price, decimals, signal_type, atr, conviction = market_engine.fetch_live_market_data(item)
    pair = item["name"]
    asset_type = item["type"]
    session_name = market_engine.get_market_session(asset_type == "CRYPTO")
    date_str = now.strftime("%d %b %Y | %H:%M UTC")
    fmt = f".{decimals}f"

    # Evaluate existing open trades first
    tracker.check_open_trades({pair: price})

    # Tightened Scalping Multipliers for Early TP Hits
    entry = price
    entry_low = entry - (0.10 * atr)
    entry_high = entry + (0.10 * atr)

    if signal_type == "BUY":
        sl = entry - (1.00 * atr)
        tp1 = entry + (0.35 * atr)
        tp2 = entry + (0.70 * atr)
        tp3 = entry + (1.20 * atr)
        tp4 = entry + (1.80 * atr)
    else:
        sl = entry + (1.00 * atr)
        tp1 = entry - (0.35 * atr)
        tp2 = entry - (0.70 * atr)
        tp3 = entry - (1.20 * atr)
        tp4 = entry - (1.80 * atr)

    # Save Trade
    trades = tracker.load_trades()
    trades.append({
        "pair": pair, "signal_type": signal_type, "entry": entry,
        "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "sl": sl,
        "tp1_hit": False, "status": "OPEN", "timestamp": date_str
    })
    tracker.save_trades(trades)

    card = image_generator.generate_signal_card(pair, signal_type, session_text=session_name, is_update=False)

    caption = (
        f"👑 *JAYFX PREMIUM SIGNALS*\n"
        f"🌐 *Session:* `{session_name}` | `{conviction}`\n"
        f"🕒 *Date & Time:* `{date_str}`\n\n"
        f"📊 *Asset:* `{pair}`\n"
        f"📈 *Direction:* `{signal_type}`\n"
        f"🎯 *Entry Zone:* `{entry_low:{fmt}} - {entry_high:{fmt}}`\n"
        f"⚖️ *Risk:Reward Ratio:* `1:1.8 (TP4 Max)`\n\n"
        f"✅ *Take Profit 1:* `{tp1:{fmt}}`\n"
        f"✅ *Take Profit 2:* `{tp2:{fmt}}`\n"
        f"✅ *Take Profit 3:* `{tp3:{fmt}}`\n"
        f"✅ *Take Profit 4:* `{tp4:{fmt}}`\n\n"
        f"🛑 *Stop Loss:* `{sl:{fmt}}`\n\n"
        f"⚠️ _Trade Responsibly. Proper risk management is required._"
    )

    send_telegram_photo(caption, card)

if __name__ == "__main__":
    action = os.getenv("ACTION_TYPE", "signal").lower()
    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]

    if action == "prealert":
        run_prealert()
    elif action == "news":
        news_engine.run_news_dispatch(is_weekend=is_weekend)
    else:
        run_signal_dispatch()
