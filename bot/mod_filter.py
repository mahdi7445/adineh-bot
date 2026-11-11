"""فیلتر هوشمند حضور و غیاب و گزارش‌ها: چه کسی (همه/عنوان/افراد) × چه بازه‌ای × چه وضعیتی — نمایش و اکسل."""
import io
from datetime import date, timedelta

from openpyxl import Workbook
from telegram import InlineKeyboardButton as B

from . import attlogic, crypto, db, exports, jdate
from .core import Ctx, Step, back_row, define_flow, esc, fa, p_date, route, start_flow

KINDS = [("all", "📋 همه وضعیت‌ها"), ("absent", "❌ فقط غیبت"), ("present", "✅ فقط حضور"), ("leave", "🏖 مرخصی"),
         ("sick", "🩺 استعلاجی"), ("mission", "🚗 مأموریت"), ("none", "⬜ ثبت‌نشده")]
PERIODS = [("today", "امروز"), ("week", "۷ روز اخیر"), ("month", "این ماه"), ("last", "ماه قبل"), ("year", "امسال")]
MAX_DAYS = 400


def _st(ctx):
    return ctx.ud.setdefault("af", {"who": "all", "ids": [], "per": "month", "k": "absent"})


def period_range(st):
    t = jdate.today()
    y, m, _ = jdate.j_today()
    per = st.get("per")
    if per == "today":
        return t, t
    if per == "week":
        return jdate.add_days(t, -6), t
    if per == "last":
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        return jdate.month_bounds(y, m)
    if per == "year":
        return jdate.year_bounds(y)
    if per == "custom" and st.get("d1") and st.get("d2"):
        return st["d1"], st["d2"]
    return jdate.month_bounds(y, m)


def people(st):
    ros = db.att_roster()
    if st["who"] == "t":
        return [s for s in ros if s["title_id"] in st["ids"]]
    if st["who"] == "p":
        return [s for s in ros if s["id"] in st["ids"]]
    return ros


def compute(st):
    """[(staff, [(day, status_or_None)])] طبق فیلتر؛ روزهای تعطیل و آینده شمرده نمی‌شوند."""
    d1, d2 = period_range(st)
    today = jdate.today()
    days = []
    cur = date.fromisoformat(d1)
    end = min(date.fromisoformat(d2), date.fromisoformat(today))
    while cur <= end and len(days) < MAX_DAYS:
        days.append(cur.isoformat())
        cur += timedelta(days=1)
    k = st["k"]
    out = []
    for s in people(st):
        hit = []
        for d in days:
            e = attlogic.eff_status(s["id"], d)
            if e is None and attlogic.off_reason(d):
                continue
            if e == "off":
                continue
            if k == "all" or (k == "none" and e is None) or e == k:
                hit.append((d, e))
        out.append((s, hit))
    return out, (d1, d2)


def _who_label(st):
    if st["who"] == "t":
        names = [db.title_name(i) for i in st["ids"]]
        return "عنوان: " + "، ".join(names) if names else "همه"
    if st["who"] == "p":
        return "، ".join(db.staff_name(i) for i in st["ids"][:4]) + (f" (+{fa(len(st['ids']) - 4)})" if len(st["ids"]) > 4 else "") if st["ids"] else "همه"
    return "همهٔ پرسنل"


def _k_label(k):
    return dict(KINDS)[k]


def _per_label(st):
    d1, d2 = period_range(st)
    return f"{jdate.fmt(d1)} تا {jdate.fmt(d2)}"


@route("af:menu", perm=("att_manage", "rep_view", "export"))
async def af_menu(ctx: Ctx, reset=None):
    if reset:
        ctx.ud.pop("af", None)
    st = _st(ctx)
    kb = [[B("👥 چه کسی: " + _who_label(st)[:28], callback_data="af:who")],
          [B("📅 بازه: " + _per_label(st), callback_data="af:per")],
          [B("🔎 وضعیت: " + _k_label(st["k"]), callback_data="af:kind")],
          [B("▶️ نمایش نتیجه", callback_data="af:go:0"), B("📥 اکسل", callback_data="af:x")]]
    if ctx.can("rep_view"):
        kb.append([B("📝 گزارش‌های متنیِ همین فیلتر", callback_data="af:rp:0")])
    kb.append([B("♻️ بازنشانی", callback_data="af:menu:1")])
    kb.append(back_row())
    await ctx.show("🔎 <b>فیلتر حضور و غیاب و گزارش‌ها</b>\n"
                   "فیلتر را بچینید؛ سپس «نمایش» یا «اکسل» را بزنید. روزهای جمعه و تعطیل رسمی شمرده نمی‌شوند.\n\n"
                   f"👥 {esc(_who_label(st))}\n📅 {_per_label(st)}\n🔎 {_k_label(st['k'])}", kb)


