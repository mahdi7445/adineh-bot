"""امور و اتفاقات روزانه، رویدادهای مهم، دوربین‌ها و پیام همگانی."""
from telegram import InlineKeyboardButton as B

from . import crypto, db, jdate
from .core import (DATE_CHOICES, Ctx, Step, attachments, back_row, define_flow, delete_attachments, esc, goto, grid,
                   bg, notify, notify_admins, notify_perm, p_date, p_text, pager, route, start_attach, start_flow)

SEV = {"normal": "🟢 عادی", "important": "🟡 مهم", "urgent": "🔴 فوری"}


# ───────────── امور و اتفاقات ─────────────
@route("inc:menu", perm=("inc_write", "inc_manage"))
async def inc_menu(ctx: Ctx):
    n_open = db.one("SELECT COUNT(*) c FROM incidents WHERE status='open'")["c"]
    kb = [[B("➕ ثبت مورد جدید", callback_data="inc:new")],
          [B(f"🔓 موارد باز ({n_open})", callback_data="inc:list:open:0"), B("✅ حل‌شده", callback_data="inc:list:done:0")]]
    kb.append(back_row())
    await ctx.show("📋 <b>امور و اتفاقات روزانه</b>\nهر مورد می‌تواند فایل، عکس و ویدئو داشته باشد.", kb)


@route("inc:list", perm=("inc_write", "inc_manage"))
async def inc_list(ctx: Ctx, status, page="0"):
    page = int(page)
    total = db.one("SELECT COUNT(*) c FROM incidents WHERE status=?", (status,))["c"]
    rows = db.q("SELECT * FROM incidents WHERE status=? ORDER BY id DESC LIMIT 8 OFFSET ?", (status, page * 8))
    kb = [[B(f"{SEV.get(r['severity'], '')[:1]} {jdate.fmt(r['day'])} — {r['title'][:35]}", callback_data=f"inc:v:{r['id']}")] for r in rows]
    pg = pager(f"inc:list:{status}", page, total, 8)
    if pg:
        kb.append(pg)
    kb.append(back_row("inc:menu"))
    await ctx.show(f"📋 <b>{'موارد باز' if status == 'open' else 'موارد حل‌شده'}</b> ({total})" + ("" if rows else "\n\nموردی نیست."), kb)


@route("inc:v", perm=("inc_write", "inc_manage"))
async def inc_view(ctx: Ctx, iid):
    r = db.one("SELECT * FROM incidents WHERE id=?", (int(iid),))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    n = len(attachments("incident", r["id"]))
    txt = [f"📋 <b>{esc(r['title'])}</b>", f"{SEV.get(r['severity'], '')} — {'🔓 باز' if r['status'] == 'open' else '✅ حل‌شده'}",
           f"📅 {jdate.fmt_long(r['day'])} {r['tm'] or ''} — ثبت: {esc(db.staff_name(r['created_by']))}", "",
           esc(crypto.dec(r["body"]))]
    if r["status"] == "done":
        txt += ["", f"✅ <b>نتیجه رسیدگی</b> ({jdate.fmt(r['resolved_day'])} — {esc(db.staff_name(r['resolved_by']))}):",
                esc(crypto.dec(r["resolution"]))]
    kb = []
    if n:
        kb.append([B(f"📎 مشاهده فایل‌ها ({n})", callback_data=f"at:list:incident:{iid}")])
    kb.append([B("➕ افزودن فایل", callback_data=f"inc:att:{iid}")])
    if ctx.can("inc_manage"):
        kb.append([B("🔓 بازگشایی", callback_data=f"inc:reopen:{iid}")] if r["status"] == "done"
                  else [B("✅ حل شد / رسیدگی", callback_data=f"inc:res:{iid}")])
        kb.append([B("🗑 حذف", callback_data=f"inc:del:{iid}")])
    kb.append(back_row(f"inc:list:{r['status']}:0"))
    await ctx.show("\n".join(txt), kb, protect=True)


@route("inc:new", perm=("inc_write", "inc_manage"))
async def inc_new(ctx: Ctx):
    await start_flow(ctx, "inc_new")


async def _inc_done(ctx: Ctx, d):
    iid = db.run("INSERT INTO incidents(day,tm,title,body,severity,created_by) VALUES(?,?,?,?,?,?)",
                 (jdate.today(), jdate.hhmm(), d["title"], crypto.enc(d["body"]), d["sev"], ctx.me["id"]))
    ctx.audit("incident_add", d["title"])
    sev = d["sev"]
    await notify_perm(ctx.bot, "inc_manage", f"📋 <b>مورد جدید</b> {SEV[sev]}\n{esc(d['title'])}\nثبت: {esc(ctx.me['name'])}",
                      [[B("مشاهده", callback_data=f"inc:v:{iid}")]], skip_tg=ctx.tg_id)
    await start_attach(ctx, "incident", iid, f"inc:v:{iid}",
                       "✅ ثبت شد. اگر فایل، عکس یا ویدئو دارید همین‌جا بفرستید؛ وگرنه «پایان» را بزنید.")


