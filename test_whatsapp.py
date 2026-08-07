# -*- coding: utf-8 -*-
"""
בדיקת חיבור הוואטסאפ — לפני שמריצים את הבוט המלא.

    python test_whatsapp.py

שולח הודעת בדיקה אחת. אם היא לא מגיעה, אין טעם להמשיך —
כל השאר יעבוד והמודעות פשוט ילכו לאיבוד.
"""

import notifier

DEMO = {
    "location": "בדיקה · מבשרת ציון",
    "price": 3900,
    "rooms": 3,
    "drive": "22 דקות למרכז ירושלים, חניה חופשית ברחוב",
    "kids": "בית ספר יסודי 300 מ׳, חטיבה 1.2 ק״מ, פארק ליד",
    "highlights": "זו הודעת בדיקה — לא מודעה אמיתית.",
    "verdict": "אם קיבלת את זה בוואטסאפ, החיבור עובד ✅",
}


def main():
    import bot  # מיובא כאן כדי שההודעה למעלה תודפס קודם

    ready = notifier.configured_channels()
    if not ready:
        print("❌ אין אף ערוץ מוגדר.")
        print("   בדוק שהוגדרו: WHATSAPP_TO, GREEN_API_INSTANCE_ID, GREEN_API_TOKEN")
        return

    print(f"ערוצים מוגדרים: {', '.join(ready)}")
    print(f"שולח אל: {notifier.normalize_phone(notifier.WHATSAPP_TO)}")
    print()

    ok, channel = notifier.send(
        lambda ch: bot.format_message(DEMO, "https://example.com", ch),
        log=print,
    )

    if ok:
        print(f"\n✅ נשלח דרך {channel}. בדוק שההודעה הגיעה בפועל.")
        if channel == "green":
            print("   אם היא לא הגיעה — ב-Green API בדוק שהסטטוס 'authorized'.")
    else:
        print("\n❌ כל הערוצים נכשלו. ראה את השגיאות למעלה.")


if __name__ == "__main__":
    main()
