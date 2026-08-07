# -*- coding: utf-8 -*-
"""
שליחת ההתראות. תומך בכמה ערוצים, ונופל מאחד לשני לפי הסדר ב-config.NOTIFY_CHANNELS.

הערוצים:
  callmebot  — וואטסאפ. הכי פשוט להקמה, שירות חינמי לשימוש אישי.
  green      — וואטסאפ דרך Green API. יציב יותר, דורש סריקת QR.
  telegram   — נשאר בקוד כגיבוי אם וואטסאפ ייפול.
"""

import os
import urllib.parse

import requests

import config

# --- וואטסאפ ---
WHATSAPP_TO = os.environ.get("WHATSAPP_TO", "").strip()          # 972501234567
CALLMEBOT_APIKEY = os.environ.get("CALLMEBOT_APIKEY", "").strip()
GREEN_INSTANCE_ID = os.environ.get("GREEN_API_INSTANCE_ID", "").strip()
GREEN_TOKEN = os.environ.get("GREEN_API_TOKEN", "").strip()
GREEN_URL = os.environ.get("GREEN_API_URL", "https://api.green-api.com").strip().rstrip("/")

# --- טלגרם ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def normalize_phone(raw):
    """0501234567 / +972-50-123-4567  ->  972501234567"""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    return digits


def bold(text, channel):
    """וואטסאפ משתמש בכוכביות, טלגרם ב-HTML."""
    if channel == "telegram":
        return f"<b>{text}</b>"
    return f"*{text}*"


# ---------------------------------------------------------------------------
def _send_callmebot(text):
    if not (CALLMEBOT_APIKEY and WHATSAPP_TO):
        return False, "חסר CALLMEBOT_APIKEY או WHATSAPP_TO"
    try:
        resp = requests.get(
            "https://api.callmebot.com/whatsapp.php",
            params={
                "phone": "+" + normalize_phone(WHATSAPP_TO),
                "text": text,
                "apikey": CALLMEBOT_APIKEY,
            },
            timeout=45,
        )
    except requests.RequestException as e:
        return False, f"שגיאת רשת: {e}"

    # השירות מחזיר 200 גם על שגיאות לוגיות, אז בודקים את גוף התשובה
    body = resp.text.lower()
    if resp.status_code != 200:
        return False, f"קוד {resp.status_code}"
    if "apikey" in body and ("invalid" in body or "wrong" in body):
        return False, "ה-API key שגוי"
    if "queued" in body or "message sent" in body or "success" in body:
        return True, None
    return True, None  # ברירת מחדל אופטימית — 200 בלי שגיאה מפורשת


def _send_green(text):
    if not (GREEN_INSTANCE_ID and GREEN_TOKEN and WHATSAPP_TO):
        return False, "חסרים פרטי Green API או WHATSAPP_TO"
    url = f"{GREEN_URL}/waInstance{GREEN_INSTANCE_ID}/sendMessage/{GREEN_TOKEN}"
    try:
        resp = requests.post(
            url,
            json={"chatId": f"{normalize_phone(WHATSAPP_TO)}@c.us", "message": text},
            timeout=45,
        )
    except requests.RequestException as e:
        return False, f"שגיאת רשת: {e}"

    if resp.status_code != 200:
        return False, f"קוד {resp.status_code}: {resp.text[:150]}"
    return True, None


def _send_telegram(text):
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return False, "חסר TELEGRAM_TOKEN או TELEGRAM_CHAT_ID"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        return False, f"שגיאת רשת: {e}"

    if resp.status_code != 200:
        return False, f"קוד {resp.status_code}: {resp.text[:150]}"
    return True, None


SENDERS = {
    "callmebot": _send_callmebot,
    "green": _send_green,
    "telegram": _send_telegram,
}


def configured_channels():
    """רק ערוצים שבאמת יש להם סודות מוגדרים."""
    ready = []
    for ch in config.NOTIFY_CHANNELS:
        if ch == "callmebot" and CALLMEBOT_APIKEY and WHATSAPP_TO:
            ready.append(ch)
        elif ch == "green" and GREEN_INSTANCE_ID and GREEN_TOKEN and WHATSAPP_TO:
            ready.append(ch)
        elif ch == "telegram" and TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            ready.append(ch)
    return ready


def send(build_text, log=print):
    """
    build_text(channel) -> str
    מנסה כל ערוץ לפי הסדר עד שאחד מצליח. מחזיר (הצליח, שם_הערוץ).
    """
    channels = configured_channels()
    if not channels:
        log("  אין אף ערוץ שליחה מוגדר")
        return False, None

    for ch in channels:
        ok, err = SENDERS[ch](build_text(ch))
        if ok:
            return True, ch
        log(f"  {ch} נכשל: {err}")

    return False, None
