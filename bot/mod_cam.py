"""دوربین‌ها: لینک، عکس لحظه‌ای، ویدیوی بازهٔ دقیق از حافظهٔ دوربین، فهرست ویدیوهای ذخیره‌شده."""
import io
import os
from pathlib import Path

from telegram import InlineKeyboardButton as B

from . import cam, crypto, db, jdate
from .core import (Ctx, Step, back_row, bg, define_flow, esc, fa, goto, grid, notify, p_date, p_text, route, start_flow)

NOTE = ("ℹ️ دوربین باید از اینترنت (یا VPN) برای ربات قابل دسترس باشد. "
        "ویدیوی ضبط‌شده معمولاً با سرعت واقعی خوانده می‌شود؛ کلیپ ۱۰ دقیقه‌ای حدود ۱۰ دقیقه طول می‌کشد.")


def _cfg(r):
    c = cam.load_cfg(r)
    c.setdefault("brand", r["brand"] or "link")
    return c


@route("cam:menu", perm=("cam_view", "cam_clip", "cam_manage"))
async def cam_menu(ctx: Ctx):
    rows = db.q("SELECT * FROM cameras ORDER BY name")
    kb = grid([B(f"📷 {r['name']}", callback_data=f"cam:v:{r['id']}") for r in rows])
    if ctx.can("cam_manage"):
        kb.append([B("➕ افزودن دوربین", callback_data="cam:add")])
    kb.append(back_row())
    await ctx.show(f"📷 <b>دوربین‌ها</b> ({fa(len(rows))})" + ("" if rows else "\nهنوز دوربینی ثبت نشده."), kb)


@route("cam:v", perm=("cam_view", "cam_clip", "cam_manage"))
async def cam_view(ctx: Ctx, cid):
    r = db.one("SELECT * FROM cameras WHERE id=?", (int(cid),))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    c = _cfg(r)
    url = crypto.dec(r["url"]) if r["url"] else ""
    kb = []
    if url.lower().startswith(("http://", "https://")) and ctx.can("cam_view"):
        kb.append([B("🔗 پخش زنده", url=url)])
    if c["brand"] != "link" and ctx.can("cam_clip"):
        kb.append([B("📸 عکس همین الان", callback_data=f"cam:snap:{cid}"), B("🎞 ویدیوی یک بازه", callback_data=f"cam:clip:{cid}")])
        kb.append([B("🗂 ویدیوهای ذخیره‌شده", callback_data=f"cam:cls:{cid}")])
    if ctx.can("cam_manage"):
        kb.append([B("🧪 آزمایش اتصال", callback_data=f"cam:snap:{cid}"), B("🗑 حذف", callback_data=f"cam:del:{cid}")])
    kb.append(back_row("cam:menu"))
    ctx.audit("camera_view", r["name"])
    txt = f"📷 <b>{esc(r['name'])}</b> — {esc(r['location'] or '—')}\nنوع: {cam.BRANDS.get(c['brand'], '—')}"
    if c["brand"] != "link":
        txt += "\n\n" + NOTE
    await ctx.show(txt, kb, protect=True)


@route("cam:snap", perm=("cam_clip", "cam_manage"))
async def cam_snap(ctx: Ctx, cid):
    r = db.one("SELECT * FROM cameras WHERE id=?", (int(cid),))
    if not r:
        return await ctx.answer("پیدا نشد", True)
    await ctx.answer("در حال اتصال به دوربین…")
    ok, res = await cam.snapshot(_cfg(r))
    if ok:
        bio = io.BytesIO(res)
        bio.name = "snap.jpg"
        await ctx.update.effective_chat.send_photo(bio, caption=f"📸 {r['name']} — {jdate.hhmm()}", protect_content=True)
        ctx.audit("camera_snap", r["name"])
    else:
        await ctx.send(f"❌ اتصال برقرار نشد.\n<code>{esc(res)}</code>\nنشانی/پورت/کاربر/رمز و دسترسی اینترنتی دوربین را بررسی کنید.",
                       [back_row(f"cam:v:{cid}")])


# ───────────── ویدیوی بازه ─────────────
@route("cam:clip", perm="cam_clip")
async def cam_clip(ctx: Ctx, cid):
    await start_flow(ctx, "cam_clip", {"cid": int(cid)})


async def _clip_done(ctx: Ctx, d):
    r = db.one("SELECT * FROM cameras WHERE id=?", (d["cid"],))
    s = cam.to_utc(d["day"], d["tm"])
    mins = int(d["dur"])
    await ctx.send(f"⏳ دریافت ویدیوی {esc(r['name'])} ({jdate.fmt(d['day'])} {d['tm']}، {fa(mins)} دقیقه) شروع شد. "
                   "پس از آماده شدن همین‌جا ارسال می‌شود.", [back_row(f"cam:v:{d['cid']}")])
    ctx.audit("camera_clip", f"{r['name']} {d['day']} {d['tm']} {mins}m")
    bg(_clip_job(ctx.bot, ctx.tg_id, ctx.me["id"], r, s, mins, int(d["q"]), d["day"], d["tm"]))


