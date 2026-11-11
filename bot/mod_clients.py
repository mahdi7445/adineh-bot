"""پرونده مددجویان: ثبت، جستجو، ویرایش فیلدها، یادداشت‌ها، فایل‌ها و ورود گروهی از اکسل/ورد/متن."""
from telegram import InlineKeyboardButton as B

from . import crypto, db, importer, jdate
from .core import (DATE_CHOICES, HOOKS, Ctx, Step, attachments, back_row, define_flow, delete_attachments, esc, goto,
                   grid, media_of, p_date, p_text, pager, route, start_attach, start_flow)

STANDARD_FIELDS = ["کد ملی", "تاریخ تولد", "جنسیت", "تلفن", "نام ولی/سرپرست", "تلفن ولی", "آدرس", "تشخیص",
                   "داروها", "حساسیت‌ها", "تاریخ پذیرش", "شماره پرونده", "توضیحات"]
ST = {"active": "🟢 فعال", "discharged": "⚪️ ترخیص‌شده"}


def _data(c) -> dict:
    return crypto.dec_json(c["data"])


def _fields_for(c):
    d = _data(c)
    keys = list(d.keys()) + [f for f in STANDARD_FIELDS if f not in d]
    return keys


def client_text(c) -> str:
    d = _data(c)
    lines = [f"🧒 <b>{esc(c['name'])}</b>", f"شماره پرونده (سیستمی): {c['id']} — {ST.get(c['status'], '')}",
             f"📅 پذیرش: {jdate.fmt(c['admit_day'])}", ""]
    for k, v in d.items():
        lines.append(f"▫️ <b>{esc(k)}</b>: {esc(v)}")
    if not d:
        lines.append("هنوز جزئیاتی ثبت نشده. از «ویرایش/افزودن فیلد» استفاده کنید.")
    return "\n".join(lines)


# ───────────── منو و فهرست ─────────────
@route("cli:menu", perm=("cli_view", "cli_manage"))
async def cli_menu(ctx: Ctx):
    n = db.one("SELECT COUNT(*) c FROM clients WHERE status='active'")["c"]
    kb = [[B("🔍 جستجوی مددجو", callback_data="cli:find"), B(f"📋 فهرست فعال‌ها ({n})", callback_data="cli:list:active:0")],
          [B("⚪️ ترخیص‌شده‌ها", callback_data="cli:list:discharged:0")]]
    if ctx.can("cli_manage"):
        kb.insert(0, [B("➕ مددجوی جدید", callback_data="cli:add"), B("📥 ورود گروهی از فایل", callback_data="cli:import")])
    if ctx.can("export"):
        kb.append([B("📊 خروجی اکسل همه مددجویان", callback_data="exp:cli")])
    kb.append(back_row())
    await ctx.show("🧒 <b>پرونده مددجویان</b>\nاطلاعات و فایل‌های هر مددجو رمزنگاری‌شده نگهداری می‌شود.", kb)


@route("cli:list", perm=("cli_view", "cli_manage"))
async def cli_list(ctx: Ctx, status, page="0"):
    page = int(page)
    total = db.one("SELECT COUNT(*) c FROM clients WHERE status=?", (status,))["c"]
    rows = db.q("SELECT * FROM clients WHERE status=? ORDER BY name LIMIT 10 OFFSET ?", (status, page * 10))
    kb = grid([B(r["name"], callback_data=f"cli:v:{r['id']}") for r in rows])
    pg = pager(f"cli:list:{status}", page, total, 10)
    if pg:
        kb.append(pg)
    kb.append(back_row("cli:menu"))
    await ctx.show(f"🧒 <b>{ST[status]}</b> ({total})" + ("" if rows else "\n\nموردی نیست."), kb)


@route("cli:find", perm=("cli_view", "cli_manage"))
async def cli_find(ctx: Ctx):
    await start_flow(ctx, "cli_find")


