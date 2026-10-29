"""بازیابی پشتیبان رمزنگاری‌شده:  DATA_KEY=... python tools/decrypt_backup.py backup.db.enc data/adineh.db"""
import os
import sys

from cryptography.fernet import Fernet

if len(sys.argv) != 3 or not os.environ.get("DATA_KEY"):
    sys.exit("استفاده: DATA_KEY=... python tools/decrypt_backup.py <backup.db.enc> <خروجی.db>")
src, dst = sys.argv[1], sys.argv[2]
if os.path.exists(dst):
    sys.exit(f"{dst} وجود دارد؛ برای جلوگیری از بازنویسی، ابتدا آن را جابه‌جا کنید.")
open(dst, "wb").write(Fernet(os.environ["DATA_KEY"].encode()).decrypt(open(src, "rb").read()))
print("بازیابی شد:", dst)
