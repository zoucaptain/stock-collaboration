#!/usr/bin/env bash
# ==============================================================
# ensure_deps.sh — 依赖体检 + 自动补装 (Hermes 更新免疫)
# ==============================================================
# 背景 (2026-10-22 实测):
#   Hermes 每天自动更新 -> 重建 AppData/Local/hermes/tools/ 整个目录
#   -> 装在 tools/python-*/site-packages 的 akshare/baostock 全部消失
#   -> 15:30 复盘 / 02:00 隔夜 / 19:50 持仓 等 cron 相继崩
#
# 本脚本:
#   1. 检查持久 venv (~/.hermes/pyenv, Hermes 更新不碰) 是否存在
#   2. 逐个 import 检查第三方包
#   3. 缺什么用 uv 补什么 (幂等)
#   4. 全部正常 -> 静默退出 0 (cron 不会打扰用户)
#   5. 有问题且修不好 -> 写日志 + 退出码非 0 (让 cron 报警)
#
# 用法: bash ensure_deps.sh [--quiet]
# ==============================================================

QUIET=0
[ "$1" = "--quiet" ] && QUIET=1

LOG="C:/Users/yanyan.zou/AppData/Local/hermes/logs/deps-check.log"
mkdir -p "$(dirname "$LOG")" 2>/dev/null

say() { [ "$QUIET" = "1" ] || echo "$@"; }
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

PYENV="C:\\Users\\yanyan.zou\\.hermes\\pyenv"
PYBIN="C:/Users/yanyan.zou/.hermes/pyenv/Scripts/python.exe"
UV="C:/Users/yanyan.zou/AppData/Local/hermes/tools/uv-0.12.3-win32-x64/uv.exe"
DEPS="akshare baostock requests pandas numpy lxml bs4 curl_cffi openpyxl tabulate tqdm"
# import 名 → pip 包名 (uv 遇到非法包名会整批中止, 必须逐个映射)
pipname() {
  case "$1" in
    bs4)   echo "beautifulsoup4" ;;
    lxml)  echo "lxml" ;;
    curl_cffi) echo "curl_cffi" ;;
    *)     echo "$1" ;;
  esac
}

log "--- 依赖体检开始 ---"

# 1) venv 存在?
if [ ! -f "$PYBIN" ]; then
  say "[deps] venv 缺失, 重建..."
  log "venv 缺失, 重建"
  "$UV" venv "$PYENV" --python 3.13 >>"$LOG" 2>&1
fi
if [ ! -f "$PYBIN" ]; then
  log "FATAL: venv 重建失败"
  say "[deps] ❌ venv 重建失败, 见 $LOG"
  exit 1
fi

# 2) uv 是否存在 (Hermes 更新可能换版本)
if [ ! -f "$UV" ]; then
  UV=$(ls -1 C:/Users/yanyan.zou/AppData/Local/hermes/tools/uv-*/uv.exe 2>/dev/null | head -1)
fi
if [ ! -f "$UV" ]; then
  log "FATAL: uv 不存在"
  say "[deps] ❌ uv 不存在, 无法自动补装"
  exit 1
fi

# 3) 逐个检查
MISSING=""
for m in $DEPS; do
  "$PYBIN" -c "import $m" >/dev/null 2>&1 || MISSING="$MISSING $m"
done

if [ -n "$MISSING" ]; then
  say "[deps] 补装:$MISSING"
  log "补装:$MISSING"
  # 逐个装 (uv 批量时遇一个非法名会整批中止)
  # 必须 --reinstall: 删掉包目录但残留 .dist-info 时, uv 会误判"已安装"而跳过
  for m in $MISSING; do
    PKG=$(pipname "$m")
    "$UV" pip install --python "$PYBIN" --reinstall "$PKG" >>"$LOG" 2>&1 \
      || log "安装失败 $m (pip名 $PKG)"
  done
  STILL=""
  for m in $MISSING; do
    "$PYBIN" -c "import $m" >/dev/null 2>&1 || STILL="$STILL $m"
  done
  if [ -n "$STILL" ]; then
    log "FATAL: 补装后仍缺:$STILL"
    say "[deps] ❌ 补装失败:$STILL"
    exit 1
  fi
  say "[deps] ✅ 补装完成"
else
  say "[deps] ✅ 全部正常 ($DEPS)"
fi

log "依赖体检通过"
exit 0
