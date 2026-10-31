"""ورود/خروج پرسنل، مدیریت دستی ساعات توسط ادمین، گزارش روزانه و مرخصی."""
from telegram import InlineKeyboardButton as B

from . import attlogic, crypto, db, jdate
from .core import (Ctx, Step, back_row, define_flow, esc, goto, grid, notify, notify_admins,
                   p_date, p_text, p_time, p_time_or_clear, pager, route, start_attach, start_flow)


def _rec_line(r) -> str:
    h = jdate.hours(r["t_in"], r["t_out"])
    out = r["t_out"] or "—"
    extra = f" ({jdate.hm(h)})" if r["t_out"] else " ⏳"
    src = " ✍️" if r["source"] == "admin" else ""
    note = f" — {esc(r['note'])}" if r["note"] else ""
    return f"🟢 {r['t_in'] or '—'}  →  🔴 {out}{extra}{src}{note}"


# ───────────── ورود و خروج خود فرد ─────────────
@route("att:menu", perm=("att_self", "att_view_self"))
async def att_menu(ctx: Ctx):
    t = jdate.today()
    me = ctx.me["id"]
    recs = db.q("SELECT * FROM attendance WHERE staff_id=? AND day=? ORDER BY id", (me, t))
    opn = db.one("SELECT * FROM attendance WHERE staff_id=? AND t_out IS NULL AND day>=? ORDER BY id DESC",
                 (me, jdate.add_days(t, -1)))
    txt = [f"🕘 <b>ورود و خروج</b> — {jdate.fmt_long(t)}", ""]
    st = attlogic.eff_status(me, t, recs)
    if st:
        txt.append(f"وضعیت امروز: {attlogic.STATUS[st][0]} {attlogic.STATUS[st][1]}")
    txt += [_rec_line(r) for r in recs] or ["امروز هنوز چیزی ثبت نشده."]
    if opn:
        txt.append(f"\n⏳ شما از ساعت {opn['t_in']} ({jdate.fmt(opn['day'])}) حاضر هستید.")
    kb = []
    if ctx.can("att_self"):
        kb.append([B("🚪 ثبت خروج", callback_data="att:out")] if opn else [B("✅ ثبت ورود", callback_data="att:in")])
    if ctx.can("att_view_self", "att_self"):
        kb.append([B("📆 سوابق من (این ماه)", callback_data="att:mine")])
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
    s_, e_ = jdate.month_bounds(jy, jm)
    by_day = {}
    for r in db.q("SELECT * FROM attendance WHERE staff_id=? AND day BETWEEN ? AND ? ORDER BY day, id", (sid, s_, e_)):
        by_day.setdefault(r["day"], []).append(r)
    pres = {r["day"]: r["status"] for r in db.q("SELECT day,status FROM presence WHERE staff_id=? AND day BETWEEN ? AND ?", (sid, s_, e_))}
    lines, total, days = [], 0.0, 0
    for day in sorted(set(by_day) | set(pres)):
        st = pres.get(day) or ("present" if by_day.get(day) else None)
        head = f"{jdate.fmt(day)} {jdate.weekday(day)}: {attlogic.STATUS[st][0]} {attlogic.STATUS[st][1]}" if st else f"{jdate.fmt(day)}"
        lines.append(head + "".join("\n   " + _rec_line(r) for r in by_day.get(day, [])))
        total += sum(jdate.hours(r["t_in"], r["t_out"]) for r in by_day.get(day, []))
        days += 1 if st == "present" else 0
    return lines, total, days


@route("att:mine", perm=("att_self", "att_view_self"))
async def att_mine(ctx: Ctx, jy=None, jm=None):
    from .mod_monthly import mr_person
    cy, cm, _ = jdate.j_today()
    await mr_person(ctx, ctx.me["id"], jy or cy, jm or cm)


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


define_flow("am_goto", [Step("day", "تاریخ شمسی را بنویسید:", p_date, kind="date")], _goto_done, "am:menu")