async def _clip_job(bot, tg_id, by, row, s_utc, mins, height, day, tm, src=None):
    ok, res = await cam.clip(_cfg(row), s_utc, mins, height, src)
    if not ok:
        return await notify(bot, tg_id, f"❌ ویدیو گرفته نشد.\n<code>{esc(res)}</code>")
    p = Path(res)
    try:
        with open(p, "rb") as f:
            m = await bot.send_video(tg_id, f, caption=f"🎞 {row['name']} — {jdate.fmt(day)} {tm} ({fa(mins)} دقیقه)",
                                     supports_streaming=True, protect_content=True)
        fid = m.video.file_id if getattr(m, "video", None) else None
        db.run("INSERT INTO clips(camera_id,cam_name,t_start,t_end,tg_file_id,size,requested_by) VALUES(?,?,?,?,?,?,?)",
               (row["id"], row["name"], f"{day} {tm}", f"{mins}m", fid, p.stat().st_size, by))
    except Exception as e:
        await notify(bot, tg_id, f"❌ ارسال ویدیو ناموفق بود ({type(e).__name__}).")
    finally:
        p.unlink(missing_ok=True)


define_flow("cam_clip", [
    Step("day", "📅 روز ویدیو:", p_date, kind="date"),
    Step("tm", "⏰ ساعت شروع:", lambda t: jdate.parse_time(t), kind="time"),
    Step("dur", "مدت ویدیو:", lambda t: t, [(f"{fa(m)} دقیقه", str(m)) for m in (1, 2, 5, 10, 15, 30)]),
    Step("q", "کیفیت (کیفیت کمتر = حجم کمتر):", lambda t: t, [("۴۸۰p", "480"), ("۳۶۰p (کم‌حجم)", "360")]),
], _clip_done, "cam:menu")


@route("cam:cls", perm="cam_clip")
async def cam_cls(ctx: Ctx, cid):
    rows = db.q("SELECT * FROM clips WHERE camera_id=? AND tg_file_id IS NOT NULL ORDER BY id DESC LIMIT 10", (int(cid),))
    kb = [[B(f"▶️ {c['t_start']} ({c['t_end']})", callback_data=f"cam:cl:{c['id']}")] for c in rows]
    kb.append(back_row(f"cam:v:{cid}"))
    await ctx.show("🗂 <b>ویدیوهای ذخیره‌شده</b> (۱۰ مورد اخیر)" + ("" if rows else "\nهنوز ویدیویی گرفته نشده."), kb)


@route("cam:cl", perm="cam_clip")
async def cam_cl(ctx: Ctx, clid):
    c = db.one("SELECT * FROM clips WHERE id=?", (int(clid),))
    if not c:
        return await ctx.answer("پیدا نشد", True)
    await ctx.update.effective_chat.send_video(c["tg_file_id"], caption=f"🎞 {c['cam_name']} — {c['t_start']}", protect_content=True)


# ───────────── افزودن/حذف ─────────────
@route("cam:add", perm="cam_manage")
async def cam_add(ctx: Ctx):
    await start_flow(ctx, "cam_add")


def _nl(d):
    return d["brand"] != "link"


async def _cam_done(ctx, d):
    b = d["brand"]
    cfg = {"brand": b}
    if b != "link":
        cfg.update(host=d["host"], port=d.get("port") or "554", user=d.get("user") or "", password=d.get("pw") or "",
                   channel=d.get("ch") or "1", tz=d.get("tz") or "utc", template=d.get("tpl") or "")
    cid = db.run("INSERT INTO cameras(name,location,url,note,brand,cfg) VALUES(?,?,?,?,?,?)",
                 (d["name"], d.get("loc"), crypto.enc(d.get("url") or ""), crypto.enc(""), b, crypto.enc_json(cfg)))
    ctx.audit("camera_add", d["name"])
    await goto(ctx, f"cam:v:{cid}")


define_flow("cam_add", [
    Step("name", "نام دوربین (مثلاً «حیاط»):"),
    Step("loc", "محل نصب (اختیاری):", p_text, optional=True),
    Step("brand", "نوع دوربین/دستگاه ضبط:", lambda t: t, [(v, k) for k, v in cam.BRANDS.items()]),
    Step("url", "لینک پخش زنده (اختیاری):", p_text, optional=True),
    Step("host", "نشانی دوربین/دستگاه (IP یا دامنه، قابل دسترس از اینترنت):", p_text, when=_nl),
    Step("port", "پورت RTSP (پیش‌فرض ۵۵۴):", lambda t: str(int(jdate.norm(t))), optional=True, when=_nl),
    Step("user", "نام کاربری:", p_text, when=_nl),
    Step("pw", "رمز (بعد از دریافت پاک می‌شود):", p_text, secret=True, when=_nl),
    Step("ch", "شمارهٔ کانال (پیش‌فرض ۱):", lambda t: str(int(jdate.norm(t))), optional=True, when=_nl),
    Step("tpl", "الگوی RTSP با {user} {password} {host} {port} {channel} {start} {end}:", p_text, when=lambda d: d["brand"] == "custom"),
    Step("tz", "ساعت دستگاه به چه وقتی تنظیم است؟", lambda t: t, [("UTC (معمول)", "utc"), ("وقت محلی", "local")], when=lambda d: d["brand"] in ("hikvision", "dahua")),
], _cam_done, "cam:menu")


@route("cam:del", perm="cam_manage")
async def cam_del(ctx: Ctx, cid):
    await ctx.show("⚠️ این دوربین حذف شود؟", [[B("✅ بله", callback_data=f"cam:del2:{cid}"), B("خیر", callback_data=f"cam:v:{cid}")]])


@route("cam:del2", perm="cam_manage")
async def cam_del2(ctx: Ctx, cid):
    db.run("DELETE FROM cameras WHERE id=?", (int(cid),))
    ctx.audit("camera_delete", cid)
    await cam_menu(ctx)
