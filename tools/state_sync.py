"""ذخیره/بازیابی کل داده‌های ربات (دیتابیس + فایل‌ها) به‌صورت یک فایل رمزنگاری‌شده.
برای اجرای ربات روی گیت‌هاب اکشنز که دیسکش بعد از هر اجرا پاک می‌شود.
  python tools/state_sync.py save    <پوشه_state>
  python tools/state_sync.py restore <پوشه_state>
فقط با DATA_KEY قابل خواندن است. ( از DATA_DIR و DATA_KEY محیط استفاده می‌کند )"""
import io
import os
import sqlite3
import sys
import tarfile
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

DATA = Path(os.environ.get("DATA_DIR", "data"))
NAME = "state.enc"
MARK = DATA / ".restore_mark"   # نشان می‌دهد بازیابی کامل انجام شده و وزن داده در آن لحظه
USER_TABLES = {"staff", "attendance", "presence", "reports", "incidents", "events", "tasks", "clients", "client_notes",
               "loans", "loan_payments", "payouts", "leaves", "cameras", "attachments", "clips"}
KEEP_SNAPS = 7
MAX_BYTES = 90 * 1024 * 1024    # سقف ۱۰۰ مگابایتی گیت‌هاب



def fernet():
    k = os.environ.get("DATA_KEY")
    if not k:
        sys.exit("DATA_KEY تنظیم نشده است.")
    return Fernet(k.encode())


def weight(db_path: Path) -> int:
    """مجموع تعداد ردیف‌های جدول‌ها (به‌جز ممیزی) برای تشخیص خالی/کوچک شدن ناگهانی داده."""
    c = sqlite3.connect(db_path)
    try:
        n = 0
        have = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in USER_TABLES & have:
            n += c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        return n
    finally:
        c.close()


def rotate_snapshots(state: Path):
    """حالت قبلی را به‌صورت نسخهٔ روزانه نگه می‌دارد (۷ روز اخیر) تا خرابی احتمالی قابل برگشت باشد."""
    import datetime
    cur = state / NAME
    if cur.exists():
        snap = state / f"snap-{datetime.date.today():%Y%m%d}.enc"
        if not snap.exists():
            snap.write_bytes(cur.read_bytes())
    for old in sorted(state.glob("snap-*.enc"))[:-KEEP_SNAPS]:
        old.unlink()


def save(state: Path):
    db = DATA / "adineh.db"
    if not db.exists():
        print("هنوز دیتابیسی نیست؛ ذخیره‌ای انجام نشد.")
        return
    if not MARK.exists():
        sys.exit("بازیابی انجام نشده است؛ برای جلوگیری از بازنویسی داده، ذخیره رد شد.")
    base = int(MARK.read_text().strip() or 0)
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "adineh.db"
        src, dst = sqlite3.connect(db), sqlite3.connect(snap)
        with dst:
            src.backup(dst)  # نسخه سازگار حتی هنگام کار ربات
        src.close(); dst.close()
        cur = weight(snap)
        if base >= 10 and cur < base * 0.5:
            sys.exit(f"حجم داده ناگهان از {base} به {cur} ردیف رسیده؛ ذخیره رد شد (محافظت در برابر پاک شدن).")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(snap, arcname="adineh.db")
            if (DATA / "files").is_dir():
                tar.add(DATA / "files", arcname="files")
    data = fernet().encrypt(buf.getvalue())
    if len(data) > MAX_BYTES:
        sys.exit("حجم داده از سقف گیت‌هاب بیشتر شد؛ فایل‌های سنگین را حذف کنید (ذخیره رد شد).")
    out = state / NAME
    rotate_snapshots(state)
    tmp_out = state / (NAME + ".tmp")
    tmp_out.write_bytes(data)
    tmp_out.replace(out)
    MARK.write_text(str(cur))
    print(f"ذخیره شد: {out.stat().st_size / 1024:.0f} KB")


def restore(state: Path):
    f = state / NAME
    DATA.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        print("حالت ذخیره‌شده‌ای نیست؛ شروع تازه.")
        MARK.write_text("0")
        return
    raw = fernet().decrypt(f.read_bytes())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(DATA, filter="data")  # جلوگیری از مسیرهای خطرناک
    dbp = DATA / "adineh.db"
    MARK.write_text(str(weight(dbp)) if dbp.exists() else "0")
    print("بازیابی شد.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("save", "restore"):
        sys.exit(__doc__)
    {"save": save, "restore": restore}[sys.argv[1]](Path(sys.argv[2]))
