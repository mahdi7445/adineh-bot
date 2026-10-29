"""ورود/خروج پرسنل، مدیریت دستی ساعات توسط ادمین، گزارش روزانه و مرخصی."""
from telegram import InlineKeyboardButton as B

from . import db, jdate
from .core import (DATE_CHOICES, Ctx, Step, back_row, define_flow, esc, goto, grid, notify, notify_admins,
                   p_date, p_text, p_time, p_time_or_clear, pager, route, start_attach, start_flow)


def _rec_line(r) -> str:
    h = jdate.hours(r["t_in"], r["t_out"])
    out = r["t_out"] or "—"
    extra = f" ({jdate.hm(h)})" if r["t_out"] else " ⏳"
    src = " ✍️" if r["source"] == "admin" else ""
    note = f" — {esc(r['note'])}" if r["note"] else ""
    return f"🟢 {r['t_in'] or '—'}  →  🔴 {out}{extra}{src}{note}"


# ───────────── ورود و خروج خود فرد ─────────────
@route("att:menu", perm=("att_self", "att_manage"))
async def att_menu(ctx: Ctx):
    t = jdate.today()
    me = ctx.me["id"]
    recs = db.q("SELECT * FROM attendance WHERE staff_id=? AND day=? ORDER BY id", (me, t))
    opn = db.one("SELECT * FROM attendance WHERE staff_id=? AND t_out IS NULL AND day>=? ORDER BY id DESC",
                 (me, jdate.add_days(t, -1)))
    txt = [f"🕘 <b>ورود و خروج</b> — {jdate.fmt_long(t)}", ""]
    txt += [_rec_line(r) for r in recs] or ["امروز هنوز چیزی ثبت نشده."]
    if opn:
        txt.append(f"\n⏳ شما از ساعت {opn['t_in']} ({jdate.fmt(opn['day'])}) حاضر هستید.")
    kb = []
    if ctx.can("att_self"):
        kb.append([B("🚪 ثبت خروج", callback_data="att:out")] if opn else [B("✅ ثبت ورود", callback_data="att:in")])
        kb.append([B("📆 سوابق من (این ماه)", callback_data="att:mine")])
    if ctx.can("att_manage"):
        kb.append([B("⏱ مدیریت ساعات پرسنل", callback_data="am:menu")])
    kb.append(back_row())
    await ctx.show("\n".join(txt), kb)


@route("att:in", perm="att_self")
async def att_in(ctx: Ctx):
    t = jdate.today()
    if db.one("SELECT id FROM attendance WHERE staff_id=? AND t_out IS NULL AND day>=?", (ctx.me["id"], jdate.add_days(t, -1))):
        await ctx.answer("ورود قبلی شما هنوز بسته نشده است.", True)
        return await att_menu(ctx)
    db.run("INSERT INTO attendance(staff_id,day,t_in,source) VALUES(?,?,?,'self')", (ctx.me["id"], t, jdate.hhmm()))
    ctx.audit("att_in", jdate.hhmm())
    await ctx.answer(f"ورود ثبت شد ✅ {jdate.hhmm()}")
    await att_menu(ctx)


@route("att:out", perm="att_self")
async def att_out(ctx: Ctx):
    opn = db.one("SELECT * FROM attendance WHERE staff_id=? AND t_out IS NULL AND day>=? ORDER BY id DESC",
                 (ctx.me["id"], jdate.add_days(jdate.today(), -1)))
    if not opn:
        await ctx.answer("ورود بازی ندارید.", True)
        return await att_menu(ctx)
    db.run("UPDATE attendance SET t_out=? WHERE id=?", (jdate.hhmm(), opn["id"]))
    ctx.audit("att_out", jdate.hhmm())
    await ctx.answer(f"خروج ثبت شد 🚪 {jdate.hhmm()}")
    await att_menu(ctx)


