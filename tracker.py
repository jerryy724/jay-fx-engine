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

def log_new_trade(pair, direction, entry, sl, tps):
    trades = load_trades()
    new_trade = {
        "pair": pair,
        "direction": direction,
        "entry": entry,
        "initial_sl": sl,
        "current_sl": sl,
        "tps": tps,
        "status": "OPEN",
        "hit_tps": []
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

    # Identify pairs we need prices for but don't have
    missing_pairs = [t["pair"] for t in open_trades if t["pair"] not in price_map]
    
    # Batch fetch missing prices to bypass API limits
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

        # 1. Check Stop Loss (Initial, Breakeven, or Trailed)
        if (direction == "BUY" and current_price <= current_sl) or (direction == "SELL" and current_price >= current_sl):
            if current_sl == initial_sl:
                trade["status"] = "CLOSED_SL"
                send_telegram_update(f"🛑 *TRADE CLOSED:* `{pair}` hit Stop Loss at `{current_price}`.")
            elif current_sl == entry:
                trade["status"] = "CLOSED_BREAKEVEN"
                send_telegram_update(f"🛡️ *TRADE CLOSED:* `{pair}` stopped out at Risk-Free Breakeven (`{current_price}`).")
            else:
                trade["status"] = "CLOSED_PROFIT"
                send_telegram_update(f"🔒 *TRADE CLOSED:* `{pair}` stopped out in Profit at trailed SL (`{current_price}`).")
            
            updated = True
            continue

        # 2. Check Take Profits and Apply Trailing Logic
        for idx, tp in enumerate(tps, 1):
            if idx not in hit_tps:
                if (direction == "BUY" and current_price >= tp) or (direction == "SELL" and current_price <= tp):
                    hit_tps.append(idx)
                    trade["hit_tps"] = hit_tps
                    updated = True
                    send_telegram_update(f"🎯 *TARGET HIT:* `{pair}` reached *Take Profit {idx}* at `{current_price}`!")
                    
                    # Progressive Stop Loss / Breakeven Logic
                    if idx == 1:
                        trade["current_sl"] = entry
                        send_telegram_update(f"🛡️ *RISK FREE:* `{pair}` Stop Loss moved to Entry (`{entry}`).")
                    elif idx == 2:
                        trade["current_sl"] = tps[0] # Move SL to TP1
                        send_telegram_update(f"🔒 *PROFIT LOCKED:* `{pair}` Stop Loss trailed to TP1 (`{tps[0]}`).")
                    elif idx == 3:
                        trade["current_sl"] = tps[1] # Move SL to TP2
                        send_telegram_update(f"🔒 *PROFIT LOCKED:* `{pair}` Stop Loss trailed to TP2 (`{tps[1]}`).")

        if len(hit_tps) == len(tps):
            trade["status"] = "CLOSED_TP_MAX"
            updated = True
            send_telegram_update(f"👑 *FULL SEND:* `{pair}` smashed all targets!")

    if updated:
        save_trades(trades)

def send_telegram_update(text):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": config.CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Tracker Telegram Error: {e}")
