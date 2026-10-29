"""منوی خروجی اکسل: ورود/خروج (روز، ماه، سال)، وام، واریزی، مددجویان، امور و اتفاقات."""
import io
import re

from telegram import InlineKeyboardButton as B

from . import db, exports, jdate
from .core import DATE_CHOICES, Ctx, Step, back_row, define_flow, esc, p_date, route, start_flow


async def _send_xlsx(ctx: Ctx, data: bytes, name: str, caption: str):
    bio = io.BytesIO(data)
    bio.name = name
    await ctx.update.effective_chat.send_document(bio, caption=caption)
    ctx.audit("export", name)
    await ctx.send("✅ فایل ارسال شد.", [back_row("exp:menu")])


@route("exp:menu", perm="export")
async def exp_menu(ctx: Ctx):
    await ctx.show("📊 <b>خروجی اکسل</b>\nتاریخ‌ها شمسی هستند و فایل‌ها راست‌به‌چپ‌اند.", [
        [B("🕘 ورود/خروج روزانه", callback_data="exp:att:day"), B("🗓 ماهانه", callback_data="exp:att:month")],
        [B("📆 سالانه", callback_data="exp:att:year")],
        [B("💰 وام‌ها", callback_data="exp:loans"), B("💵 واریزی‌ها", callback_data="exp:pay")],
        [B("🧒 مددجویان", callback_data="exp:cli"), B("📋 امور و اتفاقات", callback_data="exp:inc")],
        back_row()])


def _scope_choices(_d):
    return [("👥 همه پرسنل", "all")] + [(s["name"], str(s["id"])) for s in db.active_staff()]


def _parse_scope(t):
    return None if t == "all" else int(t)


def _parse_ym(t):
    s = jdate.norm(t)
    m = re.match(r"^(\d{4})[/\-.](\d{1,2})$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1300 <= y <= 1500 and 1 <= mo <= 12:
            return (y, mo)
    raise ValueError("سال و ماه را مثل 1405/08 بنویسید.")


def _parse_y(t):
    s = jdate.norm(t)
    if s.isdigit() and 1300 <= int(s) <= 1500:
        return int(s)
    raise ValueError("سال شمسی را مثل 1405 بنویسید.")


def _month_choices(_d):
    y, m, _ = jdate.j_today()
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    return [(f"این ماه ({jdate.MONTHS[m - 1]})", f"{y}/{m}"), (f"ماه قبل ({jdate.MONTHS[pm - 1]})", f"{py}/{pm}")]


def _year_choices(_d):
    y = jdate.j_today()[0]
    return [(f"سال {y}", str(y)), (f"سال {y - 1}", str(y - 1))]


@route("exp:att", perm="export")
async def exp_att(ctx: Ctx, kind):
    await start_flow(ctx, f"exp_att_{kind}")


async def _day_done(ctx, d):
    await ctx.answer("در حال ساخت فایل…")
    await _send_xlsx(ctx, exports.att_day(d["day"], d["scope"]), f"attendance-{jdate.fmt(d['day']).replace('/', '-')}.xlsx",
                     f"🕘 ورود و خروج {jdate.fmt(d['day'])}")


async def _month_done(ctx, d):
    y, m = d["ym"]
    await _send_xlsx(ctx, exports.att_month(y, m, d["scope"]), f"attendance-{y}-{m:02d}.xlsx", f"🗓 ورود/خروج {jdate.MONTHS[m - 1]} {y}")


async def _year_done(ctx, d):
    await _send_xlsx(ctx, exports.att_year(d["year"], d["scope"]), f"attendance-{d['year']}.xlsx", f"📆 ورود/خروج سال {d['year']}")


SCOPE = Step("scope", "👤 برای چه کسی؟", _parse_scope, _scope_choices)
define_flow("exp_att_day", [SCOPE, Step("day", "📅 تاریخ روز (شمسی):", p_date, DATE_CHOICES)], _day_done, "exp:menu")
define_flow("exp_att_month", [SCOPE, Step("ym", "🗓 ماه را انتخاب کنید یا بنویسید (مثال 1405/08):", _parse_ym, _month_choices)], _month_done, "exp:menu")
define_flow("exp_att_year", [SCOPE, Step("year", "📆 سال شمسی:", lambda t: _parse_y(t), _year_choices)], _year_done, "exp:menu")


@route("exp:loans", perm="export")
async def exp_loans(ctx: Ctx):
    await ctx.answer("در حال ساخت فایل…")
    await _send_xlsx(ctx, exports.loans(), "loans.xlsx", "💰 وام‌ها و پرداخت اقساط")


@route("exp:pay", perm="export")
async def exp_pay(ctx: Ctx):
    await start_flow(ctx, "exp_pay")


async def _pay_done(ctx, d):
    await _send_xlsx(ctx, exports.payouts(d["year"]), f"payouts-{d['year']}.xlsx", f"💵 واریزی‌های سال {d['year']}")


define_flow("exp_pay", [Step("year", "📆 سال شمسی:", lambda t: _parse_y(t), _year_choices)], _pay_done, "exp:menu")


@route("exp:cli", perm=("export", "cli_manage"))
async def exp_cli(ctx: Ctx):
    if not ctx.can("export"):
        return await ctx.answer("⛔ دسترسی ندارید", True)
    await ctx.answer("در حال ساخت فایل…")
    await _send_xlsx(ctx, exports.clients(), "clients.xlsx", "🧒 پرونده مددجویان")


@route("exp:cl1", perm="export")
async def exp_cl1(ctx: Ctx, cid):
    await ctx.answer("در حال ساخت فایل…")
    await _send_xlsx(ctx, exports.clients(int(cid)), f"client-{cid}.xlsx", "🧒 پرونده مددجو")


@route("exp:inc", perm="export")
async def exp_inc(ctx: Ctx):
    await ctx.answer("در حال ساخت فایل…")
    await _send_xlsx(ctx, exports.incidents(), "incidents.xlsx", "📋 امور و اتفاقات")
