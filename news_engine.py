import os
import requests
import feedparser
from datetime import datetime, timezone
import config
import image_generator

def send_telegram_photo(caption, image_bio):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendPhoto"
        res = requests.post(
            url, 
            data={'chat_id': config.CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}, 
            files={'photo': image_bio}, 
            timeout=12
        )
        print(f"Telegram News Photo Dispatch Status: {res.status_code}")
    except Exception as e:
        print(f"Telegram Photo Error: {e}")

def run_news_briefing():
    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() in [5, 6]
    
    if is_weekend:
        rss_url = "https://cointelegraph.com/rss"
        title_header = "CRYPTO MARKET INTELLIGENCE"
        sub_header = "BTC & ETH VOLATILITY BRIEF"
    else:
        rss_url = "https://www.dailyforex.com/rss/forex-news"
        title_header = "FOREX MARKET INTELLIGENCE"
        sub_header = "CURRENCY PAIRS BRIEF"

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    headlines = []

    try:
        response = requests.get(rss_url, headers=headers, timeout=10)
        feed = feedparser.parse(response.content)
        
        if feed.entries:
            for entry in feed.entries[:3]:
                title = entry.title.replace('*', '').replace('_', '')
                link = entry.link
                headlines.append(f"• *{title}*\n  🔗 [Read Full Breakdown]({link})")
        else:
            headlines.append("• *Market Volatility Watch:* High-impact macro events unfolding. Maintain proper risk management.")
    except Exception as e:
        print(f"RSS Fetching Error: {e}")
        headlines.append("• *Market Volatility Watch:* Active volatility observed across major instruments. Maintain proper risk management.")

    news_body = "\n\n".join(headlines)
    card = image_generator.generate_signal_card(title_header, sub_header, is_update=True)

    msg = (
        f"📰 *JAYFX {title_header}*\n"
        f"🌐 *Coverage:* Active Currency & Crypto Drivers\n\n"
        f"{news_body}\n\n"
        f"💡 *Trading Advice:* Use these market-moving drivers to evaluate position risk alongside automated signals."
    )

    send_telegram_photo(msg, card)

# Function alias to prevent naming mismatch errors
run_news_dispatch = run_news_briefing
