"""پرسنل، عناوین و دسترسی‌ها، داشبورد و ابزارهای سیستم (فقط ادمین)."""
import json
import secrets
import tempfile
from pathlib import Path

from telegram import InlineKeyboardButton as B

from . import config, crypto, db, invite, jdate
from .core import (Ctx, Step, back_row, define_flow, esc, goto, grid, money, p_phone, p_text, route,
                   start_flow, notify_admins, p_text)
from .perms import GROUPS, PERMS


# ───────────── پرسنل ─────────────
@route("st:menu", perm="admin")
async def st_menu(ctx: Ctx):
    rows = db.q("SELECT * FROM staff ORDER BY active DESC, name")
    kb = []
    for r in rows:
        mark = "👑" if r["is_admin"] else ("⛔" if not r["active"] else "👤")
        link = "" if r["tg_id"] else " 🔗؟"
        kb.append([B(f"{mark} {r['name']} — {db.title_label(r)}{link}",
                     callback_data=f"st:v:{r['id']}")])
    kb.append([B("➕ افزودن پرسنل", callback_data="st:add"), B("🏷 عناوین و دسترسی‌ها", callback_data="tt:menu")])
    kb.append(back_row())
    await ctx.show(f"👥 <b>پرسنل</b> ({len(rows)} نفر)\n🔗؟ = هنوز به تلگرام وصل نشده", kb)


@route("st:v", perm="admin")
async def st_view(ctx: Ctx, sid):
    r = db.staff_by_id(int(sid))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    t = db.title_label(r) + (" (دسترسی کامل مدیریت)" if r["is_admin"] else "")
    txt = (f"👤 <b>{esc(r['name'])}</b>\n🏷 عنوان: {esc(t)}\n📞 تلفن: {esc(r['phone'] or '—')}\n"
           f"🔗 تلگرام: {'وصل ✅ (' + str(r['tg_id']) + ')' if r['tg_id'] else 'وصل نشده'}\n"
           f"وضعیت: {'فعال' if r['active'] else 'غیرفعال'}"
           + (f"\n🔑 کد دعوت فعال است (تا {invite.exp_local(r['invite_exp'])})" if (not r["tg_id"] and r["invite_code"] and r["invite_exp"] and not invite.expired(r["invite_exp"])) else ""))
    kb = [[B("✏️ نام", callback_data=f"st:en:{sid}"), B("📞 تلفن", callback_data=f"st:ep:{sid}")],
          [B("🏷 تغییر عنوان", callback_data=f"st:title:{sid}")]]
    if not r["is_admin"]:
        ov = len(_ov(r))
        kb.append([B("🔐 دسترسی‌های این فرد" + (f" ({ov} استثنا)" if ov else ""), callback_data=f"st:pm:{sid}")])
    if not r["tg_id"]:
        active = r["invite_code"] and r["invite_exp"] and not invite.expired(r["invite_exp"])
        kb.append([B("🔑 کد جدید (کد قبلی باطل)" if active else "🔑 ساخت کد دعوت", callback_data=f"st:inv:{sid}")])
        if active:
            kb.append([B("🚫 لغو کد فعال", callback_data=f"st:rv:{sid}")])
    else:
        kb.append([B("🔌 جدا کردن تلگرام", callback_data=f"st:unb:{sid}")])
    kb.append([B("👑 دسترسی مدیر: " + ("روشن" if r["is_admin"] else "خاموش"), callback_data=f"st:adm:{sid}"), B("⛔/✅ فعال‌سازی", callback_data=f"st:tog:{sid}")])
    kb.append(back_row("st:menu"))
    await ctx.show(txt, kb)


def _invite(sid):
    """کد تازه می‌سازد (کد قبلی باطل می‌شود)؛ فقط هش ذخیره می‌شود و کد خام یک‌بار نمایش داده می‌شود."""
    raw = invite.generate()
    db.run("UPDATE staff SET invite_code=?, invite_exp=? WHERE id=?", (invite.digest(raw), invite.expiry(), sid))
    return raw


