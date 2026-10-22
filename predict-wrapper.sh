#!/usr/bin/env bash
# ==============================================================
# predict-wrapper.sh — 次日涨 5%+ 候选预测 cron wrapper
# ==============================================================
# 调度: 15:40 (15:30 收盘复盘之后 10 分钟)
# 流程:
#   1. source pyenv.sh (持久 venv, Hermes 更新免疫)
#   2. 对账上一交易日的预测 (--score) -> 写 accuracy_log.md
#   3. 出今日预测 (--predict) -> 写 predictions/predict_YYYYMMDD.json
#   4. git fetch + rebase + add + commit + push (v9.7 协议)
#   5. 输出预测结果 (供 cron 投递到微信)
#
# 纪律 (v10.0):
#   - 无符合标的 = 输出"弃权", 绝不硬凑
#   - 输出必须附 OOS precision + 基线 + 样本量
# ==============================================================

set -e
REPO_DIR="C:/Users/yanyan.zou/stock-collaboration"
SCRIPTS="C:/Users/yanyan.zou/AppData/Local/hermes/scripts"
TS=$(date +%Y%m%d-%H%M%S)
LOG="$REPO_DIR/.cron/predict-$TS.log"

source "$SCRIPTS/pyenv.sh" 2>/dev/null || true
: "${PY:=$HERMES_PYENV_BIN}"

echo "=== 预测任务 $TS ===" >> "$LOG"

# 1) 对账昨日
"$PY" "$SCRIPTS/predict_next_day.py" --score >> "$LOG" 2>&1 || echo "[score] 失败 (见 log)" >> "$LOG"

# 2) 今日预测
OUT=$("$PY" "$SCRIPTS/predict_next_day.py" --predict 2>&1)
echo "$OUT" >> "$LOG"

# 3) 推 GitHub (v9.7: fetch + rebase + 验证)
cd "$REPO_DIR"
git fetch origin 2>/dev/null || true
BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
if [ "$BEHIND" -gt 0 ]; then
  git pull --rebase origin main >> "$LOG" 2>&1 || git rebase origin/main >> "$LOG" 2>&1 || true
fi
git add predict_rule.json accuracy_log.md predictions/ 2>/dev/null || true
if ! git diff --cached --quiet 2>/dev/null; then
  git commit -m "auto: 预测+准确率台账 $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1 || true
  git push origin main >> "$LOG" 2>&1 || true
  git fetch origin
  LH=$(git log -1 --format='%h' HEAD); RH=$(git log -1 --format='%h' origin/main)
  [ "$LH" = "$RH" ] && echo "[push] ✅ verified $LH" >> "$LOG" || echo "[push] ❌ 未前进" >> "$LOG"
fi

# 4) 输出给 cron 投递
RULE_INFO=$("$PY" "$SCRIPTS/predict_next_day.py" --rule-info 2>&1 | tr '\n' ' ')
echo ""
echo "$RULE_INFO"
echo ""
echo "$OUT"
