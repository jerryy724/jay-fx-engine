import os
import sys
import requests
from datetime import datetime, timezone, timedelta
import config
import market_engine
import image_generator
import news_engine
import prealerts
import tracker
import data_client

def is_channel_quiet_time():
    """
    Checks if the current time falls within the 10:00 PM to 12:00 AM UTC quiet window.
    """
    now = datetime.now(timezone.utc)
    return config.QUIET_HOUR_START <= now.hour < config.QUIET_HOUR_END

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
    if is_channel_quiet_time():
        print("Channel is in Quiet Mode (22:00 UTC - 00:00 UTC). Skipping pre-alert dispatch.")
        return

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
    if is_channel_quiet_time():
        print("Channel is in Quiet Mode (22:00 UTC - 00:00 UTC). Skipping tracker check.")
        return

    open_trades = tracker.load_trades()
    open_pairs = list({t["pair"] for t in open_trades if t.get("status") == "OPEN"})

    if not open_pairs:
        print("No open trades — skipping tracker API call.")
        return

    symbols_str = ",".join(open_pairs)
    price_map = {}

    res = data_client.twelvedata_get("price", {"symbol": symbols_str})
    if len(open_pairs) == 1:
        if "price" in res:
            price_map[open_pairs[0]] = float(res["price"])
        else:
            print(f"Tracker price fetch error for {open_pairs[0]}: {res}")
    else:
        for sym in open_pairs:
            if sym in res and "price" in res[sym]:
                price_map[sym] = float(res[sym]["price"])
            else:
                print(f"Tracker missing price for {sym}: {res.get(sym)}")

    if price_map:
        try:
            tracker.check_open_trades(price_map)
        except Exception as e:
            print(f"Tracker Execution Error: {e}")
    else:
        print("Tracker run skipped: no prices retrieved.")