@route("am:add", perm="att_manage")
async def am_add(ctx: Ctx, sid, day):
    await start_flow(ctx, "am_add", {"sid": int(sid), "day": day})


async def _add_done(ctx, d):
    rid = db.run("INSERT INTO attendance(staff_id,day,t_in,t_out,note,source,updated_by) VALUES(?,?,?,?,?,'admin',?)",
                 (d["sid"], d["day"], d["t_in"], d.get("t_out"), d.get("note"), ctx.me["id"]))
    ctx.audit("att_add", f"{d['sid']} {d['day']} {d['t_in']}-{d.get('t_out')}")
    await goto(ctx, f"am:day:{d['sid']}:{d['day']}")


define_flow("am_add", [
    Step("t_in", lambda d: f"⏱ ساعت <b>ورود</b> {db.staff_name(d['sid'])} در {jdate.fmt(d['day'])} ", p_time, kind="time"),
    Step("t_out", "ساعت <b>خروج</b>:", p_time, kind="time", optional=True),
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


def _mk_edit(field, col, prompt, parse, kind="text", optional=False):
    async def done(ctx, d):
        v = d["v"]
        if col in ("t_in", "day") and v is None:
            return await ctx.send("⚠️ این مورد قابل خالی کردن نیست.")
        db.run(f"UPDATE attendance SET {col}=?, updated_by=?, source='admin' WHERE id=?", (v, ctx.me["id"], d["rid"]))
        ctx.audit("att_edit", f"{d['rid']} {col}={v}")
        await goto(ctx, f"am:edit:{d['rid']}")
    define_flow(f"am_e_{field}", [Step("v", prompt, parse, kind=kind, optional=optional)], done, "am:menu")


_mk_edit("in", "t_in", "ساعت ورود جدید:", p_time, "time")
_mk_edit("out", "t_out", "ساعت خروج جدید (یا «رد کردن» برای پاک کردن خروج):", p_time, "time", True)
_mk_edit("day", "day", "تاریخ جدید:", p_date, "date")
_mk_edit("note", "note", "توضیح جدید (یا «رد کردن» برای پاک کردن):", p_text, "text", True)


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
    if ctx.can("att_manage", "export", "rep_view"):
        kb.append([B("📊 گزارش ماهانهٔ پرسنل", callback_data="mr:menu")])
    kb.append(back_row())
    await ctx.show(f"📝 <b>گزارش روزانه</b>\nامروز {mine} گزارش ثبت کرده‌اید.", kb)


@route("rep:new", perm="rep_write")
async def rep_new(ctx: Ctx):
    await start_flow(ctx, "rep_new")


async def _rep_done(ctx, d):
    from . import crypto
    rid = db.run("INSERT INTO reports(staff_id,day,body) VALUES(?,?,?)", (ctx.me["id"], jdate.today(), crypto.enc(d["body"])))
    ctx.audit("report_add", rid)
    from .core import notify_perm
    row = db.one("SELECT * FROM reports WHERE id=?", (rid,))
    full = "📝 <b>گزارش جدید</b>\n" + rep_block(row)
    parts = [full[i:i + 3800] for i in range(0, len(full), 3800)]
    for i, part in enumerate(parts):
        await notify_perm(ctx.bot, "rep_view", part, [[B("🗂 گزارش‌های امروز", callback_data=f"rep:day:{jdate.today()}")]] if i == len(parts) - 1 else None,
                          skip_tg=ctx.tg_id)
    await ctx.send("✅ گزارش ثبت شد.", [[B("📎 افزودن فایل/عکس/ویدئو", callback_data=f"rep:att:{rid}")],
                                       [B("✍️ گزارش دیگر", callback_data="rep:new")], back_row("rep:menu")])


define_flow("rep_new", [Step("body", "📝 گزارش فعالیت امروز را بنویسید:")], _rep_done, "rep:menu")


@route("rep:att", perm="rep_write")
async def rep_att(ctx: Ctx, rid):
    await start_attach(ctx, "report", int(rid), "rep:menu")


def rep_block(r) -> str:
    """یک گزارش کامل: نام، عنوان شغلی، تاریخ با روز هفته، ساعت ثبت، متن کامل و تعداد فایل پیوست."""
    from . import crypto
    st = db.staff_by_id(r["staff_id"])
    who = esc(st["name"]) if st else "؟"
    title = esc(db.title_label(st)) if st else ""
    n = db.one("SELECT COUNT(*) c FROM attachments WHERE kind='report' AND ref_id=?", (r["id"],))["c"]
    tm = jdate.local_hhmm(r["created"] or "")
    return (f"👤 <b>{who}</b> — {title}\n📅 {jdate.fmt(r['day'])} {jdate.weekday(r['day'])}" + (f"  🕐 {tm}" if tm else "")
            + (f"  📎 {n} فایل" if n else "") + f"\n{esc(crypto.dec(r['body']))}")


def _rep_text(r, with_name=True):
    return rep_block(r)


def _paged(blocks, base, page, back, extra_kb=None):
    from .mod_monthly import chunk
    pages = chunk(blocks)
    page = min(max(page, 0), len(pages) - 1)
    nav = []
    if page > 0:
        nav.append(B("◀️ قبل", callback_data=f"{base}:{page - 1}"))
    if page < len(pages) - 1:
        nav.append(B("بعد ▶️", callback_data=f"{base}:{page + 1}"))
    kb = ([nav] if nav else []) + (extra_kb or []) + [back_row(back)]
    return "\n\n".join(pages[page]), kb, (page + 1, len(pages))


def _att_btns(rows):
    return [[B(f"📎 فایل‌های گزارش {db.staff_name(r['staff_id'])} {jdate.fmt(r['day'])}", callback_data=f"at:list:report:{r['id']}")]
            for r in rows if db.one("SELECT 1 FROM attachments WHERE kind='report' AND ref_id=?", (r["id"],))]


@route("rep:mine", perm="rep_write")
async def rep_mine(ctx: Ctx, page="0"):
    rows = db.q("SELECT * FROM reports WHERE staff_id=? ORDER BY id DESC LIMIT 30", (ctx.me["id"],))
    body, kb, (p, n) = _paged([rep_block(r) for r in rows], "rep:mine", int(page), "rep:menu", _att_btns(rows))
    await ctx.show(f"📚 <b>گزارش‌های من</b> (۳۰ مورد اخیر" + (f" — صفحهٔ {p}/{n}" if n > 1 else "") + ")\n\n"
                   + (body or "هنوز گزارشی ندارید."), kb)


@route("rep:day", perm="rep_view")
async def rep_day(ctx: Ctx, day, page="0"):
    rows = db.q("SELECT * FROM reports WHERE day=? ORDER BY staff_id, id", (day,))
    sent = {r["staff_id"] for r in rows}
    missing = [s["name"] for s in db.roster() if s["id"] not in sent]
    nav = [[B("◀️ روز قبل", callback_data=f"rep:day:{jdate.add_days(day, -1)}"),
            B("روز بعد ▶️", callback_data=f"rep:day:{jdate.add_days(day, 1)}")]]
    body, kb, (p, n) = _paged([rep_block(r) for r in rows], f"rep:day:{day}", int(page), "rep:menu", nav + _att_btns(rows))
    head = (f"🗂 <b>گزارش‌های {jdate.fmt_long(day)}</b> — {len(rows)} گزارش از {len({r['staff_id'] for r in rows})} نفر"
            + (f" (صفحهٔ {p}/{n})" if n > 1 else ""))
    tail = ("\n\n⏳ <b>گزارش نداده‌اند:</b> " + "، ".join(esc(x) for x in missing)) if missing and p == n else ""
    await ctx.show(head + "\n\n" + (body or "گزارشی نیست.") + tail, kb)


@route("rep:pick", perm="rep_view")
async def rep_pick(ctx: Ctx):
    kb = grid([B(s["name"], callback_data=f"rep:st:{s['id']}:0") for s in db.active_staff()])
    kb.append(back_row("rep:menu"))
    await ctx.show("👤 پرسنل را انتخاب کنید:", kb)


@route("rep:st", perm="rep_view")
async def rep_st(ctx: Ctx, sid, page="0"):
    sid = int(sid)
    rows = db.q("SELECT * FROM reports WHERE staff_id=? ORDER BY id DESC LIMIT 30", (sid,))
    body, kb, (p, n) = _paged([rep_block(r) for r in rows], f"rep:st:{sid}", int(page), "rep:pick", _att_btns(rows))
    cy, cm, _ = jdate.j_today()
    kb.insert(0, [B("📊 گزارش ماهانهٔ این نفر", callback_data=f"mr:p:{sid}:{cy}:{cm}")])
    await ctx.show(f"👤 <b>گزارش‌های {esc(db.staff_name(sid))}</b> (۳۰ مورد اخیر" + (f" — صفحهٔ {p}/{n}" if n > 1 else "") + ")\n\n"
                   + (body or "گزارشی نیست."), kb)


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
    Step("from", "تاریخ <b>شروع</b> مرخصی:", p_date, kind="date"),
    Step("to", "تاریخ <b>پایان</b> مرخصی:", p_date, kind="date"),
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


# ───────────── حضور و غیاب روزانه (فقط مدیر حضور؛ پرسنل نمی‌توانند تغییر دهند) ─────────────
def _person_btn(s, day):
    st = attlogic.eff_status(s["id"], day)
    recs = attlogic.records(s["id"], day)
    icon = attlogic.STATUS[st][0] if st else "⬜️"
    t = attlogic.times_text(recs)
    return B(f"{icon} {s['name']}" + (f"  {t}" if t else ""), callback_data=f"rc:p:{s['id']}:{day}")


@route("rc:day", perm="att_manage")
async def rc_day(ctx: Ctx, day=None):
    day = day or jdate.today()
    people = db.roster()
    counts = attlogic.day_counts(day)
    summ = " · ".join(f"{attlogic.STATUS[k][0]} {v}" for k, v in counts.items() if k)
    if counts.get(None):
        summ += (" · " if summ else "") + f"⬜️ ثبت‌نشده {counts[None]}"
    kb = [[_person_btn(s, day)] for s in people]
    if not people:
        kb = [[B("👥 ابتدا پرسنل را اضافه کنید", callback_data="st:menu")]] if ctx.is_admin else []
    if counts.get(None):
        kb.append([B(f"✅ بقیهٔ ثبت‌نشده‌ها حاضر ({counts[None]})", callback_data=f"rc:all:{day}")])
    kb.append([B("◀️ روز قبل", callback_data=f"rc:day:{jdate.add_days(day, -1)}"),
               B("روز بعد ▶️", callback_data=f"rc:day:{jdate.add_days(day, 1)}")])
    row = [B("📅 تاریخ دیگر", callback_data="rc:goto")]
    if ctx.can("export"):
        row.append(B("📤 اکسل این روز", callback_data=f"exp:atd:{day}"))
    kb.append(row)
    kb.append([B("📊 گزارش ماهانهٔ پرسنل", callback_data="mr:menu")])
    kb.append(back_row())
    await ctx.show(f"📋 <b>حضور و غیاب</b> — {jdate.fmt_long(day)}\n{summ or 'بدون پرسنل'}", kb)


@route("rc:goto", perm="att_manage")
async def rc_goto(ctx: Ctx):
    await start_flow(ctx, "rc_goto")


async def _rc_goto_done(ctx, d):
    await goto(ctx, f"rc:day:{d['day']}")


define_flow("rc_goto", [Step("day", "📅 کدام روز؟", p_date, kind="date")], _rc_goto_done, "rc:day")


@route("rc:all", perm="att_manage")
async def rc_all(ctx: Ctx, day):
    n = 0
    for s in db.roster():
        if attlogic.eff_status(s["id"], day) is None:
            attlogic.set_status(s["id"], day, "present", ctx.me["id"])
            n += 1
    ctx.audit("rc_all_present", f"{day} n={n}")
    await ctx.answer(f"{n} نفر حاضر ثبت شد")
    await rc_day(ctx, day)


@route("rc:p", perm="att_manage")
async def rc_person(ctx: Ctx, sid, day):
    sid = int(sid)
    s = db.staff_by_id(sid)
    if not s:
        return await ctx.answer("پیدا نشد", True)
    st = attlogic.eff_status(sid, day)
    recs = attlogic.records(sid, day)
    txt = [f"👤 <b>{esc(s['name'])}</b> — {esc(db.title_label(s))}", f"📅 {jdate.fmt_long(day)}", "",
           "وضعیت: " + (f"{attlogic.STATUS[st][0]} <b>{attlogic.STATUS[st][1]}</b>" if st else "⬜️ ثبت نشده")]
    txt += [_rec_line(r) for r in recs]
    if recs:
        txt.append(f"جمع: {jdate.hm(sum(jdate.hours(r['t_in'], r['t_out']) for r in recs))}")
    kb = grid([B(f"{ic} {lb}", callback_data=f"rc:s:{sid}:{day}:{k}") for k, (ic, lb, _) in attlogic.STATUS.items()], 3)
    kb.append([B("🟢 ثبت/اصلاح ورود", callback_data=f"rc:t:{sid}:{day}:in"), B("🔴 ثبت/اصلاح خروج", callback_data=f"rc:t:{sid}:{day}:out")])
    if recs:
        kb.append([B("✏️ ویرایش/حذف ردیف‌ها", callback_data=f"am:edit:{recs[0]['id']}")])
    kb.append([B("🧹 پاک کردن وضعیت", callback_data=f"rc:clr:{sid}:{day}"), B("➡️ نفر بعدی", callback_data=f"rc:n:{sid}:{day}")])
    kb.append(back_row(f"rc:day:{day}"))
    await ctx.show("\n".join(txt), kb)


@route("rc:s", perm="att_manage")
async def rc_set(ctx: Ctx, sid, day, status):
    attlogic.set_status(int(sid), day, status, ctx.me["id"])
    ctx.audit("rc_status", f"{sid} {day} {status}")
    await rc_person(ctx, sid, day)


@route("rc:clr", perm="att_manage")
async def rc_clear(ctx: Ctx, sid, day):
    attlogic.clear_status(int(sid), day)
    ctx.audit("rc_clear", f"{sid} {day}")
    await rc_person(ctx, sid, day)


@route("rc:n", perm="att_manage")
async def rc_next(ctx: Ctx, sid, day):
    ids = [s["id"] for s in db.roster()]
    if not ids:
        return await rc_day(ctx, day)
    nxt = ids[(ids.index(int(sid)) + 1) % len(ids)] if int(sid) in ids else ids[0]
    await rc_person(ctx, nxt, day)


@route("rc:t", perm="att_manage")
async def rc_time(ctx: Ctx, sid, day, which):
    await start_flow(ctx, "rc_time", {"sid": int(sid), "day": day, "which": which})


async def _rc_time_done(ctx, d):
    attlogic.set_time(d["sid"], d["day"], d["which"], d["t"], ctx.me["id"])
    ctx.audit("rc_time", f"{d['sid']} {d['day']} {d['which']} {d['t']}")
    await goto(ctx, f"rc:p:{d['sid']}:{d['day']}")


define_flow("rc_time", [Step("t", lambda d: f"⏱ ساعت <b>{'ورود' if d['which'] == 'in' else 'خروج'}</b> "
                                           f"{esc(db.staff_name(d['sid']))} — {jdate.fmt(d['day'])}:", p_time, kind="time")],
            _rc_time_done, "rc:day")
