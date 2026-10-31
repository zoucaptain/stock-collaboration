#!/bin/bash
# overnight-news-wrapper.sh
# 用途：隔夜要闻采集 cron wrapper（凌晨 2:00 工作日）
# 调度：cron 0 2 * * 1-5（周一~周五）
# 创建：2026-09-17
#
# 流程：
# 1. 跑 overnight-news-collector.py 收集数据
# 2. 验证输出非空
# 3. git add + commit + push 到 GitHub
# 4. 失败时推微信告警
#
# 复用 stock-position-wrapper.sh 的 token 读取 + push retry 逻辑

set -e
source "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/pyenv.sh" 2>/dev/null || true

# ---- 交易日守卫 (2026-10-31): 周末/法定节假日跳过, 到开市再正常启动 ----
_TD=$(bash "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/is_trading_day.sh" 2>/dev/null || echo CLOSED)
if [ "$_TD" != "TRADING" ]; then
  echo "非交易日 ($(date '+%Y-%m-%d %A')), 本次任务跳过"
  exit 0
fi


REPO_DIR="C:/Users/yanyan.zou/stock-collaboration"
SCRIPT="C:/Users/yanyan.zou/AppData/Local/hermes/scripts/overnight-news-collector.py"
ALERT="C:/Users/yanyan.zou/AppData/Local/hermes/scripts/_send_alert.sh"
NOW=$(date '+%Y-%m-%d %H:%M')
LOG="C:/Users/yanyan.zou/stock-collaboration/.cron/overnight-${NOW//[: ]/-}.log"

TOKEN_FILE="C:/Users/yanyan.zou/AppData/Local/hermes/.github_token"
if [ -f "$TOKEN_FILE" ]; then
    STOCK_GITHUB_TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
fi
REMOTE_URL="https://x-access-token:${STOCK_GITHUB_TOKEN}@github.com/zoucaptain/stock-collaboration.git"

export GIT_ASKPASS=true
export GIT_TERMINAL_PROMPT=0

mkdir -p "$(dirname "$LOG")"

cd "$REPO_DIR" || { bash "$ALERT" "overnight wrapper: cd $REPO_DIR 失败" "error"; exit 1; }

ERRORS=()
FAIL_FLAG=0

# 1) 跑采集脚本
if [ ! -f "$SCRIPT" ]; then
    ERRORS+=("overnight-news-collector.py 不存在: $SCRIPT")
    FAIL_FLAG=1
else
    if ! timeout 90 "$PY" "$SCRIPT" >> "$LOG" 2>&1; then
        ERRORS+=("python overnight-news-collector.py 失败 (exit $?)")
        FAIL_FLAG=1
    fi
fi

# 2) 校验输出文件
OUTPUT_FILE="$REPO_DIR/overnight_news.md"
if [ "$FAIL_FLAG" -eq 0 ]; then
    if [ ! -s "$OUTPUT_FILE" ]; then
        ERRORS+=("overnight_news.md 为空 (size=0)")
        FAIL_FLAG=1
    elif ! head -3 "$OUTPUT_FILE" | grep -q "隔夜要闻"; then
        ERRORS+=("overnight_news.md 首部不是'隔夜要闻'")
        FAIL_FLAG=1
    fi
fi

# 2.5) 拉取 origin 同步 (2026-09-17 修复: origin 可能已前进, push 会失败)
# 2026-10-26 修: fetch 遇网络抖动就置 FAIL_FLAG=1, 会把后面 commit/push 全跳过
# (谐音清单同款 bug)。改为: fetch 重试 3 次; 仍失败只告警不致命。
FETCH_OK=0
for i in 1 2 3; do
    if timeout 30 git fetch origin 2>>"$LOG"; then
        FETCH_OK=1
        break
    fi
    echo "[RETRY $i] git fetch 失败, 5s 后重试" >> "$LOG"
    sleep 5
done
if [ "$FETCH_OK" -ne 1 ]; then
    ERRORS+=("git fetch 失败 3 次(网络问题, 不阻断 commit/push)")
    LOCAL_BEHIND=0
else
    LOCAL_BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
fi
if [ "$LOCAL_BEHIND" -gt 0 ]; then
    echo "[INFO] origin 领先本地 $LOCAL_BEHIND 个 commit, 尝试 rebase" >> "$LOG"
    # 先 stash 未提交改动
    if ! git diff --cached --quiet 2>/dev/null || ! git diff --quiet 2>/dev/null; then
        timeout 30 git stash push -m "auto-stash-before-rebase-$(date +%H%M%S)" 2>>"$LOG" || true
    fi
    if ! timeout 30 git pull --rebase origin main 2>>"$LOG"; then
        ERRORS+=("git pull --rebase 失败, origin 领先 $LOCAL_BEHIND")
        FAIL_FLAG=1
    fi
    # 恢复 stash
    timeout 30 git stash pop 2>>"$LOG" || true
fi

# 3) git add + commit
if [ "$FAIL_FLAG" -eq 0 ]; then
    timeout 30 git add overnight_news.md 2>>"$LOG" || { ERRORS+=("git add 失败"); FAIL_FLAG=1; }
    if ! git diff --cached --quiet 2>/dev/null; then
        if ! timeout 30 git commit -m "auto: 隔夜要闻 $(date '+%Y-%m-%d')" 2>>"$LOG"; then
            ERRORS+=("git commit 失败")
            FAIL_FLAG=1
        fi
    else
        echo "[INFO] overnight_news.md 无变化, 跳过 commit" >> "$LOG"
    fi
fi

# 4) git push 3 次重试
if [ "$FAIL_FLAG" -eq 0 ]; then
    PUSH_OK=0
    for i in 1 2 3; do
        if timeout 60 git push "$REMOTE_URL" main 2>>"$LOG"; then
            PUSH_OK=1
            break
        fi
        echo "[RETRY $i] push 失败，10s 后重试" >> "$LOG"
        sleep 10
    done
    if [ "$PUSH_OK" -ne 1 ]; then
        ERRORS+=("git push 失败 3 次")
        FAIL_FLAG=1
    fi
fi

# 5) 失败时推微信
if [ "$FAIL_FLAG" -eq 1 ]; then
    MSG="隔夜要闻 cron 失败 ($(date '+%H:%M'))
${ERRORS[*]}

日志: $LOG
排查: https://github.com/zoucaptain/stock-collaboration/commits/main"
    bash "$ALERT" "$MSG" "error"
    exit 1
fi

# 6) 成功时推简短摘要到微信 (可选 - 可注释掉)
SUMMARY=$(head -20 "$OUTPUT_FILE" | grep -E '^##|美股|中概|黄金|原油' | head -5 | tr '\n' '|')
MSG="🌙 隔夜要闻已推送 ($(date '+%H:%M'))
${SUMMARY}

详情: https://github.com/zoucaptain/stock-collaboration/blob/main/overnight_news.md
（这条由 cron 自动推，2026-09-17 加）"
bash "$ALERT" "$MSG" "info"

exit 0