async def _show_invite(ctx: Ctx, sid, raw):
    uname = ctx.bot.username
    link = f"https://t.me/{uname}?start={raw}" if uname else ""
    await ctx.show(
        f"🔑 <b>کد دعوت اختصاصی {esc(db.staff_name(sid))}</b>\n\n<code>{invite.pretty(raw)}</code>\n\n"
        f"لینک مستقیم:\n{esc(link)}\n\n"
        f"• فقط برای همین فرد، <b>یک‌بار مصرف</b> و تا {config.INVITE_HOURS} ساعت معتبر است.\n"
        "• کد را فقط حضوری یا از مسیر امن به خود فرد بدهید؛ این کد دیگر نمایش داده نمی‌شود "
        "(اگر گم شد «کد جدید» بسازید).\n"
        "• بعد از اتصال، به شما اطلاع داده می‌شود که چه حساب تلگرامی وصل شده است.",
        [[B("🚫 لغو این کد", callback_data=f"st:rv:{sid}")], back_row(f"st:v:{sid}")])


@route("st:rv", perm="admin")
async def st_revoke(ctx: Ctx, sid):
    db.run("UPDATE staff SET invite_code=NULL, invite_exp=NULL WHERE id=?", (int(sid),))
    ctx.audit("invite_revoke", db.staff_name(int(sid)))
    await ctx.answer("کد لغو شد")
    await st_view(ctx, sid)


@route("st:inv", perm="admin")
async def st_inv(ctx: Ctx, sid):
    await _show_invite(ctx, int(sid), _invite(int(sid)))


@route("st:unb", perm="admin")
async def st_unb(ctx: Ctx, sid):
    r = db.staff_by_id(int(sid))
    if r["is_admin"] and r["tg_id"] in config.ADMIN_IDS:
        return await ctx.answer("ادمین اصلی (از تنظیمات سرور) را نمی‌توان جدا کرد.", True)
    db.run("UPDATE staff SET tg_id=NULL WHERE id=?", (int(sid),))
    ctx.audit("staff_unbind", r["name"])
    await ctx.answer("جدا شد")
    await st_view(ctx, sid)


@route("st:adm", perm="admin")
async def st_adm(ctx: Ctx, sid):
    r = db.staff_by_id(int(sid))
    if r["tg_id"] in config.ADMIN_IDS and r["is_admin"]:
        return await ctx.answer("ادمین اصلی را نمی‌توان تغییر داد.", True)
    if r["is_admin"] and db.one("SELECT COUNT(*) c FROM staff WHERE is_admin=1 AND active=1")["c"] <= 1:
        return await ctx.answer("حداقل یک ادمین باید بماند.", True)
    db.run("UPDATE staff SET is_admin=? WHERE id=?", (0 if r["is_admin"] else 1, r["id"]))
    ctx.audit("staff_admin_toggle", r["name"])
    await st_view(ctx, sid)


@route("st:tog", perm="admin")
async def st_tog(ctx: Ctx, sid):
    r = db.staff_by_id(int(sid))
    if r["tg_id"] == ctx.tg_id:
        return await ctx.answer("نمی‌توانید خودتان را غیرفعال کنید.", True)
    if r["tg_id"] in config.ADMIN_IDS:
        return await ctx.answer("ادمین اصلی را نمی‌توان غیرفعال کرد.", True)
    db.run("UPDATE staff SET active=? WHERE id=?", (0 if r["active"] else 1, r["id"]))
    ctx.audit("staff_active_toggle", r["name"])
    await st_view(ctx, sid)


@route("st:title", perm="admin")
async def st_title(ctx: Ctx, sid):
    kb = grid([B(t["name"], callback_data=f"st:sett:{sid}:{t['id']}") for t in db.q("SELECT * FROM titles ORDER BY name")])
    kb.append(back_row(f"st:v:{sid}"))
    await ctx.show("🏷 عنوان جدید را انتخاب کنید:", kb)


@route("st:sett", perm="admin")
async def st_sett(ctx: Ctx, sid, tid):
    db.run("UPDATE staff SET title_id=? WHERE id=?", (int(tid), int(sid)))
    ctx.audit("staff_title", f"{sid}->{tid}")
    await st_view(ctx, sid)


@route("st:add", perm="admin")
async def st_add(ctx: Ctx):
    await start_flow(ctx, "st_add")


