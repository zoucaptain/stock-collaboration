#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pending_push.py — 微信推送失败时的待推队列 (补推机制)

背景 (2026-10-21 实测):
  微信 iLink 平台是 getupdates 轮询式, 推送通道依赖 **context_token**,
  而 context_token **只在用户主动发消息时** 才由 getupdates 返回。
  微信服务端对闲置会话返回:
      "iLink sendmessage session not ready: ret=-2 ... prepare failed
       — the user must send the bot a message first (or re-pair)"
  → 这是**平台硬限制**, 不是 cron/脚本/模型问题, 代码层面无法根治。

永久修法 (本脚本 + 两个 cron):
  1. 15:30 复盘 cron 推送失败 → 报告写入 pending 队列 (不丢内容)
  2. 每 15 分钟跑一次 pending_push.py → 若会话已恢复 (用户发过消息) 则补推
  3. 用户交互时, 助手也会主动检查队列

用法:
  python pending_push.py enqueue <job_id> <report_path>   # 入队
  python pending_push.py check                             # 查询待推 (只读)
  python pending_push.py deliver                           # 尝试补推全部
  python pending_push.py clear <job_id>                    # 出队
"""
import json
import os
import sys
from datetime import datetime

PENDING_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "pending_push"
)
INDEX = os.path.join(PENDING_DIR, "index.json")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load():
    if not os.path.exists(INDEX):
        return []
    try:
        with open(INDEX, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(items):
    os.makedirs(PENDING_DIR, exist_ok=True)
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, INDEX)


def enqueue(job_id, report_path):
    """推送失败 → 入队"""
    items = _load()
    for it in items:
        if it.get("job_id") == job_id and it.get("report_path") == report_path:
            it["attempts"] = it.get("attempts", 0) + 1
            it["last_attempt"] = _now()
            _save(items)
            print(f"[pending] 已存在, 计数+1: {job_id} {report_path}")
            return
    items.append({
        "job_id": job_id,
        "report_path": os.path.abspath(report_path),
        "enqueued_at": _now(),
        "attempts": 1,
        "last_attempt": _now(),
    })
    _save(items)
    print(f"[pending] 已入队: {job_id} <- {report_path}")


def check():
    items = _load()
    if not items:
        print("[pending] 队列为空")
        return 0
    print(f"[pending] {len(items)} 条待推:")
    for it in items:
        p = it.get("report_path", "")
        exists = os.path.exists(p)
        size = os.path.getsize(p) if exists else 0
        print(f"  - {it.get('job_id')} | {it.get('enqueued_at')} | "
              f"尝试 {it.get('attempts')} 次 | 文件{'存在' if exists else '丢失'}"
              f" ({size} 字)")
        print(f"    {p}")
    return len(items)


def deliver():
    """尝试补推 (需要能发消息的通道)"""
    items = _load()
    if not items:
        print("[pending] 队列为空, 无需补推")
        return 0
    delivered = 0
    for it in list(items):
        p = it.get("report_path", "")
        if not os.path.exists(p):
            print(f"[pending] 跳过 (文件丢失): {p}")
            _save([x for x in items if x is not it])
            continue
        content = open(p, encoding="utf-8").read()
        print(f"[pending] 待推 {it.get('job_id')} ({len(content)} 字) — "
              f"由调用方发送到微信")
        delivered += 1
    return delivered


def clear(job_id):
    items = _load()
    kept = [it for it in items if it.get("job_id") != job_id]
    _save(kept)
    print(f"[pending] 已清除 {job_id} ({len(items) - len(kept)} 条)")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "enqueue" and len(sys.argv) >= 4:
        enqueue(sys.argv[2], sys.argv[3])
    elif cmd == "check":
        check()
    elif cmd == "deliver":
        deliver()
    elif cmd == "clear" and len(sys.argv) >= 3:
        clear(sys.argv[2])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
