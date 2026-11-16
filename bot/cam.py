"""دوربین‌ها: ساخت نشانی RTSP برای پخش‌ِ ضبط‌شده (Playback) و گرفتن عکس/ویدیو با ffmpeg.

⚠️ فرمت نشانی‌ها از مستندات متداول هیک‌ویژن و داهوا نوشته شده و به مدل/فریم‌ور دستگاه بستگی دارد.
   «آزمایش اتصال» را بزنید؛ اگر دستگاه شما فرمت دیگری داشت، برند «دلخواه» را با الگوی خودتان بسازید.
⚠️ دوربین باید از سمت اینترنت (یا VPN) برای ربات قابل دسترس باشد؛ دوربین پشت مودم بدون پورت‌فوروارد
   از اجرای ابری قابل‌دسترس نیست. ضبط‌شده معمولاً با سرعت واقعی پخش می‌شود (کلیپ ۱۰ دقیقه‌ای ≈ ۱۰ دقیقه زمان)."""
import asyncio
import ipaddress
import os
import socket
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from . import config, crypto, db

BRANDS = {"xm": "ایکس‌می / زیونگمای (DVR با پورت ۳۴۵۶۷)", "hikvision": "هیک‌ویژن / Hikvision", "dahua": "داهوا / Dahua", "custom": "دلخواه (الگوی RTSP)", "link": "فقط لینک"}
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


def is_private(host: str) -> bool:
    """آیا نشانی فقط داخل شبکهٔ محلی معنا دارد؟ (ربات ابری به آن نمی‌رسد مگر با VPN/تونل)"""
    try:
        return ipaddress.ip_address(socket.gethostbyname(host)).is_private
    except Exception:
        return False


PRIVATE_HINT = ("نشانی دستگاه داخلی است (192.168.x.x) و ربات روی اینترنت اجرا می‌شود. راه‌حل‌ها: (۱) تونل Tailscale (توصیه‌شده، "
                "بدون باز کردن پورت) — راهنما در README بخش «اتصال به دوربین»؛ یا (۲) پورت‌فوروارد مودم برای 554 و 34567 + نشانی ثابت/DDNS.")


def _q(v):
    return quote(str(v or ""), safe="")


def xm_live_urls(cfg) -> list:
    """چند الگوی RTSP دستگاه‌های ایکس‌می (به ترتیب تلاش)."""
    ch = int(cfg.get("channel") or 1)
    hp = _hostport(cfg)
    u, p = _q(cfg.get("user")), _q(cfg.get("password"))
    return [f"rtsp://{hp}/user={u}&password={p}&channel={ch}&stream={st}.sdp?real_stream" for st in (0, 1)] + \
           [f"rtsp://{hp}/user={u}&password={p}&channel={ch}&stream=0.sdp"]


def xm_playback_urls(cfg, s_loc: datetime, e_loc: datetime) -> list:
    ch = int(cfg.get("channel") or 1)
    hp = _hostport(cfg)
    u, p = _q(cfg.get("user")), _q(cfg.get("password"))
    base = f"rtsp://{hp}/user={u}&password={p}&channel={ch}&stream=0.sdp"
    out = []
    for f in ("%Y-%m-%d %H:%M:%S", "%Y_%m_%d_%H_%M_%S", "%Y-%m-%d-%H-%M-%S"):
        out.append(f"{base}?starttime={quote(s_loc.strftime(f))}&endtime={quote(e_loc.strftime(f))}")
    return out


def _auth(cfg):
    u = quote(str(cfg.get("user", "")), safe="")
    p = quote(str(cfg.get("password", "")), safe="")
    return f"{u}:{p}@" if u else ""


def _hostport(cfg):
    return f"{cfg['host']}:{cfg.get('port') or 554}"


def live_url(cfg) -> str:
    ch = int(cfg.get("channel") or 1)
    b = cfg.get("brand")
    if b == "xm":
        return xm_live_urls(cfg)[0]
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
    for secret in (cfg.get("password"), quote(str(cfg.get("password", "")), safe=""), quote(str(cfg.get("password", "")), safe="")):
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


def _tcp_open(host, port, timeout=6) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout):
            return True
    except Exception:
        return False


def _dvrip_login(cfg):
    from dvrip import DVRIPCam   # کتابخانهٔ اختیاری python-dvr
    c = DVRIPCam(cfg["host"], user=cfg.get("user") or "admin", password=cfg.get("password") or "", port=int(cfg.get("media_port") or 34567))
    if not c.login():
        raise RuntimeError("ورود به دستگاه ناموفق بود (نام کاربری یا رمز اشتباه است؟)")
    return c


