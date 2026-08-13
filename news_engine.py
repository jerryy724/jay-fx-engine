import requests
import feedparser
import config
import image_generator

def send_telegram_photo(caption, image_bio):
    try:
        url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendPhoto"
        requests.post(url, data={'chat_id': config.CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}, files={'photo': image_bio}, timeout=10)
    except Exception as e:
        print(f"Telegram Photo Error: {e}")

def run_news_dispatch(is_weekend=False):
    if is_weekend:
        # Crypto News Processing
        rss_url = "https://cointelegraph.com/rss"
        title_header = "CRYPTO MARKET INTELLIGENCE"
        sub_header = "BTC & ETH VOLATILITY BRIEF"
    else:
        # Forex & Currency News Processing
        rss_url = "https://www.dailyforex.com/rss/forex-news"
        title_header = "FOREX MARKET INTELLIGENCE"
        sub_header = "CURRENCY PAIRS BRIEF"

    feed = feedparser.parse(rss_url)
    headlines = []

    if feed.entries:
        for entry in feed.entries[:3]:
            title = entry.title.replace('*', '')
            link = entry.link
            headlines.append(f"• *{title}*\n  🔗 [Read Full Breakdown]({link})")
    else:
        headlines.append("• *Market Volatility Watch:* High-impact macro events unfolding. Maintain proper risk management.")

    news_body = "\n\n".join(headlines)
    card = image_generator.generate_signal_card(title_header, sub_header, is_update=True)

    msg = (
        f"📰 *JAY FX {title_header}*\n"
        f"🌐 *Coverage:* Active Currency & Crypto Drivers\n\n"
        f"{news_body}\n\n"
        f"💡 *Trading Advice:* Use these market-moving drivers to evaluate position risk alongside automated signals."
    )

    send_telegram_photo(msg, card)
