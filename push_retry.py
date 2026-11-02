#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
push_retry.py — no_agent 补推器 (零 LLM, stdout 空 = 完全静默)

背景 (2026-10-23):
  微信 iLink 的 context_token 只在**用户主动发消息**时刷新。
  用户 10:30-17:18 沉默 -> 15:30 复盘 + 15:40 预测 两个 cron 都
  `session not ready` 推送失败 (last_status=delivery_failed),
  但产物已完整落盘 -> "任务生成了但用户没收到"。

本脚本:
  - 扫 cron/output/ 下各 job 的最新产物
  - 读 jobs.json 里该 job 的 last_status / last_delivery_error
  - 有投递错误 -> 把产物正文写到 stdout (scheduler 原样投递)
  - 投递成功 (status=ok) -> 标记已送达, 不再重复推
  - 没有待推内容 -> stdout 为空, 平台不发任何消息

铁律:
  1. stdout = 投递内容, 所有诊断走 stderr
  2. 一次只推一份 (按时间正序, 先推旧的)
  3. 送达判定读**推送器自己** jobs.json 里的 last_status:
       ok              -> 上一份已送达   -> 标记, 换下一份
       delivery_failed -> 上一份没送到   -> 重推同一份
  4. 推送器 job id 配在同目录 push_retry.json: { "pusher_job_id": "..." }
