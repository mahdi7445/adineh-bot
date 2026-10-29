"""وام پرسنل (مبلغ، نوبت، قسط ماهانه، پرداخت‌ها) و واریزی‌های پرسنل."""
import math

from telegram import InlineKeyboardButton as B

from . import db, jdate
from .core import (DATE_CHOICES, Ctx, Step, back_row, define_flow, esc, goto, grid, money, notify, p_amount, p_date,
                   p_int, p_text, pager, route, start_flow)

KINDS = ["حقوق", "مساعده", "پاداش", "اضافه‌کاری", "عیدی", "سایر"]


def loan_stats(l):
    r = db.one("SELECT COALESCE(SUM(amount),0) s, COUNT(*) c FROM loan_payments WHERE loan_id=?", (l["id"],))
    paid, cnt = r["s"], r["c"]
    rem = max(0, l["amount"] - paid)
    left = math.ceil(rem / l["installment"]) if l["installment"] else 0
    nxt = jdate.add_months(l["start_day"], cnt) if l["start_day"] and rem > 0 else None
    return paid, cnt, rem, left, nxt


def loan_text(l) -> str:
    paid, cnt, rem, left, nxt = loan_stats(l)
    st = {"active": "🟢 فعال", "queued": "⏳ در صف نوبت", "done": "✅ تسویه‌شده"}[l["status"]]
    t = [f"💰 <b>وام {esc(db.staff_name(l['staff_id']))}</b> — {st}",
         f"🔢 نوبت: {l['turn_no'] or '—'}",
         f"💵 مبلغ وام: {money(l['amount'])}",
         f"📆 قسط ماهانه: {money(l['installment'])} (تعداد کل: {l['n_installments']})",
         f"📅 شروع: {jdate.fmt(l['start_day'])}",
         f"✅ پرداخت‌شده: {money(paid)} ({cnt} قسط)",
         f"⏳ مانده: {money(rem)} (حدود {left} قسط)"]
    if nxt:
        t.append(f"🔔 سررسید قسط بعدی: {jdate.fmt(nxt)}")
    if l["note"]:
        t.append(f"📝 {esc(l['note'])}")
    pays = db.q("SELECT * FROM loan_payments WHERE loan_id=? ORDER BY day, id", (l["id"],))
    if pays:
        t += ["", "<b>سابقه پرداخت:</b>"] + [f"{i + 1}) {jdate.fmt(p['day'])} — {money(p['amount'])}" + (f" ({esc(p['note'])})" if p["note"] else "")
                                           for i, p in enumerate(pays)]
    return "\n".join(t)


# ───────────── منو ─────────────
@route("loan:menu", perm=("loan_self", "loan_manage"))
async def loan_menu(ctx: Ctx):
    kb = [[B("💰 وام و واریزی‌های من", callback_data="loan:me")]]
    if ctx.can("loan_manage"):
        kb = [[B("➕ ثبت وام", callback_data="loan:add"), B("➕ ثبت واریزی", callback_data="po:add")],
              [B("📋 وام‌های فعال", callback_data="loan:list:active:0"), B("⏳ صف نوبت وام", callback_data="loan:list:queued:0")],
              [B("✅ تسویه‌شده‌ها", callback_data="loan:list:done:0"), B("📆 واریزی‌های این ماه", callback_data="po:month")],
              [B("👤 واریزی/وام هر پرسنل", callback_data="po:pick")]] + kb
    kb.append(back_row())
    await ctx.show("💰 <b>وام و واریزی پرسنل</b>", kb)


@route("loan:me", perm=("loan_self", "loan_manage"))
async def loan_me(ctx: Ctx):
    await _staff_money(ctx, ctx.me["id"], "loan:menu")


async def _staff_money(ctx: Ctx, sid: int, back: str):
    parts = [f"💰 <b>{esc(db.staff_name(sid))}</b>"]
    loans = db.q("SELECT * FROM loans WHERE staff_id=? ORDER BY id DESC", (sid,))
    for l in loans:
        parts += ["", loan_text(l)]
    if not loans:
        parts.append("\nوامی ثبت نشده.")
    pos = db.q("SELECT * FROM payouts WHERE staff_id=? ORDER BY day DESC, id DESC LIMIT 12", (sid,))
    if pos:
        parts += ["", "<b>آخرین واریزی‌ها:</b>"] + [
            f"• {jdate.fmt(p['day'])} — {esc(p['kind'])}: {money(p['amount'])}" + (f" (کسر وام: {money(p['loan_deduct'])})" if p["loan_deduct"] else "")
            for p in pos]
    kb = []
    if ctx.can("loan_manage"):
        kb += [[B(f"💳 وام #{l['id']}", callback_data=f"loan:v:{l['id']}")] for l in loans]
    kb.append(back_row(back))
    await ctx.show("\n".join(parts), kb, protect=True)


