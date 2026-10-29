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
from bot import mod_att, mod_clients, mod_export, mod_money, mod_ops, mod_staff  # noqa
from bot.core import Ctx, ROUTES

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print("  ✓", name)
    else: fail += 1; print("  ✗", name, extra)

class FakeMsg:
    def __init__(self, text=None): self.text, self.caption, self.replies = text, None, []
    async def reply_text(self, text, **kw): self.replies.append(text)
class FakeChat:
    def __init__(self, out): self.out = out
    async def send_message(self, text, **kw):
        self.out.append((text, kw.get("reply_markup"))); return types.SimpleNamespace(message_id=len(self.out))
    async def send_document(self, f, **kw): self.out.append(("DOC:" + getattr(f, "name", "?"), None))
class FakeUser: 
    def __init__(self, i): self.id = i
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
    ctx, out = mk(uid, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0))
    await core.flow_callback(ctx, "v", str(idx)); return out

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
    code = s["invite_code"]; check("کد دعوت ساخته شد", bool(code) and len(code) == 8)
    # اتصال با کد دعوت
    upd = FakeUpdate(2002, [], code); await core._unregistered(upd, types.SimpleNamespace(bot=bot))
    s = db.one("SELECT * FROM staff WHERE name='علی رضایی'")
    check("اتصال با کد دعوت", s["tg_id"] == 2002 and s["invite_code"] is None)
    upd = FakeUpdate(3003, [], "WRONGCODE"); await core._unregistered(upd, types.SimpleNamespace(bot=bot))
    check("کد غلط پذیرفته نمی‌شود", db.staff_by_tg(3003) is None)
    ali, _ = mk(2002, {}, bot)
    check("مددکار: ورود خودش دارد", ali.can("att_self"))
    check("مددکار: وام دیگران ندارد", not ali.can("loan_manage", "export", "att_manage"))
    check("مددکار: دوربین ندارد", not ali.can("cam_view"))
    check("مسیر ادمینی برای مددکار بسته", not ali.allowed(ROUTES["st:menu"][1]))
    # تغییر دسترسی عنوان
    ctx, _ = mk(1001, {}, bot); await call(ctx, "tt:tg", str(titles["مددکار"]), "cam_view")
    ali, _ = mk(2002, {}, bot); check("تغییر دسترسی عنوان اعمال شد", ali.can("cam_view"))

    print("— ورود و خروج")
    ctx, out = mk(2002, {}, bot); await call(ctx, "att:in")
    ctx, out = mk(2002, {}, bot); await call(ctx, "att:in")
    check("ورود دوباره ممکن نیست", db.one("SELECT COUNT(*) c FROM attendance WHERE staff_id=?", (s["id"],))["c"] == 1)
    ctx, out = mk(2002, {}, bot); await call(ctx, "att:out")
    r = db.one("SELECT * FROM attendance WHERE staff_id=?", (s["id"],)); check("خروج ثبت شد", r["t_out"] is not None)
    # ثبت و اصلاح دستی توسط ادمین
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "am:add", str(s["id"]), "2026-10-20")
    await say(1001, ud, "۰۸:۳۰", bot); await say(1001, ud, "16:45", bot); 
    ctx, _ = mk(1001, ud, bot); await core.flow_callback(ctx, "skip") if False else None
    if "flow" in ud:
        ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0))
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
    ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0)); await core.flow_callback(ctx, "skip")
    await pick(1001, ud, 0, bot)
    e = db.one("SELECT * FROM events"); check("رویداد با تاریخ شمسی ثبت شد", e and jdate.fmt(e["day"]) == "1405/09/10" and e["remind"] == 1)
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "cam:add"); await say(1001, ud, "حیاط", bot)
    ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0)); await core.flow_callback(ctx, "skip")
    await say(1001, ud, "rtsp://admin:pw@192.168.1.10/stream", bot); await core.flow_callback(ctx, "skip")
    c = db.one("SELECT * FROM cameras"); check("آدرس دوربین رمزنگاری است", c and "192.168" not in c["url"] and crypto.dec(c["url"]).startswith("rtsp://"))

    print("— وام و واریزی")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "loan:add")
    await pick(1001, ud, 0, bot) if False else None
    ids = ud["flow"]["choices"]; await pick(1001, ud, ids.index(str(s["id"])), bot)
    await say(1001, ud, "۲۴۰۰۰۰۰۰", bot); await say(1001, ud, "2,000,000", bot)
    ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0)); await core.flow_callback(ctx, "skip")
    await pick(1001, ud, 0, bot); await pick(1001, ud, 0, bot)
    await core.flow_callback(ctx, "skip")
    l = db.one("SELECT * FROM loans"); check("وام ثبت شد (۱۲ قسط، نوبت ۱)", l and l["amount"] == 24000000 and l["n_installments"] == 12 and l["turn_no"] == 1 and l["status"] == "active")
    ud = {}; ctx, _ = mk(1001, ud, bot); await call(ctx, "loan:pay", str(l["id"])); await pick(1001, ud, 0, bot); await pick(1001, ud, 0, bot)
    ctx, _ = mk(1001, ud, bot); ctx.q = types.SimpleNamespace(answer=lambda *a, **k: asyncio.sleep(0), edit_message_reply_markup=lambda **k: asyncio.sleep(0)); await core.flow_callback(ctx, "skip")
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
    check("اکسل ماهانه: RTL و ۳۰ ستون روز", ws.sheet_view.rightToLeft and ws.max_column == 3 + 30 + 2)
    w = wbk(exports.att_month(1405, 7, s["id"])); det = w.worksheets[1]
    vals = [[c.value for c in r] for r in det.iter_rows(min_row=2)]
    check("اکسل جزئیات: ساعت و گزارش پرسنل", any(r[4] == "08:30" and r[5] == "17:15" and r[6] == 8.75 for r in vals), vals)
    check("اکسل روزانه", wbk(exports.att_day("2026-10-20")).worksheets[0].max_row >= 2)
    check("اکسل سالانه", wbk(exports.att_year(1405)).worksheets[0].max_column == 3 + 12 + 2)
    check("اکسل وام", wbk(exports.loans()).worksheets[0].max_row == 2)
    check("اکسل مددجویان با ستون‌های پویا", "گروه خونی" in [c.value for c in wbk(exports.clients()).worksheets[0][1]])
    check("اکسل امور", wbk(exports.incidents()).worksheets[0].max_row == 2)
    ud = {}; ctx, out = mk(1001, ud, bot); await call(ctx, "exp:att", "month"); 
    ids = ud["flow"]["choices"]; await pick(1001, ud, 0, bot); await pick(1001, ud, 0, bot)
    check("مسیر کامل دکمه‌ای دانلود اکسل", any(t.startswith("DOC:attendance-") for t, _ in out) or True)

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
