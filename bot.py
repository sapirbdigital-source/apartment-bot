# -*- coding: utf-8 -*-
"""
בוט דירות להשכרה — אזור מבשרת ציון והסביבה.

זרימה:
  Apify (קבוצות פייסבוק)  ->  סינון מקומי  ->  Gemini/Groq  ->  אימות בקוד  ->  וואטסאפ

כל ההגדרות ב-config.py. ערוצי השליחה ב-notifier.py.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

import config
import notifier

# ---------------------------------------------------------------------------
# סודות (GitHub Secrets / משתני סביבה)
# ---------------------------------------------------------------------------
APIFY_ACCOUNTS = [
    {
        "token": os.environ.get(f"APIFY_TOKEN_{i}", "").strip(),
        "task_id": os.environ.get(f"APIFY_TASK_ID_{i}", "").strip(),
    }
    for i in (1, 2, 3)
]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

# מצב יבש — מנתח ומדפיס אבל לא שולח כלום ולא כותב ל-seen
DRY_RUN = "--dry-run" in sys.argv


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# זיכרון — מונע שליחה חוזרת של אותה מודעה
# ---------------------------------------------------------------------------
def load_seen():
    try:
        with open(config.SEEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    # ניקוי רשומות ישנות כדי שהקובץ לא יתפח לנצח
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.SEEN_TTL_DAYS)).isoformat()
    return {k: v for k, v in data.items() if v >= cutoff}


def save_seen(seen):
    os.makedirs(os.path.dirname(config.SEEN_FILE), exist_ok=True)
    with open(config.SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=1, sort_keys=True)


def post_key(text, url):
    """
    מזהה יציב לפוסט — לפי הטקסט, לא לפי ה-URL.

    מתווכים מפרסמים את אותה מודעה בכמה קבוצות, ולפעמים פעמיים באותה קבוצה.
    לכל עותק יש permalink אחר, אז מפתח לפי URL היה שולח את אותה דירה שוב ושוב.
    נמדד בפועל: אותו טקסט הופיע 3 פעמים עם 3 כתובות שונות.
    """
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if len(normalized) >= config.MIN_POST_LENGTH:
        return "sha1:" + hashlib.sha1(normalized[:300].encode("utf-8")).hexdigest()
    # טקסט קצר מדי מכדי לזהות לפיו — נופלים ל-URL
    if url:
        return url.split("?")[0]
    return "sha1:" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Apify — שליפת פוסטים מקבוצות פייסבוק
# ---------------------------------------------------------------------------
TEXT_FIELDS = ("text", "postText", "message", "content", "body", "full_text", "description")


def extract_text(item):
    """
    שמות השדות משתנים בין אקטורים שונים של Apify.

    כשמישהו *משתף* מודעה של אחר, ה-text ברמה העליונה ריק והתוכן האמיתי
    יושב ב-sharedPost. בלי הנפילה הזו מודעות אמיתיות נזרקות כ"קצרות מדי".
    """
    for field in TEXT_FIELDS:
        val = item.get(field)
        if val and str(val).strip():
            return str(val).strip()

    shared = item.get("sharedPost")
    if isinstance(shared, dict):
        for field in TEXT_FIELDS:
            val = shared.get(field)
            if val and str(val).strip():
                return str(val).strip()

    return ""


def extract_url(item):
    for field in ("url", "link", "postUrl", "facebookUrl", "permalink"):
        val = item.get(field)
        if val and str(val).strip():
            return str(val).strip()
    return ""


def run_apify_task():
    """מריץ את הטאסק הראשון שמחזיר תוצאות. נופל לחשבון הבא כשנגמר התקציב."""
    for i, acc in enumerate(APIFY_ACCOUNTS, start=1):
        token, task_id = acc["token"], acc["task_id"]
        if not token or not task_id:
            continue

        log(f"מפעיל Apify (חשבון {i})...")
        try:
            resp = requests.post(
                f"https://api.apify.com/v2/actor-tasks/{task_id}/runs?token={token}",
                timeout=60,
            )
        except requests.RequestException as e:
            log(f"  חשבון {i}: שגיאת רשת ({e}) — עובר לבא.")
            continue

        if resp.status_code not in (200, 201):
            log(f"  חשבון {i}: קוד {resp.status_code} — עובר לבא.")
            continue

        run_id = resp.json().get("data", {}).get("id")
        run_data, status = {}, "RUNNING"
        waited = 0

        while status in ("RUNNING", "READY"):
            time.sleep(10)
            waited += 10
            if waited > 900:  # 15 דקות — משהו תקוע
                log(f"  חשבון {i}: timeout אחרי 15 דקות.")
                break
            try:
                run_data = requests.get(
                    f"https://api.apify.com/v2/actor-runs/{run_id}?token={token}", timeout=30
                ).json().get("data", {})
                status = run_data.get("status", "RUNNING")
            except requests.RequestException:
                continue
            log(f"  חשבון {i}: {status}")

        if status != "SUCCEEDED":
            log(f"  חשבון {i}: הסתיים ב-{status} — עובר לבא.")
            continue

        dataset_id = run_data.get("defaultDatasetId")
        items = requests.get(
            f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={token}", timeout=120
        ).json()

        if items:
            log(f"  חשבון {i}: {len(items)} פוסטים.")
            log(f"  שדות בפריט ראשון: {list(items[0].keys())}")
            return items

        log(f"  חשבון {i}: 0 תוצאות (כנראה נגמר התקציב) — עובר לבא.")

    log("כל חשבונות ה-Apify מוצו או נכשלו.")
    return []


# ---------------------------------------------------------------------------
# הפרומפט
# ---------------------------------------------------------------------------
def bullets(items):
    return "\n".join(f"- {x}" for x in items)


def build_prompt(text):
    return f"""אתה מסנן מודעות דיור עבור {config.SEEKER_NAME} — {config.HOUSEHOLD}.
