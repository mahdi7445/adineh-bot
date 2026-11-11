#!/usr/bin/env bash
# استفاده: bash tools/state.sh restore|save   (فقط داخل گیت‌هاب اکشنز)
# داده رمزنگاری‌شده در شاخه «state» نگه‌داری می‌شود (بدون تاریخچه).
#  • مخزن خصوصی بودن کد:  ذخیره‌گاه می‌تواند همین مخزن باشد.
#  • مخزن عمومی:           حتماً STATE_REPO (مخزن خصوصی جدا) و STATE_TOKEN لازم است؛ وگرنه اجرا متوقف می‌شود.
set -euo pipefail
# فاصله/خط‌جدید اضافهٔ ابتدا و انتهای مقدار (هنگام paste کردن) حذف می‌شود
REPO="$(printf '%s' "${STATE_REPO:-$GITHUB_REPOSITORY}" | tr -d '[:space:]')"
REPO="${REPO#https://github.com/}"; REPO="${REPO%.git}"; REPO="${REPO%/}"
TOKEN="$(printf '%s' "${STATE_TOKEN:-$GITHUB_TOKEN}" | tr -d '[:space:]')"
URL="${STATE_REMOTE_OVERRIDE:-https://github.com/${REPO}.git}"   # OVERRIDE فقط برای تست محلی
AUTH="$(printf 'x-access-token:%s' "$TOKEN" | base64 -w0)"
# احراز هویت با هدر (مثل actions/checkout)؛ توکن داخل نشانی نمی‌آید
# actions/checkout یک هدر احراز هویت (با GITHUB_TOKEN همین مخزن) در تنظیمات git می‌گذارد که روی مخزن خصوصی دیگر
# «Repository not found» می‌دهد؛ ابتدا آن را خالی می‌کنیم و بعد هدر خودمان را می‌گذاریم.
g() { git -c "http.https://github.com/.extraheader=" -c "http.https://github.com/.extraheader=Authorization: Basic ${AUTH}" "$@"; }

guard() {
  [ -n "${STATE_REMOTE_OVERRIDE:-}" ] && return 0
  local priv
  priv=$(GH_TOKEN="$TOKEN" gh api "repos/${REPO}" --jq .private 2>/dev/null || echo unknown)
  if [ "$priv" != "true" ]; then
    echo "::error::ذخیره‌گاه داده ($REPO) خصوصی نیست یا قابل بررسی نیست. برای امنیت، اجرا متوقف شد. STATE_REPO را روی یک مخزن خصوصی جدا تنظیم کنید."
    exit 1
  fi
}

case "${1:-}" in
  restore)
    guard
    rm -rf state
    # فرق «شاخه وجود ندارد (اولین اجرا)» با «خطای شبکه/دسترسی» حیاتی است: خطا یعنی توقف، نه شروع تازه.
    set +e
    ERR=$(g ls-remote --exit-code --heads "$URL" state 2>&1 >/dev/null)
    rc=$?
    set -e
    ERR="${ERR//$TOKEN/***}"; ERR="${ERR//$AUTH/***}"
    if [ "$rc" = "0" ]; then
      ok=0
      for i in 1 2 3; do
        rm -rf state
        if g clone -q --depth 1 --branch state "$URL" state; then ok=1; break; fi
        sleep $((i * 5))
      done
      [ "$ok" = "1" ] || { echo "::error::دریافت داده از مخزن ناموفق بود؛ برای جلوگیری از پاک شدن داده، اجرا متوقف شد."; exit 1; }
    elif [ "$rc" = "2" ]; then
      echo "اولین اجرا: هنوز داده‌ای ذخیره نشده."
      mkdir -p state
    else
      echo "جزئیات خطا (git): $ERR"
      echo "مخزن مورد استفاده: $REPO"
      echo "توکن STATE_TOKEN تنظیم شده؟ $([ -n "${STATE_TOKEN:-}" ] && echo بله || echo "خیر (از GITHUB_TOKEN استفاده شد)")"
      echo "دسترسی توکن از دید API: $(GH_TOKEN="$TOKEN" gh api "repos/${REPO}" --jq '"private=\(.private) pull=\(.permissions.pull) push=\(.permissions.push)"' 2>&1 | head -c 200)"
      echo "دسترسی به محتوای مخزن: $(GH_TOKEN="$TOKEN" gh api "repos/${REPO}/contents" >/dev/null 2>&1 && echo مجاز || echo "رد شد ← توکن Contents ندارد")"
      case "$ERR" in
        *"not found"*|*"Not Found"*) HINT="نام مخزن در Variable به نام STATE_REPO درست نیست (باید به شکل نام‌کاربری/نام‌مخزن باشد) یا توکن به این مخزن دسترسی ندارد." ;;
        *"denied"*|*"403"*|*"Permission"*) HINT="توکن STATE_TOKEN دسترسی «Contents: Read and write» روی مخزن خصوصی ندارد." ;;
        *"Authentication"*|*"401"*|*"could not read Username"*) HINT="توکن STATE_TOKEN اشتباه، منقضی یا خالی است." ;;
        *) HINT="STATE_REPO و STATE_TOKEN را بررسی کنید." ;;
      esac
      echo "::error::دسترسی به مخزن داده ممکن نیست (کد $rc). $HINT"
      exit 1
    fi
    python tools/state_sync.py restore state
    ;;
  save)
    guard
    mkdir -p state
    python tools/state_sync.py save state
    [ -f state/state.enc ] || exit 0
    cd state
    rm -rf .git
    git init -q -b state
    git config user.name "adineh-bot"; git config user.email "bot@users.noreply.github.com"
    git add state.enc snap-*.enc 2>/dev/null || git add state.enc
    git commit -q -m "state $(date -u +%FT%TZ)"
    g push -q -f "$URL" state
    echo "state pushed"
    ;;
  *) echo "usage: state.sh restore|save"; exit 2 ;;
esac
