"""کارهای زمان‌بندی‌شده: یادآوری رویدادها، خروج فراموش‌شده، سررسید اقساط، پشتیبان‌گیری روزانه."""
import logging
from datetime import time

from . import config, db, jdate
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


def schedule(app):
    jq = app.job_queue
    tz = config.TZ
    jq.run_daily(events_reminder, time(8, 0, tzinfo=tz), name="events")
    jq.run_daily(forgot_checkout, time(21, 30, tzinfo=tz), name="forgot")
    jq.run_daily(open_checkout_report, time(23, 0, tzinfo=tz), name="open_out")
    jq.run_daily(loans_due, time(9, 0, tzinfo=tz), name="loans_due")
    jq.run_daily(daily_backup, time(23, 45, tzinfo=tz), name="backup")
