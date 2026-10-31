"""پیامک: ارسال به همه/یک نفر/دسته‌بندی‌شده، زمان‌بندی، گروه‌ها، قالب‌ها و تنظیمات سرویس."""
import json

from telegram import InlineKeyboardButton as B

from . import crypto, db, jdate, sms
from .core import (Ctx, Step, back_row, bg, define_flow, esc, fa, goto, grid, notify, p_date, p_phone, p_text, p_time, route,
                   start_flow)

configured = sms.configured


# ───────────── گیرندگان ─────────────
def _client_phone(c):
    d = crypto.dec_json(c["data"]) or {}
    return d.get("تلفن ولی") or d.get("تلفن") or ""


def staff_item(s):
    return (s["name"], s["phone"] or "")


def client_item(c):
    return (c["name"], _client_phone(c))


def resolve(kind, who=None):
    """→ فهرست (نام، شماره)"""
    if kind == "all":
        return [staff_item(s) for s in db.roster()]
    if kind == "title":
        return [staff_item(s) for s in db.roster() if s["title_id"] == int(who)]
    if kind == "staff":
        s = db.staff_by_id(int(who))
        return [staff_item(s)] if s else []
    if kind == "clients":
        return [client_item(c) for c in db.q("SELECT * FROM clients WHERE status='active' ORDER BY name")]
    if kind == "client":
        c = db.one("SELECT * FROM clients WHERE id=?", (int(who),))
        return [client_item(c)] if c else []
    if kind == "group":
        g = db.one("SELECT * FROM sms_groups WHERE id=?", (int(who),))
        out = []
        for m in json.loads(g["members"]) if g else []:
            t, _, i = m.partition(":")
            if t == "s":
                s = db.staff_by_id(int(i))
                out += [staff_item(s)] if s and s["active"] else []
            else:
                c = db.one("SELECT * FROM clients WHERE id=?", (int(i),))
                out += [client_item(c)] if c else []
        return out
    if kind == "manual":
        return [("", x) for x in str(who).replace("،", " ").replace(",", " ").split()]
    return []


async def send_to_staff(bot, staff_ids, text, by_id, label="پرسنل"):
    """برای ماژول‌های دیگر (وظایف، اعلان‌ها): ارسال پیامک به فهرست شناسهٔ پرسنل."""
    items = [staff_item(s) for s in (db.staff_by_id(i) for i in staff_ids) if s]
    ok, fail, _ = await sms.send_many(items, text, by_id, label)
    return ok, fail


# ───────────── منو ─────────────
@route("sms:menu", perm=("sms_send", "sms_manage"))
async def sms_menu(ctx: Ctx):
    ok = configured()
    kb = []
    if ok and ctx.can("sms_send"):
        kb.append([B("✉️ پیامک جدید", callback_data="sms:new")])
        kb.append([B("🕓 زمان‌بندی‌شده‌ها", callback_data="sms:q"), B("📜 سابقه", callback_data="sms:log:0")])
    if ctx.can("sms_manage"):
        kb.append([B("👥 گروه‌ها", callback_data="sms:grp"), B("📝 قالب‌ها", callback_data="sms:tpl")])
        kb.append([B("⚙️ تنظیم سرویس پیامک", callback_data="sms:set")])
    kb.append(back_row())
    st = "✅ سرویس: " + sms.PROVIDERS[sms.load_cfg()["provider"]][0] if ok else "⚠️ سرویس پیامک هنوز تنظیم نشده."
    await ctx.show(f"📲 <b>پیامک</b>\n{st}", kb)


# ───────────── ارسال ─────────────
def _kinds(_d):
    out = [("👥 همهٔ پرسنل", "all"), ("🏷 یک عنوان شغلی", "title"), ("👤 یک نفر از پرسنل", "staff")]
    if db.one("SELECT 1 FROM sms_groups"):
        out.append(("📂 یک گروه", "group"))
    out += [("🧒 ولی همهٔ مددجویان", "clients"), ("🧒 ولی یک مددجو", "client"), ("✍️ شمارهٔ دستی", "manual")]
    return out


