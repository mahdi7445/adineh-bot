"""هسته ربات: زمینه (Ctx)، مسیریابی دکمه‌ها، موتور فرم‌های چندمرحله‌ای، پیوست فایل، منوی اصلی."""
import html
import io
import logging
import secrets
import asyncio
import time
from datetime import date
from dataclasses import dataclass
from typing import Any, Callable, Optional

from telegram import InlineKeyboardButton as B
from telegram import InlineKeyboardMarkup as M
from telegram.constants import ParseMode
from telegram.error import BadRequest

from . import config, crypto, db, digest, invite, jdate, texts

log = logging.getLogger("adineh")
HTML = ParseMode.HTML


def esc(s) -> str:
    return html.escape("" if s is None else str(s))


def money(n) -> str:
    return f"{int(n or 0):,} {config.CURRENCY}"


def split_text(text: str, n: int = 3900):
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > n:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:n])
            line = line[n:]
        if len(cur) + len(line) + 1 > n:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur)
    return out or [""]


# ───────────────────────────── مسیریابی ─────────────────────────────
ROUTES: dict = {}
HOOKS: dict = {}


def route(key: str, perm=None):
    """perm: None | 'admin' | 'نام_دسترسی' | ('دسترسی۱','دسترسی۲') = هرکدام."""
    def deco(fn):
        ROUTES[key] = (fn, perm)
        return fn
    return deco


def btn(text: str, data: str = None, url: str = None):
    return B(text, url=url) if url else B(text, callback_data=data)


def back_row(target: str = "m:main"):
    row = []
    if target != "m:main":
        row.append(B("🔙 بازگشت", callback_data=target))
    row.append(B("🏠 منوی اصلی", callback_data="m:main"))
    return row