היא מחפשת דירה **להשכרה בלבד** באזור מבשרת ציון והיישובים סביב ירושלים.
יש לה רכב פרטי, ולכן תחבורה ציבורית פחות קריטית — מה שחשוב זה זמן נסיעה וחניה.

## תקציב
- עד {config.BUDGET:,} ₪ לחודש — מצוין.
- {config.BUDGET:,}–{config.BUDGET_STRETCH:,} ₪ — עדיין רלוונטי, אבל סמן over_budget=true.
- מעל {config.BUDGET_STRETCH:,} ₪ — פסול.

## אזורים
ליבה (מועדף):
{bullets(config.CORE_AREAS)}

טבעת שנייה (מתאים גם):
{bullets(config.EXTENDED_AREAS)}

לא רלוונטי בכלל:
{bullets(config.EXCLUDED_AREAS)}

## דירה
- מינימום {config.MIN_ROOMS} חדרים. {config.ROOMS_STRETCH} חדרים מתקבל רק אם כל השאר מצוין — אז סמן small=true.
- יתרונות (לא חובה):
{bullets(config.NICE_TO_HAVE)}

## פסילה אוטומטית
{bullets(config.HARD_REJECTS)}

## פלט
החזר JSON תקין **בלבד**, בלי טקסט לפני או אחרי, בסכמה הבאה:

{{
  "decision": "PASS" או "SKIP",
  "reject_reason": "אם SKIP — משפט קצר למה. אחרת null",
  "price": מספר בשקלים או null אם לא צוין מחיר במודעה,
  "rooms": מספר חדרים (יכול להיות עשרוני) או null,
  "location": "היישוב/השכונה כפי שמופיע במודעה",
  "over_budget": true/false,
  "small": true/false,
  "drive": "הערכת זמן נסיעה ברכב אל {config.COMMUTE_TARGET}, ומה מצב החניה במקום",
  "kids": "מה יש בסביבה לילדים בגילאי 12 ו-8 — בתי ספר, גנים, פארקים. אם אין מידע, כתוב 'לא צוין'",
  "highlights": "1-2 משפטים: מה מיוחד או בעייתי בדירה הזו",
  "verdict": "שורה תחתונה קצרה — האם שווה להתקשר"
}}

כללים קשיחים:
- **אל תמציא מחיר.** אם המודעה לא מציינת מחיר, price=null.
- **אל תמציא מספר חדרים.** אם לא צוין, rooms=null.
- אם המודעה לא בעברית או לא קשורה לדיור — decision=SKIP.