async def _find_done(ctx: Ctx, d):
    q = importer._clean(d["q"]).lower()
    hits = []
    for c in db.q("SELECT * FROM clients ORDER BY name"):
        hay = importer._clean(c["name"]).lower() + " " + " ".join(importer._clean(v).lower() for v in _data(c).values())
        if q in hay:
            hits.append(c)
    kb = grid([B(("⚪️ " if c["status"] != "active" else "") + c["name"], callback_data=f"cli:v:{c['id']}") for c in hits[:30]])
    kb.append(back_row("cli:menu"))
    await ctx.send(f"🔍 {len(hits)} نتیجه برای «{esc(d['q'])}»" + ("" if hits else "\nچیزی پیدا نشد."), kb)


define_flow("cli_find", [Step("q", "🔍 بخشی از نام، کد ملی، تلفن یا هر مشخصه‌ای را بنویسید:")], _find_done, "cli:menu")


# ───────────── نمایش پرونده ─────────────
@route("cli:v", perm=("cli_view", "cli_manage"))
async def cli_view(ctx: Ctx, cid):
    c = db.one("SELECT * FROM clients WHERE id=?", (int(cid),))
    if not c:
        return await ctx.answer("پیدا نشد", True)
    ctx.audit("client_view", f"{c['id']} {c['name']}")
    nf = len(attachments("client", c["id"]))
    nn = db.one("SELECT COUNT(*) c FROM client_notes WHERE client_id=?", (c["id"],))["c"]
    kb = []
    if nf:
        kb.append([B(f"📎 مشاهده فایل‌ها ({nf})", callback_data=f"at:list:client:{cid}")])
    if nn:
        kb.append([B(f"🗒 یادداشت‌ها و گزارش‌ها ({nn})", callback_data=f"cli:notes:{cid}:0")])
    row = [B("📝 یادداشت جدید", callback_data=f"cli:note:{cid}")]
    if ctx.can("cli_manage"):
        row.append(B("➕ افزودن فایل", callback_data=f"cli:att:{cid}"))
        kb.append(row)
        kb.append([B("✏️ ویرایش/افزودن فیلد", callback_data=f"cli:ef:{cid}"), B("🔄 فعال/ترخیص", callback_data=f"cli:tog:{cid}")])
        kb.append([B("✏️ نام", callback_data=f"cli:en:{cid}"), B("🗑 حذف پرونده", callback_data=f"cli:del:{cid}")])
    else:
        kb.append(row)
    if ctx.can("export"):
        kb.append([B("📤 اکسل این پرونده", callback_data=f"exp:cl1:{cid}")])
    kb.append(back_row(f"cli:list:{c['status']}:0"))
    await ctx.show(client_text(c), kb, protect=True)


@route("cli:att", perm="cli_manage")
async def cli_att(ctx: Ctx, cid):
    await start_attach(ctx, "client", int(cid), f"cli:v:{cid}", "📎 فایل‌های مددجو (ورد، اکسل، pdf، عکس، ویدئو و …) را بفرستید.")


@route("cli:tog", perm="cli_manage")
async def cli_tog(ctx: Ctx, cid):
    c = db.one("SELECT * FROM clients WHERE id=?", (int(cid),))
    db.run("UPDATE clients SET status=? WHERE id=?", ("discharged" if c["status"] == "active" else "active", c["id"]))
    ctx.audit("client_status", f"{c['id']} {c['name']}")
    await cli_view(ctx, cid)


@route("cli:del", perm="cli_manage")
async def cli_del(ctx: Ctx, cid):
    c = db.one("SELECT * FROM clients WHERE id=?", (int(cid),))
    await ctx.show(f"⚠️ پرونده «{esc(c['name'])}» با همه فایل‌ها و یادداشت‌هایش برای همیشه حذف شود؟ (قابل بازگشت نیست)",
                   [[B("✅ بله، حذف کن", callback_data=f"cli:del2:{cid}"), B("خیر", callback_data=f"cli:v:{cid}")]])


