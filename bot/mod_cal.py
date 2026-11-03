"""تعطیلات رسمی و ساعت کار پیش‌فرض. جمعه‌ها همیشه تعطیل‌اند؛ تعطیلی‌های رسمی را مدیر حضور ثبت می‌کند."""
from datetime import date, timedelta

from telegram import InlineKeyboardButton as B

from . import attlogic, db, jdate
from .core import Ctx, Step, back_row, define_flow, esc, fa, goto, p_date, p_text, p_time, route, start_flow


def _year(y):
    return int(y) if y else jdate.j_today()[0]


@route("hol:menu", perm="att_manage")
async def hol_menu(ctx: Ctx, y=None, page="0"):
    y, page = _year(y), int(page)
    d1, d2 = jdate.year_bounds(y)
    rows = db.q("SELECT * FROM holidays WHERE day BETWEEN ? AND ? ORDER BY day", (d1, d2))
    per = 12
    part = rows[page * per:(page + 1) * per]
    ws, we = attlogic.work_hours()
    lines = [f"• {jdate.fmt(r['day'])} {jdate.weekday(r['day'])} — {esc(r['title'])}" for r in part]
    kb = [[B(f"🗑 {jdate.fmt(r['day'])} {r['title'][:20]}", callback_data=f"hol:del:{r['day']}")] for r in part]
    nav = []
    if page > 0:
        nav.append(B("◀️ قبل", callback_data=f"hol:menu:{y}:{page - 1}"))
    if (page + 1) * per < len(rows):
        nav.append(B("بعد ▶️", callback_data=f"hol:menu:{y}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([B("◀️ سال قبل", callback_data=f"hol:menu:{y - 1}:0"), B("سال بعد ▶️", callback_data=f"hol:menu:{y + 1}:0")])
    kb.append([B("➕ ثبت تعطیلی رسمی", callback_data="hol:add"), B("🕗 تغییر ساعت کار", callback_data="wh:set")])
    kb.append(back_row("rc:day"))
    await ctx.show(f"🎌 <b>تعطیلات رسمی {fa(y)}</b>\n🕗 ساعت کار پیش‌فرض: <b>{ws}</b> تا <b>{we}</b>\n"
                   "💤 جمعه‌ها همیشه تعطیل‌اند و نیازی به ثبت ندارند.\n\n" + ("\n".join(lines) or "تعطیلی رسمی ثبت نشده."), kb)


@route("hol:add", perm="att_manage")
async def hol_add(ctx: Ctx):
    await start_flow(ctx, "hol_add")


def _parse_title(t):
    t = t.strip()
    if not t:
        raise ValueError("عنوان را بنویسید.")
    return t[:60]


async def _hol_done(ctx: Ctx, d):
    d1 = date.fromisoformat(d["d1"])
    d2 = date.fromisoformat(d.get("d2") or d["d1"])
    if d2 < d1:
        return await ctx.send("⚠️ تاریخ پایان قبل از شروع است.", [back_row("hol:menu")])
    if (d2 - d1).days > 30:
        return await ctx.send("⚠️ حداکثر ۳۱ روز پشت‌سرهم.", [back_row("hol:menu")])
    n, cur = 0, d1
    while cur <= d2:
        db.run("INSERT INTO holidays(day,title) VALUES(?,?) ON CONFLICT(day) DO UPDATE SET title=excluded.title", (cur.isoformat(), d["title"]))
        cur += timedelta(days=1)
        n += 1
    ctx.audit("holiday_add", f"{d['title']} {d['d1']} n={n}")
    await goto(ctx, f"hol:menu:{jdate.to_j(d['d1'])[0]}:0")


define_flow("hol_add", [
    Step("title", "🎌 عنوان تعطیلی (مثلاً «تاسوعا»):", _parse_title),
    Step("d1", "📅 تاریخ (یا روز اول):", p_date, kind="date"),
    Step("d2", "📅 اگر چند روز است، روز آخر را بزنید؛ وگرنه «رد کردن»:", p_date, kind="date", optional=True),
], _hol_done, "hol:menu")


@route("hol:del", perm="att_manage")
async def hol_del(ctx: Ctx, day):
    db.run("DELETE FROM holidays WHERE day=?", (day,))
    ctx.audit("holiday_del", day)
    await hol_menu(ctx, jdate.to_j(day)[0], 0)


@route("wh:set", perm="att_manage")
async def wh_set(ctx: Ctx):
    await start_flow(ctx, "wh_set")


async def _wh_done(ctx: Ctx, d):
    if d["a"] >= d["b"]:
        return await ctx.send("⚠️ ساعت پایان باید بعد از شروع باشد.", [back_row("hol:menu")])
    db.kv_set("wh_start", d["a"])
    db.kv_set("wh_end", d["b"])
    ctx.audit("work_hours", f"{d['a']}-{d['b']}")
    await goto(ctx, "hol:menu")


define_flow("wh_set", [
    Step("a", "🕗 ساعت شروع کار پیش‌فرض:", p_time, kind="time"),
    Step("b", "🕐 ساعت پایان کار پیش‌فرض:", p_time, kind="time"),
], _wh_done, "hol:menu")