def _who_choices(d):
    k = d["kind"]
    if k == "title":
        return [(t["name"], str(t["id"])) for t in db.q("SELECT * FROM titles ORDER BY name")]
    if k == "staff":
        return [(s["name"], str(s["id"])) for s in db.roster()]
    if k == "group":
        return [(g["name"], str(g["id"])) for g in db.q("SELECT * FROM sms_groups ORDER BY name")]
    if k == "client":
        return [(c["name"], str(c["id"])) for c in db.q("SELECT id,name FROM clients WHERE status='active' ORDER BY name LIMIT 90")]
    return None


def _who_prompt(d):
    return "شماره‌ها را بنویسید (چند شماره با فاصله):" if d["kind"] == "manual" else "انتخاب کنید:"


def _tpl_choices(_d):
    return [(t["name"], t["body"]) for t in db.q("SELECT * FROM sms_tpl ORDER BY name")] or None


def _recips(d):
    return resolve(d["kind"], d.get("who"))


def _confirm_prompt(d):
    r = _recips(d)
    good = sum(1 for _, p in r if sms.normalize(p))
    when = "همین حالا" if d["when"] == "now" else f"{jdate.fmt(d['day'])} ساعت {d['tm']}"
    return (f"📲 <b>تأیید ارسال</b>\nگیرنده: {fa(good)} شماره" + (f" (⚠️ {fa(len(r) - good)} بدون شمارهٔ معتبر)" if good < len(r) else "")
            + f"\nزمان: {when}\n\n{esc(d['text'])}")


@route("sms:new", perm="sms_send")
async def sms_new(ctx: Ctx):
    if not configured():
        return await ctx.answer("ابتدا سرویس پیامک را تنظیم کنید.", True)
    await start_flow(ctx, "sms_new")


async def _sms_done(ctx: Ctx, d):
    r = [(n, p) for n, p in _recips(d) if sms.normalize(p)]
    if not r:
        return await ctx.send("⚠️ هیچ شمارهٔ معتبری پیدا نشد.", [back_row("sms:menu")])
    if d["when"] == "now":
        await ctx.send(f"⏳ ارسال {fa(len(r))} پیامک شروع شد؛ نتیجه را اعلام می‌کنم.", [back_row("sms:menu")])
        bg(_run_and_report(ctx.bot, ctx.tg_id, r, d["text"], ctx.me["id"], d["kind"]))
    else:
        run_at = f"{d['day']}T{d['tm']}"
        db.run("INSERT INTO sms_queue(run_at,by_id,target,recipients,body) VALUES(?,?,?,?,?)",
               (run_at, ctx.me["id"], d["kind"], crypto.enc_json(r), crypto.enc(d["text"])))
        await ctx.send(f"🕓 زمان‌بندی شد: {jdate.fmt(d['day'])} ساعت {d['tm']} برای {fa(len(r))} شماره.", [back_row("sms:menu")])
    ctx.audit("sms_new", f"{d['kind']} n={len(r)} {d['when']}")


async def _run_and_report(bot, tg_id, items, text, by_id, label):
    ok, fail, errs = await sms.send_many(items, text, by_id, label)
    msg = f"📲 نتیجهٔ ارسال پیامک: ✅ {fa(ok)} موفق" + (f" — ❌ {fa(fail)} ناموفق" if fail else "")
    if errs:
        msg += "\n" + "\n".join("• " + esc(e) for e in errs[:8])
    await notify(bot, tg_id, msg)


define_flow("sms_new", [
    Step("kind", "پیامک برای چه کسانی؟", lambda t: t, _kinds),
    Step("who", _who_prompt, lambda t: t.strip(), _who_choices, when=lambda d: d["kind"] in ("title", "staff", "group", "client", "manual")),
    Step("text", "✍️ متن پیامک را بنویسید (می‌توانید {name} را برای درج نام بنویسید) یا یک قالب بزنید:", p_text, _tpl_choices),
    Step("when", "ارسال:", lambda t: t, [("🚀 همین حالا", "now"), ("🕓 زمان‌بندی", "later")]),
    Step("day", "📅 روز ارسال:", p_date, kind="date", when=lambda d: d["when"] == "later"),
    Step("tm", "⏰ ساعت ارسال:", p_time, kind="time", when=lambda d: d["when"] == "later"),
    Step("ok", _confirm_prompt, lambda t: t, [("✅ ارسال", "1")]),
], _sms_done, "sms:menu")