@route("cli:del2", perm="cli_manage")
async def cli_del2(ctx: Ctx, cid):
    c = db.one("SELECT * FROM clients WHERE id=?", (int(cid),))
    if c:
        delete_attachments("client", c["id"])
        for n in db.q("SELECT id FROM client_notes WHERE client_id=?", (c["id"],)):
            delete_attachments("cnote", n["id"])
        db.run("DELETE FROM client_notes WHERE client_id=?", (c["id"],))
        db.run("DELETE FROM clients WHERE id=?", (c["id"],))
        ctx.audit("client_delete", f"{c['id']} {c['name']}")
    await cli_menu(ctx)


# ───────────── ثبت و ویرایش ─────────────
@route("cli:add", perm="cli_manage")
async def cli_add(ctx: Ctx):
    await start_flow(ctx, "cli_add")


async def _add_done(ctx: Ctx, d):
    det = {}
    for k, key in (("nid", "کد ملی"), ("birth", "تاریخ تولد"), ("guardian", "نام ولی/سرپرست"), ("gphone", "تلفن ولی"),
                   ("diag", "تشخیص"), ("desc", "توضیحات")):
        if d.get(k):
            det[key] = d[k]
    cid = db.run("INSERT INTO clients(name,admit_day,data,updated) VALUES(?,?,?,?)",
                 (d["name"], d.get("admit") or jdate.today(), crypto.enc_json(det), jdate.today()))
    ctx.audit("client_add", f"{cid} {d['name']}")
    await goto(ctx, f"cli:v:{cid}")


define_flow("cli_add", [
    Step("name", "🧒 نام و نام خانوادگی مددجو:"),
    Step("nid", "کد ملی (اختیاری):", p_text, optional=True),
    Step("birth", "تاریخ تولد (اختیاری، مثال 1385/03/12):", p_text, optional=True),
    Step("guardian", "نام ولی/سرپرست (اختیاری):", p_text, optional=True),
    Step("gphone", "تلفن ولی (اختیاری):", p_text, optional=True),
    Step("diag", "تشخیص / نوع معلولیت (اختیاری):", p_text, optional=True),
    Step("admit", "تاریخ پذیرش:", p_date, kind="date"),
    Step("desc", "توضیحات (اختیاری):", p_text, optional=True),
], _add_done, "cli:menu")


@route("cli:en", perm="cli_manage")
async def cli_en(ctx: Ctx, cid):
    await start_flow(ctx, "cli_en", {"cid": int(cid)})


async def _en_done(ctx, d):
    db.run("UPDATE clients SET name=?, updated=? WHERE id=?", (d["v"], jdate.today(), d["cid"]))
    ctx.audit("client_rename", d["cid"])
    await goto(ctx, f"cli:v:{d['cid']}")


define_flow("cli_en", [Step("v", "نام جدید:")], _en_done, "cli:menu")


@route("cli:ef", perm="cli_manage")
async def cli_ef(ctx: Ctx, cid):
    c = db.one("SELECT * FROM clients WHERE id=?", (int(cid),))
    keys = _fields_for(c)
    kb = grid([B(k[:28], callback_data=f"cli:fk:{cid}:{i}") for i, k in enumerate(keys)])
    kb.append([B("➕ فیلد جدید با نام دلخواه", callback_data=f"cli:nf:{cid}")])
    kb.append(back_row(f"cli:v:{cid}"))
    await ctx.show("✏️ کدام فیلد را ویرایش یا اضافه می‌کنید؟", kb)


@route("cli:fk", perm="cli_manage")
async def cli_fk(ctx: Ctx, cid, idx):
    c = db.one("SELECT * FROM clients WHERE id=?", (int(cid),))
    key = _fields_for(c)[int(idx)]
    await start_flow(ctx, "cli_ev", {"cid": int(cid), "key": key, "old": _data(c).get(key, "—")})


@route("cli:nf", perm="cli_manage")
async def cli_nf(ctx: Ctx, cid):
    await start_flow(ctx, "cli_nf", {"cid": int(cid)})


