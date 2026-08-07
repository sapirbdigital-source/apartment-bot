# -*- coding: utf-8 -*-
"""
בדיקת הסינון בלי לגעת ב-Apify וב-Telegram.

    python test_local.py

מריץ את הפרומפט על מודעות דוגמה שמכסות את מקרי הקצה, ומדפיס
מה היה נשלח ומה נדחה. עולה כמה אגורות, חוסך הרבה קרדיטים של Apify.

לבדיקה על מודעות אמיתיות: שים אותן ב-sample_posts.json כרשימת מחרוזות.
"""

import json
import time

import bot
import config

SAMPLES = [
    # אמורה לעבור נקי
    "להשכרה במבשרת ציון, 3 חדרים משופצת, קומה 1 מתוך 3, מרפסת שמש, חניה בטאבו, "
    "ממ\"ד. 3,900 ש\"ח כולל ועד. כניסה ב-1.9. מתאים למשפחה. 052-1234567",

    # מעל התקציב אבל בטווח הגמיש → אמורה לעבור עם דגל
    "דירת 3.5 חדרים באבו גוש להשכרה, נוף מדהים, 4,300 ש\"ח. חניה פרטית, "
    "קרוב לבית ספר. כניסה מיידית.",

    # הרבה מעל התקציב → אמורה להיחסם
    "דירת 4 חדרים במבשרת, ממוזגת, 6,800 ש\"ח לחודש.",

    # שותפים → אמורה להיחסם
    "מחפשים שותף/ה לדירת 3 חדרים במבשרת ציון. החדר הפנוי 1,800 ש\"ח כולל הכל.",

    # מחפשת ולא מציעה → אמורה להיחסם
    "היי, מחפשת דירת 3 חדרים באזור מבשרת עד 4,000 ש\"ח. אמא + 2 ילדים. תודה!",

    # למכירה → אמורה להיחסם
    "למכירה במבשרת ציון דירת 4 חדרים, 2,750,000 ש\"ח, גמיש למציע רציני.",

    # אזור לא רלוונטי → אמורה להיחסם
    "להשכרה בתל אביב, 3 חדרים ברוטשילד, 4,000 ש\"ח. הזדמנות!",

    # יחידת דיור בלי מחיר → תלוי ב-SEND_IF_NO_PRICE
    "יחידת דיור 2.5 חדרים בבית זית, כניסה נפרדת, חצר, חניה. מחיר בפרטי.",

    # סאבלט → אמורה להיחסם
    "סאבלט לחודשיים במבשרת, 3 חדרים מרוהטת קומפלט, 4,000 ש\"ח לחודש.",
]


def main():
    try:
        with open("sample_posts.json", encoding="utf-8") as f:
            posts = json.load(f)
        print(f"קורא {len(posts)} מודעות מ-sample_posts.json\n")
    except FileNotFoundError:
        posts = SAMPLES
        print(f"מריץ על {len(posts)} מודעות דוגמה מובנות\n")

    passed = 0
    for i, text in enumerate(posts, start=1):
        preview = text.replace("\n", " ")[:70]
        print(f"[{i}/{len(posts)}] {preview}...")

        result = bot.analyze_with_gemini(text) or bot.analyze_with_groq(text)
        if result is None:
            print("    ❌ הניתוח נכשל (בדוק שיש מפתח API תקין)\n")
            continue

        ok, reason = bot.enforce_rules(result)
        if ok:
            passed += 1
            print("    ✅ נשלח:")
            preview = bot.format_message(result, "https://example.com/post", "email")
            print("    " + preview.replace("\n", "\n    "))
        else:
            print(f"    ⏭️ נדחה: {reason}")
        print()
        time.sleep(config.SLEEP_BETWEEN_CALLS)

    print(f"סה\"כ: {passed}/{len(posts)} עברו.")


if __name__ == "__main__":
    main()