# ───────────── صف زمان‌بندی ─────────────
async def process_queue(bot):
    """هر دقیقه: پیامک‌های موعدرسیده را می‌فرستد."""
    now = jdate.now().strftime("%Y-%m-%dT%H:%M")
    for row in db.q("SELECT * FROM sms_queue WHERE status='pending' AND run_at<=? ORDER BY id", (now,)):
        db.run("UPDATE sms_queue SET status='sending' WHERE id=?", (row["id"],))
        items = [tuple(x) for x in crypto.dec_json(row["recipients"])]
        ok, fail, _ = await sms.send_many(items, crypto.dec(row["body"]), row["by_id"], row["target"] or "زمان‌بندی")
        db.run("UPDATE sms_queue SET status=?, note=? WHERE id=?", ("done" if ok else "failed", f"{ok}/{fail}", row["id"]))
        by = db.staff_by_id(row["by_id"]) if row["by_id"] else None
        if by and by["tg_id"]:
            await notify(bot, by["tg_id"], f"📲 پیامک زمان‌بندی‌شده ارسال شد: ✅ {fa(ok)} — ❌ {fa(fail)}")


@route("sms:q", perm="sms_send")
async def sms_q(ctx: Ctx):
    rows = db.q("SELECT * FROM sms_queue WHERE status='pending' ORDER BY run_at")
    kb = []
    lines = []
    for r in rows:
        day, _, tm = r["run_at"].partition("T")
        n = len(crypto.dec_json(r["recipients"]))
        lines.append(f"• {jdate.fmt(day)} {tm} — {fa(n)} گیرنده\n  {esc(crypto.dec(r['body'])[:50])}")
        kb.append([B(f"🗑 لغو {jdate.fmt(day)} {tm}", callback_data=f"sms:qd:{r['id']}")])
    kb.append(back_row("sms:menu"))
    await ctx.show("🕓 <b>پیامک‌های زمان‌بندی‌شده</b>\n" + ("\n".join(lines) or "مورد منتظری نیست."), kb)


@route("sms:qd", perm="sms_send")
async def sms_qd(ctx: Ctx, rid):
    db.run("UPDATE sms_queue SET status='cancelled' WHERE id=? AND status='pending'", (int(rid),))
    await sms_q(ctx)


@route("sms:log", perm="sms_send")
async def sms_log(ctx: Ctx, page="0"):
    from .core import pager
    page = int(page)
    total = db.one("SELECT COUNT(*) c FROM sms_log")["c"]
    rows = db.q("SELECT * FROM sms_log ORDER BY id DESC LIMIT 10 OFFSET ?", (page * 10,))
    lines = [f"• {esc(r['ts'][5:16])} {esc(db.staff_name(r['by_id']))}: ✅{fa(r['n_ok'])} ❌{fa(r['n_fail'])}\n  {esc(crypto.dec(r['body'])[:60])}" for r in rows]
    kb = []
    pg = pager("sms:log", page, total, 10)
    if pg:
        kb.append(pg)
    kb.append(back_row("sms:menu"))
    await ctx.show("📜 <b>سابقهٔ پیامک</b> (زمان UTC)\n" + ("\n".join(lines) or "خالی"), kb)


# ───────────── گروه‌ها ─────────────
@route("sms:grp", perm="sms_manage")
async def sms_grp(ctx: Ctx):
    rows = db.q("SELECT * FROM sms_groups ORDER BY name")
    kb = [[B(f"📂 {g['name']} ({fa(len(json.loads(g['members'])))})", callback_data=f"sms:gv:{g['id']}")] for g in rows]
    kb.append([B("➕ گروه جدید", callback_data="sms:gn")])
    kb.append(back_row("sms:menu"))
    await ctx.show("👥 <b>گروه‌های پیامک</b>\nمثلاً «همکاران شیفت شب» یا «اولیای گروه الف».", kb)