async def _set_field(ctx, cid, key, value):
    c = db.one("SELECT * FROM clients WHERE id=?", (cid,))
    d = _data(c)
    if value in (None, "-", "—"):
        d.pop(key, None)
    else:
        d[key] = value
    db.run("UPDATE clients SET data=?, updated=? WHERE id=?", (crypto.enc_json(d), jdate.today(), cid))
    ctx.audit("client_edit", f"{cid} {key}")
    await goto(ctx, f"cli:v:{cid}")


async def _ev_done(ctx, d):
    await _set_field(ctx, d["cid"], d["key"], d["v"])


async def _nf_done(ctx, d):
    await _set_field(ctx, d["cid"], d["key"], d["v"])


define_flow("cli_ev", [Step("v", lambda d: f"مقدار جدید «{esc(d['key'])}» را بنویسید (فعلی: {esc(d['old'])}).\nبرای حذف این فیلد «-» بنویسید:")],
            _ev_done, "cli:menu")
define_flow("cli_nf", [Step("key", "نام فیلد جدید (مثلاً «گروه خونی»):"), Step("v", "مقدار:")], _nf_done, "cli:menu")


# ───────────── یادداشت‌ها ─────────────
@route("cli:note", perm=("cli_view", "cli_manage"))
async def cli_note(ctx: Ctx, cid):
    await start_flow(ctx, "cli_note", {"cid": int(cid)})


async def _note_done(ctx, d):
    nid = db.run("INSERT INTO client_notes(client_id,day,body,author) VALUES(?,?,?,?)",
                 (d["cid"], jdate.today(), crypto.enc(d["text"]), ctx.me["id"]))
    ctx.audit("client_note", f"{d['cid']}")
    await start_attach(ctx, "cnote", nid, f"cli:v:{d['cid']}", "✅ یادداشت ثبت شد. در صورت نیاز فایل/عکس هم بفرستید؛ وگرنه «پایان».")


define_flow("cli_note", [Step("text", "🗒 متن یادداشت/گزارش مددجو (پیشرفت، رفتار، جلسه درمان، …):")], _note_done, "cli:menu")


@route("cli:notes", perm=("cli_view", "cli_manage"))
async def cli_notes(ctx: Ctx, cid, page="0"):
    cid, page = int(cid), int(page)
    total = db.one("SELECT COUNT(*) c FROM client_notes WHERE client_id=?", (cid,))["c"]
    rows = db.q("SELECT * FROM client_notes WHERE client_id=? ORDER BY id DESC LIMIT 5 OFFSET ?", (cid, page * 5))
    txt = [f"🗒 <b>یادداشت‌های {esc(db.one('SELECT name FROM clients WHERE id=?', (cid,))['name'])}</b>", ""]
    kb = []
    for r in rows:
        n = len(attachments("cnote", r["id"]))
        txt.append(f"📅 {jdate.fmt(r['day'])} — {esc(db.staff_name(r['author']))}{' 📎' + str(n) if n else ''}\n{esc(crypto.dec(r['body']))}\n")
        if n:
            kb.append([B(f"📎 فایل‌های یادداشت {jdate.fmt(r['day'])}", callback_data=f"at:list:cnote:{r['id']}")])
    pg = pager(f"cli:notes:{cid}", page, total, 5)
    if pg:
        kb.append(pg)
    kb.append(back_row(f"cli:v:{cid}"))
    await ctx.show("\n".join(txt), kb, protect=True)


