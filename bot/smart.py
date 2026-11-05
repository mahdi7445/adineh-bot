"""هشدارهای هوشمند مدیر: مواردی که امروز نیاز به توجه دارند، مرتب‌شده بر اساس اهمیت، هرکدام با دکمهٔ رسیدگی."""
from . import attlogic, db, jdate, sms


def alerts(day=None, hour=None):
    """→ فهرست (اهمیت 1=فوری 2=مهم 3=اطلاع، متن، callback). hour برای تست قابل تنظیم است."""
    day = day or jdate.today()
    now = jdate.now()
    hour = now.hour if hour is None else hour
    off = attlogic.off_reason(day)
    out = []

    urgent = db.one("SELECT COUNT(*) c FROM incidents WHERE status='open' AND severity='urgent'")["c"]
    if urgent:
        out.append((1, f"🔴 {urgent} اتفاق فوری باز", "inc:list:open:0"))
    important = db.one("SELECT COUNT(*) c FROM incidents WHERE status='open' AND severity='important'")["c"]
    if important:
        out.append((2, f"🟡 {important} اتفاق مهم باز", "inc:list:open:0"))

    if not off and hour >= 10:
        miss = attlogic.day_counts(day).get(None, 0)
        if miss:
            out.append((1 if hour >= 13 else 2, f"⬜ حضور و غیاب امروز برای {miss} نفر ثبت نشده", f"rc:day:{day}"))

    pend = db.one("SELECT COUNT(*) c FROM leaves WHERE status='pending'")["c"]
    if pend:
        out.append((2, f"🏖 {pend} درخواست مرخصی منتظر تأیید", "lv:pend"))

    hhmm = now.strftime("%H:%M")
    late = db.one("SELECT COUNT(*) c FROM tasks WHERE day=? AND status!='done' AND due IS NOT NULL AND due<?", (day, hhmm))["c"]
    if late:
        out.append((2, f"⏰ {late} وظیفهٔ امروز از مهلت گذشته", f"tk:all:{day}"))
    old = db.one("SELECT COUNT(*) c FROM tasks WHERE day<? AND status!='done' AND day>=?", (day, jdate.add_days(day, -7)))["c"]
    if old:
        out.append((3, f"📌 {old} وظیفهٔ انجام‌نشدهٔ ۷ روز اخیر", f"tk:all:{jdate.add_days(day, -1)}"))

    if not off and hour >= 12:
        ros = db.roster()
        done = {r["staff_id"] for r in db.q("SELECT staff_id FROM reports WHERE day=?", (day,))}
        miss = [s for s in ros if s["id"] not in done and attlogic.eff_status(s["id"], day) in (None, "present")]
        if miss:
            out.append((3, f"📝 {len(miss)} نفر هنوز گزارش امروز را نداده‌اند", f"rep:day:{day}"))

    unlinked = db.one("SELECT COUNT(*) c FROM staff WHERE active=1 AND tg_id IS NULL")["c"]
    if unlinked:
        out.append((3, f"🔗 {unlinked} نفر هنوز به تلگرام وصل نشده‌اند (کد دعوت)", "st:menu"))

    for k in range(0, 4):
        d = jdate.add_days(day, k)
        for e in db.q("SELECT * FROM events WHERE day=? ORDER BY id", (d,)):
            when = "امروز" if k == 0 else ("فردا" if k == 1 else f"{k} روز دیگر")
            out.append((3, f"📅 {when}: {e['title']}", "evt:menu"))
    for k in range(1, 8):
        d = jdate.add_days(day, k)
        h = db.one("SELECT title FROM holidays WHERE day=?", (d,))
        if h:
            out.append((3, f"🎌 {k} روز دیگر تعطیل رسمی: {h['title']}", "hol:menu"))
            break

    if not sms.configured():
        out.append((3, "📲 سرویس پیامک هنوز تنظیم نشده", "sms:set"))
    out.sort(key=lambda x: x[0])
    return out
