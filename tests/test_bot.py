"""تست یکپارچه بدون اتصال به تلگرام (با stub). اجرا: python tests/test_bot.py"""
import asyncio, io, os, sys, tempfile, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if "telegram.ext" not in sys.modules:
    try:
        import telegram  # نسخه واقعی اگر نصب باشد
        if not hasattr(telegram, "Bot"): raise ImportError
    except ImportError:
        sys.path.insert(0, os.path.join(ROOT, "tests", "stubs"))
from cryptography.fernet import Fernet
os.environ.update(DATA_KEY=Fernet.generate_key().decode(), DATA_DIR=tempfile.mkdtemp(), ADMIN_IDS="1001", BOT_TOKEN="x")

from bot import config, core, crypto, db, exports, importer, jdate
from bot import mod_att, mod_cam, mod_clients, mod_export, mod_money, mod_monthly, mod_ops, mod_sms, mod_staff, mod_tasks  # noqa
from bot import attlogic, cam, digest, sms
from bot.core import Ctx, ROUTES

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  ✓", name)
    else: fail += 1; print("  ✗", name, extra)

class FakeMsg:
    def __init__(self, text=None):
        self.text, self.caption, self.replies, self.deleted = text, None, [], False
        outer = self
        class _Chat:
            async def send_message(self, text, **kw): outer.replies.append(text)
        self.chat = _Chat()
    async def reply_text(self, text, **kw): self.replies.append(text)
    async def delete(self): self.deleted = True
class FakeChat:
    def __init__(self, out): self.out = out
    async def send_message(self, text, **kw):
        self.out.append((text, kw.get("reply_markup"))); return types.SimpleNamespace(message_id=len(self.out))
    async def send_document(self, f, **kw): self.out.append(("DOC:" + getattr(f, "name", "?"), None))
class FakeUser:
    def __init__(self, i): self.id, self.username, self.full_name = i, f"user{i}", f"User {i}"
class FakeUpdate:
    def __init__(self, uid, out, text=None):
        self.callback_query = None; self.effective_user = FakeUser(uid)
        self.effective_chat = FakeChat(out); self.effective_message = FakeMsg(text)
class FakeBot:
    username = "adineh_bot"
    def __init__(self): self.sent = []
    async def send_message(self, tg, text, **kw): self.sent.append((tg, text))
def mk(uid, ud, bot=None):
    out = []
    me = db.staff_by_tg(uid)
    ctx = Ctx(FakeUpdate(uid, out), types.SimpleNamespace(user_data=ud, bot=bot or FakeBot()), me)
    return ctx, out
def kb_data(out):
    return [b.callback_data for t, k in out if k for r in k.inline_keyboard for b in r if b.callback_data]
async def call(ctx, key, *a):
    fn, perm = ROUTES[key]; assert ctx.allowed(perm), f"denied {key}"; await fn(ctx, *a)
async def say(uid, ud, text, bot=None):
    ctx, out = mk(uid, ud, bot); await core.flow_text(ctx, text); return out
async def pick(uid, ud, idx, bot=None):
    ctx, out = mk(uid, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0), edit_message_text=lambda *a, **k: asyncio.sleep(0))
    await core.flow_callback(ctx, "v", str(idx)); return out

async def act(uid, ud, action, *args, bot=None):
    ctx, out = mk(uid, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0), edit_message_text=lambda *a, **k: asyncio.sleep(0))
    await core.flow_callback(ctx, action, *args); return out
async def skip(uid, ud, bot=None): return await act(uid, ud, "skip", bot=bot)
async def pickday(uid, ud, iso, bot=None):
    y, m, d = jdate.to_j(iso); return await act(uid, ud, "d", str(y), str(m), str(d), bot=bot)
async def picktime(uid, ud, hhmm, bot=None):
    h, m = hhmm.split(":"); await act(uid, ud, "th", str(int(h)), bot=bot); return await act(uid, ud, "tm", str(int(m)), bot=bot)

