"""پایگاه داده SQLite. فیلدهای حساس (گزارش‌ها، پرونده مددجو، آدرس دوربین، ...) رمزنگاری می‌شوند."""
import json
import os
import sqlite3
import time

from . import config
from .perms import DEFAULT_TITLES, PERMS

SCHEMA = """
CREATE TABLE IF NOT EXISTS titles(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, perms TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS staff(
  id INTEGER PRIMARY KEY, tg_id INTEGER UNIQUE, name TEXT NOT NULL, title_id INTEGER,
  is_admin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, phone TEXT,
  invite_code TEXT, invite_exp TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL, day TEXT NOT NULL, t_in TEXT, t_out TEXT,
  note TEXT, source TEXT DEFAULT 'self', updated_by INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_att ON attendance(staff_id, day);
CREATE TABLE IF NOT EXISTS reports(
  id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL, day TEXT NOT NULL, body TEXT,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_rep ON reports(day);
CREATE TABLE IF NOT EXISTS incidents(
  id INTEGER PRIMARY KEY, day TEXT NOT NULL, tm TEXT, title TEXT NOT NULL, body TEXT,
  severity TEXT DEFAULT 'normal', status TEXT DEFAULT 'open', resolution TEXT,
  created_by INTEGER, resolved_by INTEGER, resolved_day TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL, body TEXT, remind INTEGER DEFAULT 1,
  created_by INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS attachments(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref_id INTEGER NOT NULL, filename TEXT, mime TEXT,
  ftype TEXT, path TEXT, tg_file_id TEXT, size INTEGER, caption TEXT, uploaded_by INTEGER,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_at ON attachments(kind, ref_id);
CREATE TABLE IF NOT EXISTS cameras(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, location TEXT, url TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS loans(
  id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL, turn_no INTEGER, amount INTEGER NOT NULL,
  installment INTEGER NOT NULL, n_installments INTEGER, start_day TEXT, status TEXT DEFAULT 'active',
  note TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS loan_payments(
  id INTEGER PRIMARY KEY, loan_id INTEGER NOT NULL, day TEXT NOT NULL, amount INTEGER NOT NULL,
  note TEXT, created_by INTEGER);
CREATE TABLE IF NOT EXISTS payouts(
  id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL, day TEXT NOT NULL, kind TEXT, amount INTEGER NOT NULL,
  loan_deduct INTEGER DEFAULT 0, note TEXT, created_by INTEGER);
CREATE INDEX IF NOT EXISTS ix_po ON payouts(staff_id, day);
CREATE TABLE IF NOT EXISTS clients(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, status TEXT DEFAULT 'active', admit_day TEXT,
  data TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP, updated TEXT);
CREATE TABLE IF NOT EXISTS client_notes(
  id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, day TEXT NOT NULL, body TEXT, author INTEGER,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS leaves(
  id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL, from_day TEXT, to_day TEXT, reason TEXT,
  status TEXT DEFAULT 'pending', decided_by INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, val TEXT);
CREATE TABLE IF NOT EXISTS presence(
  staff_id INTEGER NOT NULL, day TEXT NOT NULL, status TEXT NOT NULL, note TEXT, marked_by INTEGER,
  updated TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(staff_id, day));
CREATE TABLE IF NOT EXISTS task_tpl(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT, target TEXT NOT NULL, due TEXT,
  skip_fri INTEGER DEFAULT 0, active INTEGER DEFAULT 1, created_by INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, day TEXT NOT NULL, title TEXT NOT NULL, body TEXT, staff_id INTEGER NOT NULL,
  due TEXT, status TEXT DEFAULT 'open', created_by INTEGER, done_at TEXT, tpl_id INTEGER,
  created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_tk ON tasks(day, staff_id);
CREATE TABLE IF NOT EXISTS clips(
  id INTEGER PRIMARY KEY, camera_id INTEGER, cam_name TEXT, t_start TEXT, t_end TEXT, tg_file_id TEXT,
  size INTEGER, requested_by INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sms_log(
  id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, by_id INTEGER, target TEXT, n_ok INTEGER, n_fail INTEGER,
  body TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS sms_queue(
  id INTEGER PRIMARY KEY, run_at TEXT NOT NULL, by_id INTEGER, target TEXT, recipients TEXT, body TEXT,
  status TEXT DEFAULT 'pending', note TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sms_groups(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, members TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS sms_tpl(id INTEGER PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, tg_id INTEGER, action TEXT, detail TEXT);
"""

_conn = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        config.FILES_DIR.mkdir(parents=True, exist_ok=True)
        path = config.DATA_DIR / "adineh.db"
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
        _conn.executescript(SCHEMA)
        _migrate()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _seed()
    return _conn