def grid(buttons, per=2):
    rows, row = [], []
    for b in buttons:
        row.append(b)
        if len(row) == per:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def pager(base: str, page: int, total: int, per: int):
    """ردیف دکمه‌های صفحه‌بندی؛ base مثل 'inc:list:open' و صفحه به انتهای آن اضافه می‌شود."""
    pages = max(1, -(-total // per))
    row = []
    if page > 0:
        row.append(B("◀️ قبلی", callback_data=f"{base}:{page - 1}"))
    if pages > 1:
        row.append(B(f"{page + 1}/{pages}", callback_data="noop:x"))
    if page < pages - 1:
        row.append(B("بعدی ▶️", callback_data=f"{base}:{page + 1}"))
    return row


class Ctx:
    def __init__(self, update, context, me):
        self.update, self.context, self.me = update, context, me
        self.q = update.callback_query
        self.ud = context.user_data
        self.perms = db.perms_of(me)
        self.answered = False
        self.route = None

    @property
    def tg_id(self):
        return self.update.effective_user.id

    @property
    def is_admin(self):
        return bool(self.me["is_admin"])

    @property
    def bot(self):
        return self.context.bot

    def can(self, *ps) -> bool:
        return self.is_admin or any(p in self.perms for p in ps)

    def allowed(self, perm) -> bool:
        if perm is None:
            return True
        if perm == "admin":
            return self.is_admin
        if isinstance(perm, (tuple, list)):
            return self.can(*perm)
        return self.can(perm)

    def audit(self, action, detail=""):
        db.audit(self.tg_id, action, detail)

    async def answer(self, text="", alert=False):
        if self.q and not self.answered:
            self.answered = True
            try:
                await self.q.answer(text, show_alert=alert)
            except Exception:
                pass

    async def send(self, text, kb=None, protect=False):
        parts = split_text(text)
        msg = None
        for i, p in enumerate(parts):
            last = i == len(parts) - 1
            msg = await self.update.effective_chat.send_message(
                p, parse_mode=HTML, reply_markup=M(kb) if (kb and last) else None,
                disable_web_page_preview=True, protect_content=protect)
        return msg

    async def show(self, text, kb=None, protect=False):
        """اگر از دکمه آمده باشیم پیام قبلی ویرایش می‌شود، وگرنه پیام تازه. راهنمای کوتاه هر بخش خودکار اضافه می‌شود."""
        hint = texts.HINTS.get(self.route)
        if hint and len(text) + len(hint) < 3800:
            text = f"{text}\n\n💡 <i>{hint}</i>"
        if self.q and len(text) <= 3900:
            try:
                await self.q.edit_message_text(
                    text, parse_mode=HTML, reply_markup=M(kb) if kb else None, disable_web_page_preview=True)
                return
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return
            except Exception:
                log.exception("edit failed")
        await self.send(text, kb, protect)


async def notify(bot, tg_id, text, kb=None, protect=False):
    try:
        await bot.send_message(tg_id, text, parse_mode=HTML, reply_markup=M(kb) if kb else None,
                               disable_web_page_preview=True, protect_content=protect)
        return True
    except Exception as e:
        log.warning("notify failed: %s", type(e).__name__)  # شناسه کاربر عمداً لاگ نمی‌شود
        return False


async def notify_admins(bot, text, kb=None, skip_tg=None):
    for t in db.admin_tg_ids():
        if t != skip_tg:
            await notify(bot, t, text, kb)


async def notify_perm(bot, perm, text, kb=None, skip_tg=None, protect=True):
    """به همه افراد فعال دارای دسترسی «perm» (و روشن بودن دریافت اعلان) پیام می‌دهد."""
    n = 0
    for s in db.q("SELECT * FROM staff WHERE active=1 AND tg_id IS NOT NULL"):
        if s["tg_id"] == skip_tg:
            continue
        p = db.perms_of(s)
        if perm in p and "dig_recv" in p and await notify(bot, s["tg_id"], text, kb, protect):
            n += 1
    return n


_bg_tasks: set = set()


def bg(coro):
    """اجرای کار طولانی در پس‌زمینه تا ربات برای بقیه پاسخگو بماند."""
    t = asyncio.get_running_loop().create_task(coro)
    _bg_tasks.add(t)

    def _done(x):
        _bg_tasks.discard(x)
        if not x.cancelled() and x.exception():
            log.error("background task failed", exc_info=x.exception())
    t.add_done_callback(_done)
    return t


async def wait_bg():
    while _bg_tasks:
        await asyncio.gather(*list(_bg_tasks), return_exceptions=True)


async def goto(ctx: Ctx, cb: str):
    parts = cb.split(":")
    ent = ROUTES.get(":".join(parts[:2]))
    if ent and ctx.allowed(ent[1]):
        ctx.route = ":".join(parts[:2])
        await ent[0](ctx, *parts[2:])
    else:
        await show_main(ctx)


# ───────────────────────────── فرم‌های چندمرحله‌ای ─────────────────────────────
def p_text(t):
    t = (t or "").strip()
    if not t:
        raise ValueError("متن خالی است.")
    return t


def p_date(t):
    return jdate.parse_date(t)


def p_time(t):
    return jdate.parse_time(t)


def p_time_or_clear(t):
    return None if jdate.norm(t) in ("-", "—") else jdate.parse_time(t)


def p_amount(t):
    s = jdate.norm(t).replace(",", "").replace(" ", "")
    for w in ("تومان", "ریال"):
        s = s.replace(w, "")
    if not s.isdigit() or int(s) <= 0:
        raise ValueError("مبلغ را فقط با عدد بنویسید (مثال: 5000000).")
    return int(s)


def p_int(t):
    s = jdate.norm(t)
    if not s.lstrip("-").isdigit():
        raise ValueError("فقط عدد وارد کنید.")
    return int(s)


def p_phone(t):
    s = jdate.norm(t).replace(" ", "").replace("-", "")
    if not s.isdigit() or len(s) < 8:
        raise ValueError("شماره تلفن معتبر نیست.")
    return s


@dataclass
class Step:
    key: str
    prompt: Any                      # str یا تابع(data)->str
    parse: Callable = p_text
    choices: Any = None              # لیست (برچسب، مقدار) یا تابع(data)->لیست
    optional: bool = False
    kind: str = "text"               # text | date (تقویم شمسی) | time (ساعت‌یاب)
    when: Optional[Callable] = None  # تابع(data)->bool؛ اگر False باشد این مرحله رد می‌شود
    secret: bool = False             # پیام کاربر بعد از دریافت پاک شود (رمز عبور و …)


FLOWS: dict = {}
DATE_CHOICES = [("📅 امروز", "today"), ("دیروز", "yest")]  # سازگاری با کدهای قدیمی

_FA_DIG = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(n) -> str:
    return str(n).translate(_FA_DIG)


def define_flow(name, steps, finish, back="m:main"):
    FLOWS[name] = (steps, finish, back)


def _active(f, i) -> bool:
    st = FLOWS[f["name"]][0][i]
    if st.key in f["pre"]:
        return False
    if not st.when:
        return True
    try:
        return bool(st.when(f["data"]))
    except KeyError:   # شرط به پاسخ مرحله‌ای وابسته است که هنوز داده نشده (مثلاً برای شمارندهٔ مراحل)
        return True


def _next_i(f, frm) -> int:
    n = len(FLOWS[f["name"]][0])
    i = frm
    while i < n and not _active(f, i):
        i += 1
    return i


def _prev_i(f) -> int:
    i = f["i"] - 1
    while i >= 0 and not _active(f, i):
        i -= 1
    return i


def _cal_rows(y, m):
    first = date.fromisoformat(jdate.from_j(y, m, 1))
    lead = (first.weekday() + 2) % 7          # شنبه = ۰
    n = jdate.month_days(y, m)
    cells = [None] * lead + list(range(1, n + 1))
    cells += [None] * (-len(cells) % 7)
    ty, tm, td = jdate.j_today()
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    ny, nm = (y, m + 1) if m < 12 else (y + 1, 1)
    rows = [[B("◀️ ماه قبل", callback_data=f"f:cal:{py}:{pm}"),
             B(f"{jdate.MONTHS[m - 1]} {fa(y)}", callback_data="noop:x"),
             B("ماه بعد ▶️", callback_data=f"f:cal:{ny}:{nm}")],
            [B(x, callback_data="noop:x") for x in ["ج", "پ", "چ", "س", "د", "ی", "ش"]]]   # شنبه سمت راست
    for i in range(0, len(cells), 7):
        week = cells[i:i + 7][::-1]
        rows.append([B((("•" if (y, m, d) == (ty, tm, td) else "") + fa(d)), callback_data=f"f:d:{y}:{m}:{d}") if d
                     else B(" ", callback_data="noop:x") for d in week])
    rows.append([B("📍 امروز", callback_data=f"f:d:{ty}:{tm}:{td}")])
    return rows


def _time_rows(f):
    h = f.get("hour")
    if h is None:
        return grid([B(fa(f"{i:02d}"), callback_data=f"f:th:{i}") for i in range(24)], 6)
    rows = grid([B(fa(f"{h:02d}:{mm:02d}"), callback_data=f"f:tm:{mm}") for mm in range(0, 60, 5)], 4)
    rows.append([B("⬅️ تغییر ساعت", callback_data="f:thx")])
    return rows


def _flow_rows(f):
    steps, _, _ = FLOWS[f["name"]]
    st = steps[f["i"]]
    rows = []
    if st.kind == "date":
        y, m = f.get("cal") or jdate.j_today()[:2]
        rows += _cal_rows(y, m)
        f["choices"], f["labels"] = None, None
    elif st.kind == "time":
        rows += _time_rows(f)
        f["choices"], f["labels"] = None, None
    else:
        ch = st.choices(f["data"]) if callable(st.choices) else st.choices
        f["choices"] = [v for _, v in ch] if ch else None
        f["labels"] = [lb for lb, _ in ch] if ch else None
        rows += grid([B(lb, callback_data=f"f:v:{i}") for i, (lb, _) in enumerate(ch or [])], 2)
    ctl = []
    if _prev_i(f) >= 0:
        ctl.append(B("↩️ قبلی", callback_data="f:back"))
    if st.optional:
        ctl.append(B("⏭ رد کردن", callback_data="f:skip"))
    ctl.append(B("❌ لغو", callback_data="f:cancel"))
    rows.append(ctl)
    return rows


async def start_flow(ctx: Ctx, name: str, data: dict = None):
    ctx.ud.pop("attach", None)
    f = {"name": name, "i": 0, "data": dict(data or {}), "choices": None, "labels": None,
         "pre": set((data or {}).keys()), "cal": None, "hour": None}
    ctx.ud["flow"] = f
    f["i"] = _next_i(f, 0)
    steps, finish, _ = FLOWS[name]
    if f["i"] >= len(steps):
        ctx.ud.pop("flow", None)
        return await finish(ctx, f["data"])
    await _ask(ctx)


async def _ask(ctx: Ctx):
    f = ctx.ud["flow"]
    steps, _, _ = FLOWS[f["name"]]
    st = steps[f["i"]]
    rows = _flow_rows(f)
    act = [i for i in range(len(steps)) if _active(f, i)]
    n = f"<i>({fa(act.index(f['i']) + 1)}/{fa(len(act))})</i> " if len(act) > 1 and f["i"] in act else ""
    prompt = st.prompt(f["data"]) if callable(st.prompt) else st.prompt
    await ctx.send(n + prompt, rows)


async def _advance(ctx: Ctx, value):
    f = ctx.ud["flow"]
    steps, finish, _ = FLOWS[f["name"]]
    f["data"][steps[f["i"]].key] = value
    f["hour"] = f["cal"] = None
    f["i"] = _next_i(f, f["i"] + 1)
    if f["i"] >= len(steps):
        data = f["data"]
        ctx.ud.pop("flow", None)
        await finish(ctx, data)
    else:
        await _ask(ctx)


def _err_text(e) -> str:
    m = str(e)
    return m if any("؀" <= ch <= "ۿ" for ch in m) else "ورودی نامعتبر است."


async def flow_text(ctx: Ctx, text: str):
    f = ctx.ud["flow"]
    st = FLOWS[f["name"]][0][f["i"]]
    try:
        val = st.parse(text)
    except ValueError as e:
        if st.secret:
            await _delete_user_msg(ctx)
        await ctx.send(f"⚠️ {esc(_err_text(e))}\nدوباره وارد کنید یا از دکمه‌ها استفاده کنید.")
        return
    if st.secret:
        await _delete_user_msg(ctx)
    await _advance(ctx, val)


async def _delete_user_msg(ctx: Ctx):
    try:
        await ctx.update.effective_message.delete()
    except Exception:
        pass


async def _strip_kb(ctx: Ctx):
    if ctx.q:
        try:
            await ctx.q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


async def _mark_chosen(ctx: Ctx, label):
    """پیام سؤال را با گزینهٔ انتخاب‌شده جایگزین می‌کند تا تاریخچهٔ چت خوانا بماند."""
    if not ctx.q:
        return
    try:
        old = ctx.q.message.text_html or ""
        lab = str(label)
        lab = lab if len(lab) <= 60 else lab[:59] + "…"
        await ctx.q.edit_message_text(f"{old}\n✅ <b>{esc(lab)}</b>", parse_mode=HTML)
    except Exception:
        await _strip_kb(ctx)


async def _edit_kb(ctx: Ctx, f):
    if not ctx.q:
        return
    try:
        await ctx.q.edit_message_reply_markup(reply_markup=M(_flow_rows(f)))
    except Exception:
        pass


async def flow_callback(ctx: Ctx, action: str, *args):
    f = ctx.ud.get("flow")
    if action == "cancel":
        back = FLOWS[f["name"]][2] if f else "m:main"
        ctx.ud.pop("flow", None)
        ctx.ud.pop("attach", None)
        ctx.ud.pop("import", None)
        await ctx.answer("لغو شد")
        await _strip_kb(ctx)
        await goto(ctx, back)
        return
    if action == "attach_done":
        a = ctx.ud.pop("attach", None)
        await ctx.answer("ذخیره شد ✅")
        await goto(ctx, a["back"] if a else "m:main")
        return
    if not f:
        await ctx.answer("این مرحله منقضی شده است.", True)
        return
    steps, _, _ = FLOWS[f["name"]]
    st = steps[f["i"]]
    if action == "skip":
        if not st.optional:
            await ctx.answer("این مرحله اجباری است.", True)
            return
        await ctx.answer()
        await _mark_chosen(ctx, "رد شد")
        await _advance(ctx, None)
        return
    if action == "back":
        j = _prev_i(f)
        if j < 0:
            return await ctx.answer("مرحلهٔ قبلی وجود ندارد.")
        await ctx.answer()
        await _strip_kb(ctx)
        f["i"], f["hour"], f["cal"] = j, None, None
        f["data"].pop(steps[j].key, None)
        return await _ask(ctx)
    if action == "cal" and st.kind == "date":
        f["cal"] = (int(args[0]), int(args[1]))
        return await _edit_kb(ctx, f)
    if action in ("th", "thx", "tm") and st.kind == "time":
        if action == "th":
            f["hour"] = int(args[0])
            return await _edit_kb(ctx, f)
        if action == "thx":
            f["hour"] = None
            return await _edit_kb(ctx, f)
        if f.get("hour") is None:
            return await ctx.answer("ابتدا ساعت را انتخاب کنید.")
        val = f"{f['hour']:02d}:{int(args[0]):02d}"
        await ctx.answer()
        await _mark_chosen(ctx, fa(val))
        try:
            parsed = st.parse(val)
        except ValueError as e:
            await ctx.send(f"⚠️ {esc(_err_text(e))}")
            return
        return await _advance(ctx, parsed)
    if action == "d" and st.kind == "date":
        try:
            iso = jdate.from_j(int(args[0]), int(args[1]), int(args[2]))
            parsed = st.parse(iso)
        except ValueError as e:
            await ctx.answer("تاریخ نامعتبر", True)
            return
        await ctx.answer()
        await _mark_chosen(ctx, jdate.fmt_long(iso))
        return await _advance(ctx, parsed)
    if action == "v":
        idx = int(args[0])
        choices = f.get("choices") or []
        if idx >= len(choices):
            await ctx.answer("گزینه نامعتبر")
            return
        await ctx.answer()
        await _mark_chosen(ctx, (f.get("labels") or [""] * (idx + 1))[idx])
        try:
            val = st.parse(str(choices[idx]))
        except ValueError as e:
            await ctx.send(f"⚠️ {esc(_err_text(e))}")
            return
        await _advance(ctx, val)


# ───────────────────────────── پیوست فایل (رمزنگاری‌شده روی سرور) ─────────────────────────────
EXT = {"photo": "jpg", "video": "mp4", "voice": "ogg", "audio": "mp3", "video_note": "mp4", "animation": "mp4"}
ICON = {"photo": "🖼", "video": "🎞", "voice": "🎙", "audio": "🎵", "video_note": "🎞", "animation": "🎞", "document": "📄"}
KIND_VIEW = {"incident": ("inc_write", "inc_manage"), "event": ("evt_view", "evt_manage"),
             "client": ("cli_view", "cli_manage"), "report": ("rep_view", "rep_write"), "cnote": ("cli_view", "cli_manage")}
KIND_MANAGE = {"incident": ("inc_manage",), "event": ("evt_manage",), "client": ("cli_manage",),
               "report": ("rep_view",), "cnote": ("cli_manage",)}
KIND_BACK = {"incident": "inc:v:{}", "event": "evt:v:{}", "client": "cli:v:{}", "report": "rep:menu", "cnote": "cli:v:{}"}


def media_of(m):
    for attr in ("photo", "video", "document", "audio", "voice", "video_note", "animation"):
        v = getattr(m, attr, None)
        if v:
            return attr, (v[-1] if attr == "photo" else v)
    return None, None


async def save_attachment(ctx: Ctx, kind: str, ref_id: int, m=None) -> bool:
    m = m or ctx.update.effective_message
    ftype, obj = media_of(m)
    if not obj:
        return False
    size = getattr(obj, "file_size", 0) or 0
    name = getattr(obj, "file_name", None) or f"{ftype}_{int(time.time())}.{EXT.get(ftype, 'bin')}"
    mime = getattr(obj, "mime_type", None)
    path = None
    if size <= config.MAX_LOCAL_FILE:
        tgf = await obj.get_file()
        data = bytes(await tgf.download_as_bytearray())
        fn = secrets.token_hex(16) + ".enc"
        (config.FILES_DIR / fn).write_bytes(crypto.enc_bytes(data))
        path = fn
        size = len(data)
    db.run("INSERT INTO attachments(kind,ref_id,filename,mime,ftype,path,tg_file_id,size,caption,uploaded_by)"
           " VALUES(?,?,?,?,?,?,?,?,?,?)",
           (kind, ref_id, name, mime, ftype, path, None if path else obj.file_id, size, m.caption, ctx.me["id"]))
    return True


async def start_attach(ctx: Ctx, kind: str, ref_id: int, back: str, intro: str = None):
    ctx.ud.pop("flow", None)
    msg = await ctx.send(
        (intro or "📎 فایل، عکس، ویدئو، صدا یا سند را بفرستید. می‌توانید چند فایل پشت سر هم بفرستید.")
        + "\nدر پایان دکمه «✅ پایان» را بزنید.",
        [[B("✅ پایان", callback_data="f:attach_done")], [B("❌ لغو", callback_data="f:cancel")]])
    ctx.ud["attach"] = {"kind": kind, "ref": ref_id, "n": 0, "back": back, "msg": msg.message_id}


async def attach_incoming(ctx: Ctx):
    a = ctx.ud["attach"]
    ok = await save_attachment(ctx, a["kind"], a["ref"])
    if not ok:
        await ctx.send("⚠️ این نوع پیام فایل نیست. فایل/عکس/ویدئو بفرستید.")
        return
    a["n"] += 1
    ctx.audit("attach", f"{a['kind']}:{a['ref']}")
    try:
        await ctx.bot.edit_message_text(
            f"✅ {a['n']} فایل ذخیره شد. فایل بعدی را بفرستید یا پایان را بزنید.",
            chat_id=ctx.update.effective_chat.id, message_id=a["msg"],
            reply_markup=M([[B("✅ پایان", callback_data="f:attach_done")]]))
    except Exception:
        pass


async def send_attachment(ctx: Ctx, att):
    chat = ctx.update.effective_chat
    cap = att["caption"] or None
    if att["path"]:
        p = config.FILES_DIR / att["path"]
        if not p.exists():
            await ctx.send("⚠️ فایل روی سرور پیدا نشد.")
            return
        bio = io.BytesIO(crypto.dec_bytes(p.read_bytes()))
        bio.name = att["filename"] or "file"
        src = bio
    else:
        src = att["tg_file_id"]
    ft = att["ftype"]
    kw = {"caption": cap, "protect_content": True}
    if ft == "photo":
        await chat.send_photo(src, **kw)
    elif ft == "video":
        await chat.send_video(src, **kw)
    elif ft == "voice":
        await chat.send_voice(src, **kw)
    elif ft == "audio":
        await chat.send_audio(src, **kw)
    elif ft == "video_note":
        await chat.send_video_note(src, protect_content=True)
    elif ft == "animation":
        await chat.send_animation(src, **kw)
    else:
        await chat.send_document(src, **kw)


def attachments(kind, ref_id):
    return db.q("SELECT * FROM attachments WHERE kind=? AND ref_id=? ORDER BY id", (kind, ref_id))


@route("at:list")
async def at_list(ctx: Ctx, kind, ref):
    if not ctx.can(*KIND_VIEW.get(kind, ())):
        return await ctx.answer("⛔ دسترسی ندارید", True)
    rows = attachments(kind, int(ref))
    back = KIND_BACK[kind].format(ref)
    if not rows:
        await ctx.answer("فایلی ثبت نشده.", True)
        return
    kb = [[B(f"{ICON.get(r['ftype'], '📄')} {(r['filename'] or 'فایل')[:40]}", callback_data=f"at:get:{r['id']}")] for r in rows]
    kb.append(back_row(back))
    await ctx.show(f"📎 <b>فایل‌ها</b> ({len(rows)})\nروی هر فایل بزنید تا ارسال شود:", kb)


@route("at:get")
async def at_get(ctx: Ctx, aid):
    att = db.one("SELECT * FROM attachments WHERE id=?", (int(aid),))
    if not att or not ctx.can(*KIND_VIEW.get(att["kind"], ())):
        return await ctx.answer("⛔ دسترسی ندارید", True)
    await ctx.answer("در حال ارسال…")
    ctx.audit("file_view", f"{att['kind']}:{att['ref_id']}:{att['id']}")
    kb = [[B("🗑 حذف این فایل", callback_data=f"at:del:{aid}")]] if ctx.can(*KIND_MANAGE.get(att["kind"], ())) else None
    await send_attachment(ctx, att)
    if kb:
        await ctx.send("⬆️ فایل بالا", kb)


@route("at:del")
async def at_del(ctx: Ctx, aid):
    att = db.one("SELECT * FROM attachments WHERE id=?", (int(aid),))
    if not att or not ctx.can(*KIND_MANAGE.get(att["kind"], ())):
        return await ctx.answer("⛔ دسترسی ندارید", True)
    await ctx.show(f"⚠️ فایل «{esc(att['filename'])}» برای همیشه حذف شود؟",
                   [[B("✅ بله، حذف", callback_data=f"at:del2:{aid}"), B("خیر", callback_data="m:main")]])


@route("at:del2")
async def at_del2(ctx: Ctx, aid):
    att = db.one("SELECT * FROM attachments WHERE id=?", (int(aid),))
    if not att or not ctx.can(*KIND_MANAGE.get(att["kind"], ())):
        return await ctx.answer("⛔ دسترسی ندارید", True)
    if att["path"]:
        try:
            (config.FILES_DIR / att["path"]).unlink()
        except OSError:
            pass
    db.run("DELETE FROM attachments WHERE id=?", (att["id"],))
    ctx.audit("file_delete", f"{att['kind']}:{att['ref_id']}:{att['filename']}")
    await ctx.answer("حذف شد")
    await goto(ctx, KIND_BACK[att["kind"]].format(att["ref_id"]))


def delete_attachments(kind, ref_id):
    for a in attachments(kind, ref_id):
        if a["path"]:
            try:
                (config.FILES_DIR / a["path"]).unlink()
            except OSError:
                pass
    db.run("DELETE FROM attachments WHERE kind=? AND ref_id=?", (kind, ref_id))


# ───────────────────────────── منوی اصلی ─────────────────────────────
@route("noop:x")
async def noop(ctx: Ctx, *a):
    await ctx.answer()


@route("m:main")
async def show_main(ctx: Ctx, *a):
    c = ctx.can
    rows = []

    def add(*items):
        r = [B(t, callback_data=d) for t, d, ok in items if ok]
        if r:
            rows.append(r)

    add(("📋 حضور و غیاب", "rc:day", c("att_manage")), ("🕘 ورود و خروج من", "att:menu", c("att_self", "att_view_self")))
    add(("📝 گزارش روزانه", "rep:menu", c("rep_write", "rep_view")), ("📌 وظایف روزانه", "tk:menu", c("task_self", "task_manage")))
    add(("📋 امور و اتفاقات", "inc:menu", c("inc_write", "inc_manage")), ("📅 رویدادهای مهم", "evt:menu", c("evt_view", "evt_manage")))
    add(("🧒 مددجویان", "cli:menu", c("cli_view", "cli_manage")), ("📷 دوربین‌ها", "cam:menu", c("cam_view", "cam_clip", "cam_manage")))
    add(("💰 وام و واریزی", "loan:menu", c("loan_self", "loan_manage")), ("🏖 مرخصی", "lv:menu", c("leave_self", "leave_manage")))
    add(("📲 پیامک", "sms:menu", c("sms_send", "sms_manage")), ("📢 پیام همگانی", "bc:menu", c("broadcast")))
    add(("📊 خروجی اکسل", "exp:menu", c("export")), ("👥 پرسنل و دسترسی", "st:menu", ctx.is_admin))
    add(("⚙️ سیستم", "sys:menu", ctx.is_admin), ("👤 پروفایل من", "me:menu", True))
    add(("❓ راهنما", "help:menu", True), ("🏥 درباره ما", "about:menu", True))
    if ctx.is_admin and not ctx.me["title_id"]:
        rows.insert(0, [B("🏷 ثبت عنوان شغلی من", callback_data="me:title")])
    t = jdate.today()
    top = digest.build(ctx.me, ctx.perms, ctx.is_admin, "top")
    await ctx.show(
        f"🏥 <b>{esc(config.CENTER_NAME)}</b>\n"
        f"👤 {esc(ctx.me['name'])} — <i>{esc(db.title_label(ctx.me))}</i>\n"
        f"📅 {jdate.fmt_long(t)}  🕐 {jdate.hhmm()}\n\n"
        + (top if top else "✨ امروز مورد فوری یا معوقی ندارید.") + "\n\nیکی از گزینه‌ها را انتخاب کنید:", rows)


@route("about:menu")
async def about_menu(ctx: Ctx):
    await ctx.show(texts.about(), [back_row()], protect=True)


@route("help:menu")
async def help_menu(ctx: Ctx):
    await ctx.show(
        "❓ <b>راهنمای سریع</b>\n\n"
        "• همه کارها با دکمه است؛ تاریخ را از تقویم و ساعت را از دکمه‌ها انتخاب کنید.\n"
        "• هر جا لازم باشد ربات فقط همان یک اطلاعات را می‌پرسد؛ «↩️ قبلی» یک مرحله برمی‌گردد و «❌ لغو» انصراف است.\n"
        "• بالای منوی اصلی، اتفاقات مهم، وظایف و گزارش‌های امروز نشان داده می‌شود.\n"
        "• اطلاعات مددجویان محرمانه است و قابل فوروارد نیست.\n"
        "• اگر چیزی کار نکرد /start را بزنید.", [back_row()])


# ───────────────────────────── ورودی‌های اصلی ─────────────────────────────
_fail: dict = {}      # tg_id -> (تعداد تلاش ناموفق، زمان آخرین)
_global_fail: list = []   # زمان همه تلاش‌های ناموفق (برای قفل سراسری)
_lock_alerted = [0.0]


def _blocked(tg_id) -> bool:
    n, ts = _fail.get(tg_id, (0, 0))
    if time.time() - ts >= 900:
        _fail.pop(tg_id, None)
        return False
    return n >= 5


def _global_locked() -> bool:
    now = time.time()
    _global_fail[:] = [t for t in _global_fail if now - t < 600]
    return len(_global_fail) >= 20


async def _register_failure(u, context):
    n, _ = _fail.get(u.id, (0, 0))
    _fail[u.id] = (n + 1, time.time())
    _global_fail.append(time.time())
    db.audit(u.id, "invite_fail", f"n={n + 1}")
    if n + 1 == 3:
        who = f"@{u.username}" if getattr(u, "username", None) else esc(getattr(u, "full_name", "") or "")
        await notify_admins(context.bot, f"⚠️ <b>تلاش ناموفق مکرر برای ورود</b>\nشناسه تلگرام: <code>{u.id}</code> {who}\n"
                            "اگر این فرد را نمی‌شناسید، کدهای دعوت فعال را از «👥 پرسنل» لغو کنید.")


async def _unregistered(update, context):
    """کاربر ناشناس: فقط با کد دعوت اختصاصی می‌تواند وصل شود؛ در غیر این‌صورت فقط متن خوش‌آمد عمومی را می‌بیند."""
    u = update.effective_user
    m = update.effective_message
    text = (m.text or "").strip() if m else ""
    if text.startswith("/start"):
        text = text[6:].strip()
    code = invite.normalize(text) if text and not text.startswith("/") else ""
    if len(code) != invite.LEN:
        # چیزی شبیه کد نیست ← فقط خوش‌آمد عمومی (بدون هیچ اطلاعات یا تلاش شمرده‌شده)
        return await m.reply_text(texts.welcome_public(u.id), parse_mode=HTML)
    if _blocked(u.id):
        return await m.reply_text("⛔ تعداد تلاش‌ها زیاد بود. حدود ۱۵ دقیقه بعد دوباره امتحان کنید یا با مدیر تماس بگیرید.")
    if _global_locked():
        if time.time() - _lock_alerted[0] > 600:
            _lock_alerted[0] = time.time()
            await notify_admins(context.bot, "🚨 <b>تلاش‌های ناموفق ورود زیاد بود</b>؛ ثبت‌نام با کد دعوت ۱۰ دقیقه به‌طور موقت متوقف شد.")
        return await m.reply_text("⛔ ثبت‌نام موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید.")
    r = db.one("SELECT * FROM staff WHERE invite_code=? AND active=1 AND tg_id IS NULL", (invite.digest(code),))
    if r and r["invite_exp"] and not invite.expired(r["invite_exp"]):
        db.run("UPDATE staff SET tg_id=?, invite_code=NULL, invite_exp=NULL WHERE id=?", (u.id, r["id"]))
        _fail.pop(u.id, None)
        db.audit(u.id, "invite_used", r["name"])
        try:
            await m.delete()  # پیام حاوی کد از چت پاک شود
        except Exception:
            pass
        await m.chat.send_message(texts.welcome_staff(esc(r["name"])), parse_mode=HTML)
        who = f"@{u.username}" if getattr(u, "username", None) else esc(getattr(u, "full_name", "") or "—")
        await notify_admins(context.bot, f"🔗 «{esc(r['name'])}» با حساب تلگرام {who} (<code>{u.id}</code>) به ربات متصل شد.\n"
                            "اگر این فرد نیست، همین الان جدایش کنید:", [[B("🔌 جدا کردن", callback_data=f"st:unb:{r['id']}")]])
        return
    await _register_failure(u, context)
    await m.reply_text("⛔ کد نامعتبر، مصرف‌شده یا منقضی است. از مدیر کد جدید بخواهید.")


def load_me(update):
    me = db.staff_by_tg(update.effective_user.id)
    if me and me["name"].startswith("⏳"):
        nm = (getattr(update.effective_user, "full_name", "") or "").strip()
        if nm:
            db.run("UPDATE staff SET name=? WHERE id=?", (nm, me["id"]))
            me = db.staff_by_tg(update.effective_user.id)
    return me


async def on_callback(update, context):
    q = update.callback_query
    me = load_me(update)
    if not me or not me["active"]:
        return await q.answer("⛔ دسترسی ندارید", show_alert=True)
    ctx = Ctx(update, context, me)
    data = q.data or ""
    try:
        if data.startswith("f:"):
            parts = data.split(":")
            await flow_callback(ctx, parts[1], *parts[2:])
        else:
            parts = data.split(":")
            ent = ROUTES.get(":".join(parts[:2]))
            if not ent:
                return await q.answer("گزینه نامعتبر")
            fn, perm = ent
            if not ctx.allowed(perm):
                return await q.answer("⛔ به این بخش دسترسی ندارید", show_alert=True)
            ctx.route = ":".join(parts[:2])
            if parts[0] not in ("noop", "at") and ":".join(parts[:2]) != "cli:impok":
                for k in ("flow", "attach", "import"):
                    ctx.ud.pop(k, None)
            await fn(ctx, *parts[2:])
    except Exception:
        log.exception("callback error: %s", data)
        await ctx.answer("⚠️ خطا رخ داد", True)
        await ctx.send("⚠️ خطایی رخ داد. دوباره تلاش کنید.", [back_row()])
    finally:
        await ctx.answer()


async def on_message(update, context):
    m = update.effective_message
    me = load_me(update)
    if not me or not me["active"]:
        return await _unregistered(update, context)
    ctx = Ctx(update, context, me)
    try:
        if "flow" in ctx.ud and m.text:
            return await flow_text(ctx, m.text)
        if "attach" in ctx.ud:
            return await attach_incoming(ctx)
        if "import" in ctx.ud and media_of(m)[0] == "document":
            return await HOOKS["import"](ctx)
        await show_main(ctx)
    except Exception:
        log.exception("message error")
        await ctx.send("⚠️ خطایی رخ داد. دوباره تلاش کنید.", [back_row()])


async def cmd_start(update, context):
    me = load_me(update)
    if not me or not me["active"]:
        return await _unregistered(update, context)
    ctx = Ctx(update, context, me)
    for k in ("flow", "attach", "import"):
        ctx.ud.pop(k, None)
    await show_main(ctx)


async def cmd_cancel(update, context):
    context.user_data.clear()
    await cmd_start(update, context)


async def cmd_myid(update, context):
    await update.effective_message.reply_text(f"شناسه تلگرام شما: {update.effective_user.id}")


async def on_error(update, context):
    log.error("unhandled error", exc_info=context.error)