define_flow("inc_new", [
    Step("title", "عنوان کوتاه مورد/اتفاق را بنویسید:"),
    Step("body", "شرح کامل ماجرا، افراد درگیر و اقدام انجام‌شده:"),
    Step("sev", "اهمیت:", lambda t: t if t in SEV else "normal", [(v, k) for k, v in SEV.items()]),
], _inc_done, "inc:menu")


@route("inc:att", perm=("inc_write", "inc_manage"))
async def inc_att(ctx: Ctx, iid):
    await start_attach(ctx, "incident", int(iid), f"inc:v:{iid}")


@route("inc:res", perm="inc_manage")
async def inc_res(ctx: Ctx, iid):
    await start_flow(ctx, "inc_res", {"iid": int(iid)})


async def _res_done(ctx, d):
    db.run("UPDATE incidents SET status='done', resolution=?, resolved_by=?, resolved_day=? WHERE id=?",
           (crypto.enc(d["text"]), ctx.me["id"], jdate.today(), d["iid"]))
    ctx.audit("incident_resolve", d["iid"])
    await goto(ctx, f"inc:v:{d['iid']}")


define_flow("inc_res", [Step("text", "نتیجه رسیدگی / اقدام انجام‌شده را بنویسید:")], _res_done, "inc:menu")


@route("inc:reopen", perm="inc_manage")
async def inc_reopen(ctx: Ctx, iid):
    db.run("UPDATE incidents SET status='open' WHERE id=?", (int(iid),))
    await inc_view(ctx, iid)


@route("inc:del", perm="inc_manage")
async def inc_del(ctx: Ctx, iid):
    await ctx.show("⚠️ این مورد و همه فایل‌هایش برای همیشه حذف شود؟",
                   [[B("✅ بله، حذف", callback_data=f"inc:del2:{iid}"), B("خیر", callback_data=f"inc:v:{iid}")]])


@route("inc:del2", perm="inc_manage")
async def inc_del2(ctx: Ctx, iid):
    delete_attachments("incident", int(iid))
    db.run("DELETE FROM incidents WHERE id=?", (int(iid),))
    ctx.audit("incident_delete", iid)
    await inc_menu(ctx)


# ───────────── رویدادهای مهم ─────────────
@route("evt:menu", perm=("evt_view", "evt_manage"))
async def evt_menu(ctx: Ctx):
    kb = [[B("📅 رویدادهای پیش‌رو", callback_data="evt:list:up:0"), B("🗂 گذشته", callback_data="evt:list:past:0")]]
    if ctx.can("evt_manage"):
        kb.insert(0, [B("➕ ثبت رویداد مهم", callback_data="evt:new")])
    kb.append(back_row())
    await ctx.show("📅 <b>رویدادهای مهم</b>\nجلسه، بازدید، مناسبت، مهلت‌های اداری و …", kb)


@route("evt:list", perm=("evt_view", "evt_manage"))
async def evt_list(ctx: Ctx, which, page="0"):
    page, t = int(page), jdate.today()
    cond, order = ("day>=?", "ASC") if which == "up" else ("day<?", "DESC")
    total = db.one(f"SELECT COUNT(*) c FROM events WHERE {cond}", (t,))["c"]
    rows = db.q(f"SELECT * FROM events WHERE {cond} ORDER BY day {order}, id LIMIT 8 OFFSET ?", (t, page * 8))
    kb = [[B(f"{jdate.fmt(r['day'])} — {r['title'][:35]}", callback_data=f"evt:v:{r['id']}")] for r in rows]
    pg = pager(f"evt:list:{which}", page, total, 8)
    if pg:
        kb.append(pg)
    kb.append(back_row("evt:menu"))
    await ctx.show(f"📅 <b>{'رویدادهای پیش‌رو' if which == 'up' else 'رویدادهای گذشته'}</b> ({total})" + ("" if rows else "\n\nموردی نیست."), kb)


@route("evt:v", perm=("evt_view", "evt_manage"))
async def evt_view(ctx: Ctx, eid):
    r = db.one("SELECT * FROM events WHERE id=?", (int(eid),))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    n = len(attachments("event", r["id"]))
    kb = []
    if n:
        kb.append([B(f"📎 فایل‌ها ({n})", callback_data=f"at:list:event:{eid}")])
    if ctx.can("evt_manage"):
        kb.append([B("➕ افزودن فایل", callback_data=f"evt:att:{eid}"), B("🗑 حذف", callback_data=f"evt:del:{eid}")])
    kb.append(back_row("evt:menu"))
    await ctx.show(f"📅 <b>{esc(r['title'])}</b>\n🗓 {jdate.fmt_long(r['day'])}\n"
                   f"🔔 یادآوری به ادمین‌ها: {'بله' if r['remind'] else 'خیر'}\n\n{esc(crypto.dec(r['body']))}", kb)


