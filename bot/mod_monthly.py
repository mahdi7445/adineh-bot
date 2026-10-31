"""گزارش ماهانه حضور و غیاب و ساعت کاری: همه پرسنل (کلیات) و هر نفر (جزئیات)، در ربات و اکسل."""
import io

from telegram import InlineKeyboardButton as B

from . import attlogic, crypto, db, exports, jdate
from .core import Ctx, back_row, esc, fa, route

LIMIT = 3300
ST_ICON = {k: v[0] for k, v in attlogic.STATUS.items()}


def chunk(blocks, limit=LIMIT):
    """فهرست متن‌ها را به صفحه‌هایی کمتر از حد پیام تلگرام تقسیم می‌کند."""
    pages, cur, n = [], [], 0
    for b in blocks:
        if cur and n + len(b) + 2 > limit:
            pages.append(cur)
            cur, n = [], 0
        cur.append(b)
        n += len(b) + 2
    if cur:
        pages.append(cur)
    return pages or [[]]


def _months_nav(base, y, m, extra=""):
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
    return [B("◀️ ماه قبل", callback_data=f"{base}:{py}:{pm}{extra}"), B("ماه بعد ▶️", callback_data=f"{base}:{ny}:{nm}{extra}")]


def _ym(y, m):
    cy, cm, _ = jdate.j_today()
    return (int(y), int(m)) if y else (cy, cm)


def _line(p, st):
    c = st["counts"]
    parts = [f"✅ حضور {fa(c['present'])}", f"❌ غیبت {fa(c['absent'])}"]
    if c["leave"]:
        parts.append(f"🏖 مرخصی {fa(c['leave'])}")
    if c["sick"]:
        parts.append(f"🩺 استعلاجی {fa(c['sick'])}")
    if c["mission"]:
        parts.append(f"🚗 مأموریت {fa(c['mission'])}")
    txt = (f"👤 <b>{esc(p['name'])}</b> — {esc(db.title_label(p))}\n   " + " · ".join(parts)
           + f"\n   ⏱ جمع کارکرد <b>{jdate.hm(st['hours'])}</b> ساعت (میانگین روزانه {jdate.hm(st['avg'])})"
           + f" · 📝 گزارش {fa(st['reports'])}")
    warn = []
    if c["unrecorded"]:
        warn.append(f"⬜ بدون وضعیت {fa(c['unrecorded'])} روز")
    if c["incomplete"]:
        warn.append(f"⚠️ ساعت ناقص {fa(c['incomplete'])} روز")
    return txt + ("\n   " + " · ".join(warn) if warn else "")


@route("mr:menu", perm=("att_manage", "export", "rep_view"))
async def mr_menu(ctx: Ctx):
    y, m, _ = jdate.j_today()
    await mr_all(ctx, y, m)


@route("mr:all", perm=("att_manage", "export", "rep_view"))
async def mr_all(ctx: Ctx, y=None, m=None):
    y, m = _ym(y, m)
    people = db.roster()
    stats = [(p, attlogic.month_stats(p["id"], y, m)) for p in people]
    tot_h = sum(s["hours"] for _, s in stats)
    tot_p = sum(s["counts"]["present"] for _, s in stats)
    head = (f"📊 <b>گزارش ماهانهٔ همهٔ پرسنل — {jdate.MONTHS[m - 1]} {fa(y)}</b>\n"
            f"👥 {fa(len(people))} نفر · مجموع روزهای حضور {fa(tot_p)} · مجموع کارکرد {jdate.hm(tot_h)} ساعت\n"
            "برای جزئیات روزبه‌روز، نام هر نفر را بزنید.")
    kb = [_months_nav("mr:all", y, m)]
    kb += [[B(f"👤 {p['name']}", callback_data=f"mr:p:{p['id']}:{y}:{m}")] for p, _ in stats]
    kb.append([B("📤 اکسل همهٔ پرسنل (کلیات + جزئیات)", callback_data=f"exp:mr:0:{y}:{m}")])
    kb.append(back_row())
    body = "\n\n".join(_line(p, s) for p, s in stats) or "پرسنلی ثبت نشده."
    if len(head) + len(body) < 3700:
        await ctx.show(head + "\n\n" + body, kb)
    else:
        await ctx.show(head, kb)
        for pg in chunk([_line(p, s) for p, s in stats]):
            await ctx.send("\n\n".join(pg))


def _day_line(d, with_report=True):
    day = d["day"]
    if d["future"]:
        return ""
    st = d["status"]
    if st:
        icon, label = ST_ICON[st], attlogic.STATUS[st][1]
    elif d["friday"]:
        icon, label = "💤", "جمعه"
    else:
        icon, label = "⬜", "ثبت نشده"
    j = jdate.to_j(day)[2]
    line = f"{fa(j):>2} {jdate.weekday(day)}: {icon} {label}"
    for r in d["recs"]:
        line += f"\n      🟢 {r['t_in'] or '؟'} → 🔴 {r['t_out'] or '؟'}" + (f" ({jdate.hm(jdate.hours(r['t_in'], r['t_out']))})" if r["t_in"] and r["t_out"] else " ⚠️")
    if len(d["recs"]) > 1:
        line += f"\n      ∑ {jdate.hm(d['hours'])}"
    if with_report and d["reports"]:
        line += f"\n      📝 {fa(len(d['reports']))} گزارش"
    return line


