# -*- coding: utf-8 -*-
"""
שליחת ההתראות. תומך בכמה ערוצים, ונופל מאחד לשני לפי הסדר ב-config.NOTIFY_CHANNELS.

הערוצים, מהפשוט להקמה למסובך:
  email      — מייל דרך SMTP. אין אפליקציה, אין סשן שמתנתק, אין חשבון חדש.
               ספרייה סטנדרטית של פייתון. ברירת המחדל.
  ntfy       — פוש לנייד דרך ntfy.sh. בלי חשבון ובלי API key בכלל.
  green      — וואטסאפ דרך Green API. דורש QR וטלפון מחובר.
  callmebot  — וואטסאפ, שירות חינמי לשימוש אישי.
  telegram   — טלגרם.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage

import requests

import config

# --- וואטסאפ (מוגדר אחרי env(), ראה למטה) ---

def env(name, default=""):
    """
    כמו os.environ.get, אבל מחזיר את ברירת המחדל גם כשהערך ריק ולא רק כשהוא חסר.

    GitHub Actions מעביר כל Secret שלא הוגדר כמחרוזת ריקה, לא כמשתנה נעדר.
    לכן os.environ.get(name, default) לא מחזיר את ברירת המחדל שם, וההגדרה
    יוצאת ריקה — מה שהפיל את ntfy עם 'Invalid URL' ואת SMTP עם host ריק.
    """
    return (os.environ.get(name) or "").strip() or default


# --- מייל ---
SMTP_HOST = env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_USER = env("SMTP_USER")
# גוגל מציגה App Password כ-"abcd efgh ijkl mnop". הרווחים הם לקריאוּת בלבד
# ואינם חלק מהסיסמה — עם רווחים ההתחברות נכשלת ב-535.
SMTP_PASSWORD = "".join(env("SMTP_PASSWORD").split())
EMAIL_TO = env("EMAIL_TO")

# --- ntfy.sh ---
NTFY_TOPIC = env("NTFY_TOPIC")
NTFY_SERVER = env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

# --- וואטסאפ ---
WHATSAPP_TO = env("WHATSAPP_TO")                  # 972501234567
CALLMEBOT_APIKEY = env("CALLMEBOT_APIKEY")
GREEN_INSTANCE_ID = env("GREEN_API_INSTANCE_ID")
GREEN_TOKEN = env("GREEN_API_TOKEN")
GREEN_URL = env("GREEN_API_URL", "https://api.green-api.com").rstrip("/")

# --- טלגרם ---
TELEGRAM_TOKEN = env("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")


def normalize_phone(raw):
    """0501234567 / +972-50-123-4567  ->  972501234567"""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    return digits


def bold(text, channel):
    """כל ערוץ והסימון שלו. מייל ו-ntfy הם טקסט נקי — סימני הדגשה רק יפריעו."""
    if channel == "telegram":
        return f"<b>{text}</b>"
    if channel in ("green", "callmebot"):
        return f"*{text}*"
    return text


# ---------------------------------------------------------------------------
def _send_email(text, subject=None):
    if not (SMTP_USER and SMTP_PASSWORD and EMAIL_TO):
        return False, "חסר SMTP_USER / SMTP_PASSWORD / EMAIL_TO"

    msg = EmailMessage()
    msg["Subject"] = subject or "דירות חדשות"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    msg.set_content(text)

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                                      context=ssl.create_default_context(), timeout=45)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=45)
            server.starttls(context=ssl.create_default_context())
        with server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        return False, "התחברות נדחתה — ב-Gmail צריך App Password, לא סיסמת החשבון"
    except (smtplib.SMTPException, OSError) as e:
        return False, f"{type(e).__name__}: {e}"
    return True, None


def _send_ntfy(text, subject=None):
    if not NTFY_TOPIC:
        return False, "חסר NTFY_TOPIC"
    headers = {"Content-Type": "text/plain; charset=utf-8"}
    if subject:
        # כותרות HTTP חייבות להיות ASCII, אז כותרת עברית חייבת קידוד RFC 2047
        headers["Title"] = "=?UTF-8?B?" + __import__("base64").b64encode(
            subject.encode("utf-8")).decode("ascii") + "?="
    try:
        resp = requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}",
                             data=text.encode("utf-8"), headers=headers, timeout=45)
    except requests.RequestException as e:
        return False, f"שגיאת רשת: {e}"
    if resp.status_code != 200:
        return False, f"קוד {resp.status_code}: {resp.text[:150]}"
    return True, None


def _send_callmebot(text, subject=None):
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


def _send_green(text, subject=None):
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


def _send_telegram(text, subject=None):
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
    "email": _send_email,
    "ntfy": _send_ntfy,
    "callmebot": _send_callmebot,
    "green": _send_green,
    "telegram": _send_telegram,
}

# מה חייב להיות מוגדר כדי שהערוץ ייחשב זמין
REQUIREMENTS = {
    "email":     lambda: bool(SMTP_USER and SMTP_PASSWORD and EMAIL_TO),
    "ntfy":      lambda: bool(NTFY_TOPIC),
    "green":     lambda: bool(GREEN_INSTANCE_ID and GREEN_TOKEN and WHATSAPP_TO),
    "callmebot": lambda: bool(CALLMEBOT_APIKEY and WHATSAPP_TO),
    "telegram":  lambda: bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
}


def configured_channels():
    """רק ערוצים שבאמת יש להם סודות מוגדרים."""
    return [ch for ch in config.NOTIFY_CHANNELS
            if ch in REQUIREMENTS and REQUIREMENTS[ch]()]


def send(build_text, log=print, subject=None):
    """
    build_text(channel) -> str
    מנסה כל ערוץ לפי הסדר עד שאחד מצליח. מחזיר (הצליח, שם_הערוץ).
    """
    channels = configured_channels()
    if not channels:
        log("  אין אף ערוץ שליחה מוגדר")
        return False, None

    for ch in channels:
        ok, err = SENDERS[ch](build_text(ch), subject)
        if ok:
            return True, ch
        log(f"  {ch} נכשל: {err}")

    return False, None
