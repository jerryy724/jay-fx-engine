import json
import os
import requests
from datetime import datetime, timezone
import config

TRADES_FILE = "trades.json"

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_trades(trades):
    with open(TRADES_FILE, 'w') as f:
        json.dump(trades, f, indent=2)

def calculate_pips(pair, entry, exit_price, signal_type):
    pip_multiplier = 100.0 if "JPY" in pair else (1.0 if ("BTC" in pair or "ETH" in pair) else 10000.0)
    return round((exit_price - entry) * pip_multiplier if signal_type == "BUY" else (entry - exit_price) * pip_multiplier, 1)

def send_telegram_msg(text):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": config.CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

def check_open_trades(price_map):
    trades = load_trades()
    if not trades: return

    now_str = datetime.now(timezone.utc).strftime("%d %b %Y | %H:%M UTC")
    updated_trades = []

    for trade in trades:
        if trade["status"] != "OPEN":
            updated_trades.append(trade)
            continue

        pair = trade["pair"]
        curr_price = price_map.get(pair)
        if not curr_price:
            updated_trades.append(trade)
            continue

        is_buy = (trade["signal_type"] == "BUY")
        entry = trade["entry"]
        sl = trade["sl"]

        # Stop Loss / Breakeven Hit
        if (curr_price <= sl if is_buy else curr_price >= sl):
            trade["status"] = "CLOSED_SL"
            pips = calculate_pips(pair, entry, sl, trade["signal_type"])
            pips_str = "0.0 pips (Breakeven)" if trade["tp1_hit"] else f"{pips} pips"
            title = "🛡️ TRADE UPDATE: BREAKEVEN HIT" if trade["tp1_hit"] else "🚨 TRADE UPDATE: STOP LOSS HIT"
            
            msg = f"*{title}*\n\n📌 *Pair:* `{pair}`\n🕒 *Hit Time:* `{now_str}`\n📊 *Pips:* `{pips_str}`"
            send_telegram_msg(msg)
            updated_trades.append(trade)
            continue

        # TP1 Hit -> Shift Stop Loss to Breakeven
        if (curr_price >= trade["tp1"] if is_buy else curr_price <= trade["tp1"]) and not trade["tp1_hit"]:
            trade["tp1_hit"] = True
            trade["sl"] = entry # Move SL to Breakeven
            pips = calculate_pips(pair, entry, trade["tp1"], trade["signal_type"])
            msg = (
                f"⚡ *TRADE UPDATE: TAKE PROFIT 1 HIT* 🎯\n"
                f"🛡️ *Breakeven Guard:* Stop Loss moved to Entry (`{entry}`).\n\n"
                f"📌 *Pair:* `{pair}`\n📊 *Pips:* `+{pips} pips`"
            )
            send_telegram_msg(msg)

        updated_trades.append(trade)

    save_trades(updated_trades)