def _dvrip_snapshot(cfg):
    c = _dvrip_login(cfg)
    try:
        ch = int(cfg.get("channel") or 1) - 1
        try:
            data = c.snapshot(ch)
        except TypeError:
            data = c.snapshot()
        return data
    finally:
        try:
            c.close()
        except Exception:
            pass


async def snapshot(cfg) -> tuple[bool, str | bytes]:
    """یک فریم از پخش زنده → (True, bytes JPEG) یا (False, پیام خطا). برای ایکس‌می چند روش پشت‌سرهم امتحان می‌شود."""
    if cfg.get("brand") == "link":
        return False, "برای این دوربین فقط لینک ثبت شده است."
    urls = xm_live_urls(cfg) if cfg.get("brand") == "xm" else [live_url(cfg)]
    last = ""
    for _ in range(2):                                   # دو دور تلاش (شبکه ناپایدار)
        for url in urls:
            out = Path(tempfile.mkdtemp()) / "snap.jpg"
            ok, msg = await _ffmpeg(["-rtsp_transport", "tcp", "-i", url, "-frames:v", "1", "-q:v", "3", str(out)], 40, cfg)
            try:
                if ok and out.exists() and out.stat().st_size > 500:
                    return True, out.read_bytes()
                last = msg or last
            finally:
                out.unlink(missing_ok=True)
    if cfg.get("brand") == "xm":                          # روش دوم: پروتکل اختصاصی دستگاه (پورت ۳۴۵۶۷)
        try:
            data = await asyncio.to_thread(_dvrip_snapshot, cfg)
            if data and len(data) > 500:
                return True, bytes(data)
        except Exception as e:
            last = f"{last}\n{type(e).__name__}: {mask(str(e), cfg)}"
    if is_private(cfg.get("host", "")):
        last = (last + "\n" if last else "") + PRIVATE_HINT
    return False, last or "عکس گرفته نشد."


async def diagnose(cfg) -> str:
    """گزارش کامل تشخیص اتصال (بدون افشای رمز)."""
    host = cfg.get("host", "")
    lines = [f"🖥 {host}"]
    try:
        ip = socket.gethostbyname(host)
        lines.append(f"• نشانی: {ip}" + (" (داخلی)" if ipaddress.ip_address(ip).is_private else " (اینترنتی)"))
    except Exception:
        return "❌ نشانی دستگاه پیدا نشد (IP یا دامنه را بررسی کنید)."
    ports = [("RTSP", cfg.get("port") or 554)]
    if cfg.get("brand") == "xm":
        ports += [("پورت رسانه", cfg.get("media_port") or 34567), ("HTTP", cfg.get("http_port") or 80)]
    any_open = False
    for name, pt in ports:
        o = await asyncio.to_thread(_tcp_open, host, pt)
        any_open |= o
        lines.append(f"• {name} ({pt}): " + ("✅ باز" if o else "❌ بسته/در دسترس نیست"))
    if not any_open:
        lines.append("\n⛔ هیچ پورتی در دسترس نیست. " + (PRIVATE_HINT if is_private(host) else "پورت‌فوروارد/فایروال/روشن بودن دستگاه را بررسی کنید."))
        return "\n".join(lines)
    if cfg.get("brand") == "xm":
        try:
            await asyncio.to_thread(_dvrip_login, cfg)
            lines.append("• ورود با نام کاربری/رمز: ✅")
        except ImportError:
            lines.append("• ورود با پروتکل دستگاه: ➖ (کتابخانهٔ python-dvr نصب نیست)")
        except Exception as e:
            lines.append(f"• ورود با نام کاربری/رمز: ❌ {mask(str(e), cfg)[:120]}")
    ok, res = await snapshot(cfg)
    lines.append("• عکس لحظه‌ای: " + ("✅" if ok else f"❌ {mask(str(res), cfg)[-160:]}"))
    return "\n".join(lines)


def _parse_len(v) -> int:
    try:
        return int(str(v), 16) if str(v).lower().startswith("0x") else int(v)
    except Exception:
        return 0