def _title_choices(_d):
    return [(t["name"], str(t["id"])) for t in db.q("SELECT * FROM titles ORDER BY name")]


async def _st_add_done(ctx: Ctx, d):
    sid = db.run("INSERT INTO staff(name,title_id,phone) VALUES(?,?,?)", (d["name"], int(d["title"]), d.get("phone")))
    ctx.audit("staff_add", d["name"])
    await _show_invite(ctx, sid, _invite(sid))


define_flow("st_add", [
    Step("name", "نام و نام خانوادگی پرسنل را بنویسید:"),
    Step("title", "عنوان (سمت) را انتخاب کنید:", parse=lambda t: int(t), choices=_title_choices),
    Step("phone", "شماره تلفن (اختیاری):", parse=p_phone, optional=True),
], _st_add_done, "st:menu")


@route("st:en", perm="admin")
async def st_en(ctx: Ctx, sid):
    await start_flow(ctx, "st_en", {"sid": int(sid)})


@route("st:ep", perm="admin")
async def st_ep(ctx: Ctx, sid):
    await start_flow(ctx, "st_ep", {"sid": int(sid)})


async def _en_done(ctx, d):
    db.run("UPDATE staff SET name=? WHERE id=?", (d["v"], d["sid"]))
    await goto(ctx, f"st:v:{d['sid']}")


async def _ep_done(ctx, d):
    db.run("UPDATE staff SET phone=? WHERE id=?", (d["v"], d["sid"]))
    await goto(ctx, f"st:v:{d['sid']}")


define_flow("st_en", [Step("v", "نام جدید را بنویسید:")], _en_done, "st:menu")
define_flow("st_ep", [Step("v", "شماره تلفن جدید:", parse=p_phone)], _ep_done, "st:menu")


# ───────────── دسترسی جزءبه‌جز برای هر فرد ─────────────
def _lists(r):
    try:
        g = set(json.loads(r["perm_grant"] or "[]"))
        d = set(json.loads(r["perm_deny"] or "[]"))
    except Exception:
        g, d = set(), set()
    return g, d


def _ov(r):
    g, d = _lists(r)
    return (g | d) & set(PERMS)


def _title_base(r):
    t = db.one("SELECT perms FROM titles WHERE id=?", (r["title_id"],)) if r["title_id"] else None
    return set(json.loads(t["perms"])) if t else set()


@route("st:pm", perm="admin")
async def st_pm(ctx: Ctx, sid):
    r = db.staff_by_id(int(sid))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    if r["is_admin"]:
        return await ctx.answer("مدیر همهٔ دسترسی‌ها را دارد.", True)
    eff = db.perms_of(r)
    ov = _ov(r)
    kb = []
    for title, items in GROUPS:
        kb.append([B(title, callback_data=f"st:pm:{sid}")])
        for k, lb in items:
            kb.append([B(("✅ " if k in eff else "⬜️ ") + lb + (" ✱" if k in ov else ""), callback_data=f"st:pt:{sid}:{k}")])
    kb.append([B("↩️ برگرداندن همه به دسترسی عنوان", callback_data=f"st:pr:{sid}")])
    kb.append(back_row(f"st:v:{sid}"))
    await ctx.show(f"🔐 <b>دسترسی‌های {esc(r['name'])}</b> — {esc(db.title_label(r))}\n"
                   "روی هر مورد بزنید تا روشن/خاموش شود. ✱ = استثنا نسبت به دسترسی عنوان.", kb)


@route("st:pt", perm="admin")
async def st_pt(ctx: Ctx, sid, perm):
    r = db.staff_by_id(int(sid))
    if not r or perm not in PERMS or r["is_admin"]:
        return await ctx.answer("نامعتبر", True)
    base = _title_base(r)
    g, d = _lists(r)
    want = perm not in db.perms_of(r)  # وضعیت جدید
    g.discard(perm)
    d.discard(perm)
    if want and perm not in base:
        g.add(perm)
    if not want and perm in base:
        d.add(perm)
    db.run("UPDATE staff SET perm_grant=?, perm_deny=? WHERE id=?",
           (json.dumps(sorted(g)), json.dumps(sorted(d)), r["id"]))
    ctx.audit("person_perm", f"{r['name']}:{perm}={'on' if want else 'off'}")
    await st_pm(ctx, sid)