def _month_lines(sid, jy, jm):
    s, e = jdate.month_bounds(jy, jm)
    rows = db.q("SELECT * FROM attendance WHERE staff_id=? AND day BETWEEN ? AND ? ORDER BY day, id", (sid, s, e))
    lines, total, days = [], 0.0, set()
    for r in rows:
        lines.append(f"{jdate.fmt(r['day'])} {jdate.weekday(r['day'])}: {_rec_line(r)}")
        total += jdate.hours(r["t_in"], r["t_out"])
        days.add(r["day"])
    return lines, total, len(days)


@route("att:mine", perm="att_self")
async def att_mine(ctx: Ctx, jy=None, jm=None):
    cy, cm, _ = jdate.j_today()
    jy, jm = int(jy or cy), int(jm or cm)
    lines, total, days = _month_lines(ctx.me["id"], jy, jm)
    py, pm = (jy, jm - 1) if jm > 1 else (jy - 1, 12)
    ny, nm = (jy, jm + 1) if jm < 12 else (jy + 1, 1)
    kb = [[B("◀️ ماه قبل", callback_data=f"att:mine:{py}:{pm}"), B("ماه بعد ▶️", callback_data=f"att:mine:{ny}:{nm}")],
          back_row("att:menu")]
    await ctx.show(f"📆 <b>سوابق {jdate.MONTHS[jm - 1]} {jy}</b>\n\n" + ("\n".join(lines) or "موردی نیست.")
                   + f"\n\n📊 روزهای حضور: {days} — جمع ساعت: {jdate.hm(total)}", kb)


# ───────────── مدیریت ساعات توسط ادمین ─────────────
@route("am:menu", perm="att_manage")
async def am_menu(ctx: Ctx):
    kb = grid([B(f"👤 {s['name']}", callback_data=f"am:day:{s['id']}:{jdate.today()}") for s in db.active_staff()])
    kb.insert(0, [B("📅 وضعیت همه پرسنل (امروز)", callback_data=f"am:all:{jdate.today()}")])
    kb.append(back_row())
    await ctx.show("⏱ <b>مدیریت ورود و خروج</b>\nپرسنل را انتخاب کنید تا ساعت‌هایش را ببینید، اضافه یا اصلاح کنید:", kb)


@route("am:all", perm="att_manage")
async def am_all(ctx: Ctx, day):
    lines = [f"📅 <b>{jdate.fmt_long(day)}</b>", ""]
    for s in db.active_staff():
        recs = db.q("SELECT * FROM attendance WHERE staff_id=? AND day=? ORDER BY id", (s["id"], day))
        if recs:
            tot = sum(jdate.hours(r["t_in"], r["t_out"]) for r in recs)
            lines.append(f"👤 <b>{esc(s['name'])}</b> ({jdate.hm(tot)})")
            lines += ["   " + _rec_line(r) for r in recs]
        else:
            lines.append(f"👤 {esc(s['name'])}: — ثبت نشده")
    kb = [[B("◀️ روز قبل", callback_data=f"am:all:{jdate.add_days(day, -1)}"),
           B("روز بعد ▶️", callback_data=f"am:all:{jdate.add_days(day, 1)}")],
          [B("📅 رفتن به تاریخ…", callback_data="am:goto:0")], back_row("am:menu")]
    await ctx.show("\n".join(lines), kb)


@route("am:day", perm="att_manage")
async def am_day(ctx: Ctx, sid, day):
    sid = int(sid)
    recs = db.q("SELECT * FROM attendance WHERE staff_id=? AND day=? ORDER BY id", (sid, day))
    lines = [f"👤 <b>{esc(db.staff_name(sid))}</b>", f"📅 {jdate.fmt_long(day)}", ""]
    lines += [f"{i + 1}) {_rec_line(r)}" for i, r in enumerate(recs)] or ["ثبتی برای این روز نیست."]
    kb = [[B(f"✏️ ویرایش {i + 1}", callback_data=f"am:edit:{r['id']}") for i, r in enumerate(recs)][:4]] if recs else []
    kb.append([B("➕ افزودن ورود/خروج دستی", callback_data=f"am:add:{sid}:{day}")])
    kb.append([B("◀️ روز قبل", callback_data=f"am:day:{sid}:{jdate.add_days(day, -1)}"),
               B("روز بعد ▶️", callback_data=f"am:day:{sid}:{jdate.add_days(day, 1)}")])
    kb.append([B("📅 رفتن به تاریخ…", callback_data=f"am:goto:{sid}")])
    kb.append(back_row("am:menu"))
    await ctx.show("\n".join(lines), [r for r in kb if r])


