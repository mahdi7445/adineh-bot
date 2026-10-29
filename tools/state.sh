#!/usr/bin/env bash
# استفاده: bash tools/state.sh restore|save   (فقط داخل گیت‌هاب اکشنز)
# داده رمزنگاری‌شده در شاخه «state» نگه‌داری می‌شود (بدون تاریخچه).
#  • مخزن خصوصی بودن کد:  ذخیره‌گاه می‌تواند همین مخزن باشد.
#  • مخزن عمومی:           حتماً STATE_REPO (مخزن خصوصی جدا) و STATE_TOKEN لازم است؛ وگرنه اجرا متوقف می‌شود.
set -euo pipefail
REPO="${STATE_REPO:-$GITHUB_REPOSITORY}"
TOKEN="${STATE_TOKEN:-$GITHUB_TOKEN}"
URL="${STATE_REMOTE_OVERRIDE:-https://x-access-token:${TOKEN}@github.com/${REPO}.git}"   # OVERRIDE فقط برای تست محلی

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
    if git ls-remote --exit-code --heads "$URL" state >/dev/null 2>&1; then
      git clone -q --depth 1 --branch state "$URL" state
    else
      mkdir -p state
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
    git add state.enc
    git commit -q -m "state $(date -u +%FT%TZ)"
    git push -q -f "$URL" state
    echo "state pushed"
    ;;
  *) echo "usage: state.sh restore|save"; exit 2 ;;
esac
