"""وظایف روزانه: تعریف توسط مدیر وظایف، انجام توسط خود فرد، وظایف تکرارشونده و اعلان فوری."""
from telegram import InlineKeyboardButton as B

from . import db, jdate
from .core import (Ctx, Step, back_row, bg, define_flow, esc, goto, grid, notify, p_date, p_text, p_time, route,
                   start_flow, fa)


def resolve_target(target: str):
    """'all' | 't:<عنوان>' | 's:<فرد>' → فهرست شناسه پرسنل فعال."""
    ros = db.roster()
    if target == "all":
        return [s["id"] for s in ros]
    kind, _, val = target.partition(":")
    if kind == "t":
        return [s["id"] for s in ros if s["title_id"] == int(val)]
    if kind == "s":
        s = db.staff_by_id(int(val))
        return [s["id"]] if s and s["active"] else []
    return []


def spawn_templates(day=None) -> int:
    """وظایف تکرارشونده را برای امروز می‌سازد (بدون تکرار)."""
    day = day or jdate.today()
    n = 0
    for t in db.q("SELECT * FROM task_tpl WHERE active=1"):
        if t["skip_fri"] and jdate.weekday(day) == "جمعه":
            continue
        for sid in resolve_target(t["target"]):
            if not db.one("SELECT 1 FROM tasks WHERE tpl_id=? AND staff_id=? AND day=?", (t["id"], sid, day)):
                db.run("INSERT INTO tasks(day,title,body,staff_id,due,created_by,tpl_id) VALUES(?,?,?,?,?,?,?)",
                       (day, t["title"], t["body"], sid, t["due"], t["created_by"], t["id"]))
                n += 1
    return n


def _task_btn(t, with_name=False):
    mark = "✅" if t["status"] == "done" else "⬜️"
    who = f"{db.staff_name(t['staff_id'])}: " if with_name else ""
    return B(f"{mark} {who}{t['title'][:32]}" + (f" ⏰{fa(t['due'])}" if t["due"] else ""), callback_data=f"tk:tg:{t['id']}")


@route("tk:menu", perm=("task_self", "task_manage"))
async def tk_menu(ctx: Ctx):
    await tk_my(ctx, jdate.today())


@route("tk:my", perm=("task_self", "task_manage"))
async def tk_my(ctx: Ctx, day):
    rows = db.q("SELECT * FROM tasks WHERE staff_id=? AND day=? ORDER BY status, due, id", (ctx.me["id"], day))
    done = sum(1 for t in rows if t["status"] == "done")
    kb = [[_task_btn(t)] for t in rows]
    kb.append([B("◀️ روز قبل", callback_data=f"tk:my:{jdate.add_days(day, -1)}"),
               B("روز بعد ▶️", callback_data=f"tk:my:{jdate.add_days(day, 1)}")])
    if ctx.can("task_manage"):
        kb.append([B("➕ وظیفه جدید", callback_data="tk:new"), B("👥 وظایف همه", callback_data=f"tk:all:{day}")])
        kb.append([B("🔁 وظایف تکرارشونده", callback_data="tk:tpl")])
    kb.append(back_row())
    head = f"📌 <b>وظایف من</b> — {jdate.fmt_long(day)}\n"
    head += (f"{done} از {len(rows)} انجام شد" if rows else "برای این روز وظیفه‌ای ندارید.")
    await ctx.show(head, kb)


@route("tk:tg", perm=("task_self", "task_manage"))
async def tk_toggle(ctx: Ctx, tid):
    t = db.one("SELECT * FROM tasks WHERE id=?", (int(tid),))
    if not t:
        return await ctx.answer("پیدا نشد", True)
    if t["staff_id"] != ctx.me["id"] and not ctx.can("task_manage"):
        return await ctx.answer("⛔ این وظیفه برای شما نیست", True)
    new = "open" if t["status"] == "done" else "done"
    db.run("UPDATE tasks SET status=?, done_at=? WHERE id=?", (new, jdate.now().isoformat(timespec="seconds") if new == "done" else None, t["id"]))
    ctx.audit("task_" + new, f"{t['id']} {t['title']}")
    if new == "done" and t["created_by"] and t["created_by"] != ctx.me["id"]:
        c = db.staff_by_id(t["created_by"])
        if c and c["tg_id"]:
            await notify(ctx.bot, c["tg_id"], f"✅ {esc(db.staff_name(t['staff_id']))} وظیفهٔ «{esc(t['title'])}» را انجام داد.")
    if t["staff_id"] == ctx.me["id"]:
        await tk_my(ctx, t["day"])
    else:
        await tk_all(ctx, t["day"])