@route("am:goto", perm="att_manage")
async def am_goto(ctx: Ctx, sid):
    await start_flow(ctx, "am_goto", {"sid": int(sid)})


async def _goto_done(ctx, d):
    await goto(ctx, f"am:day:{d['sid']}:{d['day']}" if d["sid"] else f"am:all:{d['day']}")


define_flow("am_goto", [Step("day", "تاریخ شمسی را بنویسید (مثال 1405/08/05):", p_date, DATE_CHOICES)], _goto_done, "am:menu")


@route("am:add", perm="att_manage")
async def am_add(ctx: Ctx, sid, day):
    await start_flow(ctx, "am_add", {"sid": int(sid), "day": day})


async def _add_done(ctx, d):
    rid = db.run("INSERT INTO attendance(staff_id,day,t_in,t_out,note,source,updated_by) VALUES(?,?,?,?,?,'admin',?)",
                 (d["sid"], d["day"], d["t_in"], d.get("t_out"), d.get("note"), ctx.me["id"]))
    ctx.audit("att_add", f"{d['sid']} {d['day']} {d['t_in']}-{d.get('t_out')}")
    await goto(ctx, f"am:day:{d['sid']}:{d['day']}")


define_flow("am_add", [
    Step("t_in", lambda d: f"⏱ ساعت <b>ورود</b> {db.staff_name(d['sid'])} در {jdate.fmt(d['day'])} (مثال 08:30):", p_time),
    Step("t_out", "ساعت <b>خروج</b> (مثال 16:00):", p_time, optional=True),
    Step("note", "توضیح (اختیاری):", p_text, optional=True),
], _add_done, "am:menu")


@route("am:edit", perm="att_manage")
async def am_edit(ctx: Ctx, rid):
    r = db.one("SELECT * FROM attendance WHERE id=?", (int(rid),))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    kb = [[B("ورود", callback_data=f"am:ef:{rid}:in"), B("خروج", callback_data=f"am:ef:{rid}:out")],
          [B("تاریخ", callback_data=f"am:ef:{rid}:day"), B("توضیح", callback_data=f"am:ef:{rid}:note")],
          [B("🗑 حذف این ثبت", callback_data=f"am:del:{rid}")],
          back_row(f"am:day:{r['staff_id']}:{r['day']}")]
    await ctx.show(f"✏️ <b>ویرایش</b> — {esc(db.staff_name(r['staff_id']))}\n📅 {jdate.fmt_long(r['day'])}\n{_rec_line(r)}\n\n"
                   "کدام مورد را اصلاح می‌کنید؟", kb)


@route("am:ef", perm="att_manage")
async def am_ef(ctx: Ctx, rid, field):
    await start_flow(ctx, f"am_e_{field}", {"rid": int(rid)})


def _mk_edit(field, col, prompt, parse):
    async def done(ctx, d):
        v = d["v"]
        if col in ("t_in", "day") and v is None:
            return await ctx.send("⚠️ این مورد قابل خالی کردن نیست.")
        db.run(f"UPDATE attendance SET {col}=?, updated_by=?, source='admin' WHERE id=?", (v, ctx.me["id"], d["rid"]))
        ctx.audit("att_edit", f"{d['rid']} {col}={v}")
        await goto(ctx, f"am:edit:{d['rid']}")
    define_flow(f"am_e_{field}", [Step("v", prompt, parse, optional=False)], done, "am:menu")


_mk_edit("in", "t_in", "ساعت ورود جدید (مثال 08:30):", p_time)
_mk_edit("out", "t_out", "ساعت خروج جدید (مثال 16:00) — برای پاک کردن «-» بنویسید:", p_time_or_clear)
_mk_edit("day", "day", "تاریخ شمسی جدید:", p_date)
_mk_edit("note", "note", "توضیح جدید — برای پاک کردن «-» بنویسید:", lambda t: None if t.strip() in ("-", "—") else p_text(t))


