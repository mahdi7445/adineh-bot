"""فهرست دسترسی‌ها (گروه‌بندی‌شده). برای هر «عنوان» و برای هر «فرد» جداگانه قابل روشن/خاموش است.
ادمین‌ها (دسترسی کامل) همه را دارند."""

GROUPS = [
    ("🕘 ورود و خروج", [
        ("att_view_self", "دیدن سوابق ورود/خروج خود"),
        ("att_self", "ثبت ورود/خروج توسط خود فرد"),
        ("att_manage", "حضور و غیاب و ساعات همه پرسنل"),
    ]),
    ("📝 گزارش و امور", [
        ("rep_write", "نوشتن گزارش روزانه"),
        ("rep_view", "دیدن گزارش همه پرسنل"),
        ("inc_write", "ثبت امور و اتفاقات"),
        ("inc_manage", "رسیدگی/حذف امور و اتفاقات"),
    ]),
    ("📌 وظایف", [
        ("task_self", "دیدن و انجام وظایف خود"),
        ("task_manage", "تعریف و پیگیری وظایف همه"),
    ]),
    ("📅 رویدادها", [
        ("evt_view", "دیدن رویدادها"),
        ("evt_manage", "ثبت/حذف رویداد"),
    ]),
    ("📷 دوربین", [
        ("cam_view", "دیدن فهرست و لینک دوربین‌ها"),
        ("cam_clip", "دریافت عکس و ویدیو از دوربین"),
        ("cam_manage", "افزودن/ویرایش دوربین"),
    ]),
    ("💰 مالی", [
        ("loan_self", "دیدن وام و واریزی خود"),
        ("loan_manage", "مدیریت وام و واریزی همه"),
    ]),
    ("🧒 مددجویان", [
        ("cli_view", "دیدن پرونده مددجویان"),
        ("cli_manage", "ثبت/ویرایش پرونده مددجویان"),
    ]),
    ("🏖 مرخصی", [
        ("leave_self", "درخواست مرخصی"),
        ("leave_manage", "تأیید/رد مرخصی"),
    ]),
    ("📲 ارتباطات", [
        ("broadcast", "پیام همگانی"),
        ("sms_send", "ارسال پیامک"),
        ("sms_manage", "تنظیمات پیامک، گروه‌ها و قالب‌ها"),
        ("dig_recv", "دریافت خلاصه روز و اعلان‌ها"),
    ]),
    ("📊 خروجی", [
        ("export", "خروجی اکسل"),
    ]),
]

PERMS = {k: lb for _, items in GROUPS for k, lb in items}

_BASIC = ["att_view_self", "task_self", "dig_recv", "leave_self", "loan_self"]

DEFAULT_TITLES = {
    "مددکار": _BASIC + ["rep_write", "inc_write", "evt_view", "cli_view", "cli_manage"],
    "کاردرمانگر / مربی": _BASIC + ["rep_write", "inc_write", "evt_view", "cli_view"],
    "پرستار": _BASIC + ["rep_write", "inc_write", "evt_view", "cli_view"],
    "نگهبان": _BASIC + ["rep_write", "inc_write", "evt_view", "cam_view"],
    "خدمات": _BASIC + ["inc_write"],
    "دفتردار / حسابدار": _BASIC + ["rep_write", "evt_view", "loan_manage", "export"],
}

# مهاجرت عناوین قدیمی: دسترسی‌های تازه به‌صورت خودکار اضافه می‌شوند
ADD_TO_ALL = ["task_self", "dig_recv"]
ADD_IF_HAS = {"att_self": ["att_view_self"], "att_manage": ["att_view_self"]}
