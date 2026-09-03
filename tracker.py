import os
import json
import requests
from datetime import datetime, timezone
import config
import image_generator

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
    """
    Calculates pips dynamically based on asset type:
    - Forex JPY Pairs: Multiplier = 100
    - Forex Standard Pairs: Multiplier = 10,000
    - Crypto / Index Pairs (BTC/USD, ETH/USD, SOL/USD, etc.): Multiplier = 1 (1 point/dollar = 1 pip)
    """
    pair_upper = pair.upper()
    
    # Identify Crypto/Index symbols
    crypto_keywords = ["BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "LINK", "LTC"]
    is_crypto = any(coin in pair_upper for coin in crypto_keywords) or "/" not in pair_upper

    if is_crypto:
        multiplier = 1.0
    elif "JPY" in pair_upper:
        multiplier = 100.0
    else:
        multiplier = 10000.0

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
        "secured_pips": 0.0,
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

        current_pips = calculate_pips(pair, entry, current_price, direction)
        pip_prefix = "+" if current_pips > 0 else ""

        # 1. Check Stop Loss / Breakeven Trailing Exit
        if (direction == "BUY" and current_price <= current_sl) or (direction == "SELL" and current_price >= current_sl):
            if current_sl == initial_sl and len(hit_tps) == 0:
                trade["status"] = "CLOSED_SL"
                trade["secured_pips"] = current_pips
                msg = (f"JAY FX PREMIUM SIGNALS VIP\n"
                       f"🛑 *STOP LOSS HIT*\n\n"
                       f"📌 *Pair:* `{pair}`\n"
                       f"📉 *Exit:* `{current_price}`\n"
                       f"📅 *Issued:* `{issued_time}`\n"
                       f"💰 *Pips:* `{pip_prefix}{current_pips}`")
                send_telegram_update(msg)
            elif current_sl == entry or len(hit_tps) > 0:
                trade["status"] = "CLOSED_PROFIT" if trade.get("secured_pips", 0) > 0 else "CLOSED_BREAKEVEN"
                final_pips = max(trade.get("secured_pips", 0.0), 0.0)
                msg = (f"JAY FX PREMIUM SIGNALS VIP\n"
                       f"🔒 *TRADE CLOSED (PROFIT SECURED)*\n\n"
                       f"📌 *Pair:* `{pair}`\n"
                       f"📉 *Exit:* `{current_price}`\n"
                       f"📅 *Issued:* `{issued_time}`\n"
                       f"💰 *Total Locked Pips:* `+{final_pips}`")
                send_telegram_update(msg)
            
            updated = True
            continue

        # 2. Check Take Profits & Trailing SL
        for idx, tp in enumerate(tps, 1):
            if idx not in hit_tps:
                if (direction == "BUY" and current_price >= tp) or (direction == "SELL" and current_price <= tp):
                    hit_tps.append(idx)
                    trade["hit_tps"] = hit_tps
                    
                    locked_pips = calculate_pips(pair, entry, tp, direction)
                    trade["secured_pips"] = max(trade.get("secured_pips", 0.0), locked_pips)
                    updated = True
                    
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

def generate_performance_report(timeframe="daily"):
    """
    Generates performance metrics and posts a high-contrast Yellow-on-Black card.
    Options: 'daily', 'weekly', 'monthly', 'annual'
    """
    trades = load_trades()
    now = datetime.now(timezone.utc)
    filtered_trades = []

    for t in trades:
        issued_str = t.get("issued_time", "")
        try:
            trade_dt = datetime.strptime(issued_str, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        except Exception:
            continue

        if timeframe == "daily" and trade_dt.date() == now.date():
            filtered_trades.append(t)
        elif timeframe == "weekly" and trade_dt.isocalendar()[1] == now.isocalendar()[1] and trade_dt.year == now.year:
            filtered_trades.append(t)
        elif timeframe == "monthly" and trade_dt.month == now.month and trade_dt.year == now.year:
            filtered_trades.append(t)
        elif timeframe == "annual" and trade_dt.year == now.year:
            filtered_trades.append(t)

    total_trades = len(filtered_trades)
    wins = 0
    losses = 0
    total_pips = 0.0

    for t in filtered_trades:
        hit_tps = t.get("hit_tps", [])
        status = t.get("status", "")
        pips = t.get("secured_pips", 0.0)

        if len(hit_tps) > 0 or status in ["CLOSED_PROFIT", "CLOSED_TP_MAX"]:
            wins += 1
            total_pips += pips
        elif status == "CLOSED_SL":
            losses += 1
            total_pips += pips  # SL pips are negative

    decided = wins + losses
    win_rate = round((wins / decided) * 100, 1) if decided > 0 else 0.0
    pip_str = f"+{round(total_pips, 1)}" if total_pips >= 0 else f"{round(total_pips, 1)}"

    title_map = {
        "daily": "DAILY PERFORMANCE TRACKER",
        "weekly": "WEEKLY PERFORMANCE TRACKER",
        "monthly": "MONTHLY PERFORMANCE TRACKER",
        "annual": "ANNUAL PERFORMANCE TRACKER"
    }
    period_title = title_map.get(timeframe, "PERFORMANCE TRACKER")

    # Generate Yellow-on-Black Card
    card_bio = image_generator.generate_performance_card(
        title=period_title,
        win_rate=f"{win_rate}%",
        total_pips=f"{pip_str} PIPS",
        total_trades=str(total_trades),
        wins=str(wins),
        losses=str(losses)
    )

    caption = (
        f"📊 *JAYFX {period_title}*\n"
        f"🗓️ *Period:* {now.strftime('%d %b %Y')}\n\n"
        f"🎯 *Total Signals Issued:* `{total_trades}`\n"
        f"✅ *Take Profit Wins:* `{wins}`\n"
        f"🛑 *Stop Losses Hit:* `{losses}`\n"
        f"🔥 *Win Rate:* `{win_rate}%`\n"
        f"💰 *Net Pips Accumulated:* `{pip_str}`\n\n"
        f"⚡ _Consistent Risk Management Drives Long-Term Success._"
    )

    send_telegram_photo(caption, card_bio)

def send_telegram_update(text):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": config.CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Tracker Telegram Error: {e}")

def send_telegram_photo(caption, image_bio):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendPhoto"
        requests.post(
            url, 
            data={'chat_id': config.CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}, 
            files={'photo': image_bio}, 
            timeout=12
        )
    except Exception as e:
        print(f"Tracker Photo Dispatch Error: {e}")