# ==========================================
# 3. MAIN SIGNAL DISPATCH JOB
# ==========================================
def run_signal_dispatch():
    if is_channel_quiet_time():
        print("Channel is in Quiet Mode (22:00 UTC - 00:00 UTC). Skipping signal dispatch.")
        return

    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]

    rotation_list = config.CRYPTO_ROTATION if is_weekend else config.FX_ROTATION
    idx = now.hour % len(rotation_list)
    item = rotation_list[idx]

    price, decimals, signal_type, atr, conviction = market_engine.fetch_live_market_data(item)

    if price is None or atr is None:
        error_msg = f"⚠️ *Execution Error*: Could not retrieve market data from Twelve Data for `{item['name']}`."
        print(error_msg)
        send_telegram_msg(error_msg)
        return

    # Trend + momentum agree -> High Conviction. Trend confirmed but RSI hasn't
    # crossed the midline yet, or RSI is extended past 70/30 -> Standard Setup.
    if conviction == "HIGH":
        conviction_tag = "🔥 *High Conviction*"
    else:
        conviction_tag = "⚙️ *Standard Setup*"

    if config.SKIP_EXTENDED_RSI_SETUPS and conviction in ("AVOID_OVERBOUGHT", "AVOID_OVERSOLD"):
        print(f"Skipping {item['name']}: RSI extended past threshold ({conviction}).")
        return

    pair = item["name"]
    asset_type = item["type"]
    session_name = market_engine.get_market_session(asset_type == "CRYPTO")
    date_str = now.strftime("%d %b %Y | %H:%M UTC")
    issued_time = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    fmt = f".{decimals}f"

    try:
        tracker.check_open_trades({pair: price})
    except Exception as e:
        print(f"Non-fatal tracker error: {e}")

    entry = price
    entry_low = round(entry - (0.25 * atr), decimals)
    entry_high = round(entry + (0.25 * atr), decimals)

    if signal_type == "BUY":
        sl = round(entry - (1.50 * atr), decimals)
        tp1 = round(entry + (1.00 * atr), decimals)
        tp2 = round(entry + (2.00 * atr), decimals)
        tp3 = round(entry + (3.20 * atr), decimals)
        tp4 = round(entry + (4.50 * atr), decimals)
    else:
        sl = round(entry + (1.50 * atr), decimals)
        tp1 = round(entry - (1.00 * atr), decimals)
        tp2 = round(entry - (2.00 * atr), decimals)
        tp3 = round(entry - (3.20 * atr), decimals)
        tp4 = round(entry - (4.50 * atr), decimals)

    entry_low_str = f"{entry_low:{fmt}}"
    entry_high_str = f"{entry_high:{fmt}}"
    sl_str = f"{sl:{fmt}}"
    tp1_str = f"{tp1:{fmt}}"
    tp2_str = f"{tp2:{fmt}}"
    tp3_str = f"{tp3:{fmt}}"
    tp4_str = f"{tp4:{fmt}}"

    caption = (
        f"👑 *JAY FX PREMIUM SIGNALS*\n"
        f"🌐 *Session:* {session_name} | {conviction_tag}\n"
        f"🕒 *Date & Time:* {date_str}\n\n"
        f"📊 *Asset:* `{pair}`\n"
        f"📈 *Direction:* *{signal_type}*\n"
        f"🎯 *Entry Zone:* `{entry_low_str} - {entry_high_str}`\n"
        f"⚖️ *Risk:Reward Ratio:* 1:3.0 (TP4 Max)\n\n"
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
        tracker.log_new_trade(pair, signal_type, entry, sl, [tp1, tp2, tp3, tp4], issued_time)
    except Exception as e:
        print(f"Non-fatal trade log error: {e}")

# ==========================================
# 4. ROTATION ALERTS (FRIDAY & SUNDAY)
# ==========================================
def run_friday_rotation_alert():
    title = "WEEKEND CRYPTO ROTATION"
    sub_text = "FOREX CLOSED — SWITCHING TO CRYPTO SIGNALS"
    
    caption = (
        f"🔄 *JAY FX MARKET ROTATION NOTICE*\n\n"
        f"The Forex market is closing for the weekend.\n"
        f"The system has officially transitioned to **Cryptocurrency Market Scanning**.\n\n"
        f"⚡ *24/7 Coverage Active:* Bitcoin & Major Altcoins\n"
        f"📊 *Forex Operations Resume:* Monday 00:00 UTC\n\n"
        f"🌐 _Stay tuned for weekend high-conviction setups._"
    )

    card_bio = image_generator.generate_signal_card(title, sub_text, session_text="CRYPTO MARKET ACTIVE", is_update=True)
    send_telegram_photo(caption, card_bio)

def run_sunday_rotation_alert():
    title = "FOREX MARKET RESUMPTION"
    sub_text = "CRYPTO PAUSED — RESUMING FOREX SIGNALS"
    
    caption = (
        f"🔄 *JAY FX MARKET ROTATION NOTICE*\n\n"
        f"Weekend Crypto Market Scanning is now on hold.\n"
        f"The system has officially transitioned back to **Forex & Commodities Market Scanning**.\n\n"
        f"🌐 *Sydney & Asian Sessions:* Live\n"
        f"📊 *Active Coverage:* Major & Minor FX Pairs\n\n"
        f"⚡ _Get ready for high-conviction market setups for the week ahead._"
    )

    card_bio = image_generator.generate_signal_card(title, sub_text, session_text="FOREX MARKET ACTIVE", is_update=True)
    send_telegram_photo(caption, card_bio)

# ==========================================
# 5. MARKET NEWS DISPATCH JOB
# ==========================================
def run_news_dispatch():
    if is_channel_quiet_time():
        print("Channel is in Quiet Mode. Skipping news briefing.")
        return
    try:
        news_engine.run_news_briefing()
    except Exception as e:
        print(f"News Briefing Error: {e}")

# ==========================================
# 6. CHANNEL CLOSE / RESUME (QUIET HOURS)
# ==========================================
def run_close_channel():
    """
    Fires at 22:00 UTC daily. Posts an explicit closing card so the
    channel going quiet reads as an intentional pause, not the bot
    breaking. On Fridays this doubles as the weekend crypto-rotation
    notice, since Sat/Sun both run the crypto rotation.
    """
    now = datetime.now(timezone.utc)
    if now.weekday() == 4:  # Friday -> weekend crypto handoff
        run_friday_rotation_alert()
        return

    title = "JAYFX SIGNAL SYSTEM"
    sub_text = "CLOSED FOR NOW — RESUMES 00:00 UTC"
    caption = (
        f"🌙 *JAY FX SIGNAL SYSTEM — CLOSING FOR NOW*\n\n"
        f"New signals are paused for the next couple of hours — this window "
        f"tends to be low-liquidity and unreliable for clean setups.\n\n"
        f"🕛 *Signals Resume:* 00:00 UTC\n"
        f"📊 *Daily performance tracker drops shortly.*\n\n"
        f"⚡ _Open trades stay monitored — SL/TP updates still post as normal._"
    )
    card_bio = image_generator.generate_signal_card(title, sub_text, session_text="OFFLINE", is_update=True)
    send_telegram_photo(caption, card_bio)

def run_resume_channel():
    """
    Fires at 00:00 UTC daily. On Mondays this doubles as the forex
    resumption notice, since the weekend crypto rotation just ended.
    """
    now = datetime.now(timezone.utc)
    if now.weekday() == 0:  # Monday -> forex resumption
        run_sunday_rotation_alert()
        return

    title = "JAYFX SIGNAL SYSTEM"
    sub_text = "BACK ONLINE — SIGNALS RESUMING"
    caption = (
        f"🌅 *JAY FX SIGNAL SYSTEM — BACK ONLINE*\n\n"
        f"The channel is live again and signal scanning has resumed.\n\n"
        f"⚡ _First setup of the new cycle drops on the next scheduled run._"
    )
    card_bio = image_generator.generate_signal_card(title, sub_text, session_text="LIVE", is_update=True)
    send_telegram_photo(caption, card_bio)

# ==========================================
# 7. SCHEDULED PERFORMANCE REPORTS
# ==========================================
def run_scheduled_reports():
    """
    Fires at 22:05 UTC daily (right after the channel closes). Always
    posts the daily tracker. Also posts the weekly tracker on Sundays
    (end of the calendar week) and the monthly tracker when today is
    the last day of the month — so one cron entry covers all three
    cadences without needing separate schedules for each.
    """
    now = datetime.now(timezone.utc)
    tracker.generate_performance_report("daily")

    if now.weekday() == 6:  # Sunday = end of week
        tracker.generate_performance_report("weekly")

    tomorrow = now + timedelta(days=1)
    if tomorrow.month != now.month:
        tracker.generate_performance_report("monthly")

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

    if action in ["signal", "engine", "engine_trigger"]:
        run_signal_dispatch()
    elif action in ["prealert", "pre-alert"]:
        run_prealert()
    elif action in ["tracker", "watch", "order_tracker"]:
        run_tracker_only()
    elif action in ["news", "market_news"]:
        run_news_dispatch()
    elif action in ["rotation_alert", "friday_alert"]:
        run_friday_rotation_alert()
    elif action in ["sunday_alert", "sunday_rotation"]:
        run_sunday_rotation_alert()
    elif action in ["close_channel", "channel_close"]:
        run_close_channel()
    elif action in ["resume_channel", "channel_resume"]:
        run_resume_channel()
    elif action in ["scheduled_reports"]:
        run_scheduled_reports()
    elif action in ["report_daily", "daily_report"]:
        tracker.generate_performance_report("daily")
    elif action in ["report_weekly", "weekly_report"]:
        tracker.generate_performance_report("weekly")
    elif action in ["report_monthly", "monthly_report"]:
        tracker.generate_performance_report("monthly")
    elif action in ["report_annual", "annual_report"]:
        tracker.generate_performance_report("annual")
    else:
        print(f"Action '{action}' unmapped or empty. Defaulting to signal dispatch.")
        run_signal_dispatch()