@route("evt:new", perm="evt_manage")
async def evt_new(ctx: Ctx):
    await start_flow(ctx, "evt_new")


async def _evt_done(ctx: Ctx, d):
    eid = db.run("INSERT INTO events(day,title,body,remind,created_by) VALUES(?,?,?,?,?)",
                 (d["day"], d["title"], crypto.enc(d.get("body")), 1 if d["remind"] == "1" else 0, ctx.me["id"]))
    ctx.audit("event_add", d["title"])
    await start_attach(ctx, "event", eid, f"evt:v:{eid}", "✅ رویداد ثبت شد. در صورت نیاز فایل یا عکس هم بفرستید؛ وگرنه «پایان».")


define_flow("evt_new", [
    Step("day", "📅 تاریخ رویداد :", p_date, kind="date"),
    Step("title", "عنوان رویداد:"),
    Step("body", "توضیحات (اختیاری):", p_text, optional=True),
    Step("remind", "یادآوری خودکار به ادمین‌ها (یک روز قبل و صبح همان روز)؟", lambda t: t, [("🔔 بله", "1"), ("خیر", "0")]),
], _evt_done, "evt:menu")


@route("evt:att", perm="evt_manage")
async def evt_att(ctx: Ctx, eid):
    await start_attach(ctx, "event", int(eid), f"evt:v:{eid}")


@route("evt:del", perm="evt_manage")
async def evt_del(ctx: Ctx, eid):
    await ctx.show("⚠️ این رویداد حذف شود؟",
                   [[B("✅ بله", callback_data=f"evt:del2:{eid}"), B("خیر", callback_data=f"evt:v:{eid}")]])


@route("evt:del2", perm="evt_manage")
async def evt_del2(ctx: Ctx, eid):
    delete_attachments("event", int(eid))
    db.run("DELETE FROM events WHERE id=?", (int(eid),))
    ctx.audit("event_delete", eid)
    await evt_menu(ctx)


# ───────────── پیام همگانی ─────────────
def _sms_ready():
    from .mod_sms import configured
    return configured()


def _bc_targets(_d):
    return [("👥 همه پرسنل", "all")] + [(t["name"], str(t["id"])) for t in db.q("SELECT * FROM titles ORDER BY name")]


async def _bc_done(ctx: Ctx, d):
    if d["ok"] != "1":
        return await ctx.send("لغو شد.", [back_row()])
    if d["target"] == "all":
        rows = db.q("SELECT * FROM staff WHERE active=1 AND tg_id IS NOT NULL")
    else:
        rows = db.q("SELECT * FROM staff WHERE active=1 AND tg_id IS NOT NULL AND title_id=?", (int(d["target"]),))
    sent = 0
    for r in rows:
        if await notify(ctx.bot, r["tg_id"], f"📢 <b>پیام مدیریت</b>\n\n{esc(d['text'])}"):
            sent += 1
    ctx.audit("broadcast", f"{sent}/{len(rows)}")
    extra = ""
    if d.get("sms") == "1":
        from .mod_sms import send_to_staff
        ids = [r["id"] for r in (db.q("SELECT * FROM staff WHERE active=1") if d["target"] == "all"
                                  else db.q("SELECT * FROM staff WHERE active=1 AND title_id=?", (int(d["target"]),)))]
        bg(send_to_staff(ctx.bot, ids, d["text"], ctx.me["id"], "پیام همگانی"))
        extra = "\n📲 پیامک هم در حال ارسال است."
    await ctx.send(f"✅ برای {sent} نفر ارسال شد (از {len(rows)}).{extra}", [back_row()])


@route("bc:menu", perm="broadcast")
async def bc_menu(ctx: Ctx):
    await start_flow(ctx, "bc")


define_flow("bc", [
    Step("target", "📢 پیام برای چه کسانی ارسال شود؟", lambda t: t, _bc_targets),
    Step("text", "متن پیام را بنویسید:"),
    Step("sms", "روش ارسال:", lambda t: t, [("فقط تلگرام", "0"), ("تلگرام + 📲 پیامک", "1")], when=lambda d: _sms_ready()),
    Step("ok", lambda d: f"پیش‌نمایش:\n\n{esc(d['text'])}\n\nارسال شود؟", lambda t: t, [("✅ ارسال", "1"), ("لغو", "0")]),
], _bc_done, "m:main")