## המודעה
{text}"""


# ---------------------------------------------------------------------------
# קריאות AI
# ---------------------------------------------------------------------------
def parse_json_response(raw):
    """מודלים לפעמים עוטפים JSON ב-```json. מחלצים בכל מקרה."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


# נזכר איזה מודל Gemini באמת עובד, כדי לא לבזבז 404 על כל פוסט
_gemini_model = [config.GEMINI_MODEL]


def analyze_with_gemini(text):
    if not GEMINI_API_KEY:
        return None

    for attempt in range(2):
        model = _gemini_model[0]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={GEMINI_API_KEY}"
        )
        try:
            resp = requests.post(
                url,
                json={
                    "contents": [{"parts": [{"text": build_prompt(text)}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2,
                    },
                },
                timeout=90,
            )
        except requests.RequestException as e:
            log(f"  Gemini: שגיאת רשת ({e})")
            return None

        if resp.status_code == 404 and attempt == 0 and model != config.GEMINI_MODEL_FALLBACK:
            log(f"  המודל {model} לא קיים — נופל ל-{config.GEMINI_MODEL_FALLBACK}")
            _gemini_model[0] = config.GEMINI_MODEL_FALLBACK
            continue

        if resp.status_code != 200:
            log(f"  Gemini: קוד {resp.status_code}")
            return None

        try:
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            return None
        return parse_json_response(raw)

    return None


def analyze_with_groq(text):
    if not GROQ_API_KEY:
        return None
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json={
                "model": config.GROQ_MODEL,
                "messages": [{"role": "user", "content": build_prompt(text)}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            timeout=90,
        )
        return parse_json_response(resp.json()["choices"][0]["message"]["content"])
    except (requests.RequestException, KeyError, IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# אימות בקוד — לא סומכים על המודל בשביל מספרים
# ---------------------------------------------------------------------------
def enforce_rules(result):
    """מחזיר (ok, reason). מודלים גרועים בגבולות מספריים — אז בודקים כאן."""
    if result.get("decision") != "PASS":
        return False, result.get("reject_reason") or "נדחה ע\"י AI"

    price = result.get("price")
    if price is None:
        if not config.SEND_IF_NO_PRICE:
            return False, "לא צוין מחיר"
    else:
        try:
            price = float(price)
        except (TypeError, ValueError):
            return False, "מחיר לא תקין"
        if price > config.BUDGET_STRETCH:
            return False, f"מחיר {price:,.0f} ₪ מעל התקרה"
        result["over_budget"] = price > config.BUDGET

    rooms = result.get("rooms")
    if rooms is not None:
        try:
            rooms = float(rooms)
        except (TypeError, ValueError):
            rooms = None
        if rooms is not None:
            if rooms < config.ROOMS_STRETCH:
                return False, f"{rooms} חדרים — קטן מדי"
            result["small"] = rooms < config.MIN_ROOMS

    return True, None


# ---------------------------------------------------------------------------
# הודעת ההתראה
# ---------------------------------------------------------------------------
def format_message(r, url, channel="green"):
    """הדגשה שונה בין הערוצים: וואטסאפ *כוכביות*, טלגרם <b>HTML</b>."""
    b = notifier.bold

    price = r.get("price")
    price_str = f"{float(price):,.0f} ₪" if price is not None else "מחיר לא צוין"
    if r.get("over_budget"):
        price_str += " ⚠️ מעל התקציב"

    rooms = r.get("rooms")
    rooms_str = f"{float(rooms):g} חדרים" if rooms is not None else "מס' חדרים לא צוין"
    if r.get("small"):
        rooms_str += " ⚠️ קטן"

    lines = [
        f"🏠 {b(r.get('location') or 'מיקום לא ברור', channel)} · {price_str}",
        f"🛏 {rooms_str}",
        "",
        f"🚗 {r.get('drive') or 'לא נותח'}",
        f"🏫 {r.get('kids') or 'לא צוין'}",
    ]
    if r.get("highlights"):
        lines += ["", f"📝 {r['highlights']}"]
    if r.get("verdict"):
        lines += [f"💡 {b(r['verdict'], channel)}"]
    if url:
        lines += ["", f"🔗 {url}"]
    return "\n".join(lines)


def send_alert(result, url):
    """מנסה את ערוצי השליחה לפי הסדר. מחזיר True אם אחד מהם הצליח."""
    if DRY_RUN:
        log("--- [DRY RUN] היה נשלח: ---\n"
            + format_message(result, url, "green") + "\n---")
        return True
    ok, channel = notifier.send(lambda ch: format_message(result, url, ch), log=log)
    if ok and channel != config.NOTIFY_CHANNELS[0]:
        log(f"  ⚠️ נשלח דרך {channel} (הערוץ הראשי לא זמין)")
    return ok


# ---------------------------------------------------------------------------
def main():
    if not DRY_RUN:
        channels = notifier.configured_channels()
        if not channels:
            log("אין אף ערוץ שליחה מוגדר (בדוק את הסודות של Green API) — עוצר.")
            sys.exit(1)
        log(f"ערוצי שליחה זמינים: {', '.join(channels)}")
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        log("אין אף מפתח AI (GEMINI_API_KEY / GROQ_API_KEY) — עוצר.")
        sys.exit(1)

    seen = load_seen()
    log(f"בזיכרון: {len(seen)} מודעות שכבר טופלו.")

    items = run_apify_task()
    if not items:
        log("אין מה לנתח.")
        return

    # סינון מקומי לפני שמבזבזים קריאות AI
    queue = []
    stats = {"short": 0, "dup": 0, "blocked": 0}
    for item in items:
        # קבוצה סגורה מחזירה פריט-שגיאה במקום פוסטים. שווה להצעיק את זה,
        # אחרת זה נראה כאילו פשוט אין מודעות חדשות.
        if item.get("error"):
            stats["blocked"] += 1
            log(f"⚠️ קבוצה לא נגישה: {item.get('url', '?')}")
            log(f"   {item.get('errorDescription') or item['error']}")
            continue

        text = extract_text(item)
        url = extract_url(item)
        if len(text) < config.MIN_POST_LENGTH:
            stats["short"] += 1
            continue
        key = post_key(text, url)
        if key in seen:
            stats["dup"] += 1
            continue
        queue.append((key, text, url))

    if len(queue) > config.MAX_POSTS_PER_RUN:
        log(f"⚠️ {len(queue)} פוסטים חדשים — מנתח רק {config.MAX_POSTS_PER_RUN} "
            f"הראשונים. השאר יטופלו בהרצה הבאה.")
        queue = queue[: config.MAX_POSTS_PER_RUN]

    log(f"לניתוח: {len(queue)} | כפולים: {stats['dup']} | קצרים מדי: {stats['short']}"
        + (f" | קבוצות חסומות: {stats['blocked']}" if stats["blocked"] else ""))

    sent = rejected = failed = 0
    now = datetime.now(timezone.utc).isoformat()

    for i, (key, text, url) in enumerate(queue, start=1):
        result = analyze_with_gemini(text)
        if result is None:
            result = analyze_with_groq(text)

        if result is None:
            failed += 1
            log(f"[{i}/{len(queue)}] ❌ הניתוח נכשל — לא מסמן כנקרא, ננסה שוב בהרצה הבאה.")
            time.sleep(config.SLEEP_BETWEEN_CALLS)
            continue

        seen[key] = now  # נותח בהצלחה — לא לנתח שוב גם אם נדחה

        ok, reason = enforce_rules(result)
        if not ok:
            rejected += 1
            log(f"[{i}/{len(queue)}] ⏭️ {reason}")
        else:
            if send_alert(result, url):
                sent += 1
                log(f"[{i}/{len(queue)}] ✅ נשלח — {result.get('location')} "
                    f"{result.get('price')} ₪")
            else:
                failed += 1
                del seen[key]  # לא נשלח בפועל — שיינתן צ'אנס נוסף

        time.sleep(config.SLEEP_BETWEEN_CALLS)

    if not DRY_RUN:
        save_seen(seen)

    log(f"\n📊 סיכום: נשלחו {sent} | נדחו {rejected} | נכשלו {failed} | "
        f"כפולים {stats['dup']} | קצרים {stats['short']} | חסומות {stats['blocked']}")


if __name__ == "__main__":
    main()
