"""ارسال پیامک از طریق پنل پیامک ایرانی یا گوشی اندرویدی (سیم‌کارت) با اپ «SMS Gateway».

⚠️ نشانی‌ها و قالب پاسخ هر سرویس از مستندات عمومی آن‌ها نوشته شده و باید با «ارسال آزمایشی» در
   بخش پیامک امتحان شود؛ اگر سرویس شما تفاوتی داشت، همین فایل (تابع مربوط به همان سرویس) را اصلاح کنید.
تنظیمات (کلید و رمز) رمزنگاری‌شده در پایگاه‌داده ذخیره می‌شود، نه در کد."""
import asyncio
import base64
import json
import re
import urllib.parse
import urllib.request

from . import crypto, db, jdate

PROVIDERS = {
    "kavenegar": ("کاوه‌نگار", ["apikey", "sender"]),
    "melipayamak": ("ملی‌پیامک", ["username", "password", "sender"]),
    "smsir": ("SMS.ir", ["apikey", "sender"]),
    "gateway": ("گوشی اندرویدی (سیم‌کارت)", ["url", "username", "password"]),
}
FIELD_LABEL = {
    "apikey": "کلید API", "sender": "شمارهٔ خط ارسال‌کننده", "username": "نام کاربری",
    "password": "رمز", "url": "نشانی سرور گوشی (مثلاً https://api.sms-gate.app/3rdparty/v1 یا http://IP:8080)",
}
SECRET_FIELDS = {"apikey", "password"}
SMS_LIMIT = 670  # حدود ۱۰ پارت فارسی؛ پیام بلندتر کوتاه می‌شود


def load_cfg() -> dict:
    raw = db.kv_get("sms_cfg")
    if not raw:
        return {}
    try:
        return crypto.dec_json(raw) or {}
    except Exception:
        return {}


def save_cfg(cfg: dict):
    db.kv_set("sms_cfg", crypto.enc_json(cfg))


def configured() -> bool:
    c = load_cfg()
    p = c.get("provider")
    if p not in PROVIDERS:
        return False
    return all(c.get(f) for f in PROVIDERS[p][1] if f not in ("sender",))


def normalize(phone) -> str | None:
    """شمارهٔ موبایل ایران را به 09xxxxxxxxx تبدیل می‌کند؛ نامعتبر → None."""
    s = re.sub(r"[^\d+]", "", jdate.norm(str(phone or "")))
    s = s.replace("+98", "0", 1) if s.startswith("+98") else s
    if s.startswith("0098"):
        s = "0" + s[4:]
    elif s.startswith("98") and len(s) == 12:
        s = "0" + s[2:]
    elif s.startswith("9") and len(s) == 10:
        s = "0" + s
    return s if re.fullmatch(r"09\d{9}", s) else None


def _http_sync(method, url, headers=None, body=None, form=None, timeout=25):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


async def _http(method, url, headers=None, body=None, form=None):
    return await asyncio.to_thread(_http_sync, method, url, headers, body, form)


def _jget(text, *path, default=None):
    try:
        v = json.loads(text)
        for p in path:
            v = v[p]
        return v
    except Exception:
        return default


async def _send_one(cfg, phone, text):
    """→ (ok: bool, توضیح کوتاه بدون اطلاعات حساس)"""
    p = cfg["provider"]
    if p == "kavenegar":
        url = f"https://api.kavenegar.com/v1/{cfg['apikey']}/sms/send.json"
        form = {"receptor": phone, "message": text}
        if cfg.get("sender"):
            form["sender"] = cfg["sender"]
        st, tx = await _http("POST", url, form=form)
        code = _jget(tx, "return", "status")
        return (st == 200 and code == 200), f"کد {code or st}"
    if p == "melipayamak":
        st, tx = await _http("POST", "https://rest.payamak-panel.com/api/SendSMS/SendSMS",
                             body={"username": cfg["username"], "password": cfg["password"], "to": phone,
                                   "from": cfg.get("sender", ""), "text": text, "isFlash": False})
        ret = _jget(tx, "RetStatus")
        return (st == 200 and ret == 1), f"کد {ret if ret is not None else st}"
    if p == "smsir":
        body = {"messageText": text, "mobiles": [phone]}
        if cfg.get("sender"):
            body["lineNumber"] = int(cfg["sender"]) if str(cfg["sender"]).isdigit() else cfg["sender"]
        st, tx = await _http("POST", "https://api.sms.ir/v1/send/bulk", {"X-API-KEY": cfg["apikey"], "Accept": "application/json"}, body=body)
        ret = _jget(tx, "status")
        return (st == 200 and ret == 1), f"کد {ret if ret is not None else st}"
    if p == "gateway":
        base = cfg["url"].rstrip("/")
        url = base if base.endswith("/message") else base + "/message"
        tok = base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
        st, _ = await _http("POST", url, {"Authorization": f"Basic {tok}"}, body={"message": text, "phoneNumbers": [phone]})
        return st in (200, 201, 202), f"کد {st}"
    return False, "سرویس نامشخص"


async def send_many(items, text_tpl, by_id=None, label=""):
    """items: فهرست (نام، شماره). متن می‌تواند {name} داشته باشد. → (ok, fail, [خطاها])"""
    cfg = load_cfg()
    if not configured():
        return 0, len(items), ["پیامک تنظیم نشده است"]
    ok, fail, errs, seen = 0, 0, [], set()
    for name, phone in items:
        ph = normalize(phone)
        if not ph:
            fail += 1
            errs.append(f"{name}: شمارهٔ نامعتبر")
            continue
        if ph in seen:
            continue
        seen.add(ph)
        txt = text_tpl.replace("{name}", name or "")[:SMS_LIMIT]
        try:
            good, info = await _send_one(cfg, ph, txt)
        except Exception as e:  # شبکه/زمان‌بر
            good, info = False, type(e).__name__
        if good:
            ok += 1
        else:
            fail += 1
            errs.append(f"{name}: {info}")
        await asyncio.sleep(0.3)
    db.run("INSERT INTO sms_log(by_id,target,n_ok,n_fail,body,detail) VALUES(?,?,?,?,?,?)",
           (by_id, label, ok, fail, crypto.enc(text_tpl[:300]), "; ".join(errs)[:500]))
    return ok, fail, errs
