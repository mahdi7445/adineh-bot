"""هشدارهای هوشمند مدیر: مواردی که امروز نیاز به توجه دارند، مرتب‌شده بر اساس اهمیت، هرکدام با دکمهٔ رسیدگی.
هر بخش جداگانه محافظت می‌شود تا خطا در یکی، کل مرکز کنترل را خراب نکند."""
import logging

from . import attlogic, db, jdate, sms

log = logging.getLogger(__name__)


def _incidents(day, hour):
    out = []
    urgent = db.one("SELECT COUNT(*) c FROM incidents WHERE status='open' AND severity='urgent'")["c"]
    if urgent:
        out.append((1, f"🔴 {urgent} اتفاق فوری باز", "inc:list:open:0"))
    important = db.one("SELECT COUNT(*) c FROM incidents WHERE status='open' AND severity='important'")["c"]
    if important:
        out.append((2, f"🟡 {important} اتفاق مهم باز", "inc:list:open:0"))
    return out


def _attendance(day, hour):
    if attlogic.off_reason(day) or hour < 10:
        return []
    miss = attlogic.day_counts(day).get(None, 0)
    return [(1 if hour >= 13 else 2, f"⬜ حضور و غیاب امروز برای {miss} نفر ثبت نشده", f"rc:day:{day}")] if miss else []


def _leaves(day, hour):
    pend = db.one("SELECT COUNT(*) c FROM leaves WHERE status='pending'")["c"]
    return [(2, f"🏖 {pend} درخواست مرخصی منتظر تأیید", "lv:pend")] if pend else []


def _tasks(day, hour):
    out = []
    hhmm = jdate.now().strftime("%H:%M")
    late = db.one("SELECT COUNT(*) c FROM tasks WHERE day=? AND status!='done' AND due IS NOT NULL AND due<?", (day, hhmm))["c"]
    if late:
        out.append((2, f"⏰ {late} وظیفهٔ امروز از مهلت گذشته", f"tk:all:{day}"))
    old = db.one("SELECT COUNT(*) c FROM tasks WHERE day<? AND status!='done' AND day>=?", (day, jdate.add_days(day, -7)))["c"]
    if old:
        out.append((3, f"📌 {old} وظیفهٔ انجام‌نشدهٔ ۷ روز اخیر", f"tk:all:{jdate.add_days(day, -1)}"))
    return out


def _reports(day, hour):
    if attlogic.off_reason(day) or hour < 12:
        return []
    done = {r["staff_id"] for r in db.q("SELECT staff_id FROM reports WHERE day=?", (day,))}
    miss = [s for s in db.att_roster() if s["id"] not in done and attlogic.eff_status(s["id"], day) in (None, "present")]
    return [(3, f"📝 {len(miss)} نفر هنوز گزارش امروز را نداده‌اند", f"rep:day:{day}")] if miss else []


def _staff_links(day, hour):
    n = db.one("SELECT COUNT(*) c FROM staff WHERE active=1 AND tg_id IS NULL")["c"]
    return [(3, f"🔗 {n} نفر هنوز به تلگرام وصل نشده‌اند (کد دعوت)", "st:menu")] if n else []


def _upcoming(day, hour):
    out = []
    for k in range(0, 4):
        d = jdate.add_days(day, k)
        for e in db.q("SELECT * FROM events WHERE day=? ORDER BY id", (d,)):
            when = "امروز" if k == 0 else ("فردا" if k == 1 else f"{k} روز دیگر")
            out.append((3, f"📅 {when}: {e['title']}", "evt:menu"))
    for k in range(1, 8):
        h = db.one("SELECT title FROM holidays WHERE day=?", (jdate.add_days(day, k),))
        if h:
            out.append((3, f"🎌 {k} روز دیگر تعطیل رسمی: {h['title']}", "hol:menu"))
            break
    return out


def _sms(day, hour):
    return [] if sms.configured() else [(3, "📲 سرویس پیامک هنوز تنظیم نشده", "sms:set")]


def alerts(day=None, hour=None):
    """→ فهرست (اهمیت 1=فوری 2=مهم 3=اطلاع، متن، callback)."""
    day = day or jdate.today()
    hour = jdate.now().hour if hour is None else hour
    out = []
    for fn in (_incidents, _attendance, _leaves, _tasks, _reports, _staff_links, _upcoming, _sms):
        try:
            out += fn(day, hour)
        except Exception:
            log.exception("alert section failed: %s", fn.__name__)
    out.sort(key=lambda x: x[0])
    return out