@route("am:del", perm="att_manage")
async def am_del(ctx: Ctx, rid):
    await ctx.show("⚠️ این ثبت ورود/خروج حذف شود؟",
                   [[B("✅ بله، حذف", callback_data=f"am:del2:{rid}"), B("خیر", callback_data=f"am:edit:{rid}")]])


@route("am:del2", perm="att_manage")
async def am_del2(ctx: Ctx, rid):
    r = db.one("SELECT * FROM attendance WHERE id=?", (int(rid),))
    if r:
        db.run("DELETE FROM attendance WHERE id=?", (r["id"],))
        ctx.audit("att_delete", f"{r['staff_id']} {r['day']} {r['t_in']}-{r['t_out']}")
        await goto(ctx, f"am:day:{r['staff_id']}:{r['day']}")


# ───────────── گزارش روزانه ─────────────
@route("rep:menu", perm=("rep_write", "rep_view"))
async def rep_menu(ctx: Ctx):
    t = jdate.today()
    mine = db.one("SELECT COUNT(*) c FROM reports WHERE staff_id=? AND day=?", (ctx.me["id"], t))["c"]
    kb = []
    if ctx.can("rep_write"):
        kb.append([B("✍️ ثبت گزارش امروز", callback_data="rep:new")])
        kb.append([B("📚 گزارش‌های من", callback_data="rep:mine:0")])
    if ctx.can("rep_view"):
        kb.append([B("🗂 گزارش‌های امروز همه", callback_data=f"rep:day:{t}")])
        kb.append([B("👤 گزارش‌های یک پرسنل", callback_data="rep:pick")])
    kb.append(back_row())
    await ctx.show(f"📝 <b>گزارش روزانه</b>\nامروز {mine} گزارش ثبت کرده‌اید.", kb)


@route("rep:new", perm="rep_write")
async def rep_new(ctx: Ctx):
    await start_flow(ctx, "rep_new")


async def _rep_done(ctx, d):
    from . import crypto
    rid = db.run("INSERT INTO reports(staff_id,day,body) VALUES(?,?,?)", (ctx.me["id"], jdate.today(), crypto.enc(d["body"])))
    ctx.audit("report_add", rid)
    await ctx.send("✅ گزارش ثبت شد.", [[B("📎 افزودن فایل/عکس/ویدئو", callback_data=f"rep:att:{rid}")],
                                       [B("✍️ گزارش دیگر", callback_data="rep:new")], back_row("rep:menu")])


define_flow("rep_new", [Step("body", "📝 گزارش فعالیت امروز را بنویسید:")], _rep_done, "rep:menu")


@route("rep:att", perm="rep_write")
async def rep_att(ctx: Ctx, rid):
    await start_attach(ctx, "report", int(rid), "rep:menu")


def _rep_text(r, with_name=True):
    from . import crypto
    head = f"<b>{esc(db.staff_name(r['staff_id']))}</b> — " if with_name else ""
    n = db.one("SELECT COUNT(*) c FROM attachments WHERE kind='report' AND ref_id=?", (r["id"],))["c"]
    return f"{head}{jdate.fmt(r['day'])}{' 📎' + str(n) if n else ''}\n{esc(crypto.dec(r['body']))}"


@route("rep:mine", perm="rep_write")
async def rep_mine(ctx: Ctx, page="0"):
    page = int(page)
    total = db.one("SELECT COUNT(*) c FROM reports WHERE staff_id=?", (ctx.me["id"],))["c"]
    rows = db.q("SELECT * FROM reports WHERE staff_id=? ORDER BY id DESC LIMIT 5 OFFSET ?", (ctx.me["id"], page * 5))
    kb = []
    pg = pager("rep:mine", page, total, 5)
    if pg:
        kb.append(pg)
    kb += [[B(f"📎 فایل‌های گزارش {jdate.fmt(r['day'])}", callback_data=f"at:list:report:{r['id']}")]
           for r in rows if db.one("SELECT 1 FROM attachments WHERE kind='report' AND ref_id=?", (r["id"],))]
    kb.append(back_row("rep:menu"))
    await ctx.show("📚 <b>گزارش‌های من</b>\n\n" + ("\n\n".join(_rep_text(r, False) for r in rows) or "هنوز گزارشی ندارید."), kb)