@route("af:who", perm=("att_manage", "rep_view", "export"))
async def af_who(ctx: Ctx):
    kb = [[B("👥 همهٔ پرسنل", callback_data="af:sw:all")],
          [B("🏷 بر اساس عنوان شغلی", callback_data="af:tl")],
          [B("👤 انتخاب یک یا چند نفر", callback_data="af:pl:0")], back_row("af:menu")]
    await ctx.show("👥 <b>فیلتر چه کسی؟</b>", kb)


@route("af:sw", perm=("att_manage", "rep_view", "export"))
async def af_sw(ctx: Ctx, who):
    st = _st(ctx)
    st["who"], st["ids"] = who, []
    await af_menu(ctx)


@route("af:tl", perm=("att_manage", "rep_view", "export"))
async def af_tl(ctx: Ctx, tid=None):
    st = _st(ctx)
    if tid:
        st["who"] = "t"
        ids = set(st["ids"]) if st["who"] == "t" else set()
        ids ^= {int(tid)}
        st["ids"] = sorted(ids)
        if not ids:
            st["who"] = "all"
    sel = set(st["ids"]) if st["who"] == "t" else set()
    rows = db.q("SELECT id,name FROM titles WHERE no_attendance=0 ORDER BY name")
    kb = [[B(("✅ " if r["id"] in sel else "⬜️ ") + r["name"], callback_data=f"af:tl:{r['id']}")] for r in rows]
    kb.append([B("✔️ تأیید", callback_data="af:menu")])
    await ctx.show("🏷 <b>عنوان‌ها را انتخاب کنید</b> (چندتایی)", kb)


