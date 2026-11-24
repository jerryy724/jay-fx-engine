"""
admin.py - private messages to the administrator (never the public channel).
Uses the ADMIN_CHAT_ID secret with the same BOT_TOKEN as the FX bot.
If ADMIN_CHAT_ID is missing, nothing is sent and nothing breaks.
"""

import requests

import config


def notify(text, html=False):
    if not config.BOT_TOKEN or not config.ADMIN_CHAT_ID:
        return False

    payload = {"chat_id": config.ADMIN_CHAT_ID, "text": str(text)[:3900]}

    if html:
        payload["parse_mode"] = "HTML"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=15,
        )

        if not response.ok and html:
            payload.pop("parse_mode", None)
            response = requests.post(
                f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage",
                json=payload,
                timeout=15,
            )

        return response.ok

    except Exception as error:
        print(f"Admin notify failed: {error}")
        return False