@route("st:pr", perm="admin")
async def st_pr(ctx: Ctx, sid):
    db.run("UPDATE staff SET perm_grant='[]', perm_deny='[]' WHERE id=?", (int(sid),))
    ctx.audit("person_perm_reset", db.staff_name(int(sid)))
    await st_pm(ctx, sid)


# ───────────── عناوین و دسترسی‌ها ─────────────
@route("tt:menu", perm="admin")
async def tt_menu(ctx: Ctx):
    rows = db.q("SELECT t.*, (SELECT COUNT(*) FROM staff s WHERE s.title_id=t.id) n FROM titles t ORDER BY name")
    kb = [[B(f"🏷 {t['name']} ({t['n']} نفر)", callback_data=f"tt:v:{t['id']}")] for t in rows]
    kb.append([B("➕ عنوان جدید", callback_data="tt:add")])
    kb.append(back_row("st:menu"))
    await ctx.show("🏷 <b>عناوین و دسترسی‌ها</b>\nهر عنوان مجموعه‌ای از دسترسی‌هاست. ادمین‌ها همه دسترسی‌ها را دارند.", kb)


@route("tt:v", perm="admin")
async def tt_view(ctx: Ctx, tid):
    t = db.one("SELECT * FROM titles WHERE id=?", (int(tid),))
    if not t:
        return await ctx.answer("پیدا نشد", True)
    have = set(json.loads(t["perms"]))
    kb = []
    for title, items in GROUPS:
        kb.append([B(title, callback_data=f"tt:v:{tid}")])
        kb += [[B(("✅ " if k in have else "⬜️ ") + lb, callback_data=f"tt:tg:{tid}:{k}")] for k, lb in items]
    kb.append([B("✏️ تغییر نام", callback_data=f"tt:ren:{tid}"), B("🗑 حذف", callback_data=f"tt:del:{tid}")])
    kb.append(back_row("tt:menu"))
    await ctx.show(f"🏷 <b>{esc(t['name'])}</b>\nبرای روشن/خاموش کردن هر دسترسی روی آن بزنید:", kb)


@route("tt:tg", perm="admin")
async def tt_tg(ctx: Ctx, tid, perm):
    t = db.one("SELECT * FROM titles WHERE id=?", (int(tid),))
    if perm not in PERMS:
        return
    have = set(json.loads(t["perms"]))
    have.symmetric_difference_update({perm})
    db.run("UPDATE titles SET perms=? WHERE id=?", (json.dumps(sorted(have)), t["id"]))
    ctx.audit("title_perm", f"{t['name']}:{perm}")
    await tt_view(ctx, tid)


@route("tt:add", perm="admin")
async def tt_add(ctx: Ctx):
    await start_flow(ctx, "tt_add")


async def _tt_add_done(ctx, d):
    try:
        tid = db.run("INSERT INTO titles(name,perms) VALUES(?,?)", (d["name"], json.dumps(["att_view_self", "task_self", "dig_recv", "rep_write", "leave_self", "loan_self"])))
    except Exception:
        return await ctx.send("⚠️ این عنوان قبلاً وجود دارد.", [back_row("tt:menu")])
    await goto(ctx, f"tt:v:{tid}")


define_flow("tt_add", [Step("name", "نام عنوان جدید (مثلاً «مسئول آشپزخانه»):")], _tt_add_done, "tt:menu")


@route("tt:ren", perm="admin")
async def tt_ren(ctx: Ctx, tid):
    await start_flow(ctx, "tt_ren", {"tid": int(tid)})


async def _tt_ren_done(ctx, d):
    try:
        db.run("UPDATE titles SET name=? WHERE id=?", (d["v"], d["tid"]))
    except Exception:
        return await ctx.send("⚠️ این نام قبلاً وجود دارد.")
    await goto(ctx, f"tt:v:{d['tid']}")


define_flow("tt_ren", [Step("v", "نام جدید عنوان:")], _tt_ren_done, "tt:menu")


