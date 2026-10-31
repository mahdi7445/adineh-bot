"""نقطه شروع ربات: python -m bot.main"""
import logging
import sys

from telegram import BotCommand, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from . import config, core, db, jobs
# ثبت ماژول‌ها (هر ماژول مسیرها و فرم‌های خودش را در core ثبت می‌کند)
from . import mod_att, mod_cam, mod_clients, mod_export, mod_money, mod_monthly, mod_ops, mod_sms, mod_staff, mod_tasks  # noqa: F401


def build_app() -> Application:
    app = Application.builder().token(config.BOT_TOKEN).build()
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", core.cmd_start, filters=private))
    app.add_handler(CommandHandler("menu", core.cmd_start, filters=private))
    app.add_handler(CommandHandler("cancel", core.cmd_cancel, filters=private))
    app.add_handler(CommandHandler("myid", core.cmd_myid, filters=private))
    app.add_handler(CallbackQueryHandler(core.on_callback))
    app.add_handler(MessageHandler(private & ~filters.COMMAND & ~filters.StatusUpdate.ALL, core.on_message))
    app.add_error_handler(core.on_error)
    jobs.schedule(app)

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start", "منوی اصلی"), BotCommand("cancel", "لغو عملیات جاری"), BotCommand("myid", "شناسه تلگرام من")])

    app.post_init = post_init
    return app


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    # توکن‌ها در لاگ HTTP دیده نشوند
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not config.BOT_TOKEN:
        sys.exit("BOT_TOKEN تنظیم نشده است.")
    if not config.ADMIN_IDS:
        sys.exit("ADMIN_IDS تنظیم نشده است (شناسه عددی تلگرام ادمین/ادمین‌ها).")
    db.conn()
    db.bootstrap_admins(config.ADMIN_IDS)
    build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)


if __name__ == "__main__":
    main()