# ───────────── ورود گروهی ─────────────
@route("cli:import", perm="cli_manage")
async def cli_import(ctx: Ctx):
    ctx.ud["import"] = {"recs": None}
    await ctx.show(
        "📥 <b>ورود گروهی مددجویان</b>\n\nفایل اکسل (xlsx)، ورد (docx)، متنی (txt) یا csv را بفرستید.\n\n"
        "• اکسل/جدول: سطر اول عنوان ستون‌ها (نام، کد ملی، تلفن، …) و هر سطر یک مددجو\n"
        "• ورد/متن: هر مددجو چند خط «عنوان: مقدار»؛ بین مددجوها یک خط خالی یا <code>---</code>\n"
        "• هر عنوان ناشناخته هم به‌عنوان فیلد جدید نگهداری می‌شود.\n\nچند فایل را می‌توانید پشت سر هم بفرستید.",
        [[B("❌ لغو", callback_data="f:cancel")]])


async def _import_incoming(ctx: Ctx):
    m = ctx.update.effective_message
    _, doc = media_of(m)
    if doc.file_size and doc.file_size > 20 * 1024 * 1024:
        return await ctx.send("⚠️ فایل بزرگ‌تر از ۲۰ مگابایت است.")
    f = await doc.get_file()
    data = bytes(await f.download_as_bytearray())
    try:
        recs = importer.parse_file(doc.file_name or "", data)
    except Exception as e:
        return await ctx.send(f"⚠️ خواندن فایل ممکن نشد: {esc(e)}")
    named = [r for r in recs if importer.split_name(r)[0]]
    skipped = len(recs) - len(named)
    imp = ctx.ud["import"]
    imp["recs"] = (imp.get("recs") or []) + named
    names = "، ".join(importer.split_name(r)[0] for r in imp["recs"][:8])
    await ctx.send(
        f"📄 «{esc(doc.file_name)}»: {len(named)} مددجو خوانده شد" + (f" ({skipped} ردیف بدون نام رد شد)" if skipped else "") +
        f"\nجمع تا اینجا: {len(imp['recs'])}\nنمونه: {esc(names)}\n\nفایل دیگری بفرستید یا تأیید کنید. "
        "اگر نام یا کد ملی تکراری باشد، اطلاعات به پرونده موجود اضافه/به‌روز می‌شود.",
        [[B("✅ ورود به پایگاه داده", callback_data="cli:impok")], [B("❌ لغو", callback_data="f:cancel")]])


HOOKS["import"] = _import_incoming


@route("cli:impok", perm="cli_manage")
async def cli_impok(ctx: Ctx):
    imp = ctx.ud.pop("import", None)
    if not imp or not imp.get("recs"):
        return await ctx.answer("چیزی برای ورود نیست.", True)
    existing = db.q("SELECT * FROM clients")
    by_name = {importer._clean(c["name"]): c for c in existing}
    by_nid = {}
    for c in existing:
        nid = _data(c).get("کد ملی")
        if nid:
            by_nid[importer._clean(nid)] = c
    added = updated = 0
    for rec in imp["recs"]:
        name, det = importer.split_name(rec)
        nid = importer._clean(det.get("کد ملی", "")) if det.get("کد ملی") else ""
        c = by_nid.get(nid) if nid else None
        c = c or by_name.get(importer._clean(name))
        if c:
            d = _data(c)
            d.update(det)
            db.run("UPDATE clients SET data=?, updated=? WHERE id=?", (crypto.enc_json(d), jdate.today(), c["id"]))
            updated += 1
        else:
            cid = db.run("INSERT INTO clients(name,admit_day,data,updated) VALUES(?,?,?,?)",
                         (name, jdate.today(), crypto.enc_json(det), jdate.today()))
            c = db.one("SELECT * FROM clients WHERE id=?", (cid,))
            by_name[importer._clean(name)] = c
            if nid:
                by_nid[nid] = c
            added += 1
    ctx.audit("client_import", f"added={added} updated={updated}")
    await ctx.show(f"✅ ورود انجام شد.\n🆕 جدید: {added}\n🔄 به‌روزرسانی: {updated}\n\n"
                   "برای افزودن فایل‌های هر مددجو، پرونده او را باز کنید و «افزودن فایل» را بزنید.",
                   [[B("📋 فهرست مددجویان", callback_data="cli:list:active:0")], back_row("cli:menu")])
