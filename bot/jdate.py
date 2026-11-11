"""ابزارهای تاریخ شمسی و زمان. در پایگاه داده تاریخ‌ها میلادی ISO و ساعت‌ها HH:MM ذخیره می‌شوند."""
import re
from datetime import date, datetime, timedelta

from . import config

MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
          "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]  # weekday(): دوشنبه=0

# ── تبدیل تقویم جلالی ⇄ میلادی (الگوریتم jalaali-js، بدون وابستگی خارجی) ──
_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _jal_cal(jy):
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += jump // 33 * 8 + (jump % 33) // 4
        jp = jm
    n = jy - jp
    leap_j += n // 33 * 8 + ((n % 33) + 3) // 4
    if jump % 33 == 4 and jump - n == 4:
        leap_j += 1
    leap_g = gy // 4 - (gy // 100 + 1) * 3 // 4 - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + (jump + 4) // 33 * 33
    leap = (((n + 1) % 33) - 1) % 4
    if leap == -1:
        leap = 4
    return leap, gy, march


def is_leap(jy: int) -> bool:
    return _jal_cal(jy)[0] == 0


def _div(a, b):
    """تقسیم صحیح با گرد به سمت صفر (مثل الگوریتم اصلی؛ // پایتون به پایین گرد می‌کند)."""
    return int(a / b) if abs(a) < 2 ** 50 else a // b


def _g2d(gy, gm, gd):
    d = _div((gy + _div(gm - 8, 6) + 100100) * 1461, 4) + _div(153 * ((gm + 9) % 12) + 2, 5) + gd - 34840408
    return d - _div(_div(gy + 100100 + _div(gm - 8, 6), 100) * 3, 4) + 752


def _d2g(jdn):
    j = 4 * jdn + 139361631
    j += (4 * jdn + 183187720) // 146097 * 3 // 4 * 4 - 3908
    i = (j % 1461) // 4 * 5 + 308
    gd = (i % 153) // 5 + 1
    gm = (i // 153) % 12 + 1
    gy = j // 1461 - 100100 + _div(8 - gm, 6)
    return gy, gm, gd


def _j2d(jy, jm, jd):
    leap, gy, march = _jal_cal(jy)
    return _g2d(gy, 3, march) + (jm - 1) * 31 - jm // 7 * (jm - 7) + jd - 1


def _g2j(gy, gm, gd):
    jdn = _g2d(gy, gm, gd)
    jy = gy - 621
    leap, gy2, march = _jal_cal(jy)
    jdn1f = _g2d(gy2, 3, march)
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + k // 31, k % 31 + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + k // 30, k % 30 + 1


_TR = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def norm(s) -> str:
    """تبدیل ارقام فارسی/عربی به لاتین و حذف فاصله‌های اضافی."""
    return str(s).translate(_TR).replace("٫", ".").replace("٬", ",").strip()


def now() -> datetime:
    return datetime.now(config.TZ)


def today() -> str:
    return now().date().isoformat()


def hhmm() -> str:
    return now().strftime("%H:%M")


def add_days(iso: str, n: int) -> str:
    return (date.fromisoformat(iso) + timedelta(days=n)).isoformat()


def to_j(iso: str):
    d = date.fromisoformat(iso)
    return _g2j(d.year, d.month, d.day)


def fmt(iso: str) -> str:
    if not iso:
        return "—"
    y, m, d = to_j(iso)
    return f"{y}/{m:02d}/{d:02d}"


def weekday(iso: str) -> str:
    return WEEKDAYS[date.fromisoformat(iso).weekday()]


def fmt_long(iso: str) -> str:
    y, m, d = to_j(iso)
    return f"{weekday(iso)} {d} {MONTHS[m - 1]} {y}"


def from_j(y: int, m: int, d: int) -> str:
    if not (1 <= m <= 12 and 1 <= d <= month_days(y, m)):
        raise ValueError("تاریخ نامعتبر")
    gy, gm, gd = _d2g(_j2d(y, m, d))
    return date(gy, gm, gd).isoformat()


def j_today():
    return to_j(today())


def month_days(y: int, m: int) -> int:
    if m <= 6:
        return 31
    if m <= 11:
        return 30
    return 30 if is_leap(y) else 29


def month_bounds(y: int, m: int):
    return from_j(y, m, 1), from_j(y, m, month_days(y, m))


def year_bounds(y: int):
    return from_j(y, 1, 1), from_j(y, 12, month_days(y, 12))


def add_months(iso: str, n: int) -> str:
    y, m, d = to_j(iso)
    t = (y * 12 + (m - 1)) + n
    y, m = divmod(t, 12)
    m += 1
    return from_j(y, m, min(d, month_days(y, m)))


def parse_date(text: str) -> str:
    """ورودی: امروز / دیروز / 1405/08/05 (یا میلادی 2026-10-27). خروجی: ISO میلادی."""
    t = norm(text).lower()
    if t in ("today", "امروز"):
        return today()
    if t in ("yest", "دیروز"):
        return add_days(today(), -1)
    mt = re.match(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$", t)
    if not mt:
        raise ValueError("تاریخ را به شکل 1405/08/05 بنویسید.")
    y, m, d = (int(x) for x in mt.groups())
    try:
        if y >= 1700:
            return date(y, m, d).isoformat()
        return from_j(y, m, d)
    except ValueError:
        raise ValueError("این تاریخ معتبر نیست.")


def parse_time(text: str) -> str:
    t = norm(text).replace(".", ":").replace("٫", ":")
    mt = re.match(r"^(\d{1,2}):(\d{2})$", t) or re.match(r"^(\d{2})(\d{2})$", t) or re.match(r"^(\d{1,2})()$", t)
    if not mt:
        raise ValueError("ساعت را به شکل 08:30 بنویسید.")
    h = int(mt.group(1))
    mi = int(mt.group(2) or 0)
    if h > 23 or mi > 59:
        raise ValueError("ساعت معتبر نیست.")
    return f"{h:02d}:{mi:02d}"


def hours(t_in, t_out) -> float:
    """مدت کارکرد به ساعت (اگر خروج کوچکتر از ورود باشد، شیفت شبانه فرض می‌شود)."""
    if not t_in or not t_out:
        return 0.0
    a = int(t_in[:2]) * 60 + int(t_in[3:5])
    b = int(t_out[:2]) * 60 + int(t_out[3:5])
    if b < a:
        b += 24 * 60
    return round((b - a) / 60, 2)


def hm(h: float) -> str:
    """۷.۵ ساعت → 7:30"""
    total = int(round(h * 60))
    return f"{total // 60}:{total % 60:02d}"


def local_hhmm(ts: str) -> str:
    """زمان UTC پایگاه‌داده ('YYYY-MM-DD HH:MM:SS') → ساعت محلی مرکز (HH:MM)."""
    from datetime import timezone
    try:
        d = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return d.astimezone(config.TZ).strftime("%H:%M")
    except Exception:
        return ""
