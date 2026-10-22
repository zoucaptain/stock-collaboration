#!/usr/bin/env bash
# ==============================================================
# pyenv.sh — 统一 Python 解释器入口 (Hermes 更新免疫)
# ==============================================================
# 背景 (2026-10-22 实测):
#   Hermes 每天自动更新 -> 重建 AppData/Local/hermes/tools/ 整个目录
#   -> 昨天装在 tools/python-*/site-packages 的 akshare/baostock 全部消失
#   -> 依赖它的一次性 cron / 脚本直接崩
#
# 修法: 用 ~/.hermes/pyenv (用户目录, Hermes 更新不碰)
#   - 所有脚本用 $PY 调解释器, 不用裸 "python"
#   - 每次调用前自动自检 + 补装 (幂等)
#
# 用法:
#   source /c/Users/yanyan.zou/AppData/Local/hermes/scripts/pyenv.sh
#   $PY -c "import akshare"
#   hermes_py /c/.../post_market_reviewer.py
# ==============================================================

export HERMES_PYENV="C:\\Users\\yanyan.zou\\.hermes\\pyenv"
export HERMES_PYENV_BIN="C:/Users/yanyan.zou/.hermes/pyenv/Scripts/python.exe"
export HERMES_UV="C:/Users/yanyan.zou/AppData/Local/hermes/tools/uv-0.12.3-win32-x64/uv.exe"
export HERMES_PY_DEPS="akshare baostock requests pandas numpy lxml bs4 curl_cffi openpyxl tabulate tqdm"

# 自检 + 自动补装 (幂等, 缺什么装什么)
hermes_py_ensure() {
  if [ ! -f "$HERMES_PYENV_BIN" ]; then
    echo "[pyenv] venv 丢失, 重建中..." >&2
    "$HERMES_UV" venv "$HERMES_PYENV" --python 3.13 >/dev/null 2>&1
  fi
  local missing=""
  for m in $HERMES_PY_DEPS; do
    "$HERMES_PYENV_BIN" -c "import $m" >/dev/null 2>&1 || missing="$missing $m"
  done
  if [ -n "$missing" ]; then
    echo "[pyenv] 补装:$missing" >&2
    "$HERMES_UV" pip install --python "$HERMES_PYENV" $missing >/dev/null 2>&1
  fi
  export PY="$HERMES_PYENV_BIN"
}

hermes_py() {
  hermes_py_ensure
  "$HERMES_PYENV_BIN" "$@"
}

hermes_py_ensure
export PY="$HERMES_PYENV_BIN"