def reset_for_tests():
    global _conn
    if _conn is not None:
        _conn.close()
    _conn = None


def q(sql, args=()):
    return conn().execute(sql, args).fetchall()


def one(sql, args=()):
    return conn().execute(sql, args).fetchone()


def run(sql, args=()):
    c = conn().execute(sql, args)
    conn().commit()
    return c.lastrowid


def _cols(table):
    return {r["name"] for r in _conn.execute(f"PRAGMA table_info({table})")}


def _add_col(table, col, decl):
    if col not in _cols(table):
        _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _migrate():
    _add_col("staff", "perm_grant", "TEXT DEFAULT '[]'")
    _add_col("staff", "perm_deny", "TEXT DEFAULT '[]'")
    _add_col("cameras", "brand", "TEXT")
    _add_col("cameras", "cfg", "TEXT")
    _conn.commit()
    if not _conn.execute("SELECT 1 FROM kv WHERE key='mig_perms_v2'").fetchone():
        from .perms import ADD_IF_HAS, ADD_TO_ALL
        for t in _conn.execute("SELECT id, perms FROM titles").fetchall():
            have = set(json.loads(t["perms"]))
            have.update(ADD_TO_ALL)
            for k, add in ADD_IF_HAS.items():
                if k in have:
                    have.update(add)
            _conn.execute("UPDATE titles SET perms=? WHERE id=?", (json.dumps(sorted(have)), t["id"]))
        _conn.execute("INSERT INTO kv(key,val) VALUES('mig_perms_v2','1')")
        _conn.commit()


def kv_get(key, default=None):
    r = one("SELECT val FROM kv WHERE key=?", (key,))
    return r["val"] if r else default


def kv_set(key, val):
    run("INSERT INTO kv(key,val) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET val=excluded.val", (key, val))


def roster():
    """پرسنل فعال که در حضور و غیاب و وظایف حساب می‌شوند (ادمین‌ها فقط اگر عنوان شغلی داشته باشند)."""
    return q("SELECT * FROM staff WHERE active=1 AND (is_admin=0 OR title_id IS NOT NULL) ORDER BY name")


def title_label(me):
    t = title_name(me["title_id"]) if me["title_id"] else None
    return t if t and t != "—" else "عنوان ثبت نشده"


def _seed():
    if _conn.execute("SELECT COUNT(*) FROM titles").fetchone()[0] == 0:
        for name, perms in DEFAULT_TITLES.items():
            _conn.execute("INSERT INTO titles(name,perms) VALUES(?,?)", (name, json.dumps(perms)))
        _conn.commit()


def bootstrap_admins(ids):
    for i in ids:
        if one("SELECT id FROM staff WHERE tg_id=?", (i,)):
            run("UPDATE staff SET is_admin=1, active=1 WHERE tg_id=?", (i,))
        else:
            run("INSERT INTO staff(tg_id,name,is_admin,active) VALUES(?,?,1,1)", (i, "⏳ نام ثبت نشده"))


def audit(tg_id, action, detail=""):
    run("INSERT INTO audit(tg_id,action,detail) VALUES(?,?,?)", (tg_id, action, str(detail)[:500]))


def staff_by_tg(tg_id):
    return one("SELECT * FROM staff WHERE tg_id=?", (tg_id,))


def staff_by_id(sid):
    return one("SELECT * FROM staff WHERE id=?", (sid,))


def active_staff():
    return q("SELECT * FROM staff WHERE active=1 ORDER BY name")


def staff_name(sid):
    r = staff_by_id(sid)
    return r["name"] if r else "—"


def title_name(tid):
    r = one("SELECT name FROM titles WHERE id=?", (tid,)) if tid else None
    return r["name"] if r else "—"


def perms_of(me) -> set:
    if me["is_admin"]:
        return set(PERMS)
    t = one("SELECT perms FROM titles WHERE id=?", (me["title_id"],)) if me["title_id"] else None
    base = set(json.loads(t["perms"])) if t else set()
    try:
        grant = set(json.loads(me["perm_grant"] or "[]"))
        deny = set(json.loads(me["perm_deny"] or "[]"))
    except (IndexError, KeyError):
        grant, deny = set(), set()
    return ((base | grant) - deny) & set(PERMS)


def admin_tg_ids():
    return [r["tg_id"] for r in q("SELECT tg_id FROM staff WHERE is_admin=1 AND active=1 AND tg_id IS NOT NULL")]


def backup_to(path):
    """نسخه سازگار از پایگاه داده (حتی هنگام کار ربات)."""
    dst = sqlite3.connect(path)
    with dst:
        conn().backup(dst)
    dst.close()


def now_ts():
    return int(time.time())
