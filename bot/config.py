"""تنظیمات از متغیرهای محیطی خوانده می‌شود (هیچ رمزی داخل کد نیست)."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATA_KEY = os.environ.get("DATA_KEY", "")  # کلید Fernet برای رمزنگاری داده‌های حساس
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()}
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
FILES_DIR = DATA_DIR / "files"
TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Tehran"))
CENTER_NAME = os.environ.get("CENTER_NAME", "مرکز توانبخشی آدینه")
CONTACT_TEXT = os.environ.get("CONTACT_TEXT", "")  # اختیاری؛ فقط اطلاعات تماس عمومی (مثلاً شماره دفتر)
CURRENCY = os.environ.get("CURRENCY", "تومان")
MAX_DOWNLOAD = 20 * 1024 * 1024  # سقف دانلود ربات از تلگرام
INVITE_HOURS = 72
