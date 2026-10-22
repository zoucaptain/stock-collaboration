#!/usr/bin/env bash
# ==============================================================
# macro-wrapper.sh — 8:00 外围宏观链条 cron wrapper
# ==============================================================
set -e
REPO_DIR="C:/Users/yanyan.zou/stock-collaboration"
SCRIPTS="C:/Users/yanyan.zou/AppData/Local/hermes/scripts"
TS=$(date +%Y%m%d-%H%M%S)
LOG="$REPO_DIR/.cron/macro-$TS.log"

source "$SCRIPTS/pyenv.sh" 2>/dev/null || true
: "${PY:=$HERMES_PYENV_BIN}"

echo "=== macro chain $TS ===" >> "$LOG"

OUT=$("$PY" "$SCRIPTS/macro_chain.py" 2>&1)
echo "$OUT" >> "$LOG"

# 推 GitHub (给 OpenClaw 消费)
cd "$REPO_DIR"
git fetch origin 2>/dev/null || true
BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
if [ "$BEHIND" -gt 0 ]; then
  git pull --rebase origin main >> "$LOG" 2>&1 || true
fi
git add macro_chain_*.md 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -m "macro: 外围宏观链条 $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1 || true
  git push origin main >> "$LOG" 2>&1 || true
  git fetch origin
  LH=$(git log -1 --format='%h' HEAD); RH=$(git log -1 --format='%h' origin/main)
  [ "$LH" = "$RH" ] && echo "[push] ✅ verified $LH" >> "$LOG" || echo "[push] ❌ 未前进" >> "$LOG"
fi

echo "$OUT"
