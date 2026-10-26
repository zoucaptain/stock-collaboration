#!/bin/bash
# harmonic-warmup-wrapper.sh
# 用途：谐音炒作清单 cron wrapper
# 调度：cron 0 9 * * 1-5 (周一~周五 9:00)
# 创建：2026-09-18
#
# 流程：
# 1. 跑 harmonic_warmup_scanner.py 生成清单
# 2. 校验输出非空
# 3. git add + commit + push 到 GitHub
# 4. 失败时推微信告警
#
# 复用 overnight-news-wrapper.sh 的 token + retry 逻辑

set -e
source "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/pyenv.sh" 2>/dev/null || true

REPO_DIR="C:/Users/yanyan.zou/stock-collaboration"
SCRIPT="C:/Users/yanyan.zou/AppData/Local/hermes/scripts/harmonic_warmup_scanner.py"
ALERT="C:/Users/yanyan.zou/AppData/Local/hermes/scripts/_send_alert.sh"
NOW=$(date '+%Y-%m-%d %H:%M')
LOG="C:/Users/yanyan.zou/stock-collaboration/.cron/harmonic-${NOW//[: ]/-}.log"

TOKEN_FILE="C:/Users/yanyan.zou/AppData/Local/hermes/.github_token"
if [ -f "$TOKEN_FILE" ]; then
    STOCK_GITHUB_TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
fi
REMOTE_URL="https://x-access-token:${STOCK_GITHUB_TOKEN}@github.com/zoucaptain/stock-collaboration.git"

export GIT_ASKPASS=true
export GIT_TERMINAL_PROMPT=0

mkdir -p "$(dirname "$LOG")"

cd "$REPO_DIR" || { bash "$ALERT" "harmonic wrapper: cd $REPO_DIR 失败" "error"; exit 1; }

ERRORS=()
FAIL_FLAG=0

# 1) 跑采集脚本
if [ ! -f "$SCRIPT" ]; then
    ERRORS+=("harmonic_warmup_scanner.py 不存在: $SCRIPT")
    FAIL_FLAG=1
else
    if ! timeout 60 "$PY" "$SCRIPT" >> "$LOG" 2>&1; then
        ERRORS+=("python harmonic_warmup_scanner.py 失败 (exit $?)")
        FAIL_FLAG=1
    fi
fi

# 2) 校验输出文件
OUTPUT_FILE="$REPO_DIR/harmonic_warmup.md"
if [ "$FAIL_FLAG" -eq 0 ]; then
    if [ ! -s "$OUTPUT_FILE" ]; then
        ERRORS+=("harmonic_warmup.md 为空 (size=0)")
        FAIL_FLAG=1
    elif ! head -3 "$OUTPUT_FILE" | grep -q "谐音炒作清单"; then
        ERRORS+=("harmonic_warmup.md 首部不是'谐音炒作清单'")
        FAIL_FLAG=1
    fi
fi

# 2.5) 拉取 origin 同步
# 2026-10-26 修: fetch 遇网络抖动就置 FAIL_FLAG=1, 导致后面 commit/push 全被跳过
# (报告已生成却推不出去)。改为: fetch 重试 3 次; 仍失败只告警不致命, commit/push 照常走。
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
if [ "${LOCAL_BEHIND:-0}" -gt 0 ]; then
    echo "[INFO] origin 领先本地 $LOCAL_BEHIND 个 commit, 尝试 rebase" >> "$LOG"
    if ! git diff --cached --quiet 2>/dev/null || ! git diff --quiet 2>/dev/null; then
        timeout 30 git stash push -m "auto-stash-before-rebase-$(date +%H%M%S)" 2>>"$LOG" || true
    fi
    if ! timeout 30 git pull --rebase origin main 2>>"$LOG"; then
        ERRORS+=("git pull --rebase 失败, origin 领先 $LOCAL_BEHIND")
        FAIL_FLAG=1
    fi
    timeout 30 git stash pop 2>>"$LOG" || true
elif [ "$FETCH_OK" -eq 1 ]; then
    # fetch 成功且未落后 -> 仍做一次幂等 rebase, 防并发 cron 造成 non-fast-forward
    timeout 30 git pull --rebase origin main 2>>"$LOG" || true
fi

# 3) git add + commit
if [ "$FAIL_FLAG" -eq 0 ]; then
    timeout 30 git add harmonic_warmup.md 2>>"$LOG" || { ERRORS+=("git add 失败"); FAIL_FLAG=1; }
    if ! git diff --cached --quiet 2>/dev/null; then
        if ! timeout 30 git commit -m "auto: 谐音炒作清单 $(date '+%Y-%m-%d')" 2>>"$LOG"; then
            ERRORS+=("git commit 失败")
            FAIL_FLAG=1
        fi
    else
        echo "[INFO] harmonic_warmup.md 无变化, 跳过 commit" >> "$LOG"
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
    MSG="谐音清单 cron 失败 ($(date '+%H:%M'))
${ERRORS[*]}
查看日志: $LOG"
    bash "$ALERT" "$MSG" "error" 2>/dev/null || true
    exit 1
fi

echo "谐音清单 cron 成功 $(date '+%H:%M')" >> "$LOG"
exit 0