@route("af:pl", perm=("att_manage", "rep_view", "export"))
async def af_pl(ctx: Ctx, page="0", sid=None):
    st = _st(ctx)
    if sid:
        ids = set(st["ids"]) if st["who"] == "p" else set()
        ids ^= {int(sid)}
        st["who"], st["ids"] = ("p", sorted(ids)) if ids else ("all", [])
    page = int(page)
    ros = db.att_roster()
    per = 10
    sel = set(st["ids"]) if st["who"] == "p" else set()
    kb = [[B(("✅ " if s["id"] in sel else "⬜️ ") + s["name"], callback_data=f"af:pl:{page}:{s['id']}")] for s in ros[page * per:(page + 1) * per]]
    nav = []
    if page > 0:
        nav.append(B("◀️ قبل", callback_data=f"af:pl:{page - 1}"))
    if (page + 1) * per < len(ros):
        nav.append(B("بعد ▶️", callback_data=f"af:pl:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([B("✔️ تأیید", callback_data="af:menu")])
    await ctx.show(f"👤 <b>افراد را انتخاب کنید</b> (چندتایی) — انتخاب‌شده: {fa(len(sel))}", kb)


@route("af:per", perm=("att_manage", "rep_view", "export"))
async def af_per(ctx: Ctx, key=None):
    st = _st(ctx)
    if key == "custom":
        return await start_flow(ctx, "af_rng")
    if key:
        st["per"] = key
        return await af_menu(ctx)
    kb = [[B(lb, callback_data=f"af:per:{k}") for k, lb in PERIODS[i:i + 3]] for i in range(0, len(PERIODS), 3)]
    kb.append([B("🗓 بازهٔ دلخواه (از تاریخ تا تاریخ)", callback_data="af:per:custom")])
    kb.append(back_row("af:menu"))
    await ctx.show("📅 <b>بازهٔ زمانی</b>", kb)


async def _rng_done(ctx: Ctx, d):
    if d["d2"] < d["d1"]:
        return await ctx.send("⚠️ تاریخ پایان قبل از شروع است.", [back_row("af:menu")])
    st = _st(ctx)
    st.update(per="custom", d1=d["d1"], d2=d["d2"])
    await af_menu(ctx)


define_flow("af_rng", [Step("d1", "📅 از تاریخ:", p_date, kind="date"),
                       Step("d2", "📅 تا تاریخ:", p_date, kind="date")], _rng_done, "af:menu")


@route("af:kind", perm=("att_manage", "rep_view", "export"))
async def af_kind(ctx: Ctx, key=None):
    st = _st(ctx)
    if key:
        st["k"] = key
        return await af_menu(ctx)
    kb = [[B(lb, callback_data=f"af:kind:{k}")] for k, lb in KINDS] + [back_row("af:menu")]
    await ctx.show("🔎 <b>کدام وضعیت‌ها نمایش داده شود؟</b>", kb)


def _day_list(hit, k):
    by = {}
    for d, e in hit:
        by.setdefault(e, []).append(fa(jdate.to_j(d)[1]) + "/" + fa(jdate.to_j(d)[2]))
    icon = lambda e: attlogic.STATUS[e][0] if e else "⬜"
    return "\n".join(f"   {icon(e)} {fa(len(v))} روز: " + "، ".join(v) for e, v in by.items())


@route("af:go", perm=("att_manage", "rep_view", "export"))
async def af_go(ctx: Ctx, page="0"):
    from .mod_att import _paged
    st = _st(ctx)
    data, _ = compute(st)
    blocks = []
    for s, hit in data:
        if hit or st["k"] == "all":
            blocks.append(f"👤 <b>{esc(s['name'])}</b> — {esc(db.title_label(s))}\n" + (_day_list(hit, st["k"]) or "   —"))
    tot = sum(len(h) for _, h in data)
    head = f"🔎 <b>نتیجهٔ فیلتر</b>\n📅 {_per_label(st)} · {esc(_k_label(st['k']))}\n👥 {esc(_who_label(st))}\nمجموع: {fa(tot)} مورد\n"
    if not blocks:
        return await ctx.show(head + "\n✨ موردی با این فیلتر پیدا نشد.", [[B("📥 اکسل", callback_data="af:x")], back_row("af:menu")])
    body, kb, _n = _paged(blocks, "af:go", int(page), "af:menu", [[B("📥 دریافت اکسل", callback_data="af:x")]])
    await ctx.show(head + "\n" + body, kb)


@route("af:rp", perm="rep_view")
async def af_rp(ctx: Ctx, page="0"):
    from .mod_att import _paged
    st = _st(ctx)
    d1, d2 = period_range(st)
    ids = [s["id"] for s in people(st)]
    rows = [r for r in db.q("SELECT * FROM reports WHERE day BETWEEN ? AND ? ORDER BY day DESC, id DESC", (d1, d2)) if r["staff_id"] in ids]
    if not rows:
        return await ctx.show("📝 در این بازه گزارشی ثبت نشده.", [back_row("af:menu")])
    blocks = [f"👤 <b>{esc(db.staff_name(r['staff_id']))}</b> — {jdate.fmt(r['day'])}\n{esc(crypto.dec(r['body']))[:700]}" for r in rows]
    body, kb, _n = _paged(blocks, "af:rp", int(page), "af:menu", [[B("📥 اکسل", callback_data="af:x")]])
    await ctx.show(f"📝 <b>گزارش‌ها</b> — {fa(len(rows))} مورد\n\n" + body, kb)


def filter_excel(st) -> bytes:
    data, (d1, d2) = compute(st)
    reps = exports._reports_by(d1, d2)
    wb = Workbook()
    sums = []
    for s, hit in data:
        c = {}
        for _, e in hit:
            c[e] = c.get(e, 0) + 1
        sums.append([s["name"], db.title_label(s)] + [c.get(k, 0) for k in ("present", "absent", "leave", "sick", "mission", None)] + [len(hit)])
    exports._sheet(wb, "خلاصه", ["نام", "عنوان", "حاضر", "غایب", "مرخصی", "استعلاجی", "مأموریت", "ثبت‌نشده", "مجموع موارد"], sums,
                   [20, 16, 9, 9, 9, 10, 10, 10, 12], first=True)
    det = []
    for s, hit in data:
        for d, e in hit:
            recs = attlogic.records(s["id"], d)
            tin = next((r["t_in"] for r in recs if r["t_in"]), "")
            tout = next((r["t_out"] for r in reversed(recs) if r["t_out"]), "")
            det.append([jdate.fmt(d), jdate.weekday(d), s["name"], db.title_label(s), attlogic.STATUS[e][1] if e else "ثبت نشده",
                        tin or "", tout or "", jdate.hours(tin, tout) if tin and tout else 0, "\n— ".join(reps.get((s["id"], d), []))])
    exports._sheet(wb, "جزئیات روزها", ["تاریخ", "روز", "نام", "عنوان", "وضعیت", "ورود", "خروج", "ساعت", "گزارش"], det,
                   [12, 10, 18, 16, 11, 8, 8, 9, 60])
    return exports._bytes(wb)


@route("af:x", perm=("att_manage", "rep_view", "export"))
async def af_x(ctx: Ctx):
    await ctx.answer("در حال ساخت فایل…")
    st = _st(ctx)
    bio = io.BytesIO(filter_excel(st))
    d1, d2 = period_range(st)
    bio.name = f"filter-{d1}_{d2}.xlsx"
    await ctx.update.effective_chat.send_document(bio, caption=f"📥 {_k_label(st['k'])} — {_per_label(st)}\n{_who_label(st)}")
    ctx.audit("export_filter", f"{st['who']} {st['k']} {d1}..{d2}")