@route("rep:day", perm="rep_view")
async def rep_day(ctx: Ctx, day):
    rows = db.q("SELECT * FROM reports WHERE day=? ORDER BY staff_id, id", (day,))
    kb = [[B("◀️ روز قبل", callback_data=f"rep:day:{jdate.add_days(day, -1)}"),
           B("روز بعد ▶️", callback_data=f"rep:day:{jdate.add_days(day, 1)}")]]
    kb += [[B(f"📎 فایل‌های گزارش {db.staff_name(r['staff_id'])}", callback_data=f"at:list:report:{r['id']}")]
           for r in rows if db.one("SELECT 1 FROM attachments WHERE kind='report' AND ref_id=?", (r["id"],))]
    kb.append(back_row("rep:menu"))
    await ctx.show(f"🗂 <b>گزارش‌های {jdate.fmt_long(day)}</b>\n\n" + ("\n\n".join(_rep_text(r) for r in rows) or "گزارشی نیست."), kb)


@route("rep:pick", perm="rep_view")
async def rep_pick(ctx: Ctx):
    kb = grid([B(s["name"], callback_data=f"rep:st:{s['id']}:0") for s in db.active_staff()])
    kb.append(back_row("rep:menu"))
    await ctx.show("👤 پرسنل را انتخاب کنید:", kb)


@route("rep:st", perm="rep_view")
async def rep_st(ctx: Ctx, sid, page="0"):
    sid, page = int(sid), int(page)
    total = db.one("SELECT COUNT(*) c FROM reports WHERE staff_id=?", (sid,))["c"]
    rows = db.q("SELECT * FROM reports WHERE staff_id=? ORDER BY id DESC LIMIT 5 OFFSET ?", (sid, page * 5))
    kb = []
    pg = pager(f"rep:st:{sid}", page, total, 5)
    if pg:
        kb.append(pg)
    kb.append(back_row("rep:pick"))
    await ctx.show(f"👤 <b>گزارش‌های {esc(db.staff_name(sid))}</b>\n\n" + ("\n\n".join(_rep_text(r, False) for r in rows) or "گزارشی نیست."), kb)


# ───────────── مرخصی ─────────────
@route("lv:menu", perm=("leave_self", "leave_manage"))
async def lv_menu(ctx: Ctx):
    kb = []
    if ctx.can("leave_self"):
        kb += [[B("➕ درخواست مرخصی", callback_data="lv:new")], [B("📋 درخواست‌های من", callback_data="lv:mine")]]
    if ctx.can("leave_manage"):
        n = db.one("SELECT COUNT(*) c FROM leaves WHERE status='pending'")["c"]
        kb += [[B(f"🕓 در انتظار تأیید ({n})", callback_data="lv:pend")], [B("🗓 مرخصی‌های تأییدشده اخیر", callback_data="lv:appr")]]
    kb.append(back_row())
    await ctx.show("🏖 <b>مرخصی</b>", kb)


@route("lv:new", perm="leave_self")
async def lv_new(ctx: Ctx):
    await start_flow(ctx, "lv_new")


async def _lv_done(ctx, d):
    if d["to"] < d["from"]:
        return await ctx.send("⚠️ تاریخ پایان قبل از شروع است. دوباره از «درخواست مرخصی» شروع کنید.", [back_row("lv:menu")])
    lid = db.run("INSERT INTO leaves(staff_id,from_day,to_day,reason) VALUES(?,?,?,?)", (ctx.me["id"], d["from"], d["to"], d.get("reason")))
    await ctx.send("✅ درخواست شما ثبت و برای مدیر ارسال شد.", [back_row("lv:menu")])
    await notify_admins(ctx.bot, f"🏖 <b>درخواست مرخصی</b>\n👤 {esc(ctx.me['name'])}\n"
                        f"از {jdate.fmt(d['from'])} تا {jdate.fmt(d['to'])}\nدلیل: {esc(d.get('reason') or '—')}",
                        [[B("✅ تأیید", callback_data=f"lv:ok:{lid}"), B("❌ رد", callback_data=f"lv:no:{lid}")]])


