import os
import json
import requests
import config

TRADES_FILE = "trades.json"

def load_trades():
    if not os.path.exists(TRADES_FILE):
        return []
    try:
        with open(TRADES_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {TRADES_FILE}: {e}")
        return []

def save_trades(trades):
    try:
        with open(TRADES_FILE, "w") as f:
            json.dump(trades, f, indent=4)
    except Exception as e:
        print(f"Error saving {TRADES_FILE}: {e}")

def calculate_pips(pair, entry, exit_price, direction):
    # Standard FX pairs use a 10,000 multiplier, JPY pairs use 100
    multiplier = 100 if "JPY" in pair.upper() else 10000
    if direction == "BUY":
        pips = (exit_price - entry) * multiplier
    else:
        pips = (entry - exit_price) * multiplier
    return round(pips, 1)

def log_new_trade(pair, direction, entry, sl, tps, issued_time):
    trades = load_trades()
    new_trade = {
        "pair": pair,
        "direction": direction,
        "entry": entry,
        "initial_sl": sl,
        "current_sl": sl,
        "tps": tps,
        "status": "OPEN",
        "hit_tps": [],
        "issued_time": issued_time
    }
    trades.append(new_trade)
    save_trades(trades)
    print(f"Logged new trade for {pair}")

def check_open_trades(price_map=None):
    trades = load_trades()
    open_trades = [t for t in trades if t.get("status") == "OPEN"]
    
    if not open_trades:
        return

    if price_map is None:
        price_map = {}

    missing_pairs = [t["pair"] for t in open_trades if t["pair"] not in price_map]
    
    if missing_pairs:
        missing_pairs = list(set(missing_pairs))
        symbols_str = ",".join(missing_pairs)
        url = f"https://api.twelvedata.com/price?symbol={symbols_str}&apikey={config.TWELVE_DATA_API_KEY}"
        try:
            res = requests.get(url, timeout=10).json()
            if len(missing_pairs) == 1:
                if "price" in res:
                    price_map[missing_pairs[0]] = float(res["price"])
            else:
                for sym in missing_pairs:
                    if sym in res and "price" in res[sym]:
                        price_map[sym] = float(res[sym]["price"])
        except Exception as e:
            print(f"Tracker Batch Price Error: {e}")

    updated = False
    for trade in trades:
        if trade.get("status") != "OPEN":
            continue

        pair = trade.get("pair")
        if pair not in price_map:
            continue

        current_price = price_map[pair]
        direction = trade.get("direction")
        current_sl = trade.get("current_sl")
        initial_sl = trade.get("initial_sl")
        entry = trade.get("entry")
        tps = trade.get("tps", [])
        hit_tps = trade.get("hit_tps", [])
        issued_time = trade.get("issued_time", "Unknown")

        # Calculate exact pips at current market price
        current_pips = calculate_pips(pair, entry, current_price, direction)
        pip_prefix = "+" if current_pips > 0 else ""

        # 1. Check Stop Loss
        if (direction == "BUY" and current_price <= current_sl) or (direction == "SELL" and current_price >= current_sl):
            if current_sl == initial_sl:
                trade["status"] = "CLOSED_SL"
                msg = (f"JAY FX PREMIUM SIGNALS VIP\n"
                       f"🛑 *STOP LOSS HIT*\n\n"
                       f"📌 *Pair:* `{pair}`\n"
                       f"📉 *Exit:* `{current_price}`\n"
                       f"📅 *Issued:* `{issued_time}`\n"
                       f"💰 *Pips:* `{pip_prefix}{current_pips}`")
                send_telegram_update(msg)
            elif current_sl == entry:
                trade["status"] = "CLOSED_BREAKEVEN"
                msg = (f"JAY FX PREMIUM SIGNALS VIP\n"
                       f"🟡 *BREAKEVEN HIT*\n\n"
                       f"📌 *Pair:* `{pair}`\n"
                       f"📉 *Exit:* `{current_price}`\n"
                       f"📅 *Issued:* `{issued_time}`\n"
                       f"💰 *Pips:* `+0.0`")
                send_telegram_update(msg)
            else:
                trade["status"] = "CLOSED_PROFIT"
                msg = (f"JAY FX PREMIUM SIGNALS VIP\n"
                       f"🔒 *TRAILING STOP HIT*\n\n"
                       f"📌 *Pair:* `{pair}`\n"
                       f"📉 *Exit:* `{current_price}`\n"
                       f"📅 *Issued:* `{issued_time}`\n"
                       f"💰 *Pips:* `{pip_prefix}{current_pips}`")
                send_telegram_update(msg)
            
            updated = True
            continue

        # 2. Check Take Profits & Trailing SL
        for idx, tp in enumerate(tps, 1):
            if idx not in hit_tps:
                if (direction == "BUY" and current_price >= tp) or (direction == "SELL" and current_price <= tp):
                    hit_tps.append(idx)
                    trade["hit_tps"] = hit_tps
                    updated = True
                    
                    # Calculate locked pips based on the TP price, not slippage price
                    locked_pips = calculate_pips(pair, entry, tp, direction)
                    
                    msg_tp = (f"JAY FX PREMIUM SIGNALS VIP\n"
                              f"✅ *TAKE PROFIT {idx} HIT!*\n\n"
                              f"📌 *Pair:* `{pair}`\n"
                              f"📈 *Exit:* `{tp}`\n"
                              f"📅 *Issued:* `{issued_time}`\n"
                              f"💰 *Pips:* `+{locked_pips}`")
                    send_telegram_update(msg_tp)
                    
                    if idx == 1:
                        trade["current_sl"] = entry
                        msg_be = (f"JAY FX PREMIUM SIGNALS VIP\n"
                                  f"🛡️ *BREAKEVEN MOVED*\n\n"
                                  f"📌 *Pair:* `{pair}`\n"
                                  f"💰 *SL moved to entry:* `{entry}`\n"
                                  f"📅 *Signal:* `{issued_time}`\n"
                                  f"✅ TP1 secured — risk-free trade now!")
                        send_telegram_update(msg_be)
                    elif idx == 2:
                        trade["current_sl"] = tps[0]
                        msg_trail = (f"JAY FX PREMIUM SIGNALS VIP\n"
                                     f"🔒 *PROFIT LOCKED*\n\n"
                                     f"📌 *Pair:* `{pair}`\n"
                                     f"💰 *SL moved to TP1:* `{tps[0]}`\n"
                                     f"📅 *Signal:* `{issued_time}`\n"
                                     f"✅ TP2 secured!")
                        send_telegram_update(msg_trail)
                    elif idx == 3:
                        trade["current_sl"] = tps[1]
                        msg_trail = (f"JAY FX PREMIUM SIGNALS VIP\n"
                                     f"🔒 *PROFIT LOCKED*\n\n"
                                     f"📌 *Pair:* `{pair}`\n"
                                     f"💰 *SL moved to TP2:* `{tps[1]}`\n"
                                     f"📅 *Signal:* `{issued_time}`\n"
                                     f"✅ TP3 secured!")
                        send_telegram_update(msg_trail)

        if len(hit_tps) == len(tps):
            trade["status"] = "CLOSED_TP_MAX"
            updated = True
            msg_max = (f"JAY FX PREMIUM SIGNALS VIP\n"
                       f"👑 *FULL SEND: ALL TARGETS SMASHED!*\n\n"
                       f"📌 *Pair:* `{pair}`\n"
                       f"📅 *Issued:* `{issued_time}`")
            send_telegram_update(msg_max)

    if updated:
        save_trades(trades)

def send_telegram_update(text):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": config.CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Tracker Telegram Error: {e}")