# ───────────── وام ─────────────
@route("loan:list", perm="loan_manage")
async def loan_list(ctx: Ctx, status, page="0"):
    page = int(page)
    order = "turn_no, id" if status == "queued" else "id DESC"
    total = db.one("SELECT COUNT(*) c FROM loans WHERE status=?", (status,))["c"]
    rows = db.q(f"SELECT * FROM loans WHERE status=? ORDER BY {order} LIMIT 8 OFFSET ?", (status, page * 8))
    kb = []
    for l in rows:
        rem = loan_stats(l)[2]
        kb.append([B(f"#{l['turn_no'] or '-'} {db.staff_name(l['staff_id'])} — {l['amount']:,} (مانده {rem:,})", callback_data=f"loan:v:{l['id']}")])
    pg = pager(f"loan:list:{status}", page, total, 8)
    if pg:
        kb.append(pg)
    kb.append(back_row("loan:menu"))
    title = {"active": "وام‌های فعال", "queued": "صف نوبت وام (به ترتیب نوبت)", "done": "وام‌های تسویه‌شده"}[status]
    await ctx.show(f"💰 <b>{title}</b> ({total})" + ("" if rows else "\n\nموردی نیست."), kb)


@route("loan:v", perm="loan_manage")
async def loan_view(ctx: Ctx, lid):
    l = db.one("SELECT * FROM loans WHERE id=?", (int(lid),))
    if not l:
        return await ctx.answer("پیدا نشد", True)
    kb = []
    if l["status"] == "active":
        kb.append([B("➕ ثبت قسط پرداخت‌شده", callback_data=f"loan:pay:{lid}"), B("↩️ حذف آخرین پرداخت", callback_data=f"loan:undo:{lid}")])
    if l["status"] == "queued":
        kb.append([B("🟢 نوبت رسید — فعال‌سازی", callback_data=f"loan:act:{lid}")])
    kb.append([B("✏️ قسط", callback_data=f"loan:ei:{lid}"), B("✏️ نوبت", callback_data=f"loan:et:{lid}"), B("✏️ توضیح", callback_data=f"loan:en:{lid}")])
    if l["status"] == "active":
        kb.append([B("✅ تسویه کامل", callback_data=f"loan:close:{lid}")])
    kb.append([B("🗑 حذف وام", callback_data=f"loan:del:{lid}")])
    kb.append(back_row(f"loan:list:{l['status']}:0"))
    await ctx.show(loan_text(l), kb, protect=True)


def _staff_choices(_d):
    return [(s["name"], str(s["id"])) for s in db.active_staff()]


@route("loan:add", perm="loan_manage")
async def loan_add(ctx: Ctx):
    await start_flow(ctx, "loan_add")


async def _loan_add_done(ctx: Ctx, d):
    n = math.ceil(d["amount"] / d["inst"])
    turn = d.get("turn")
    if turn is None:
        turn = (db.one("SELECT COALESCE(MAX(turn_no),0) m FROM loans")["m"] or 0) + 1
    status = "active" if d["status"] == "active" else "queued"
    lid = db.run("INSERT INTO loans(staff_id,turn_no,amount,installment,n_installments,start_day,status,note) VALUES(?,?,?,?,?,?,?,?)",
                 (int(d["staff"]), turn, d["amount"], d["inst"], n, d["start"], status, d.get("note")))
    ctx.audit("loan_add", f"{d['staff']} {d['amount']}")
    s = db.staff_by_id(int(d["staff"]))
    if s and s["tg_id"] and status == "active":
        await notify(ctx.bot, s["tg_id"], f"💰 وام شما به مبلغ {money(d['amount'])} با قسط ماهانه {money(d['inst'])} ثبت شد.")
    await goto(ctx, f"loan:v:{lid}")


define_flow("loan_add", [
    Step("staff", "👤 وام برای کدام پرسنل است؟", lambda t: int(t), _staff_choices),
    Step("amount", "💵 مبلغ کل وام را بنویسید (فقط عدد):", p_amount),
    Step("inst", "📆 مبلغ قسط ماهانه:", p_amount),
    Step("turn", "🔢 شماره نوبت وام (اگر رد کنید خودکار بعدی داده می‌شود):", p_int, optional=True),
    Step("status", "وضعیت وام:", lambda t: t, [("🟢 فعال (پرداخت شده)", "active"), ("⏳ در صف نوبت", "queued")]),
    Step("start", "📅 تاریخ شروع اقساط (برای وام صف‌دار تاریخ تقریبی):", p_date, DATE_CHOICES),
    Step("note", "توضیح (اختیاری):", p_text, optional=True),
], _loan_add_done, "loan:menu")