define_flow("lv_new", [
    Step("from", "تاریخ <b>شروع</b> مرخصی:", p_date, DATE_CHOICES),
    Step("to", "تاریخ <b>پایان</b> مرخصی:", p_date, DATE_CHOICES),
    Step("reason", "دلیل (اختیاری):", p_text, optional=True),
], _lv_done, "lv:menu")


@route("lv:mine", perm="leave_self")
async def lv_mine(ctx: Ctx):
    rows = db.q("SELECT * FROM leaves WHERE staff_id=? ORDER BY id DESC LIMIT 15", (ctx.me["id"],))
    st = {"pending": "🕓 در انتظار", "approved": "✅ تأیید", "rejected": "❌ رد"}
    await ctx.show("📋 <b>درخواست‌های من</b>\n\n" + ("\n".join(
        f"{st[r['status']]} — {jdate.fmt(r['from_day'])} تا {jdate.fmt(r['to_day'])}" for r in rows) or "موردی نیست."),
        [back_row("lv:menu")])


@route("lv:pend", perm="leave_manage")
async def lv_pend(ctx: Ctx):
    rows = db.q("SELECT * FROM leaves WHERE status='pending' ORDER BY id")
    if not rows:
        return await ctx.show("🕓 درخواستی در انتظار نیست.", [back_row("lv:menu")])
    await ctx.show("🕓 <b>در انتظار تأیید</b>", [back_row("lv:menu")])
    for r in rows:
        await ctx.send(f"👤 {esc(db.staff_name(r['staff_id']))}\nاز {jdate.fmt(r['from_day'])} تا {jdate.fmt(r['to_day'])}\n"
                       f"دلیل: {esc(r['reason'] or '—')}",
                       [[B("✅ تأیید", callback_data=f"lv:ok:{r['id']}"), B("❌ رد", callback_data=f"lv:no:{r['id']}")]])


@route("lv:appr", perm="leave_manage")
async def lv_appr(ctx: Ctx):
    rows = db.q("SELECT * FROM leaves WHERE status='approved' ORDER BY id DESC LIMIT 20")
    await ctx.show("🗓 <b>مرخصی‌های تأییدشده</b>\n\n" + ("\n".join(
        f"• {esc(db.staff_name(r['staff_id']))}: {jdate.fmt(r['from_day'])} تا {jdate.fmt(r['to_day'])}" for r in rows) or "موردی نیست."),
        [back_row("lv:menu")])


async def _decide(ctx: Ctx, lid, status):
    r = db.one("SELECT * FROM leaves WHERE id=?", (int(lid),))
    if not r or r["status"] != "pending":
        return await ctx.answer("قبلاً رسیدگی شده.", True)
    db.run("UPDATE leaves SET status=?, decided_by=? WHERE id=?", (status, ctx.me["id"], r["id"]))
    ctx.audit("leave_" + status, f"{r['staff_id']} {r['from_day']}")
    s = db.staff_by_id(r["staff_id"])
    word = "✅ تأیید شد" if status == "approved" else "❌ رد شد"
    if s and s["tg_id"]:
        await notify(ctx.bot, s["tg_id"], f"🏖 درخواست مرخصی شما ({jdate.fmt(r['from_day'])} تا {jdate.fmt(r['to_day'])}) {word}.")
    await ctx.show(f"{word}: {esc(db.staff_name(r['staff_id']))} — {jdate.fmt(r['from_day'])} تا {jdate.fmt(r['to_day'])}", [back_row("lv:menu")])


@route("lv:ok", perm="leave_manage")
async def lv_ok(ctx: Ctx, lid):
    await _decide(ctx, lid, "approved")


@route("lv:no", perm="leave_manage")
async def lv_no(ctx: Ctx, lid):
    await _decide(ctx, lid, "rejected")
