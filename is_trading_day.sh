#!/bin/bash
# is_trading_day.sh — 交易日守卫 (wrapper 调用入口)
# 输出: TRADING / CLOSED
# 用法 (wrapper 顶部):
#   TD=$(bash "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/is_trading_day.sh" 2>/dev/null || echo CLOSED)
#   if [ "$TD" != "TRADING" ]; then echo "非交易日, 跳过"; exit 0; fi
source "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/pyenv.sh" 2>/dev/null || true
if "$PY" "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/is_trading_day.py" >/dev/null 2>&1; then
  echo "TRADING"
else
  echo "CLOSED"
fi