@route("tk:all", perm="task_manage")
async def tk_all(ctx: Ctx, day):
    rows = db.q("SELECT * FROM tasks WHERE day=? ORDER BY staff_id, status, id", (day,))
    kb = [[_task_btn(t, True)] for t in rows]
    kb.append([B("◀️ روز قبل", callback_data=f"tk:all:{jdate.add_days(day, -1)}"),
               B("روز بعد ▶️", callback_data=f"tk:all:{jdate.add_days(day, 1)}")])
    kb.append([B("➕ وظیفه جدید", callback_data="tk:new")])
    kb.append(back_row("tk:menu"))
    done = sum(1 for t in rows if t["status"] == "done")
    await ctx.show(f"👥 <b>وظایف همه</b> — {jdate.fmt_long(day)}\n{done} از {len(rows)} انجام شد. روی هر مورد بزنید تا وضعیتش عوض شود."
                   + ("" if rows else "\nوظیفه‌ای ثبت نشده."), kb)


# ───────────── تعریف وظیفه ─────────────
def _targets(_d):
    out = [("👥 همهٔ پرسنل", "all")]
    out += [(f"🏷 {t['name']}", f"t:{t['id']}") for t in db.q("SELECT * FROM titles ORDER BY name")]
    out += [(f"👤 {s['name']}", f"s:{s['id']}") for s in db.roster()]
    return out


@route("tk:new", perm="task_manage")
async def tk_new(ctx: Ctx):
    await start_flow(ctx, "tk_new")


async def _tk_new_done(ctx: Ctx, d):
    ids = resolve_target(d["target"])
    if not ids:
        return await ctx.send("⚠️ برای این گزینه کسی پیدا نشد.", [back_row("tk:menu")])
    rep = d["repeat"]
    tpl = None
    if rep != "none":
        tpl = db.run("INSERT INTO task_tpl(title,body,target,due,skip_fri,created_by) VALUES(?,?,?,?,?,?)",
                     (d["title"], d.get("body"), d["target"], d.get("due"), 1 if rep == "nofri" else 0, ctx.me["id"]))
    for sid in ids:
        db.run("INSERT INTO tasks(day,title,body,staff_id,due,created_by,tpl_id) VALUES(?,?,?,?,?,?,?)",
               (d["day"], d["title"], d.get("body"), sid, d.get("due"), ctx.me["id"], tpl))
    ctx.audit("task_add", f"{d['title']} n={len(ids)}")
    msg = f"📌 <b>وظیفهٔ جدید</b> برای {jdate.fmt(d['day'])}\n{esc(d['title'])}" + (f"\n⏰ تا ساعت {d['due']}" if d.get("due") else "")
    if d.get("body"):
        msg += f"\n{esc(d['body'])}"
    for sid in ids:
        s = db.staff_by_id(sid)
        if s and s["tg_id"] and s["tg_id"] != ctx.tg_id and "dig_recv" in db.perms_of(s):
            await notify(ctx.bot, s["tg_id"], msg, [[B("📌 وظایف من", callback_data=f"tk:my:{d['day']}")]])
    if d.get("sms") == "1":
        from .mod_sms import send_to_staff
        bg(send_to_staff(ctx.bot, ids, f"وظیفهٔ جدید: {d['title']} ({jdate.fmt(d['day'])})", ctx.me["id"], "وظیفه"))
    await ctx.send(f"✅ وظیفه برای {len(ids)} نفر ثبت شد." + (" 🔁 تکرارشونده" if tpl else ""),
                   [[B("➕ وظیفهٔ دیگر", callback_data="tk:new")], back_row("tk:menu")])


def _sms_on(_d):
    from .mod_sms import configured
    return configured()


define_flow("tk_new", [
    Step("title", "📌 عنوان وظیفه را بنویسید:"),
    Step("body", "شرح بیشتر (اختیاری):", p_text, optional=True),
    Step("target", "این وظیفه برای چه کسی است؟", lambda t: t, _targets),
    Step("day", "📅 برای کدام روز؟", p_date, kind="date"),
    Step("due", "⏰ مهلت انجام (اختیاری):", p_time, kind="time", optional=True),
    Step("repeat", "تکرار؟", lambda t: t, [("فقط همین روز", "none"), ("🔁 هر روز", "daily"), ("🔁 هر روز به‌جز جمعه", "nofri")]),
    Step("sms", "اطلاع‌رسانی:", lambda t: t, [("فقط تلگرام", "0"), ("تلگرام + 📲 پیامک", "1")], when=_sms_on),
], _tk_new_done, "tk:menu")


# ───────────── وظایف تکرارشونده ─────────────
@route("tk:tpl", perm="task_manage")
async def tk_tpl(ctx: Ctx):
    rows = db.q("SELECT * FROM task_tpl WHERE active=1 ORDER BY id")
    kb = [[B(f"🛑 توقف: {t['title'][:30]}", callback_data=f"tk:tpx:{t['id']}")] for t in rows]
    kb.append(back_row("tk:menu"))
    await ctx.show("🔁 <b>وظایف تکرارشونده</b>\n" + ("\n".join(f"• {esc(t['title'])}" for t in rows) or "مورد فعالی نیست."), kb)


@route("tk:tpx", perm="task_manage")
async def tk_tpl_stop(ctx: Ctx, tid):
    db.run("UPDATE task_tpl SET active=0 WHERE id=?", (int(tid),))
    ctx.audit("task_tpl_stop", tid)
    await tk_tpl(ctx)