@route("sms:gn", perm="sms_manage")
async def sms_gn(ctx: Ctx):
    await start_flow(ctx, "sms_gn")


async def _gn_done(ctx, d):
    try:
        gid = db.run("INSERT INTO sms_groups(name) VALUES(?)", (d["name"],))
    except Exception:
        return await ctx.send("⚠️ این نام قبلاً هست.", [back_row("sms:grp")])
    await goto(ctx, f"sms:gv:{gid}")


define_flow("sms_gn", [Step("name", "نام گروه:")], _gn_done, "sms:grp")


def _members(gid):
    g = db.one("SELECT * FROM sms_groups WHERE id=?", (int(gid),))
    return g, set(json.loads(g["members"])) if g else set()


@route("sms:gv", perm="sms_manage")
async def sms_gv(ctx: Ctx, gid, cpage="0"):
    g, mem = _members(gid)
    if not g:
        return await ctx.answer("پیدا نشد", True)
    cpage = int(cpage)
    kb = [[B(("✅ " if f"s:{s['id']}" in mem else "⬜️ ") + s["name"], callback_data=f"sms:gt:{gid}:s:{s['id']}:{cpage}")] for s in db.roster()]
    clients = db.q("SELECT id,name FROM clients WHERE status='active' ORDER BY name")
    per = 15
    for c in clients[cpage * per:(cpage + 1) * per]:
        kb.append([B(("✅ 🧒 " if f"c:{c['id']}" in mem else "⬜️ 🧒 ") + c["name"], callback_data=f"sms:gt:{gid}:c:{c['id']}:{cpage}")])
    nav = []
    if cpage > 0:
        nav.append(B("◀️ مددجویان قبل", callback_data=f"sms:gv:{gid}:{cpage - 1}"))
    if (cpage + 1) * per < len(clients):
        nav.append(B("مددجویان بعد ▶️", callback_data=f"sms:gv:{gid}:{cpage + 1}"))
    if nav:
        kb.append(nav)
    kb.append([B("🗑 حذف گروه", callback_data=f"sms:gd:{gid}")])
    kb.append(back_row("sms:grp"))
    await ctx.show(f"📂 <b>{esc(g['name'])}</b> — {fa(len(mem))} عضو\nبرای افزودن/حذف روی نام بزنید. (برای مددجو، شمارهٔ ولی استفاده می‌شود)", kb)


@route("sms:gt", perm="sms_manage")
async def sms_gt(ctx: Ctx, gid, t, i, cpage="0"):
    g, mem = _members(gid)
    if not g or t not in ("s", "c"):
        return await ctx.answer("نامعتبر", True)
    mem.symmetric_difference_update({f"{t}:{int(i)}"})
    db.run("UPDATE sms_groups SET members=? WHERE id=?", (json.dumps(sorted(mem)), g["id"]))
    await sms_gv(ctx, gid, cpage)


@route("sms:gd", perm="sms_manage")
async def sms_gd(ctx: Ctx, gid):
    db.run("DELETE FROM sms_groups WHERE id=?", (int(gid),))
    ctx.audit("sms_group_del", gid)
    await sms_grp(ctx)


# ───────────── قالب‌ها ─────────────
@route("sms:tpl", perm="sms_manage")
async def sms_tpl(ctx: Ctx):
    rows = db.q("SELECT * FROM sms_tpl ORDER BY name")
    kb = [[B(f"🗑 {t['name']}", callback_data=f"sms:td:{t['id']}")] for t in rows]
    kb.append([B("➕ قالب جدید", callback_data="sms:tn")])
    kb.append(back_row("sms:menu"))
    await ctx.show("📝 <b>قالب‌های پیامک</b>\n" + ("\n".join(f"• <b>{esc(t['name'])}</b>: {esc(t['body'][:60])}" for t in rows) or "قالبی نیست."), kb)


@route("sms:tn", perm="sms_manage")
async def sms_tn(ctx: Ctx):
    await start_flow(ctx, "sms_tn")


