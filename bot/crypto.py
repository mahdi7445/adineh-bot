"""رمزنگاری فیلدها و فایل‌ها (Fernet = AES-128-CBC + HMAC)."""
import json

from cryptography.fernet import Fernet, InvalidToken

from . import config

_f = None


def _fernet() -> Fernet:
    global _f
    if _f is None:
        if not config.DATA_KEY:
            raise RuntimeError("DATA_KEY تنظیم نشده است (tools/gen_keys.py را اجرا کنید).")
        _f = Fernet(config.DATA_KEY.encode())
    return _f


def enc(text) -> str:
    if text is None or text == "":
        return ""
    return _fernet().encrypt(str(text).encode()).decode()


def dec(token) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return "⚠️[خطا در رمزگشایی]"


def enc_json(obj) -> str:
    return enc(json.dumps(obj, ensure_ascii=False))


def dec_json(token):
    s = dec(token)
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def enc_bytes(b: bytes) -> bytes:
    return _fernet().encrypt(b)


def dec_bytes(b: bytes) -> bytes:
    return _fernet().decrypt(b)