"""
import json
import os
import sys
from datetime import datetime

HERMES = r'C:\Users\yanyan.zou\AppData\Local\hermes'
OUT = os.path.join(HERMES, 'cron', 'output')
JOBS = os.path.join(HERMES, 'cron', 'jobs.json')
STATE = os.path.join(HERMES, 'cron', '.push_retry_state.json')
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'push_retry.json')
MIN_GAP_MIN = 3      # 同一份产物的最短重推间隔
MAX_CHARS = 1800     # 微信单条上限。适配器 MAX_MESSAGE_LENGTH=2000, 超出会被切成多个 chunk,
                     # iLink 的 prepare 闸门只放行一次 -> 第 2 个 chunk 必被拒 -> 整个任务判失败。
                     # 硬约束: 推送内容必须 <=1800 字 (1 chunk)。
MAX_ATTEMPTS = 8     # 同一条产物最多重推 8 次; 超了跳过, 防止单条永久堵死队列

# 被监控的 job id -> 正文起始标记 (必须与 cron 实际输出一致, 否则会回退到 Prompt 段)
WATCH = [
    ('post-market-review-20260924', '📊 A股收盘复盘'),
    ('814228c9d3d4', '📊 股票池预测'),
    ('94dcd757994f', '🌍 外围宏观链条'),
]


def log(m):
    print(m, file=sys.stderr)


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            log(f'[push_retry] {os.path.basename(path)} 读取失败: {e}')
    return default


def load_state():
    st = load_json(STATE, None)
    if not isinstance(st, dict):
        st = {}
    st.setdefault('sent', {})
    st.setdefault('pending', None)
    return st


def save_state(s):
    try:
        with open(STATE, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
    except Exception as e:
        log(f'[push_retry] state 写入失败: {e}')


def read_jobs():
    d = load_json(JOBS, [])
    if isinstance(d, dict):
        d = d.get('jobs', [])
    return d


def artifacts(job_id):
    """找该 job 的产物: 扁平命名 <jobid>_<ts>.txt 或 目录 <jobid>/*.txt|md"""
    out = []
    if os.path.isdir(OUT):
        for fn in os.listdir(OUT):
            if fn.startswith(f'{job_id}_') and fn.endswith('.txt'):
                p = os.path.join(OUT, fn)
                out.append((os.path.getmtime(p), p))
    sub = os.path.join(OUT, job_id)
    if os.path.isdir(sub):
        for fn in os.listdir(sub):
            if fn.endswith(('.txt', '.md')):
                p = os.path.join(sub, fn)
                out.append((os.path.getmtime(p), p))
    out.sort()
    return out


def body_of(path, marker):
    """取产物正文。

    2026-11-02 修 (根因): cron 产物文件 = "## Prompt" 段(整个 skill 全文, 可达 96K) + "## Response" 段(真正要发的内容)。
    旧实现找不到 marker 时, 兜底在 **Prompt 段**里找第一个 "# " 行, 从那儿切到文件尾
    -> 把 96K 的 prompt 连同 506 字的响应一起推给微信 -> 必然被 iLink prepare 闸门拒
    -> delivery_failed -> 无限重推 -> 队列被单条堵死, 后面所有报告全送不出去。

    修法: **先隔离 ## Response 段**, 只在 Response 段里找 marker; 找不到就用整个 Response 段。
          并加 MAX_CHARS 硬上限, 超过必截断 (微信单条 <=1800 字 = 1 chunk, 多 chunk 必被 prepare 闸门拒)。
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            t = f.read()
    except Exception as e:
        log(f'[push_retry] 产物读取失败 {path}: {e}')
        return None

    # ---- 1) 隔离 Response 段
    resp = t
    ri = t.rfind('\n## Response')
    if ri >= 0:
        resp = t[ri + len('\n## Response'):]
    else:
        ri = t.rfind('\n## Output')
        if ri >= 0:
            resp = t[ri + len('\n## Output'):]
    resp = resp.strip()

    # ---- 2) 在 Response 段里找 marker
    i = resp.find(marker)
    if i < 0:
        for ln in resp.splitlines():
            if ln.startswith('# ') and not ln.startswith('# Cron Job'):
                i = resp.find(ln)
                break
    body = (resp[i:] if i >= 0 else resp).strip()
    if not body:
        return None

    # ---- 3) 硬上限 (微信单条 <=1800 字)
    if len(body) > MAX_CHARS:
        keep = body[:MAX_CHARS - 120]
        cut = keep.rfind('\n')
        if cut > MAX_CHARS // 2:
            keep = keep[:cut]
        body = keep.rstrip() + '\n…(已截断, 全文见 GitHub)'
        log(f'[push_retry] 正文超长已截断 -> {len(body)} 字')
    return body


def main():
    cfg = load_json(CONFIG, {})
    pusher_id = cfg.get('pusher_job_id', '')
    jmap = {str(j.get('id')): j for j in read_jobs()}
    pusher_status = str(jmap.get(pusher_id, {}).get('last_status') or '')

    st = load_state()
    sent = st['sent']
    att = st.setdefault('attempts', {})

    # ---- 1) 处理上一份的送达结果
    pend = st.get('pending')
    if pend:
        key = pend.get('key')
        if pusher_status == 'ok':
            sent[key] = datetime.now().isoformat(timespec='seconds')
            st['pending'] = None
            log(f'[push_retry] 上一份已送达, 标记 {key}')
        elif pusher_status == 'delivery_failed':
            log(f'[push_retry] 上一份投递失败, 继续重推 {key}')
        else:
            log(f'[push_retry] 推送器状态未知 ({pusher_status!r}), 保守重推')

    # ---- 2) 收集未送达产物 (按时间正序 -> 先推旧的)
    items = []
    for jid, marker in WATCH:
        j = jmap.get(jid)
        if not j or not j.get('enabled', True):
            continue
        status = str(j.get('last_status') or '')
        err = str(j.get('last_delivery_error') or '')
        arts = artifacts(jid)
        if not arts:
            continue
        mt, path = arts[-1]          # 该 job 最新一份
        key = f'{jid}::{os.path.basename(path)}'
        if key in sent:
            continue
        # 该 job 自己投递成功 (ok 且无错误) -> 已送达, 标记跳过
        if status == 'ok' and not err:
            sent[key] = datetime.now().isoformat(timespec='seconds')
            log(f'[push_retry] {jid} 已投递成功, 跳过 {os.path.basename(path)}')
            continue
        items.append((mt, jid, marker, path, key))
    items.sort()

    # ---- 3) 选一份输出
    chosen = None
    if pend:
        key = pend.get('key')
        try:
            last_at = datetime.fromisoformat(pend.get('at', ''))
            gap_ok = (datetime.now() - last_at).total_seconds() >= MIN_GAP_MIN * 60
        except Exception:
            gap_ok = True
        if not gap_ok:
            log('[push_retry] 距上次推送不足 %d 分钟 — stdout 留空' % MIN_GAP_MIN)
            save_state(st)
            return 0
        # 重推次数超限 -> 跳过这条, 让后面的能出去 (防止单条永久堵死队列)
        if int(att.get(key, 0)) >= MAX_ATTEMPTS:
            log(f'[push_retry] {key} 已重推 {att[key]} 次超上限, 跳过 (不再堵队列)')
            sent[key] = datetime.now().isoformat(timespec='seconds') + ' (skipped: 超过最大重推次数)'
            st['pending'] = None
            pend = None
        else:
            for it in items:
                if it[4] == key:
                    chosen = it
                    break
            if chosen is None:
                log(f'[push_retry] 待重推的 {key} 已不在待推列表 (可能已送达), stdout 留空')
                save_state(st)
                return 0
    if chosen is None and items:
        chosen = items[0]

    if not chosen:
        log('[push_retry] 无待推内容 — stdout 留空')
        save_state(st)
        return 0

    mt, jid, marker, path, key = chosen
    body = body_of(path, marker)
    if not body:
        log(f'[push_retry] 正文提取失败 {path}')
        save_state(st)
        return 0

    st['pending'] = {'key': key, 'job': jid,
                     'at': datetime.now().isoformat(timespec='seconds')}
    att[key] = int(att.get(key, 0)) + 1
    save_state(st)

    sys.stdout.write(body)
    sys.stdout.flush()
    log(f'[push_retry] 输出正文 ({len(body)} 字, 第{att[key]}次) from {jid}/{os.path.basename(path)} '
        f'| 推送器状态: {pusher_status or "(未知)"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
