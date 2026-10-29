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


def fernet():
    k = os.environ.get("DATA_KEY")
    if not k:
        sys.exit("DATA_KEY تنظیم نشده است.")
    return Fernet(k.encode())


def save(state: Path):
    db = DATA / "adineh.db"
    if not db.exists():
        print("هنوز دیتابیسی نیست؛ ذخیره‌ای انجام نشد.")
        return
    state.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "adineh.db"
        src, dst = sqlite3.connect(db), sqlite3.connect(snap)
        with dst:
            src.backup(dst)  # نسخه سازگار حتی هنگام کار ربات
        src.close(); dst.close()
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(snap, arcname="adineh.db")
            if (DATA / "files").is_dir():
                tar.add(DATA / "files", arcname="files")
    out = state / NAME
    tmp_out = state / (NAME + ".tmp")
    tmp_out.write_bytes(fernet().encrypt(buf.getvalue()))
    tmp_out.replace(out)
    print(f"ذخیره شد: {out.stat().st_size / 1024:.0f} KB")


def restore(state: Path):
    f = state / NAME
    if not f.exists():
        print("حالت ذخیره‌شده‌ای نیست؛ شروع تازه.")
        return
    raw = fernet().decrypt(f.read_bytes())
    DATA.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        tar.extractall(DATA, filter="data")  # جلوگیری از مسیرهای خطرناک
    print("بازیابی شد.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("save", "restore"):
        sys.exit(__doc__)
    {"save": save, "restore": restore}[sys.argv[1]](Path(sys.argv[2]))