@route("tt:del", perm="admin")
async def tt_del(ctx: Ctx, tid):
    n = db.one("SELECT COUNT(*) c FROM staff WHERE title_id=?", (int(tid),))["c"]
    if n:
        return await ctx.answer(f"{n} نفر این عنوان را دارند؛ ابتدا عنوان آن‌ها را عوض کنید.", True)
    db.run("DELETE FROM titles WHERE id=?", (int(tid),))
    await tt_menu(ctx)


# ───────────── داشبورد و سیستم ─────────────
@route("sys:dash", perm="admin")
async def dash(ctx: Ctx):
    from . import attlogic
    t = jdate.today()
    people = db.roster()
    groups = {}
    for p in people:
        st = attlogic.eff_status(p["id"], t)
        groups.setdefault(st or "none", []).append(p)
    def names(k):
        out = []
        for p in groups.get(k, []):
            extra = attlogic.times_text(attlogic.records(p["id"], t)) if k == "present" else ""
            out.append(p["name"] + (f" ({extra})" if extra else ""))
        return "، ".join(out) or "—"
    lv = "، ".join(x for x in (names("leave"), names("sick"), names("mission")) if x != "—")
    inc = db.one("SELECT COUNT(*) c FROM incidents WHERE status='open'")["c"]
    pend = db.one("SELECT COUNT(*) c FROM leaves WHERE status='pending'")["c"]
    evs = db.q("SELECT * FROM events WHERE day=? ORDER BY id", (t,))
    cli = db.one("SELECT COUNT(*) c FROM clients WHERE status='active'")["c"]
    loans = db.q("SELECT l.*, COALESCE((SELECT SUM(amount) FROM loan_payments p WHERE p.loan_id=l.id),0) paid FROM loans l WHERE status='active'")
    rem = sum(max(0, l["amount"] - l["paid"]) for l in loans)
    tasks = db.q("SELECT status FROM tasks WHERE day=?", (t,))
    txt = [f"📈 <b>داشبورد امروز</b> — {jdate.fmt_long(t)}", "",
           f"✅ حاضر ({len(groups.get('present', []))}): " + names("present"),
           f"❌ غایب ({len(groups.get('absent', []))}): " + names("absent"),
           "🏖 مرخصی/بیماری/ماموریت: " + (lv or "—"),
           f"⏳ ثبت نشده ({len(groups.get('none', []))}): " + names("none"), "",
           f"🧒 مددجویان فعال: {cli}",
           f"📋 امور باز: {inc}   🕓 مرخصی در انتظار: {pend}",
           f"📌 وظایف امروز: {sum(1 for x in tasks if x['status'] == 'done')} از {len(tasks)} انجام شد",
           f"💰 وام‌های فعال: {len(loans)} — مانده کل: {money(rem)}"]
    if evs:
        txt += ["", "📅 رویدادهای امروز:"] + [f"• {esc(e['title'])}" for e in evs]
    await ctx.show("\n".join(txt), [[B("🔄 تازه‌سازی", callback_data="sys:dash")], back_row()])


@route("sys:menu", perm="admin")
async def sys_menu(ctx: Ctx):
    await ctx.show("⚙️ <b>سیستم</b>", [
        [B("💾 پشتیبان‌گیری فوری", callback_data="sys:bk")],
        [B("🧾 گزارش فعالیت‌ها (ممیزی)", callback_data="sys:aud:0")],
        back_row()])


async def send_backup(bot, tg_id):
    tmp = Path(tempfile.mkdtemp()) / "adineh.db"
    db.backup_to(tmp)
    data = crypto.enc_bytes(tmp.read_bytes())
    tmp.unlink()
    name = f"backup-{jdate.fmt(jdate.today()).replace('/', '-')}.db.enc"
    import io
    bio = io.BytesIO(data)
    bio.name = name
    await bot.send_document(tg_id, bio, caption="💾 پشتیبان رمزنگاری‌شده. برای بازیابی: tools/decrypt_backup.py", protect_content=True)


@route("sys:bk", perm="admin")
async def sys_bk(ctx: Ctx):
    await ctx.answer("در حال تهیه پشتیبان…")
    await send_backup(ctx.bot, ctx.tg_id)
    ctx.audit("backup_manual")