async def _tn_done(ctx, d):
    db.run("INSERT INTO sms_tpl(name,body) VALUES(?,?)", (d["name"], d["body"]))
    await goto(ctx, "sms:tpl")


define_flow("sms_tn", [Step("name", "نام قالب (مثلاً «یادآوری جلسه»):"), Step("body", "متن قالب ({name} = نام گیرنده):")], _tn_done, "sms:tpl")


@route("sms:td", perm="sms_manage")
async def sms_td(ctx: Ctx, tid):
    db.run("DELETE FROM sms_tpl WHERE id=?", (int(tid),))
    await sms_tpl(ctx)


# ───────────── تنظیم سرویس ─────────────
_NOTE = ("⚠️ مشخصات هر سرویس از مستندات عمومی نوشته شده؛ حتماً «ارسال آزمایشی» را بزنید.\n"
         "برای ارسال از سیم‌کارت: روی یک گوشی اندرویدی اپ «SMS Gateway» نصب و به اینترنت وصل باشد و سرور آن "
         "از بیرون (اینترنت) قابل دسترس باشد.")


@route("sms:set", perm="sms_manage")
async def sms_set(ctx: Ctx):
    c = sms.load_cfg()
    cur = sms.PROVIDERS[c["provider"]][0] if c.get("provider") in sms.PROVIDERS else "تنظیم نشده"
    kb = [[B("🔧 انتخاب/تغییر سرویس", callback_data="sms:sp")]]
    if configured():
        kb.append([B("🧪 ارسال آزمایشی", callback_data="sms:test")])
        kb.append([B("🗑 حذف تنظیمات", callback_data="sms:clr")])
    kb.append(back_row("sms:menu"))
    await ctx.show(f"⚙️ <b>تنظیم پیامک</b>\nسرویس فعلی: {esc(cur)}\n\n{_NOTE}", kb)


@route("sms:sp", perm="sms_manage")
async def sms_sp(ctx: Ctx):
    await start_flow(ctx, "sms_cfg")


def _fld(f):
    return Step(f, f"{sms.FIELD_LABEL[f]}:", p_text, secret=f in sms.SECRET_FIELDS,
                optional=(f == "sender"),
                when=lambda d, f=f: f in sms.PROVIDERS[d["provider"]][1])


async def _cfg_done(ctx, d):
    cfg = {"provider": d["provider"]}
    for f in sms.FIELD_LABEL:
        if f in sms.PROVIDERS[d["provider"]][1] and d.get(f):
            cfg[f] = d[f].strip()
    sms.save_cfg(cfg)
    ctx.audit("sms_cfg", d["provider"])
    await ctx.send("✅ ذخیره شد. حالا «ارسال آزمایشی» را بزنید.", [[B("🧪 ارسال آزمایشی", callback_data="sms:test")], back_row("sms:set")])


define_flow("sms_cfg", [
    Step("provider", "کدام سرویس؟", lambda t: t, [(v[0], k) for k, v in sms.PROVIDERS.items()]),
    *[_fld(f) for f in ("apikey", "username", "password", "url", "sender")],
], _cfg_done, "sms:set")


@route("sms:test", perm="sms_manage")
async def sms_test(ctx: Ctx):
    await start_flow(ctx, "sms_test")


async def _test_done(ctx, d):
    ok, fail, errs = await sms.send_many([("", d["phone"])], "آزمایش پیامک ربات مرکز آدینه", ctx.me["id"], "آزمایشی")
    await ctx.send("✅ ارسال شد؛ گوشی را بررسی کنید." if ok else "❌ ارسال نشد: " + esc("; ".join(errs) or "نامشخص")
                   + "\nنشانی/کلید و دسترسی اینترنتی سرویس را بررسی کنید.", [back_row("sms:set")])


define_flow("sms_test", [Step("phone", "📱 شمارهٔ موبایل خودتان برای آزمایش:", p_phone)], _test_done, "sms:set")


@route("sms:clr", perm="sms_manage")
async def sms_clr(ctx: Ctx):
    db.kv_set("sms_cfg", "")
    ctx.audit("sms_cfg_clear")
    await sms_set(ctx)