@route("loan:act", perm="loan_manage")
async def loan_act(ctx: Ctx, lid):
    await start_flow(ctx, "loan_act", {"lid": int(lid)})


async def _act_done(ctx, d):
    db.run("UPDATE loans SET status='active', start_day=? WHERE id=?", (d["start"], d["lid"]))
    ctx.audit("loan_activate", d["lid"])
    await goto(ctx, f"loan:v:{d['lid']}")


define_flow("loan_act", [Step("start", "📅 تاریخ پرداخت وام / شروع اقساط:", p_date, DATE_CHOICES)], _act_done, "loan:menu")


@route("loan:pay", perm="loan_manage")
async def loan_pay(ctx: Ctx, lid):
    await start_flow(ctx, "loan_pay", {"lid": int(lid)})


def _check_done(lid):
    l = db.one("SELECT * FROM loans WHERE id=?", (lid,))
    if l and l["status"] == "active" and loan_stats(l)[2] <= 0:
        db.run("UPDATE loans SET status='done' WHERE id=?", (lid,))


async def _pay_done(ctx, d):
    db.run("INSERT INTO loan_payments(loan_id,day,amount,note,created_by) VALUES(?,?,?,?,?)",
           (d["lid"], d["day"], d["amount"], d.get("note"), ctx.me["id"]))
    _check_done(d["lid"])
    ctx.audit("loan_pay", f"{d['lid']} {d['amount']}")
    await goto(ctx, f"loan:v:{d['lid']}")


def _pay_amount_choices(d):
    l = db.one("SELECT * FROM loans WHERE id=?", (d["lid"],))
    return [(f"قسط ماهانه: {l['installment']:,}", str(l["installment"]))]


define_flow("loan_pay", [
    Step("amount", "💳 مبلغ پرداختی این ماه:", p_amount, _pay_amount_choices),
    Step("day", "📅 تاریخ پرداخت:", p_date, DATE_CHOICES),
    Step("note", "توضیح (اختیاری):", p_text, optional=True),
], _pay_done, "loan:menu")


@route("loan:undo", perm="loan_manage")
async def loan_undo(ctx: Ctx, lid):
    p = db.one("SELECT * FROM loan_payments WHERE loan_id=? ORDER BY id DESC", (int(lid),))
    if not p:
        return await ctx.answer("پرداختی وجود ندارد.", True)
    db.run("DELETE FROM loan_payments WHERE id=?", (p["id"],))
    db.run("UPDATE loans SET status='active' WHERE id=? AND status='done'", (int(lid),))
    ctx.audit("loan_undo", f"{lid} {p['amount']}")
    await loan_view(ctx, lid)


@route("loan:close", perm="loan_manage")
async def loan_close(ctx: Ctx, lid):
    db.run("UPDATE loans SET status='done' WHERE id=?", (int(lid),))
    ctx.audit("loan_close", lid)
    await loan_view(ctx, lid)


def _mk_loan_edit(code, col, prompt, parse):
    async def done(ctx, d):
        db.run(f"UPDATE loans SET {col}=? WHERE id=?", (d["v"], d["lid"]))
        if col == "installment":
            l = db.one("SELECT * FROM loans WHERE id=?", (d["lid"],))
            db.run("UPDATE loans SET n_installments=? WHERE id=?", (math.ceil(l["amount"] / l["installment"]), l["id"]))
        ctx.audit("loan_edit", f"{d['lid']} {col}")
        await goto(ctx, f"loan:v:{d['lid']}")
    define_flow(f"loan_e_{code}", [Step("v", prompt, parse)], done, "loan:menu")

    @route(f"loan:e{code}", perm="loan_manage")
    async def start(ctx: Ctx, lid):
        await start_flow(ctx, f"loan_e_{code}", {"lid": int(lid)})


_mk_loan_edit("i", "installment", "قسط ماهانه جدید:", p_amount)
_mk_loan_edit("t", "turn_no", "شماره نوبت جدید:", p_int)
_mk_loan_edit("n", "note", "توضیح جدید:", p_text)


@route("loan:del", perm="loan_manage")
async def loan_del(ctx: Ctx, lid):
    await ctx.show("⚠️ این وام و همه پرداخت‌هایش حذف شود؟",
                   [[B("✅ بله، حذف", callback_data=f"loan:del2:{lid}"), B("خیر", callback_data=f"loan:v:{lid}")]])


