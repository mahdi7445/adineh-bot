"""کد دعوت اختصاصی: ۱۲ حرف تصادفی (≈۶۰ بیت)، یک‌بارمصرف، دارای انقضا. فقط هش آن در دیتابیس ذخیره می‌شود."""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from . import config

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # بدون حروف/ارقام شبیه‌به‌هم (O,0,I,1)
LEN = 12
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def generate() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LEN))


def pretty(raw: str) -> str:
    return "-".join(raw[i:i + 4] for i in range(0, LEN, 4))


def normalize(text: str) -> str:
    """حروف بزرگ، حذف خط تیره/فاصله، ارقام فارسی→لاتین."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").translate(_FA).upper())


def digest(raw: str) -> str:
    return hashlib.sha256(("adineh-invite:" + normalize(raw)).encode()).hexdigest()


def expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=config.INVITE_HOURS)).isoformat(timespec="seconds")


def expired(exp: str) -> bool:
    try:
        return datetime.fromisoformat(exp) < datetime.now(timezone.utc)
    except Exception:
        return True


def exp_local(exp: str) -> str:
    try:
        return datetime.fromisoformat(exp).astimezone(config.TZ).strftime("%H:%M")
    except Exception:
        return "—"
