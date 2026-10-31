"""منطق حضور و غیاب روزانه (مشترک بین ربات، خلاصه روز و اکسل)."""
from . import db, jdate

STATUS = {
    "present": ("✅", "حاضر", ""),
    "absent": ("❌", "غایب", "غ"),
    "leave": ("🏖", "مرخصی", "م"),
    "sick": ("🩺", "استعلاجی", "ب"),
    "mission": ("🚗", "مأموریت", "ما"),
    "off": ("💤", "استراحت/تعطیل", "—"),
}


def records(sid, day):
    return db.q("SELECT * FROM attendance WHERE staff_id=? AND day=? ORDER BY id", (sid, day))


def on_leave(sid, day) -> bool:
    return bool(db.one("SELECT 1 FROM leaves WHERE staff_id=? AND status='approved' AND from_day<=? AND to_day>=?",
                       (sid, day, day)))


def eff_status(sid, day, recs=None):
    """وضعیت مؤثر روز: ثبت دستی ادمین ← وجود ساعت ← مرخصی تأییدشده ← None."""
    r = db.one("SELECT status FROM presence WHERE staff_id=? AND day=?", (sid, day))
    if r:
        return r["status"]
    recs = records(sid, day) if recs is None else recs
    if recs:
        return "present"
    if on_leave(sid, day):
        return "leave"
    return None


def set_status(sid, day, status, by):
    if status not in STATUS:
        raise ValueError("وضعیت نامعتبر")
    db.run("INSERT INTO presence(staff_id,day,status,marked_by,updated) VALUES(?,?,?,?,CURRENT_TIMESTAMP) "
           "ON CONFLICT(staff_id,day) DO UPDATE SET status=excluded.status, marked_by=excluded.marked_by, updated=CURRENT_TIMESTAMP",
           (sid, day, status, by))


def clear_status(sid, day):
    db.run("DELETE FROM presence WHERE staff_id=? AND day=?", (sid, day))


def set_time(sid, day, which, hhmm, by):
    """ورود/خروج را روی ردیف همان روز ثبت یا اصلاح می‌کند؛ ثبت ساعت یعنی فرد حاضر بوده است."""
    recs = records(sid, day)
    col = "t_in" if which == "in" else "t_out"
    if recs:
        target = recs[0] if which == "in" else recs[-1]
        db.run(f"UPDATE attendance SET {col}=?, source='admin', updated_by=? WHERE id=?", (hhmm, by, target["id"]))
    else:
        db.run(f"INSERT INTO attendance(staff_id,day,{col},source,updated_by) VALUES(?,?,?,'admin',?)", (sid, day, hhmm, by))
    set_status(sid, day, "present", by)


def times_text(recs) -> str:
    if not recs:
        return ""
    t_in = next((r["t_in"] for r in recs if r["t_in"]), None)
    t_out = next((r["t_out"] for r in reversed(recs) if r["t_out"]), None)
    return f"{t_in or '؟'}→{t_out or '…'}"


def day_counts(day):
    """شمارش وضعیت‌ها برای کل پرسنل: دیکشنری status→تعداد (None = ثبت‌نشده)."""
    out = {}
    for s in db.roster():
        st = eff_status(s["id"], day)
        out[st] = out.get(st, 0) + 1
    return out