@route("loan:del2", perm="loan_manage")
async def loan_del2(ctx: Ctx, lid):
    db.run("DELETE FROM loan_payments WHERE loan_id=?", (int(lid),))
    db.run("DELETE FROM loans WHERE id=?", (int(lid),))
    ctx.audit("loan_delete", lid)
    await loan_menu(ctx)


# ───────────── واریزی پرسنل ─────────────
@route("po:add", perm="loan_manage")
async def po_add(ctx: Ctx):
    await start_flow(ctx, "po_add")


async def _po_done(ctx: Ctx, d):
    sid = int(d["staff"])
    ded = d.get("ded") or 0
    db.run("INSERT INTO payouts(staff_id,day,kind,amount,loan_deduct,note,created_by) VALUES(?,?,?,?,?,?,?)",
           (sid, d["day"], d["kind"], d["amount"], ded, d.get("note"), ctx.me["id"]))
    msg = ""
    if ded:
        l = db.one("SELECT * FROM loans WHERE staff_id=? AND status='active' ORDER BY id LIMIT 1", (sid,))
        if l:
            db.run("INSERT INTO loan_payments(loan_id,day,amount,note,created_by) VALUES(?,?,?,?,?)",
                   (l["id"], d["day"], ded, "کسر از واریزی", ctx.me["id"]))
            _check_done(l["id"])
            msg = f"\n💳 قسط {money(ded)} هم روی وام #{l['id']} ثبت شد."
        else:
            msg = "\n⚠️ وام فعالی برای این فرد نبود؛ کسر وام ثبت نشد."
    ctx.audit("payout_add", f"{sid} {d['amount']}")
    s = db.staff_by_id(sid)
    if s and s["tg_id"]:
        await notify(ctx.bot, s["tg_id"], f"💵 واریزی {esc(d['kind'])} به مبلغ {money(d['amount'])} برای شما ثبت شد ({jdate.fmt(d['day'])}).")
    await ctx.send(f"✅ واریزی ثبت شد.{msg}", [[B("➕ واریزی دیگر", callback_data="po:add")], back_row("loan:menu")])


define_flow("po_add", [
    Step("staff", "👤 واریزی برای کدام پرسنل؟", lambda t: int(t), _staff_choices),
    Step("kind", "نوع واریزی:", lambda t: t, [(k, k) for k in KINDS]),
    Step("amount", "💵 مبلغ واریزی:", p_amount),
    Step("day", "📅 تاریخ واریز:", p_date, DATE_CHOICES),
    Step("ded", "💳 مبلغ کسر شده بابت قسط وام (اگر نداشت رد کنید):", p_amount, optional=True),
    Step("note", "توضیح (اختیاری):", p_text, optional=True),
], _po_done, "loan:menu")


@route("po:pick", perm="loan_manage")
async def po_pick(ctx: Ctx):
    kb = grid([B(s["name"], callback_data=f"po:staff:{s['id']}") for s in db.active_staff()])
    kb.append(back_row("loan:menu"))
    await ctx.show("👤 پرسنل را انتخاب کنید:", kb)


@route("po:staff", perm="loan_manage")
async def po_staff(ctx: Ctx, sid):
    await _staff_money(ctx, int(sid), "po:pick")


@route("po:month", perm="loan_manage")
async def po_month(ctx: Ctx, jy=None, jm=None):
    cy, cm, _ = jdate.j_today()
    jy, jm = int(jy or cy), int(jm or cm)
    s, e = jdate.month_bounds(jy, jm)
    rows = db.q("SELECT staff_id, SUM(amount) a, SUM(loan_deduct) d, COUNT(*) c FROM payouts WHERE day BETWEEN ? AND ? GROUP BY staff_id", (s, e))
    lines = [f"• {esc(db.staff_name(r['staff_id']))}: {money(r['a'])}" + (f" (کسر وام {money(r['d'])})" if r["d"] else "") for r in rows]
    total = sum(r["a"] for r in rows)
    py, pm = (jy, jm - 1) if jm > 1 else (jy - 1, 12)
    ny, nm = (jy, jm + 1) if jm < 12 else (jy + 1, 1)
    kb = [[B("◀️ ماه قبل", callback_data=f"po:month:{py}:{pm}"), B("ماه بعد ▶️", callback_data=f"po:month:{ny}:{nm}")], back_row("loan:menu")]
    await ctx.show(f"📆 <b>واریزی‌های {jdate.MONTHS[jm - 1]} {jy}</b>\n\n" + ("\n".join(lines) or "موردی نیست.")
                   + f"\n\n<b>جمع کل: {money(total)}</b>", kb, protect=True)
