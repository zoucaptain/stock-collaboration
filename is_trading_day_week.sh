#!/bin/bash
# is_trading_day_week.sh — 周报类任务的守卫: 本周(周一~周日)内有交易日即放行
# 周五遇法定节假日时, 本周最后交易日是周四, 周报仍应生成
source "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/pyenv.sh" 2>/dev/null || true
if "$PY" "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/is_trading_day.py" --week >/dev/null 2>&1; then
  echo "TRADING"
else
  echo "CLOSED"
fi