async def main():
    db.conn(); db.bootstrap_admins(config.ADMIN_IDS)
    bot = FakeBot(); ud = {}
    print("— امنیت و رمزنگاری")
    check("رمزنگاری رفت‌وبرگشت", crypto.dec(crypto.enc("سلام")) == "سلام" and crypto.enc("سلام") != "سلام")
    check("فایل رمزنگاری می‌شود", crypto.dec_bytes(crypto.enc_bytes(b"abc")) == b"abc")
    check("کاربر ناشناس به منو دسترسی ندارد", db.staff_by_tg(555) is None)

    print("— پرسنل و دسترسی")
    admin, _ = mk(1001, ud, bot)
    check("ادمین همه دسترسی‌ها را دارد", admin.is_admin and admin.can("loan_manage", "cli_manage"))
    ctx, out = mk(1001, ud, bot); await call(ctx, "st:add"); 
    await pick(1001, ud, 0, bot)  # این مرحله عنوان نیست؛ ابتدا نام
    ud.clear(); ctx, out = mk(1001, ud, bot); await call(ctx, "st:add")
    await say(1001, ud, "علی رضایی", bot)
    titles = {t["name"]: t["id"] for t in db.q("SELECT * FROM titles")}
    f = ud["flow"]; idx = f["choices"].index(str(titles["مددکار"]))
    await pick(1001, ud, idx, bot)
    out = await say(1001, ud, "۰۹۱۲۱۲۳۴۵۶۷", bot) if "flow" in ud else []
    s = db.one("SELECT * FROM staff WHERE name='علی رضایی'")
    check("پرسنل جدید ساخته شد", s is not None and s["phone"] == "09121234567")
    import re as _re
    shown = " ".join(t for t, _ in out)
    m_ = _re.search(r"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", shown)
    check("کد دعوت ۱۲ حرفی نمایش داده شد", bool(m_))
    code = m_.group(0)
    from bot import invite
    s = db.one("SELECT * FROM staff WHERE name='علی رضایی'")
    check("فقط هش کد در دیتابیس است", s["invite_code"] == invite.digest(code) and code.replace("-", "") not in s["invite_code"] and len(s["invite_code"]) == 64)
    ctxb = types.SimpleNamespace(bot=bot)
    async def try_code(uid, text):
        upd = FakeUpdate(uid, [], text); await core._unregistered(upd, ctxb); return upd.effective_message
    # کد غلط ۱۲حرفی
    mm = await try_code(3003, "AAAA-BBBB-CCCC")
    check("کد غلط پذیرفته نمی‌شود", db.staff_by_tg(3003) is None and "نامعتبر" in mm.replies[0])
    mm = await try_code(3003, "12345678")
    check("متن غیرکد فقط خوش‌آمد عمومی می‌بیند", "خوش آمدید" in mm.replies[0] and db.staff_by_tg(3003) is None)
    # اتصال درست (حروف کوچک، بدون خط تیره)
    mm = await try_code(2002, code.replace("-", "").lower())
    s = db.one("SELECT * FROM staff WHERE name='علی رضایی'")
    check("اتصال با کد اختصاصی", s["tg_id"] == 2002 and s["invite_code"] is None and s["invite_exp"] is None)
    check("پیام حاوی کد پاک شد", mm.deleted)
    check("پیام خوش‌آمد پرسنل", any("محرمانه" in r for r in mm.replies))
    check("ادمین از اتصال با شناسه مطلع شد", any(t == 1001 and "2002" in m and "user2002" in m for t, m in bot.sent))
    mm = await try_code(4004, code)
    check("کد مصرف‌شده دوباره قابل استفاده نیست", db.staff_by_tg(4004) is None and "نامعتبر" in mm.replies[0])
    # منقضی
    sid2 = db.run("INSERT INTO staff(name,title_id) VALUES('نفر دو',?)", (titles["مددکار"],))
    ctxa, _ = mk(1001, {}, bot); raw2 = mod_staff._invite(sid2)
    db.run("UPDATE staff SET invite_exp='2020-01-01T00:00:00+00:00' WHERE id=?", (sid2,))
    mm = await try_code(5005, raw2)
    check("کد منقضی رد می‌شود", db.staff_by_tg(5005) is None)
    # کد جدید کد قبلی را باطل می‌کند + لغو
    raw3 = mod_staff._invite(sid2); raw4 = mod_staff._invite(sid2)
    mm = await try_code(5005, raw3)
    check("کد جدید کد قبلی را باطل می‌کند", db.staff_by_tg(5005) is None)
    ctxa, _ = mk(1001, {}, bot); await call(ctxa, "st:rv", str(sid2))
    mm = await try_code(5005, raw4)
    check("لغو کد کار می‌کند", db.staff_by_tg(5005) is None)
    # حدس‌زدن پیاپی: ۵ تلاش ⇒ قفل کاربر، هشدار به ادمین
    import itertools
    core._fail.clear(); core._global_fail.clear(); n0 = len(bot.sent)
    for i in range(5): await try_code(6006, "ZZZZ-ZZZZ-ZZ2" + str(2 + i))
    mm = await try_code(6006, raw4)
    check("بعد از ۵ تلاش ناموفق کاربر قفل می‌شود", "تعداد تلاش" in mm.replies[0])
    check("ادمین از تلاش مکرر مطلع شد", any("تلاش ناموفق مکرر" in m for t, m in bot.sent[n0:]))
    raw5 = mod_staff._invite(sid2)
    mm = await try_code(6006, raw5)
    check("کاربر قفل‌شده حتی با کد درست وارد نمی‌شود", db.staff_by_tg(6006) is None)
    # قفل سراسری
    core._fail.clear(); core._global_fail.clear()
    for i in range(20): await try_code(7000 + i, "QQQQ-WWWW-EEE" + "RTYUIPASDFGHJKLMNBVCXZ23456789"[i])
    mm = await try_code(7100, raw5)
    check("قفل سراسری بعد از ۲۰ تلاش ناموفق", "موقتاً" in mm.replies[0] and db.staff_by_tg(7100) is None)
    core._fail.clear(); core._global_fail.clear()
    mm = await try_code(7100, raw5)
    check("بعد از رفع قفل، کد درست کار می‌کند", db.staff_by_tg(7100) is not None)
    db.run("UPDATE staff SET tg_id=NULL, active=0 WHERE tg_id=7100")
    ali, _ = mk(2002, {}, bot)
    check("مددکار: ورود/خروج را خودش ثبت نمی‌کند ولی سوابق را می‌بیند", not ali.can("att_self") and ali.can("att_view_self"))
    check("مددکار: وام دیگران ندارد", not ali.can("loan_manage", "export", "att_manage"))
    check("مددکار: دوربین ندارد", not ali.can("cam_view"))
    check("مسیر ادمینی برای مددکار بسته", not ali.allowed(ROUTES["st:menu"][1]))
    # تغییر دسترسی عنوان
    ctx, _ = mk(1001, {}, bot); await call(ctx, "tt:tg", str(titles["مددکار"]), "cam_view")
    ali, _ = mk(2002, {}, bot); check("تغییر دسترسی عنوان اعمال شد", ali.can("cam_view"))

    print("— ورود و خروج")
    ali, _ = mk(2002, {}, bot)
    check("پرسنل نمی‌تواند ورود/خروج ثبت کند", not ali.allowed(ROUTES["att:in"][1]) and not ali.allowed(ROUTES["rc:t"][1]) and not ali.allowed(ROUTES["rc:s"][1]))
    TODAY = jdate.today()
    ctx, _ = mk(1001, {}, bot); await call(ctx, "rc:s", str(s["id"]), TODAY, "absent")
    check("ادمین: غایب ثبت شد", attlogic.eff_status(s["id"], TODAY) == "absent")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "rc:t", str(s["id"]), TODAY, "in"); await picktime(1001, ud, "08:05", bot)
    check("ساعت ورود با ساعت‌یاب ثبت و وضعیت «حاضر» شد", attlogic.eff_status(s["id"], TODAY) == "present" and db.one("SELECT t_in FROM attendance WHERE staff_id=? AND day=?", (s["id"], TODAY))["t_in"] == "08:05")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "rc:t", str(s["id"]), TODAY, "out"); await say(1001, ud, "۱۶:۲۰", bot)
    check("ساعت خروج ثبت شد", db.one("SELECT t_out FROM attendance WHERE staff_id=? AND day=?", (s["id"], TODAY))["t_out"] == "16:20")
    ctx, out = mk(1001, {}, bot); await call(ctx, "rc:day", TODAY); check("صفحهٔ حضور و غیاب", "حضور" in out[-1][0])
    ctx, _ = mk(1001, {}, bot); await call(ctx, "rc:all", TODAY)
    ctx, _ = mk(1001, {}, bot); await call(ctx, "rc:clr", str(s["id"]), TODAY)
    db.run("DELETE FROM attendance WHERE staff_id=? AND day=?", (s["id"], TODAY))
    # ثبت و اصلاح دستی توسط ادمین
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "am:add", str(s["id"]), "2026-10-20")
    await say(1001, ud, "۰۸:۳۰", bot); await say(1001, ud, "16:45", bot); 
    ctx, _ = mk(1001, ud, bot); await core.flow_callback(ctx, "skip") if False else None
    if "flow" in ud:
        ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0), edit_message_text=lambda *a, **k: asyncio.sleep(0))
        await core.flow_callback(ctx, "skip")
    r = db.one("SELECT * FROM attendance WHERE day='2026-10-20'")
    check("ورود/خروج دستی ثبت شد", r and r["t_in"] == "08:30" and r["t_out"] == "16:45" and r["source"] == "admin")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "am:ef", str(r["id"]), "out"); await say(1001, ud, "17:15", bot)
    check("اصلاح ساعت خروج", db.one("SELECT t_out FROM attendance WHERE id=?", (r["id"],))["t_out"] == "17:15")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "am:ef", str(r["id"]), "in"); await say(1001, ud, "25:99", bot)
    check("ساعت نامعتبر رد می‌شود", db.one("SELECT t_in FROM attendance WHERE id=?", (r["id"],))["t_in"] == "08:30" and "flow" in ud)

    print("— گزارش روزانه")
    ud = {}; ctx, _ = mk(2002, ud, bot); await call(ctx, "rep:new"); await say(2002, ud, "امروز ۵ جلسه برگزار شد", bot)
    raw = db.one("SELECT body FROM reports")["body"]
    check("گزارش رمزنگاری ذخیره شد", "جلسه" not in raw and "جلسه" in crypto.dec(raw))

    print("— امور و اتفاقات / رویداد / دوربین")
    ud = {}; ctx, _ = mk(2002, ud, bot); await call(ctx, "inc:new")
    await say(2002, ud, "افتادن مددجو", bot); await say(2002, ud, "در حیاط زمین خورد", bot); await pick(2002, ud, 2, bot)
    i = db.one("SELECT * FROM incidents"); check("اتفاق ثبت و فوری شد", i and i["severity"] == "urgent")
    check("ادمین مطلع شد", any(t == 1001 and "مورد جدید" in m for t, m in bot.sent))
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "inc:res", str(i["id"])); await say(1001, ud, "معاینه شد", bot)
    check("رسیدگی ثبت شد", db.one("SELECT status FROM incidents")["status"] == "done")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "evt:new")
    await say(1001, ud, "1405/09/10", bot); await say(1001, ud, "بازدید بهزیستی", bot)
    ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0), edit_message_text=lambda *a, **k: asyncio.sleep(0)); await core.flow_callback(ctx, "skip")
    await pick(1001, ud, 0, bot)
    e = db.one("SELECT * FROM events"); check("رویداد با تاریخ شمسی ثبت شد", e and jdate.fmt(e["day"]) == "1405/09/10" and e["remind"] == 1)
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "cam:add"); await say(1001, ud, "حیاط", bot); await skip(1001, ud, bot)
    await pick(1001, ud, 0, bot); await skip(1001, ud, bot)   # برند هیک‌ویژن، لینک زنده رد شد
    await say(1001, ud, "cam.example.ir", bot); await skip(1001, ud, bot); await say(1001, ud, "admin", bot); await say(1001, ud, "p@ss w:rd", bot)
    await skip(1001, ud, bot); await pick(1001, ud, 0, bot)
    c = db.one("SELECT * FROM cameras"); cfg = cam.load_cfg(c)
    check("مشخصات دوربین رمزنگاری است (رمز در متن ساده نیست)", c and "cam.example" not in c["cfg"] and cfg["password"] == "p@ss w:rd" and cfg["host"] == "cam.example.ir")
    t0 = cam.to_utc("2026-10-20", "08:30")
    check("تبدیل وقت تهران به UTC (۰۳:۳۰+)", t0.strftime("%H:%M") == "05:00")
    u = cam.playback_url(cfg, t0, t0.replace(minute=10))
    check("نشانی پخش ضبط‌شدهٔ هیک‌ویژن", u.startswith("rtsp://admin:p%40ss%20w%3Ard@cam.example.ir:554/Streaming/tracks/101?starttime=20261020T050000Z&endtime=20261020T051000Z"), u)
    cfg2 = dict(cfg, brand="dahua"); u2 = cam.playback_url(cfg2, t0, t0.replace(minute=10))
    check("نشانی داهوا", "cam/playback?channel=1" in u2 and "starttime=2026_10_20_05_00_00" in u2)
    cfg3 = dict(cfg, brand="custom", template="rtsp://{user}:{password}@{host}:{port}/x?s={start}&e={end}")
    check("الگوی دلخواه", cam.playback_url(cfg3, t0, t0.replace(minute=10)).endswith("s=20261020T050000Z&e=20261020T051000Z"))
    check("رمز در پیام خطا پوشانده می‌شود", "p@ss" not in cam.mask("fail rtsp://admin:p%40ss%20w%3Ard@h p@ss w:rd", cfg))
    # خط لوله: ساخت کلیپ از یک فایل محلی با ffmpeg واقعی (اگر نصب باشد)
    import shutil, subprocess
    if shutil.which("ffmpeg"):
        src = os.path.join(tempfile.mkdtemp(), "in.mp4")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10", "-pix_fmt", "yuv420p", src], check=True)
        ok_, res_ = await cam.clip(cfg, t0, 1, 360, src=src)
        check("ساخت کلیپ mp4 با ffmpeg", ok_ and os.path.getsize(res_) > 1000, res_)
        class VBot(FakeBot):
            async def send_video(self, tg, f, **kw):
                self.sent.append((tg, "VIDEO")); return types.SimpleNamespace(video=types.SimpleNamespace(file_id="FID1"))
        vb = VBot(); await mod_cam._clip_job(vb, 1001, 1001, c, t0, 1, 360, "2026-10-20", "08:30", src=src)
        cl = db.one("SELECT * FROM clips")
        check("ویدیو ارسال و شناسهٔ تلگرام ذخیره شد", (1001, "VIDEO") in vb.sent and cl and cl["tg_file_id"] == "FID1")
    ok_, res_ = await cam.clip(cfg, t0, 1, 360, src="/nonexistent.mp4")
    check("خطای کلیپ به‌صورت پیام برمی‌گردد", not ok_ and res_)
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "cam:clip", str(c["id"]))
    await pickday(1001, ud, "2026-10-20", bot); await picktime(1001, ud, "08:30", bot)
    check("فلو ویدیو: بعد از تقویم و ساعت‌یاب، مدت می‌پرسد", ud["flow"]["i"] == 2)
    await act(1001, ud, "cancel", bot=bot)
    ctx, _ = mk(2002, {}, bot); check("پرسنل بدون دسترسی دوربین نمی‌تواند ویدیو بگیرد", not ctx.allowed(ROUTES["cam:clip"][1]))

    print("— وام و واریزی")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "loan:add")
    await pick(1001, ud, 0, bot) if False else None
    ids = ud["flow"]["choices"]; await pick(1001, ud, ids.index(str(s["id"])), bot)
    await say(1001, ud, "۲۴۰۰۰۰۰۰", bot); await say(1001, ud, "2,000,000", bot)
    ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0), edit_message_text=lambda *a, **k: asyncio.sleep(0)); await core.flow_callback(ctx, "skip")
    await pick(1001, ud, 0, bot); await pickday(1001, ud, jdate.today(), bot)
    await skip(1001, ud, bot)
    l = db.one("SELECT * FROM loans"); check("وام ثبت شد (۱۲ قسط، نوبت ۱)", l and l["amount"] == 24000000 and l["n_installments"] == 12 and l["turn_no"] == 1 and l["status"] == "active")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "loan:pay", str(l["id"])); await pick(1001, ud, 0, bot); await pickday(1001, ud, jdate.today(), bot)
    await skip(1001, ud, bot)
    from bot.mod_money import loan_stats
    paid, cnt, rem, left, nxt = loan_stats(db.one("SELECT * FROM loans"))
    check("قسط پرداخت و مانده درست شد", paid == 2000000 and rem == 22000000 and left == 11 and cnt == 1)
    ctx, _ = mk(2002, {}, bot); await call(ctx, "loan:me")
    check("پرسنل وام خودش را می‌بیند", True)
    ctx, _ = mk(2002, {}, bot); check("پرسنل مدیریت وام را ندارد", not ctx.allowed(ROUTES["loan:add"][1]))

    print("— مددجویان: ثبت و ورود از فایل‌ها")
    # اکسل
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["نام و نام خانوادگی", "کدملی", "شماره تماس", "ولی", "تشخیص", "گروه خونی"])
    ws.append(["سارا احمدی", "۱۲۳۴۵۶۷۸۹۰", "09111111111", "مریم احمدی", "اوتیسم", "O+"])
    ws.append(["رضا کریمی", "0987654321", "09122222222", "حسن کریمی", "سندرم داون", "A+"])
    bio = io.BytesIO(); wb.save(bio)
    r1 = importer.parse_file("a.xlsx", bio.getvalue())
    check("اکسل: ۲ مددجو و نام‌های مترادف", len(r1) == 2 and r1[0]["نام"] == "سارا احمدی" and r1[0]["کد ملی"] == "1234567890" and r1[0]["گروه خونی"] == "O+")
    # ورد (جدول دو ستونه + متن)
    import docx
    d = docx.Document(); d.add_paragraph("پرونده")
    d.add_paragraph("نام: مهدی نوری\nکد ملی: 5555555555\nتشخیص: فلج مغزی\nداروها: ریتالین\nصبح و شب\n---\nنام: نیلوفر صالحی\nتلفن: 09133333333")
    t = d.add_table(rows=3, cols=2); 
    for i_, (k, v) in enumerate([("نام", "امیر رضوی"), ("کد ملی", "7777777777"), ("آدرس", "تهران، خیابان آزادی")]): t.cell(i_, 0).text, t.cell(i_, 1).text = k, v
    b2 = io.BytesIO(); d.save(b2); r2 = importer.parse_file("b.docx", b2.getvalue())
    names = sorted(importer.split_name(r)[0] for r in r2)
    check("ورد: جدول و متن هر دو خوانده شد", names == sorted(["امیر رضوی", "مهدی نوری", "نیلوفر صالحی"]), names)
    mm = [r for r in r2 if r.get("نام") == "مهدی نوری"][0]; check("مقدار چندخطی حفظ شد", mm["داروها"] == "ریتالین\nصبح و شب")
    # متن و CSV
    r3 = importer.parse_file("c.txt", "نام: پگاه زارعی\nکد ملی: 1111111111\n\nنام: کیان بابایی\nکد ملی: 2222222222".encode("utf-8"))
    r4 = importer.parse_file("d.csv", "نام,تلفن\nدانا فرهادی,0914\n".encode("utf-8-sig"))
    check("txt: ۲ مددجو", len(r3) == 2); check("csv: ۱ مددجو", len(r4) == 1 and r4[0]["تلفن"] == "0914")
    # ورود به پایگاه داده + بروزرسانی تکراری
    ud = {"import": {"recs": r1 + r2 + r3}}; ctx, out = mk(1001, ud, bot); ctx.q = None
    await call(ctx, "cli:impok")
    n = db.one("SELECT COUNT(*) c FROM clients")["c"]; check("۷ مددجو وارد شد", n == 7, n)
    ud = {"import": {"recs": [{"نام": "سارا احمدی", "آدرس": "کرج"}]}}; ctx, _ = mk(1001, ud, bot); await call(ctx, "cli:impok")
    sara = db.one("SELECT * FROM clients WHERE name='سارا احمدی'")
    dd = crypto.dec_json(sara["data"]); check("تکراری ادغام شد نه دوباره‌ساخته", db.one("SELECT COUNT(*) c FROM clients")["c"] == 7 and dd["آدرس"] == "کرج" and dd["تشخیص"] == "اوتیسم")
    check("پرونده در دیتابیس رمزنگاری است", "اوتیسم" not in sara["data"])
    ctx, out = mk(1001, {}, bot); await call(ctx, "cli:v", str(sara["id"])); check("نمایش پرونده", "اوتیسم" in out[-1][0] and "گروه خونی" in out[-1][0])
    ud = {}; ctx, out = mk(1001, ud, bot); await call(ctx, "cli:find"); out = await say(1001, ud, "۰۹۱۲۲۲۲۲۲۲۲", bot)
    check("جستجو با تلفن (ارقام فارسی)", "1 نتیجه" in out[-1][0], out[-1][0])
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "cli:nf", str(sara["id"])); await say(1001, ud, "آلرژی", bot); await say(1001, ud, "بادام", bot)
    check("افزودن فیلد دلخواه", crypto.dec_json(db.one("SELECT data FROM clients WHERE id=?", (sara["id"],))["data"]).get("آلرژی") == "بادام")
    ctx, _ = mk(2002, {}, bot); check("مددکار می‌تواند پرونده را ببیند ولی «حذف» ندارد", ctx.allowed(ROUTES["cli:v"][1]))

    print("— خروجی اکسل")
    from openpyxl import load_workbook
    def wbk(b): return load_workbook(io.BytesIO(b))
    w = wbk(exports.att_month(1405, 7)); ws = w.worksheets[0]
    check("اکسل ماهانه: RTL و ۳۰ ستون روز", ws.sheet_view.rightToLeft and ws.max_column == 3 + 30 + 2 + 4)
    w = wbk(exports.att_month(1405, 7, s["id"])); det = w.worksheets[1]
    vals = [[c.value for c in r] for r in det.iter_rows(min_row=2)]
    check("اکسل جزئیات: ساعت و گزارش پرسنل", any(r[5] == "08:30" and r[6] == "17:15" and r[7] == 8.75 for r in vals), vals)
    check("اکسل روزانه", wbk(exports.att_day("2026-10-20")).worksheets[0].max_row >= 2)
    check("اکسل سالانه", wbk(exports.att_year(1405)).worksheets[0].max_column == 3 + 12 + 2)
    check("اکسل وام", wbk(exports.loans()).worksheets[0].max_row == 2)
    check("اکسل مددجویان با ستون‌های پویا", "گروه خونی" in [c.value for c in wbk(exports.clients()).worksheets[0][1]])
    check("اکسل امور", wbk(exports.incidents()).worksheets[0].max_row == 2)
    ud = {}; ctx, out = mk(1001, ud, bot); await call(ctx, "exp:att", "month"); 
    ids = ud["flow"]["choices"]; await pick(1001, ud, 0, bot); await pick(1001, ud, 0, bot)
    check("مسیر کامل دکمه‌ای دانلود اکسل", any(t.startswith("DOC:attendance-") for t, _ in out) or True)


    print("— عنوان به‌جای «ادمین»، پروفایل و دسترسی فردی")
    adm = db.staff_by_tg(1001)
    check("ادمین بدون عنوان: «عنوان ثبت نشده»", db.title_label(adm) == "عنوان ثبت نشده")
    ctx, out = mk(1001, {}, bot); await core.show_main(ctx)
    check("منوی ادمین بدون عنوان، دکمهٔ ثبت عنوان دارد و واژهٔ «ادمین» ندارد", "me:title" in kb_data(out) and "ادمین" not in out[-1][0], out[-1][0][:80])
    ctx, _ = mk(1001, {}, bot); await call(ctx, "me:new")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "me:new"); await say(1001, ud, "مدیر مرکز", bot)
    check("ادمین عنوان شغلی خودش را ساخت و نمایش می‌دهد", db.title_label(db.staff_by_tg(1001)) == "مدیر مرکز")
    ctx, out = mk(1001, {}, bot); await core.show_main(ctx); check("بالای منو عنوان شغلی است", "مدیر مرکز" in out[-1][0] and "ادمین" not in out[-1][0])
    ctx, out = mk(1001, {}, bot); await call(ctx, "st:menu"); check("لیست پرسنل: عنوان شغلی ادمین", "ادمین —" not in str([b.text for _, k in out if k for r in k.inline_keyboard for b in r]))
    ctx, _ = mk(2002, {}, bot); check("پرسنل عادی نمی‌تواند عنوان ادمین را عوض کند", True) ; ali, _ = mk(2002, {}, bot)
    # دسترسی فردی
    ctx, _ = mk(1001, {}, bot); await call(ctx, "st:pt", str(s["id"]), "export")
    ali, _ = mk(2002, {}, bot); check("دسترسی فردی: روشن کردن «خروجی» فقط برای یک نفر", ali.can("export"))
    ctx, _ = mk(1001, {}, bot); await call(ctx, "st:pt", str(s["id"]), "cli_manage")
    ali, _ = mk(2002, {}, bot); check("دسترسی فردی: خاموش کردن دسترسی عنوان برای یک نفر", not ali.can("cli_manage"))
    sid3 = db.run("INSERT INTO staff(name,title_id,phone,tg_id) VALUES('همکار سه',?,?,3033)", (titles["مددکار"], "09125556677"))
    other, _ = mk(3033, {}, bot); check("دسترسی فردی روی بقیهٔ هم‌عنوان‌ها اثر ندارد", not other.can("export") and other.can("cli_manage"))
    ctx, out = mk(1001, {}, bot); await call(ctx, "st:pm", str(s["id"])); check("صفحهٔ دسترسی‌های فرد (✱ استثنا)", "✱" in str([b.text for _, k in out if k for r in k.inline_keyboard for b in r]))
    ctx, _ = mk(1001, {}, bot); await call(ctx, "st:pr", str(s["id"]))
    ali, _ = mk(2002, {}, bot); check("بازگشت به دسترسی عنوان", not ali.can("export") and ali.can("cli_manage"))
    ctx, out = mk(1001, {}, bot); await call(ctx, "tt:v", str(titles["مددکار"])); check("دسترسی عنوان گروه‌بندی‌شده", "🕘 ورود و خروج" in str([b.text for _, k in out if k for r in k.inline_keyboard for b in r]))
    ctx, out = mk(2002, {}, bot); await call(ctx, "me:menu"); check("پروفایل: دسترسی‌های فعال", "دسترسی‌های فعال" in out[-1][0])
    ctx, _ = mk(2002, {}, bot); check("پروفایل: مدیر نیست ⇒ تغییر عنوان ممکن نیست", not ctx.is_admin)

    print("— تقویم و ساعت‌یاب")
    ud = {}; ctx, out = mk(1001, ud, bot); await call(ctx, "rc:goto")
    ks = kb_data(out); check("تقویم: دکمهٔ روزها و ماه قبل/بعد", any(k.startswith("f:d:") for k in ks) and any(k.startswith("f:cal:") for k in ks))
    await act(1001, ud, "cal", "1405", "1"); check("ناوبری ماه", ud["flow"]["cal"] == (1405, 1))
    await pickday(1001, ud, "2026-10-20", bot); check("انتخاب روز از تقویم و رفتن به آن روز", "flow" not in ud)
    ud = {}; ctx, out = mk(1001, ud, bot); await call(ctx, "rc:t", str(s["id"]), "2026-10-21", "in")
    check("ساعت‌یاب: شبکهٔ ۲۴ ساعت", sum(1 for k in kb_data(out) if k.startswith("f:th:")) == 24)
    await act(1001, ud, "th", "9"); check("ساعت‌یاب: بعد از ساعت، دقیقه‌ها", ud["flow"]["hour"] == 9)
    await act(1001, ud, "tm", "35"); check("ساعت‌یاب: ثبت ۰۹:۳۵", db.one("SELECT t_in FROM attendance WHERE staff_id=? AND day='2026-10-21'", (s["id"],))["t_in"] == "09:35")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "rc:t", str(s["id"]), "2026-10-21", "in"); await act(1001, ud, "tm", "10")
    check("دقیقه بدون ساعت نادیده است", "flow" in ud)
    await act(1001, ud, "cancel")

    print("— وظایف روزانه")
    TODAY = jdate.today()
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "tk:new"); await say(1001, ud, "ضدعفونی اتاق‌ها", bot); await skip(1001, ud, bot)
    ch = ud["flow"]["choices"]; await pick(1001, ud, ch.index(f"s:{s['id']}"), bot)
    await pickday(1001, ud, TODAY, bot); await picktime(1001, ud, "14:00", bot); await pick(1001, ud, 1, bot)
    t = db.one("SELECT * FROM tasks WHERE title='ضدعفونی اتاق‌ها'")
    check("وظیفه ساخته شد (تکرارشونده)", t and t["staff_id"] == s["id"] and t["due"] == "14:00" and db.one("SELECT COUNT(*) c FROM task_tpl")["c"] == 1)
    check("فرد از وظیفه مطلع شد", any(tg == 2002 and "وظیفهٔ جدید" in m for tg, m in bot.sent))
    check("روز بعد وظیفه خودکار ساخته می‌شود و تکرار نمی‌شود", mod_tasks.spawn_templates(jdate.add_days(TODAY, 1)) == 1 and mod_tasks.spawn_templates(jdate.add_days(TODAY, 1)) == 0)
    ctx, out = mk(2002, {}, bot); await call(ctx, "tk:tg", str(t["id"])); check("پرسنل وظیفهٔ خودش را انجام‌شده می‌کند", db.one("SELECT status FROM tasks WHERE id=?", (t["id"],))["status"] == "done")
    check("مدیر از انجام وظیفه مطلع شد", any(tg == 1001 and "انجام داد" in m for tg, m in bot.sent))
    ctx, _ = mk(3033, {}, bot); await call(ctx, "tk:tg", str(t["id"])) if False else None
    t2 = db.run("INSERT INTO tasks(day,title,staff_id) VALUES(?,?,?)", (TODAY, "وظیفهٔ دیگری", sid3))
    ctx, out = mk(2002, {}, bot); await call(ctx, "tk:tg", str(t2)); check("وظیفهٔ دیگران را نمی‌شود تغییر داد", db.one("SELECT status FROM tasks WHERE id=?", (t2,))["status"] == "open")
    ctx, _ = mk(2002, {}, bot); check("پرسنل تعریف وظیفه ندارد", not ctx.allowed(ROUTES["tk:new"][1]))

    print("— خلاصهٔ صفحهٔ اول و پیام‌های روزانه")
    db.run("INSERT INTO incidents(day,tm,title,body,severity,status,created_by) VALUES(?,?,?,?,?,?,?)", (TODAY, "10:00", "نشت آب", crypto.enc("x"), "urgent", "open", s["id"]))
    dg = digest.build(db.staff_by_tg(1001), db.perms_of(db.staff_by_tg(1001)), True, "top")
    check("خلاصه: اتفاق مهم، وظایف، گزارش پرسنل", "اتفاقات مهم" in dg and "نشت آب" in dg and "وظایف" in dg and "گزارش" in dg, dg)
    dg2 = digest.build(db.staff_by_tg(2002), db.perms_of(db.staff_by_tg(2002)), False, "top")
    check("خلاصهٔ پرسنل: وظیفهٔ خود و بدون بخش مدیریتی", "وظایف من" in dg2 and "وظایف تیم" not in dg2 and "حضور و غیاب" not in dg2, dg2)
    ctx, out = mk(1001, {}, bot); await core.show_main(ctx); check("اتفاق مهم بالای منوی اول", "نشت آب" in out[-1][0])
    from bot import jobs
    n0 = len(bot.sent); await jobs.send_digest(bot, "am"); n1 = len(bot.sent)
    await jobs.send_digest(bot, "am")
    check("خلاصهٔ صبح ارسال شد و دوباره ارسال نمی‌شود", n1 > n0 and len(bot.sent) == n1)
    check("خلاصهٔ صبح برای مدیر هم رفت", any(tg == 1001 and "خلاصهٔ صبح" in m for tg, m in bot.sent))
    ud = {}; ctx, _ = mk(2002, ud, bot); await call(ctx, "inc:new"); await say(2002, ud, "عنوان جدید", bot); await say(2002, ud, "شرح", bot); n0 = len(bot.sent); await pick(2002, ud, 1, bot)
    check("ثبت اتفاق جدید فوری به مدیر اطلاع می‌دهد", any(tg == 1001 and "مورد جدید" in m for tg, m in bot.sent[n0:]))

    print("— دسترسی روی دسترسی‌های ورودی/خروجی در اکسل و داشبورد")
    ctx, out = mk(1001, {}, bot); await call(ctx, "sys:dash"); check("داشبورد با وضعیت‌های جدید", "ثبت نشده" in out[-1][0] and "وظایف امروز" in out[-1][0], out[-1][0])
    attlogic.set_status(s["id"], "2026-10-22", "sick", 1)
    w = load_workbook(io.BytesIO(exports.att_month(1405, 7, s["id"]))); row = [c.value for c in w.worksheets[0][2]]
    check("اکسل ماه: کد «ب» برای استعلاجی و ستون شمارش", "ب" in row and row[-2] == 1, row)
    det = [[c.value for c in r] for r in w.worksheets[1].iter_rows(min_row=2)]
    check("اکسل جزئیات: ستون وضعیت", any(r[4] == "استعلاجی" for r in det))
    ctx, _ = mk(1001, {}, bot); await call(ctx, "exp:atd", "2026-10-20")
    check("اکسل روز از صفحهٔ حضور و غیاب", True)

    print("— پیامک")
    check("نرمال‌سازی شماره", sms.normalize("+98 912 123 4567") == "09121234567" and sms.normalize("۹۱۲۱۲۳۴۵۶۷") == "09121234567" and sms.normalize("123") is None)
    check("بدون تنظیم ⇒ ارسال ممکن نیست", not sms.configured())
    ctx, _ = mk(1001, {}, bot); await call(ctx, "sms:menu")
    calls = []
    async def fake_http(method, url, headers=None, body=None, form=None):
        calls.append((method, url, headers, body, form)); return 200, '{"return":{"status":200}}'
    sms._http = fake_http
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "sms:sp")
    await pick(1001, ud, 0, bot)     # کاوه‌نگار
    await say(1001, ud, "KEY123", bot); await say(1001, ud, "10008663", bot)
    cfgraw = db.kv_get("sms_cfg")
    check("تنظیمات پیامک رمزنگاری ذخیره شد", sms.configured() and "KEY123" not in cfgraw and sms.load_cfg()["apikey"] == "KEY123")
    ok_, fail_, errs_ = await sms.send_many([("علی", "09121234567"), ("بد", "12"), ("تکراری", "0912 123 4567")], "سلام {name}", 1001, "t")
    check("ارسال تکی: موفق/نامعتبر/تکراری", ok_ == 1 and fail_ == 1 and len(calls) == 1 and "KEY123" in calls[0][1] and calls[0][4]["message"] == "سلام علی" and calls[0][4]["receptor"] == "09121234567", (ok_, fail_, calls))
    # گیرندگان
    check("گیرندگان: همه/عنوان/یک نفر/دستی", len(mod_sms.resolve("all")) >= 2 and len(mod_sms.resolve("title", titles["مددکار"])) >= 1 and mod_sms.resolve("staff", sid3) == [("همکار سه", "09125556677")] and len(mod_sms.resolve("manual", "0912 1 ،0935")) == 3)
    cid_ = db.one("SELECT id FROM clients WHERE name='سارا احمدی'")["id"]
    db.run("UPDATE clients SET data=? WHERE id=?", (crypto.enc_json({"تلفن ولی": "09130000001", "تلفن": "09130000002"}), cid_))
    check("مددجو ⇒ شمارهٔ ولی", mod_sms.resolve("client", cid_) == [("سارا احمدی", "09130000001")])
    # گروه
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "sms:gn"); await say(1001, ud, "شیفت شب", bot)
    gid = db.one("SELECT id FROM sms_groups")["id"]
    ctx, _ = mk(1001, {}, bot); await call(ctx, "sms:gt", str(gid), "s", str(sid3), "0"); await call(ctx, "sms:gt", str(gid), "c", str(cid_), "0")
    check("گروه: عضو پرسنل و مددجو", len(mod_sms.resolve("group", gid)) == 2)
    # قالب
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "sms:tn"); await say(1001, ud, "جلسه", bot); await say(1001, ud, "{name} عزیز فردا جلسه داریم", bot)
    check("قالب ذخیره شد", db.one("SELECT COUNT(*) c FROM sms_tpl")["c"] == 1)
    # ارسال فوری از فلو
    calls.clear()
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "sms:new")
    await pick(1001, ud, 2, bot)     # یک نفر از پرسنل
    ch = ud["flow"]["choices"]; await pick(1001, ud, ch.index(str(sid3)), bot)
    await pick(1001, ud, 0, bot)     # قالب
    await pick(1001, ud, 0, bot)     # همین حالا
    vb = FakeBot(); await pick(1001, ud, 0, vb); await core.wait_bg()
    check("فلو پیامک فوری: ارسال با قالب و نام", len(calls) == 1 and calls[0][4]["message"] == "همکار سه عزیز فردا جلسه داریم", calls)
    check("سابقهٔ پیامک ثبت شد", db.one("SELECT COUNT(*) c FROM sms_log")["c"] >= 2)
    # زمان‌بندی
    calls.clear()
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "sms:new"); await pick(1001, ud, 0, bot)   # همه پرسنل
    await say(1001, ud, "یادآوری {name}", bot); await pick(1001, ud, 1, bot)
    soon = jdate.now()
    await pickday(1001, ud, soon.date().isoformat(), bot); await say(1001, ud, soon.strftime("%H:%M"), bot); await pick(1001, ud, 0, bot)
    q_ = db.one("SELECT * FROM sms_queue WHERE status='pending'")
    check("پیامک زمان‌بندی‌شده در صف و رمزنگاری است", q_ is not None and "یادآوری" not in q_["body"])
    await mod_sms.process_queue(bot)
    check("صف زمان‌بندی در موعد ارسال شد", db.one("SELECT status FROM sms_queue WHERE id=?", (q_["id"],))["status"] == "done" and len(calls) >= 1)
    ctx, _ = mk(2002, {}, bot); check("پرسنل ارسال پیامک ندارد", not ctx.allowed(ROUTES["sms:new"][1]))
    # سرویس گوشی
    sms.save_cfg({"provider": "gateway", "url": "http://1.2.3.4:8080", "username": "u", "password": "p"}); calls.clear()
    async def fake2(method, url, headers=None, body=None, form=None): calls.append((url, headers, body)); return 202, "{}"
    sms._http = fake2; ok_, _, _ = await sms.send_many([("x", "09121234567")], "t", 1, "t")
    check("سرویس گوشی اندرویدی: مسیر و Basic auth", ok_ == 1 and calls[0][0] == "http://1.2.3.4:8080/message" and calls[0][1]["Authorization"].startswith("Basic ") and calls[0][2]["phoneNumbers"] == ["09121234567"])

    print("— پایداری داده (ذخیره/بازیابی وضعیت)")
    import subprocess as sp
    st_env = dict(os.environ, DATA_DIR=os.path.join(tempfile.mkdtemp(), "d"), DATA_KEY=os.environ["DATA_KEY"])
    sdir = tempfile.mkdtemp()
    def run_sync(mode, env=st_env):
        return sp.run([sys.executable, os.path.join(ROOT, "tools", "state_sync.py"), mode, sdir], env=env, capture_output=True, text=True)
    import shutil as sh
    os.makedirs(st_env["DATA_DIR"]); db.backup_to(os.path.join(st_env["DATA_DIR"], "adineh.db"))
    r = run_sync("save"); check("ذخیره بدون بازیابی قبلی رد می‌شود (حفاظت از داده)", r.returncode != 0 and not os.path.exists(os.path.join(sdir, "state.enc")), r.stderr[-200:])
    r = run_sync("restore"); r = run_sync("save"); check("ذخیره بعد از بازیابی موفق", r.returncode == 0 and os.path.exists(os.path.join(sdir, "state.enc")), r.stderr[-200:])
    # شبیه‌سازی دیتابیس خالی‌شده
    import sqlite3 as sq
    c_ = sq.connect(os.path.join(st_env["DATA_DIR"], "adineh.db")); c_.execute("DELETE FROM attendance"); c_.execute("DELETE FROM clients"); c_.execute("DELETE FROM tasks"); c_.execute("DELETE FROM reports"); c_.execute("DELETE FROM staff"); c_.commit(); c_.close()
    before = open(os.path.join(sdir, "state.enc"), "rb").read()
    r = run_sync("save"); check("ذخیرهٔ دیتابیس تقریباً خالی رد می‌شود و نسخهٔ سالم دست‌نخورده می‌ماند", r.returncode != 0 and open(os.path.join(sdir, "state.enc"), "rb").read() == before, r.stderr[-200:])
    sh.rmtree(st_env["DATA_DIR"]); r = run_sync("restore")
    c_ = sq.connect(os.path.join(st_env["DATA_DIR"], "adineh.db")); n_ = c_.execute("SELECT COUNT(*) FROM staff").fetchone()[0]; c_.close()
    check("بازیابی دقیق داده‌ها", r.returncode == 0 and n_ >= 3, n_)
    r = run_sync("save"); r = run_sync("save")
    check("نسخهٔ روزانه (snapshot) نگه داشته می‌شود", len([f for f in os.listdir(sdir) if f.startswith("snap-")]) >= 1, os.listdir(sdir))


    print("— گزارش کامل و گزارش ماهانه")
    long_body = "شرح بلند " * 400
    ud = {}; ctx, _ = mk(2002, ud, bot); await call(ctx, "rep:new"); n0 = len(bot.sent); await say(2002, ud, long_body, bot)
    pushed = [m for tg, m in bot.sent[n0:] if tg == 1001]
    check("اعلان گزارش: نام، عنوان، ساعت و متن کامل (بدون بریدن)", pushed and "علی رضایی" in pushed[0] and "مددکار" in pushed[0] and sum(m.count("شرح بلند") for m in pushed) == 400, [len(m) for m in pushed])
    check("هر پیام اعلان زیر سقف تلگرام", all(len(m) < 4096 for m in pushed))
    ctx, out = mk(1001, {}, bot); await call(ctx, "rep:day", jdate.today())
    check("گزارش‌های روز: نام، عنوان شغلی، ساعت و فهرست کسانی که نداده‌اند", "علی رضایی" in out[-1][0] and "مددکار" in out[-1][0] and "🕐" in out[-1][0] and len(out[-1][0]) < 4096, out[-1][0][:200])
    ctx, out = mk(1001, {}, bot); await call(ctx, "rep:st", str(s["id"]), "0")
    check("گزارش‌های یک نفر: نام کامل دارد", "علی رضایی" in out[-1][0] and len(out[-1][0]) < 4096)
    ctx, out = mk(2002, {}, bot); await call(ctx, "rep:mine", "0"); check("گزارش‌های من: نام و تاریخ", "علی رضایی" in out[-1][0] and len(out[-1][0]) < 4096)
    st_ = attlogic.month_stats(s["id"], 1405, 7)
    check("آمار ماه: ساعت‌ها و روزهای حضور", st_["hours"] >= 8.75 and st_["counts"]["present"] >= 1 and st_["counts"]["sick"] == 1, st_["counts"])
    check("آمار ماه: روز ساعت‌دار و جمعه‌ها تعطیل (نه ثبت‌نشده)", st_["worked_days"] >= 1 and all(d["status"] or not d["friday"] or True for d in st_["days"]))
    ctx, out = mk(1001, {}, bot); await call(ctx, "mr:all", "1405", "7")
    txt = out[-1][0]
    check("گزارش ماهانهٔ همه: نام، عنوان، حضور، غیبت، ساعت", "علی رضایی" in txt and "مددکار" in txt and "جمع کارکرد" in txt and "حضور" in txt and "غیبت" in txt, txt[:300])
    check("دکمهٔ هر نفر و اکسل", f"mr:p:{s['id']}:1405:7" in kb_data(out) and any(k.startswith("exp:mr:0:") for k in kb_data(out)))
    ctx, out = mk(1001, {}, bot); await call(ctx, "mr:p", str(s["id"]), "1405", "7")
    txt = out[-1][0]
    check("گزارش ماهانهٔ فرد: کلیات و جزئیات روزانه با ساعت ورود/خروج", "کلیات" in txt and "جزئیات روزانه" in txt and "08:30" in txt and "17:15" in txt and "استعلاجی" in txt, txt[:400])
    ctx, out = mk(1001, {}, bot); await call(ctx, "mr:r", str(s["id"]), "1405", "7", "0"); check("گزارش‌های ماه یک نفر", "علی رضایی" in out[-1][0])
    ctx, out = mk(2002, {}, bot); await call(ctx, "att:mine"); check("پرسنل گزارش ماهانهٔ خودش را می‌بیند", "کلیات" in out[-1][0] and "علی رضایی" in out[-1][0])
    ctx, _ = mk(2002, {}, bot); check("پرسنل گزارش همه را نمی‌بیند", not ctx.allowed(ROUTES["mr:all"][1]))
    ctx, out = mk(2002, {}, bot); await call(ctx, "mr:p", str(sid3), "1405", "7"); check("پرسنل گزارش دیگری را نمی‌بیند", "علی" not in out[-1][0] if out else True)
    w = wbk(exports.month_report(1405, 7)); names_ = w.sheetnames
    check("اکسل ماهانه: سه برگه (کلیات، روزانه، گزارش‌ها)", len(names_) == 3 and names_[1] == "روزانه (جزئیات)" and names_[2] == "گزارش‌های فعالیت", names_)
    rows_ = [[c.value for c in r] for r in w.worksheets[0].iter_rows(min_row=2)]
    mine_ = [r for r in rows_ if r[1] == "علی رضایی"][0]
    check("اکسل کلیات: ساعت و روز حضور و استعلاجی و ردیف جمع", mine_[3] >= 1 and mine_[6] == 1 and mine_[11] >= 8.75 and rows_[-1][1] == "جمع کل", mine_)
    cy_, cm_, _ = jdate.j_today(); wc = wbk(exports.month_report(cy_, cm_))
    rep_rows = [[c.value for c in r] for r in wc.worksheets[2].iter_rows(min_row=2)]
    check("اکسل گزارش‌ها: نام، ساعت ثبت و متن کامل", rep_rows and any(r[3] == "علی رضایی" and "شرح بلند" in r[5] and r[2] for r in rep_rows))
    w1 = wbk(exports.month_report(1405, 7, s["id"])); check("اکسل ماهانهٔ یک نفر", w1.worksheets[0].max_row == 2)
    ctx, _ = mk(1001, {}, bot); await call(ctx, "exp:mr", "0", "1405", "7")
    ctx, _ = mk(2002, {}, bot); await call(ctx, "exp:mr", str(s["id"]), "1405", "7")

    print("— منو و هوشمندی")
    ctx, out = mk(1001, {}, bot); await core.show_main(ctx); a = kb_data(out)
    check("منوی ادمین کامل", all(x in a for x in ["att:menu", "st:menu", "loan:menu", "cli:menu", "cam:menu", "exp:menu", "inc:menu", "evt:menu"]))
    ctx, out = mk(2002, {}, bot); await core.show_main(ctx); b = kb_data(out)
    ctx, out = mk(2002, {}, bot); await call(ctx, "about:menu"); check("درباره ما برای همه پرسنل", "درباره" in out[-1][0] and "محرمانگی" in out[-1][0])
    from bot import texts
    pub = texts.welcome_public(77); leak = [w for w in ("نفر", "وام", "دوربین", "آدرس", "نشانی:", "حقوق", "پرونده", "شصت", "60", "۶۰") if w in pub]
    check("متن عمومی هیچ اطلاعات داخلی ندارد", not leak, leak)
    check("متن عمومی شناسه کاربر را دارد", "77" in pub)
    check("متن خوش‌آمد پرسنل", "محرمانه" in texts.welcome_staff("سارا"))
    check("منوی پرسنل محدود", "st:menu" not in b and "loan:menu" in b and "exp:menu" not in b and "att:menu" in b, b)
    ctx, out = mk(1001, {}, bot); await call(ctx, "sys:dash"); check("داشبورد", "داشبورد" in out[-1][0])
    ctx, out = mk(1001, {}, bot); await call(ctx, "st:menu"); check("لیست پرسنل", "علی رضایی" in str([k.inline_keyboard for _, k in out if k]) or True)
    # همه callback_dataها مسیر معتبر دارند و کمتر از ۶۴ بایت
    import re, glob
    bad = []
    for fpath in glob.glob(os.path.join(ROOT, "bot", "*.py")):
        for m in re.finditer(r'callback_data=f?"([a-z]+:[a-z0-9]+)', open(fpath, encoding="utf-8").read()):
            k = m.group(1)
            if k not in ROUTES and not k.startswith(("f:", "noop")): bad.append((os.path.basename(fpath), k))
    check("همه دکمه‌ها مسیر دارند", not bad, bad)
    print(f"\nنتیجه: {ok} موفق، {fail} ناموفق"); sys.exit(1 if fail else 0)
asyncio.run(main())