def _dvrip_fetch(cfg, s_loc: datetime, e_loc: datetime, outdir: str):
    """فایل‌های ضبط‌شدهٔ هم‌پوشان با بازه را مستقیم از DVR می‌گیرد → [(مسیر خام h264, زمان شروع فایل)]. سرعت دانلود، نه سرعت پخش."""
    import inspect
    c = _dvrip_login(cfg)
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        ch = int(cfg.get("channel") or 1) - 1
        fn = c.list_local_files
        kw = {"channel": ch} if "channel" in inspect.signature(fn).parameters else {}
        files = fn(s_loc.strftime(fmt), e_loc.strftime(fmt), "h264", **kw) or []
        res = []
        for f in files[:6]:
            if _parse_len(f.get("FileLength")) > 1_500_000_000:
                raise RuntimeError("فایل ضبط‌شده بسیار بزرگ است؛ بازهٔ کوچک‌تری انتخاب کنید.")
            tgt = os.path.join(outdir, f"seg{len(res)}.h264")
            c.download_file(f["BeginTime"], f["EndTime"], f["FileName"], tgt)
            if os.path.exists(tgt) and os.path.getsize(tgt) > 1000:
                res.append((tgt, datetime.strptime(f["BeginTime"], fmt)))
        return res
    finally:
        try:
            c.close()
        except Exception:
            pass


async def clip(cfg, s_utc: datetime, minutes: int, height: int = 480, src: str | None = None) -> tuple[bool, str]:
    """ویدیوی بازه را در یک فایل mp4 موقت می‌سازد → (True, مسیر فایل) یا (False, خطا). `src` برای تست (فایل محلی)."""
    e_utc = s_utc + timedelta(minutes=minutes)
    if cfg.get("brand") == "xm" and not src:
        return await _clip_xm(cfg, s_utc, e_utc, minutes, height)
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


def _enc_args(cfg, minutes, height, out):
    return ["-t", str(minutes * 60), *(["-an"] if cfg.get("mute") else ["-c:a", "aac", "-b:a", "48k"]), "-vf", f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "29", "-maxrate", "900k" if height <= 360 else "1500k", "-bufsize", "3M",
            "-movflags", "+faststart", "-fs", str(MAX_UPLOAD), str(out)]


async def _clip_xm(cfg, s_utc, e_utc, minutes, height):
    """ایکس‌می: ۱) دانلود مستقیم فایل ضبط‌شده با پروتکل دستگاه (سریع) ۲) پخش RTSP با چند الگو. ساعت دستگاه پیش‌فرض وقت محلی است."""
    loc = (lambda d: d.astimezone(config.TZ).replace(tzinfo=None)) if cfg.get("tz") != "utc" else (lambda d: d.replace(tzinfo=None))
    s_loc, e_loc = loc(s_utc), loc(e_utc)
    errs = []
    out = Path(tempfile.mkdtemp()) / "clip.mp4"
    async with sem():
        try:
            segs = await asyncio.to_thread(_dvrip_fetch, cfg, s_loc, e_loc, str(out.parent))
        except ImportError:
            segs = []
            errs.append("کتابخانهٔ python-dvr نصب نیست؛ فقط RTSP امتحان شد.")
        except Exception as e:
            segs = []
            errs.append(mask(f"{type(e).__name__}: {e}", cfg)[:160])
        for path, begin in segs[:1]:                       # فایلی که شروع بازه را دربرمی‌گیرد
            off = max(0, int((s_loc - begin).total_seconds()))
            for codec in ("h264", "hevc"):
                ok, msg = await _ffmpeg(["-f", codec, "-r", "25", "-ss", str(off), "-i", path, *_enc_args(cfg, minutes, height, out)], minutes * 60 + 240, cfg)
                if ok and out.exists() and out.stat().st_size > 1000:
                    return True, str(out)
                errs.append(msg)
        for url in xm_playback_urls(cfg, s_loc, e_loc):
            ok, msg = await _ffmpeg(["-rtsp_transport", "tcp", "-i", url, *_enc_args(cfg, minutes, height, out)], minutes * 60 * 1.5 + 120, cfg)
            if ok and out.exists() and out.stat().st_size > 1000:
                return True, str(out)
            errs.append(msg)
            if "refused" in (msg or "").lower() or "timed out" in (msg or "").lower() or "No route" in (msg or ""):
                break
    out.unlink(missing_ok=True)
    note = PRIVATE_HINT if is_private(cfg.get("host", "")) else "نشانی/پورت/نام کاربری/رمز و وجود ضبط در این ساعت را بررسی کنید («🧪 تشخیص اتصال»)."
    return False, "\n".join(e for e in dict.fromkeys(errs) if e)[-300:] + "\n" + note
