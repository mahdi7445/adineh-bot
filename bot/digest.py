"""خلاصه روز: اتفاقات مهم، وظایف، گزارش پرسنل (بالای منوی اصلی و پیام‌های زمان‌بندی‌شده). فقط بخش‌های مجاز هر فرد."""
import html

from . import attlogic, crypto, db, jdate

SEV_ICON = {"urgent": "🔴", "important": "🟡", "normal": "🟢"}


def _e(s):
    return html.escape(str(s or ""))


def _short(s, n=70):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _names(ids, limit=4):
    names = [db.staff_name(i) for i in ids]
    extra = len(names) - limit
    return "، ".join(_e(n) for n in names[:limit]) + (f" (+{extra})" if extra > 0 else "")


def build(me, perms, is_admin, mode="top", day=None) -> str:
    """mode: top (بالای منو) | am (صبح) | pm (عصر، با جزئیات وظایف معوق)."""
    day = day or jdate.today()
    can = lambda *ps: is_admin or any(p in perms for p in ps)  # noqa: E731
    out = []
    off = attlogic.off_reason(day)
    if off:
        out.append(f"🎌 <b>امروز تعطیل است</b> ({_e(off)})")

    # ── اتفاقات مهم
    if can("inc_write", "inc_manage"):
        rows = db.q("SELECT * FROM incidents WHERE status='open' AND (severity IN ('important','urgent') OR day=?) "
                    "ORDER BY CASE severity WHEN 'urgent' THEN 0 WHEN 'important' THEN 1 ELSE 2 END, id DESC LIMIT 4", (day,))
        if rows:
            out.append("🚨 <b>اتفاقات مهم</b>")
            out += [f"• {SEV_ICON.get(r['severity'], '')} {_e(_short(r['title'], 50))} <i>({jdate.fmt(r['day'])[5:]})</i>" for r in rows]

    # ── وظایف
    if can("task_self", "task_manage"):
        mine = db.q("SELECT * FROM tasks WHERE staff_id=? AND day=? ORDER BY status, id", (me["id"], day))
        if mine:
            done = sum(1 for t in mine if t["status"] == "done")
            out.append(f"📌 <b>وظایف من</b>: {done} از {len(mine)} انجام شد")
            out += [f"• ⬜ {_e(_short(t['title'], 45))}" + (f" ⏰{t['due']}" if t["due"] else "") for t in mine if t["status"] != "done"][:3]
        if can("task_manage"):
            allt = db.q("SELECT * FROM tasks WHERE day=?", (day,))
            if allt:
                done = sum(1 for t in allt if t["status"] == "done")
                line = f"👥 <b>وظایف تیم</b>: {done} از {len(allt)} انجام شد"
                pend = sorted({t["staff_id"] for t in allt if t["status"] != "done"})
                if pend and (mode == "pm" or done < len(allt)):
                    line += f"\n   ⏳ باقی‌مانده: {_names(pend)}"
                out.append(line)

    # ── گزارش پرسنل (فقط اگر گزارشی ثبت شده باشد)
    if can("rep_view"):
        ros = db.att_roster()
        reps = db.q("SELECT * FROM reports WHERE day=? ORDER BY id DESC", (day,))
        if reps:
            done_ids = {r["staff_id"] for r in reps}
            out.append(f"📝 <b>گزارش پرسنل</b>: {len(done_ids & {s['id'] for s in ros})} از {len(ros)} نفر")
            for r in reps[:2]:
                out.append(f"• {_e(db.staff_name(r['staff_id']))}: {_e(_short(crypto.dec(r['body']), 60))}")

    # ── حضور و غیاب (برای مدیر حضور)
    if can("att_manage"):
        c = attlogic.day_counts(day)
        if c:
            parts = [f"{attlogic.STATUS[k][0]} {v}" for k, v in c.items() if k]
            if c.get(None):
                parts.append(f"⬜ ثبت‌نشده {c[None]}")
            out.append("📋 <b>حضور و غیاب</b>: " + " · ".join(parts))
            if not attlogic.off_reason(day):
                for k in ("absent", "leave", "sick", "mission"):
                    ids = [s["id"] for s in db.att_roster() if attlogic.eff_status(s["id"], day) == k]
                    if ids:
                        out.append(f"   {attlogic.STATUS[k][0]} {_names(ids)}")
    # ── رویدادها و مرخصی
    if can("evt_view", "evt_manage"):
        ev = db.q("SELECT * FROM events WHERE day=? ORDER BY id", (day,))
        if ev:
            out.append("📅 <b>رویداد امروز</b>: " + "، ".join(_e(_short(e["title"], 30)) for e in ev[:3]))
    if can("leave_manage"):
        n = db.one("SELECT COUNT(*) c FROM leaves WHERE status='pending'")["c"]
        if n:
            out.append(f"🏖 درخواست مرخصی در انتظار: {n}")
    return "\n".join(out)
