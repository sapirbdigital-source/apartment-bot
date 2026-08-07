# -*- coding: utf-8 -*-
"""
בדיקת ערוץ ההתראות — לפני שמריצים את הבוט המלא.

    python test_notify.py

שולח דייג'סט בדיקה עם שתי דירות דמה, בדיוק בפורמט האמיתי.
אם הוא לא מגיע, אין טעם להמשיך — כל השאר יעבוד והמודעות ילכו לאיבוד.
"""

import notifier

DEMO = [
    ({
        "location": "בדיקה · מבשרת ציון",
        "price": 3900,
        "rooms": 3,
        "drive": "22 דקות למרכז ירושלים, חניה חופשית ברחוב",
        "kids": "בית ספר יסודי 300 מ׳, חטיבה 1.2 ק״מ, פארק ליד",
        "highlights": "זו הודעת בדיקה — לא מודעה אמיתית.",
        "verdict": "אם קיבלת את זה, החיבור עובד",
    }, "https://example.com/1"),
    ({
        "location": "בדיקה · אבו גוש",
        "price": 4300,
        "rooms": 2.5,
        "over_budget": True,
        "small": True,
        "drive": "28 דקות לירושלים, חניה פרטית",
        "kids": "יסודי בכפר, הסעה לחטיבה",
        "highlights": "הדוגמה הזו מראה איך נראית דירה עם דגלי אזהרה.",
        "verdict": "שווה לבדוק למרות החריגה",
    }, "https://example.com/2"),
]


def main():
    import bot  # אחרי notifier, כדי שהודעות השגיאה יהיו בסדר הנכון

    ready = notifier.configured_channels()
    if not ready:
        print("❌ אין אף ערוץ מוגדר.")
        print("   למייל צריך:  SMTP_USER, SMTP_PASSWORD, EMAIL_TO")
        print("   ל-ntfy צריך: NTFY_TOPIC")
        print("   ל-Green צריך: WHATSAPP_TO, GREEN_API_INSTANCE_ID, GREEN_API_TOKEN")
        return

    print(f"ערוצים מוגדרים, לפי סדר הניסיון: {', '.join(ready)}")
    print()

    ok = bot.send_digest(DEMO)

    if ok:
        print("\n✅ נשלח. בדוק שההודעה הגיעה בפועל.")
        print("   מייל? אם לא בתיבה — לבדוק בספאם / קידומי מכירות.")
    else:
        print("\n❌ כל הערוצים נכשלו. ראה את השגיאות למעלה.")


if __name__ == "__main__":
    main()