@route("mr:p", perm=("att_manage", "export", "rep_view", "att_view_self"))
async def mr_person(ctx: Ctx, sid, y=None, m=None, page="0"):
    sid, page = int(sid), int(page)
    if sid != ctx.me["id"] and not ctx.can("att_manage", "export", "rep_view"):
        return await ctx.answer("⛔ فقط گزارش خودتان", True)
    p = db.staff_by_id(sid)
    if not p:
        return await ctx.answer("پیدا نشد", True)
    y, m = _ym(y, m)
    st = attlogic.month_stats(sid, y, m)
    c = st["counts"]
    summ = [f"👤 <b>{esc(p['name'])}</b> — {esc(db.title_label(p))}",
            f"📆 {jdate.MONTHS[m - 1]} {fa(y)}", "",
            "<b>کلیات</b>",
            f"✅ روز حضور: {fa(c['present'])}   ❌ غیبت: {fa(c['absent'])}",
            f"🏖 مرخصی: {fa(c['leave'])}   🩺 استعلاجی: {fa(c['sick'])}   🚗 مأموریت: {fa(c['mission'])}",
            f"⏱ جمع ساعت کاری: <b>{jdate.hm(st['hours'])}</b>  (میانگین روزهای کاری: {jdate.hm(st['avg'])})",
            f"📝 گزارش ثبت‌شده: {fa(st['reports'])} (در {fa(st['report_days'])} روز)"]
    if c["unrecorded"]:
        summ.append(f"⬜ روزهای بدون وضعیت: {fa(c['unrecorded'])}")
    if c["incomplete"]:
        summ.append(f"⚠️ روزهای حاضر با ساعت ناقص: {fa(c['incomplete'])}")
    lines = [x for x in (_day_line(d) for d in st["days"]) if x]
    pages = chunk(lines, LIMIT - len("\n".join(summ)) - 200 if page == 0 else LIMIT)
    # صفحهٔ اول جمع‌بندی + بخشی از جزئیات؛ بقیه صفحه‌های بعدی
    page = min(page, len(pages) - 1)
    txt = ("\n".join(summ) + "\n\n<b>جزئیات روزانه</b>\n" if page == 0 else f"👤 <b>{esc(p['name'])}</b> — {jdate.MONTHS[m - 1]} {fa(y)} (ادامه)\n\n")
    txt += "\n".join(pages[page]) if pages[page] else "روزی ثبت نشده."
    nav = []
    if page > 0:
        nav.append(B("◀️ قبل", callback_data=f"mr:p:{sid}:{y}:{m}:{page - 1}"))
    if page < len(pages) - 1:
        nav.append(B("ادامهٔ جزئیات ▶️", callback_data=f"mr:p:{sid}:{y}:{m}:{page + 1}"))
    kb = [_months_nav(f"mr:p:{sid}", y, m)]
    if nav:
        kb.append(nav)
    if st["reports"] and ctx.can("rep_view"):
        kb.append([B("📝 گزارش‌های این ماه", callback_data=f"mr:r:{sid}:{y}:{m}:0")])
    kb.append([B("📤 اکسل این نفر", callback_data=f"exp:mr:{sid}:{y}:{m}")])
    if ctx.can("att_manage", "export", "rep_view"):
        kb.append([B("👥 همهٔ پرسنل", callback_data=f"mr:all:{y}:{m}")])
    kb.append(back_row("att:menu" if sid == ctx.me["id"] and not ctx.can("att_manage", "export", "rep_view") else "mr:menu"))
    await ctx.show(txt, kb)


@route("mr:r", perm="rep_view")
async def mr_reports(ctx: Ctx, sid, y, m, page="0"):
    """متن کامل گزارش‌های یک نفر در یک ماه (با نام، تاریخ و ساعت ثبت)."""
    sid, y, m, page = int(sid), int(y), int(m), int(page)
    d1, d2 = jdate.month_bounds(y, m)
    rows = db.q("SELECT * FROM reports WHERE staff_id=? AND day BETWEEN ? AND ? ORDER BY day, id", (sid, d1, d2))
    from .mod_att import rep_block
    pages = chunk([rep_block(r) for r in rows])
    page = min(page, len(pages) - 1)
    kb = []
    nav = []
    if page > 0:
        nav.append(B("◀️ قبل", callback_data=f"mr:r:{sid}:{y}:{m}:{page - 1}"))
    if page < len(pages) - 1:
        nav.append(B("بعد ▶️", callback_data=f"mr:r:{sid}:{y}:{m}:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append(back_row(f"mr:p:{sid}:{y}:{m}"))
    await ctx.show(f"📝 <b>گزارش‌های {esc(db.staff_name(sid))} — {jdate.MONTHS[m - 1]} {fa(y)}</b> ({fa(len(rows))} مورد)\n\n"
                   + ("\n\n".join(pages[page]) if rows else "گزارشی نیست."), kb)


@route("exp:mr", perm=("att_manage", "export", "att_view_self"))
async def exp_month(ctx: Ctx, sid, y, m):
    sid, y, m = int(sid), int(y), int(m)
    if sid != ctx.me["id"] and not ctx.can("att_manage", "export"):
        return await ctx.answer("⛔", True)
    if sid == 0 and not ctx.can("att_manage", "export"):
        return await ctx.answer("⛔", True)
    await ctx.answer("در حال ساخت فایل…")
    data = exports.month_report(y, m, sid or None)
    bio = io.BytesIO(data)
    bio.name = f"monthly-{y}-{m:02d}" + (f"-{sid}" if sid else "-all") + ".xlsx"
    await ctx.update.effective_chat.send_document(bio, caption=f"📊 گزارش ماهانه {jdate.MONTHS[m - 1]} {y}"
                                                  + (f" — {db.staff_name(sid)}" if sid else " — همهٔ پرسنل"))
    ctx.audit("export_month", f"{sid} {y}/{m}")