@route("sys:aud", perm="admin")
async def sys_aud(ctx: Ctx, page="0"):
    page = int(page)
    from .core import pager
    total = db.one("SELECT COUNT(*) c FROM audit")["c"]
    rows = db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 15 OFFSET ?", (page * 15,))
    lines = []
    for r in rows:
        s = db.staff_by_tg(r["tg_id"]) if r["tg_id"] else None
        lines.append(f"• {esc(r['ts'][5:16])} — {esc(s['name'] if s else r['tg_id'])}: {esc(r['action'])} {esc(r['detail'] or '')}")
    kb = []
    pg = pager("sys:aud", page, total, 15)
    if pg:
        kb.append(pg)
    kb.append(back_row("sys:menu"))
    await ctx.show("🧾 <b>گزارش فعالیت‌ها</b> (زمان به UTC)\n\n" + ("\n".join(lines) or "خالی"), kb)


# ───────────── پروفایل من ─────────────
@route("me:menu")
async def me_menu(ctx: Ctx):
    me = ctx.me
    eff = db.perms_of(me)
    on = [lb for _, items in GROUPS for k, lb in items if k in eff]
    txt = (f"👤 <b>{esc(me['name'])}</b>\n🏷 {esc(db.title_label(me))}\n📞 {esc(me['phone'] or '—')}\n\n"
           "✅ دسترسی‌های فعال شما:\n" + ("\n".join("• " + x for x in on) or "—"))
    kb = [[B("✏️ نام من", callback_data="me:name"), B("📞 تلفن من", callback_data="me:phone")]]
    if ctx.is_admin:
        kb.append([B("🏷 عنوان شغلی من", callback_data="me:title")])
    kb.append(back_row())
    await ctx.show(txt, kb)


@route("me:name")
async def me_name(ctx: Ctx):
    await start_flow(ctx, "me_name")


@route("me:phone")
async def me_phone(ctx: Ctx):
    await start_flow(ctx, "me_phone")


async def _me_name_done(ctx, d):
    db.run("UPDATE staff SET name=? WHERE id=?", (d["v"], ctx.me["id"]))
    await goto(ctx, "me:menu")


async def _me_phone_done(ctx, d):
    db.run("UPDATE staff SET phone=? WHERE id=?", (d["v"], ctx.me["id"]))
    await goto(ctx, "me:menu")


define_flow("me_name", [Step("v", "نام و نام خانوادگی شما:")], _me_name_done, "me:menu")
define_flow("me_phone", [Step("v", "شمارهٔ تلفن شما:", parse=p_phone)], _me_phone_done, "me:menu")


@route("me:title")
async def me_title(ctx: Ctx):
    if not ctx.is_admin:
        return await ctx.answer("عنوان شما را مدیر تعیین می‌کند.", True)
    kb = grid([B(t["name"], callback_data=f"me:st:{t['id']}") for t in db.q("SELECT * FROM titles ORDER BY name")])
    kb.append([B("➕ عنوان تازه", callback_data="me:new")])
    kb.append(back_row("me:menu"))
    await ctx.show("🏷 عنوان شغلی خود را انتخاب کنید (به‌جای «ادمین» نمایش داده می‌شود):", kb)


@route("me:st")
async def me_set_title(ctx: Ctx, tid):
    if not ctx.is_admin:
        return await ctx.answer("⛔", True)
    db.run("UPDATE staff SET title_id=? WHERE id=?", (int(tid), ctx.me["id"]))
    ctx.audit("me_title", tid)
    await goto(ctx, "me:menu")


@route("me:new")
async def me_new_title(ctx: Ctx):
    if not ctx.is_admin:
        return await ctx.answer("⛔", True)
    await start_flow(ctx, "me_new")


async def _me_new_done(ctx, d):
    try:
        tid = db.run("INSERT INTO titles(name,perms) VALUES(?,?)", (d["name"], json.dumps(["att_view_self", "task_self", "dig_recv", "leave_self", "loan_self"])))
    except Exception:
        row = db.one("SELECT id FROM titles WHERE name=?", (d["name"],))
        tid = row["id"] if row else None
    if tid:
        db.run("UPDATE staff SET title_id=? WHERE id=?", (tid, ctx.me["id"]))
    await goto(ctx, "me:menu")


define_flow("me_new", [Step("name", "نام عنوان شغلی (مثلاً «مدیر مرکز»):")], _me_new_done, "me:menu")
