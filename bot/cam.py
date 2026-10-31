"""دوربین‌ها: ساخت نشانی RTSP برای پخش‌ِ ضبط‌شده (Playback) و گرفتن عکس/ویدیو با ffmpeg.

⚠️ فرمت نشانی‌ها از مستندات متداول هیک‌ویژن و داهوا نوشته شده و به مدل/فریم‌ور دستگاه بستگی دارد.
   «آزمایش اتصال» را بزنید؛ اگر دستگاه شما فرمت دیگری داشت، برند «دلخواه» را با الگوی خودتان بسازید.
⚠️ دوربین باید از سمت اینترنت (یا VPN) برای ربات قابل دسترس باشد؛ دوربین پشت مودم بدون پورت‌فوروارد
   از اجرای ابری قابل‌دسترس نیست. ضبط‌شده معمولاً با سرعت واقعی پخش می‌شود (کلیپ ۱۰ دقیقه‌ای ≈ ۱۰ دقیقه زمان)."""
import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from . import config, crypto, db

BRANDS = {"hikvision": "هیک‌ویژن / Hikvision", "dahua": "داهوا / Dahua", "custom": "دلخواه (الگوی RTSP)", "link": "فقط لینک"}
MAX_UPLOAD = 49_000_000  # سقف آپلود ربات تلگرام ≈ ۵۰ مگابایت
_sem = None


def sem():
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(1)
    return _sem


def load_cfg(row) -> dict:
    try:
        return crypto.dec_json(row["cfg"]) or {}
    except Exception:
        return {}


def to_utc(day_iso: str, hhmm: str) -> datetime:
    """روز و ساعت (به وقت مرکز) → datetime آگاه به UTC."""
    y, m, d = map(int, day_iso.split("-"))
    h, mi = map(int, hhmm.split(":"))
    return datetime(y, m, d, h, mi, tzinfo=config.TZ).astimezone(timezone.utc)


def _auth(cfg):
    u = quote(str(cfg.get("user", "")), safe="")
    p = quote(str(cfg.get("password", "")), safe="")
    return f"{u}:{p}@" if u else ""


def _hostport(cfg):
    return f"{cfg['host']}:{cfg.get('port') or 554}"


def live_url(cfg) -> str:
    ch = int(cfg.get("channel") or 1)
    b = cfg.get("brand")
    if b == "hikvision":
        return f"rtsp://{_auth(cfg)}{_hostport(cfg)}/Streaming/Channels/{ch}01"
    if b == "dahua":
        return f"rtsp://{_auth(cfg)}{_hostport(cfg)}/cam/realmonitor?channel={ch}&subtype=0"
    return _custom(cfg, None, None, live=True)


def _custom(cfg, s: datetime | None, e: datetime | None, live=False) -> str:
    """الگو: {user} {password} {host} {port} {channel} {start} {end} (UTC به‌صورت 20260131T083000Z) و {start_d} {end_d} (به‌صورت 2026_01_31_08_30_00)."""
    t = cfg.get("template") or ""
    rep = {"user": quote(str(cfg.get("user", "")), safe=""), "password": quote(str(cfg.get("password", "")), safe=""),
           "host": cfg.get("host", ""), "port": str(cfg.get("port") or 554), "channel": str(cfg.get("channel") or 1)}
    if s and e:
        rep.update(start=s.strftime("%Y%m%dT%H%M%SZ"), end=e.strftime("%Y%m%dT%H%M%SZ"),
                   start_d=s.strftime("%Y_%m_%d_%H_%M_%S"), end_d=e.strftime("%Y_%m_%d_%H_%M_%S"))
    for k, v in rep.items():
        t = t.replace("{" + k + "}", v)
    return t


def playback_url(cfg, s_utc: datetime, e_utc: datetime) -> str:
    ch = int(cfg.get("channel") or 1)
    b = cfg.get("brand")
    if cfg.get("tz") == "local":  # برخی دستگاه‌ها زمان محلی دستگاه را می‌خواهند
        s_utc, e_utc = s_utc.astimezone(config.TZ).replace(tzinfo=timezone.utc), e_utc.astimezone(config.TZ).replace(tzinfo=timezone.utc)
    if b == "hikvision":
        f = "%Y%m%dT%H%M%SZ"
        return (f"rtsp://{_auth(cfg)}{_hostport(cfg)}/Streaming/tracks/{ch}01"
                f"?starttime={s_utc.strftime(f)}&endtime={e_utc.strftime(f)}")
    if b == "dahua":
        f = "%Y_%m_%d_%H_%M_%S"
        return (f"rtsp://{_auth(cfg)}{_hostport(cfg)}/cam/playback?channel={ch}&subtype=0"
                f"&starttime={s_utc.strftime(f)}&endtime={e_utc.strftime(f)}")
    return _custom(cfg, s_utc, e_utc)


def mask(text: str, cfg) -> str:
    for secret in (cfg.get("password"), quote(str(cfg.get("password", "")), safe="")):
        if secret:
            text = text.replace(str(secret), "***")
    return text


async def _ffmpeg(args, timeout, cfg):
    try:
        proc = await asyncio.create_subprocess_exec("ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args,
                                                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    except FileNotFoundError:
        return False, "ffmpeg روی سرور نصب نیست."
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, "زمان انتظار تمام شد (دوربین پاسخ نداد یا ضبط کند است)."
    msg = mask((err or b"").decode("utf-8", "replace")[-300:], cfg)
    return proc.returncode == 0, msg


async def snapshot(cfg) -> tuple[bool, str | bytes]:
    """یک فریم از پخش زنده → (True, bytes JPEG) یا (False, پیام خطا)"""
    if cfg.get("brand") == "link":
        return False, "برای این دوربین فقط لینک ثبت شده است."
    out = Path(tempfile.mkdtemp()) / "snap.jpg"
    ok, msg = await _ffmpeg(["-rtsp_transport", "tcp", "-i", live_url(cfg), "-frames:v", "1", "-q:v", "3", str(out)], 40, cfg)
    try:
        if ok and out.exists():
            return True, out.read_bytes()
        return False, msg or "عکس گرفته نشد."
    finally:
        out.unlink(missing_ok=True)


async def clip(cfg, s_utc: datetime, minutes: int, height: int = 480, src: str | None = None) -> tuple[bool, str]:
    """ویدیوی بازه را در یک فایل mp4 موقت می‌سازد → (True, مسیر فایل) یا (False, خطا). `src` برای تست (فایل محلی)."""
    e_utc = s_utc + timedelta(minutes=minutes)
    url = src or playback_url(cfg, s_utc, e_utc)
    out = Path(tempfile.mkdtemp()) / "clip.mp4"
    args = ([] if src else ["-rtsp_transport", "tcp"]) + ["-i", url, "-t", str(minutes * 60), "-an" if cfg.get("mute") else "-c:a",
            *([] if cfg.get("mute") else ["aac", "-b:a", "48k"]), "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "29", "-maxrate", "900k" if height <= 360 else "1500k", "-bufsize", "3M", "-movflags", "+faststart",
            "-fs", str(MAX_UPLOAD), str(out)]
    async with sem():
        ok, msg = await _ffmpeg(args, minutes * 60 * 1.5 + 120, cfg)
    if ok and out.exists() and out.stat().st_size > 1000:
        return True, str(out)
    out.unlink(missing_ok=True)
    return False, msg or "ویدیویی در این بازه پیدا نشد (ضبط نبوده یا فرمت دستگاه فرق دارد)."
