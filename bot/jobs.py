"""کارهای زمان‌بندی‌شده: یادآوری رویدادها، خروج فراموش‌شده، سررسید اقساط، پشتیبان‌گیری روزانه."""
import logging
from datetime import time

from . import config, db, digest, jdate
from .core import esc, notify, notify_admins
from .mod_staff import send_backup

log = logging.getLogger("adineh.jobs")


async def events_reminder(context):
    today = jdate.today()
    tomorrow = jdate.add_days(today, 1)
    for e in db.q("SELECT * FROM events WHERE remind=1 AND day IN (?,?) ORDER BY day", (today, tomorrow)):
        when = "امروز" if e["day"] == today else "فردا"
        await notify_admins(context.bot, f"🔔 <b>یادآوری رویداد</b> ({when} — {jdate.fmt(e['day'])})\n{esc(e['title'])}")


async def forgot_checkout(context):
    """ورودِ بدون خروج را به خود فرد یادآوری می‌کند."""
    for r in db.q("SELECT a.*, s.tg_id, s.name FROM attendance a JOIN staff s ON s.id=a.staff_id "
                  "WHERE a.t_out IS NULL AND a.day=? AND s.tg_id IS NOT NULL", (jdate.today(),)):
        await notify(context.bot, r["tg_id"], "🔔 ورود امروز شما ثبت شده ولی خروج ثبت نشده است. اگر رفته‌اید از منو «ثبت خروج» را بزنید.")


async def open_checkout_report(context):
    rows = db.q("SELECT a.*, s.name FROM attendance a JOIN staff s ON s.id=a.staff_id WHERE a.t_out IS NULL AND a.day=?", (jdate.today(),))
    if rows:
        await notify_admins(context.bot, "⚠️ <b>ورود بدون خروج امروز</b>\n" + "\n".join(f"• {esc(r['name'])} (ورود {r['t_in']})" for r in rows))


async def loans_due(context):
    """روز اول هر ماه شمسی: فهرست اقساط ماه."""
    if jdate.j_today()[2] != 1:
        return
    from .mod_money import loan_stats
    from .core import money
    lines = []
    for l in db.q("SELECT * FROM loans WHERE status='active'"):
        _, _, rem, _, nxt = loan_stats(l)
        if rem > 0:
            lines.append(f"• {esc(db.staff_name(l['staff_id']))}: قسط {money(min(l['installment'], rem))} (مانده {money(rem)})")
    if lines:
        await notify_admins(context.bot, "💰 <b>اقساط این ماه</b>\n" + "\n".join(lines))


async def daily_backup(context):
    for t in db.admin_tg_ids():
        try:
            await send_backup(context.bot, t)
        except Exception as e:
            log.warning("backup failed: %s", type(e).__name__)


async def send_digest(bot, mode="pm"):
    """خلاصهٔ روز فقط یک‌بار در روز (ساعت ۱۳:۰۰)؛ حتی با ری‌استارت ربات تکرار نمی‌شود."""
    day = jdate.today()
    key = f"dig_{day}"
    if db.kv_get(key):
        return
    db.kv_set(key, "1")
    from .mod_tasks import spawn_templates
    spawn_templates(day)
    for s in db.q("SELECT * FROM staff WHERE active=1 AND tg_id IS NOT NULL"):
        perms = db.perms_of(s)
        if "dig_recv" not in perms:
            continue
        try:
            txt = digest.build(s, perms, bool(s["is_admin"]), mode, day)
        except Exception as e:
            log.warning("digest failed: %s", type(e).__name__)
            continue
        if txt:
            await notify(bot, s["tg_id"], f"📋 <b>خلاصهٔ روز</b> — {jdate.fmt_long(day)}\n\n{txt}", protect=True)


async def digest_tick(context):
    """هر دقیقه: اگر ساعت ارسال رسیده و خلاصهٔ امروز نرفته (و روشن است) می‌فرستد؛ هر روز فقط یک‌بار."""
    from .mod_cal import dig_on, dig_time
    if dig_on() and jdate.hhmm() >= dig_time():
        await send_digest(context.bot)


async def spawn_tasks(context):
    from .mod_tasks import spawn_templates
    spawn_templates()


async def sms_queue(context):
    from .mod_sms import process_queue
    await process_queue(context.bot)


async def catch_up(context):
    """بعد از ری‌استارت (چرخهٔ ۶ ساعتهٔ گیت‌هاب): اگر ساعت ۱۳ گذشته و خلاصهٔ امروز نرفته، همین حالا می‌رود."""
    now = jdate.now()
    from .mod_tasks import spawn_templates
    spawn_templates()
    await digest_tick(context)


async def heartbeat(context):
    db.kv_set("hb", str(int(jdate.now().timestamp())))


async def startup_notice(context):
    """اگر ربات بیش از ۲۰ دقیقه خاموش بوده، به مدیران اطلاع می‌دهد (و از این لحظه ضربان ثبت می‌شود)."""
    last = db.kv_get("hb")
    await heartbeat(context)
    if last and last.isdigit():
        gap = (int(jdate.now().timestamp()) - int(last)) // 60
        if gap >= 20:
            await notify_admins(context.bot, f"⚠️ ربات حدود {gap} دقیقه خاموش بود و دوباره فعال شد. پیام‌های این مدت پردازش می‌شوند.")


def schedule(app):
    jq = app.job_queue
    tz = config.TZ
    jq.run_daily(events_reminder, time(8, 0, tzinfo=tz), name="events")
    jq.run_daily(open_checkout_report, time(23, 0, tzinfo=tz), name="open_out")
    jq.run_daily(loans_due, time(9, 0, tzinfo=tz), name="loans_due")
    jq.run_repeating(digest_tick, interval=60, first=30, name="dig_day")   # پیش‌فرض ۱۳:۰۰ (قابل تنظیم)
    jq.run_repeating(heartbeat, interval=60, first=60, name="hb")
    jq.run_once(startup_notice, 5, name="startup")
    jq.run_daily(spawn_tasks, time(0, 10, tzinfo=tz), name="spawn")
    jq.run_repeating(sms_queue, interval=60, first=20, name="sms_q")
    jq.run_once(catch_up, 15, name="catch_up")
    jq.run_daily(daily_backup, time(23, 45, tzinfo=tz), name="backup")
