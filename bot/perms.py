"""فهرست دسترسی‌هایی که برای هر «عنوان» قابل تنظیم است. ادمین‌ها همه را دارند."""

PERMS = {
    "att_self": "ثبت ورود/خروج خود",
    "att_manage": "مدیریت ورود/خروج همه پرسنل",
    "rep_write": "نوشتن گزارش روزانه",
    "rep_view": "مشاهده گزارش همه پرسنل",
    "inc_write": "ثبت امور و اتفاقات",
    "inc_manage": "رسیدگی و حذف امور و اتفاقات",
    "evt_view": "مشاهده رویدادها",
    "evt_manage": "ثبت و حذف رویداد مهم",
    "cam_view": "مشاهده دوربین‌ها",
    "cam_manage": "مدیریت دوربین‌ها",
    "loan_self": "دیدن وام و واریزی خود",
    "loan_manage": "مدیریت وام و واریزی همه",
    "cli_view": "مشاهده پرونده مددجویان",
    "cli_manage": "ثبت و ویرایش پرونده مددجویان",
    "export": "خروجی اکسل",
    "leave_self": "درخواست مرخصی",
    "leave_manage": "تأیید/رد مرخصی",
    "broadcast": "پیام همگانی",
}

DEFAULT_TITLES = {
    "مددکار": ["att_self", "rep_write", "inc_write", "evt_view", "cli_view", "cli_manage", "leave_self", "loan_self"],
    "کاردرمانگر / مربی": ["att_self", "rep_write", "inc_write", "evt_view", "cli_view", "leave_self", "loan_self"],
    "پرستار": ["att_self", "rep_write", "inc_write", "evt_view", "cli_view", "leave_self", "loan_self"],
    "نگهبان": ["att_self", "rep_write", "inc_write", "evt_view", "cam_view", "leave_self", "loan_self"],
    "خدمات": ["att_self", "inc_write", "leave_self", "loan_self"],
    "دفتردار / حسابدار": ["att_self", "rep_write", "evt_view", "loan_manage", "loan_self", "export", "leave_self"],
}
