#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
predict_monitor.py — 准确率自监控 + 自动重拟合 (2026-10-22)

用户原话: "最后我的目标还有可能卡住或者没达到。能不能改？"
= 规则是静态拟合的, 市场风格一变就会失效, 且没人盯着。

本脚本做 3 件事:
  1. SCORE  : 对账所有未结算的预测 -> 写 accuracy_log.md + 滚动准确率
  2. CHECK  : 滚动窗口 (最近 20 次预测) 准确率 < 70% -> 判定规则失效
  3. REFIT  : 失效则用全部历史重拟合, 新规则 OOS 达标才替换 (不达标就保持原规则 + 告警)

状态文件: predict_state.json
  { 'rule_locked': bool, 'active_rule': name, 'rolling': [...], 'degraded_streak': int }

**硬约束**:
  - 新规则必须样本外 >= 70% 且样本量 >= 20 才允许替换 (防止过拟合换规则)
  - 连续 2 次重拟合都失败 -> 锁定规则, 只告警不再乱换
  - 永远不为了凑数量放宽阈值
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = r"C:\Users\yanyan.zou\stock-collaboration"
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PRED_DIR = os.path.join(REPO, 'predictions')
LOG_FILE = os.path.join(REPO, 'accuracy_log.md')
RULE_FILE = os.path.join(REPO, 'predict_rule.json')
STATE_FILE = os.path.join(REPO, 'predict_state.json')

GOAL = 0.70
ROLL_WINDOW = 20        # 滚动窗口 = 最近 20 次预测
MIN_OUT_N = 20         # 新规则样本外最少样本量
MIN_ROLL_EVAL = 5      # 滚动准确率最少样本数 (2026-10-26: 样本太少不触发重拟合,
                       # 否则 1 个样本 miss 就会重写已提交的模型)
MAX_REFIT_PER_DAY = 1  # 每天最多重拟合 1 次
DEGRADE_STREAK_LIMIT = 2  # 连续 2 次重拟合失败 -> 锁定


def py():
    # 持久 venv (Hermes 每日更新会重建 tools/, 所以不能用 tools 下的解释器)
    for p in (r"C:/Users/yanyan.zou/.hermes/pyenv/Scripts/python.exe",
              os.path.join(SCRIPTS, 'pyenv.sh')):
        if p.endswith('.exe') and os.path.exists(p):
            return p
    return sys.executable


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'rolling': [], 'degraded_streak': 0, 'rule_locked': False,
            'refits_today': [], 'active_rule': None, 'history': []}


def save_state(s):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)


def load_rule():
    with open(RULE_FILE, encoding='utf-8') as f:
        return json.load(f)


def _norm_date(d):
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s


def score_pending():
    """对账所有已有后续行情的预测, 返回新结算的记录
    2026-10-26 修复: 之前只读 predict_*.json (旧 picks 格式),
    v13.0 模型写的是 rank_*.json -> 从来没结算过, 台账和滚动准确率都是空的。
    口径: 高置信日 (p >= thr) 的 **Top1** 次日最高涨幅 >= +5% 记 1 次命中,
    与模型口径 (Top1 涨5%+ 精度, 高置信日 70.0%) 对齐。"""
    if not os.path.isdir(PRED_DIR):
        return []
    from predict_next_day import tx_kline
    settled = []
    files = sorted(f for f in os.listdir(PRED_DIR)
                   if (f.startswith('predict_') or f.startswith('rank_'))
                   and f.endswith('.json'))
    for fn in files:
        with open(os.path.join(PRED_DIR, fn), encoding='utf-8') as f:
            pred = json.load(f)
        done_file = os.path.join(PRED_DIR, fn.replace('.json', '.done'))
        if os.path.exists(done_file):
            continue
        if fn.startswith('rank_'):
            s = _score_rank(pred, tx_kline)
            if s is not None:
                settled.append(s)
                with open(done_file, 'w', encoding='utf-8') as f:
                    json.dump({'tp': s['tp'], 'n': s['n']}, f, ensure_ascii=False)
            continue
        if not pred.get('picks'):
            continue
        # 幂等: 已结算过就跳过
        results = []
        all_ready = True
        for p in pred['picks']:
            k = tx_kline(p['code'], 40)
            if len(k) < 2:
                all_ready = False
                break
            nxt = next((x for x in k if x['d'] > pred['date']), None)
            if not nxt:
                all_ready = False
                break
            ret = nxt['h'] / p['px'] - 1
            results.append({**p, 'next_date': nxt['d'], 'ret': ret,
                            'hit': ret >= 0.05})
        if not all_ready or not results:
            continue
        tp = sum(1 for r in results if r['hit'])
        settled.append({'date': pred['date'], 'rule': pred.get('rule'),
                        'n': len(results), 'tp': tp, 'results': results})
        with open(done_file, 'w', encoding='utf-8') as f:
            json.dump({'tp': tp, 'n': len(results)}, f, ensure_ascii=False)
    return settled


def _score_rank(pred, tx_kline):
    """结算 rank_*.json (v13.0 概率排名模型)。
    低置信日 (未报候选) = 弃权, 不计入滚动准确率。"""
    if 'rank' not in pred:
        return None
    date = _norm_date(pred.get('date'))
    if not data_ok(pred):
        return None
    picks = pred['rank'][:3]
    results = []
    for p in picks:
        k = tx_kline(p['code'], 40)
        if len(k) < 2:
            return None
        nxt = next((x for x in k if x['d'] > date), None)
        if not nxt:
            return None
        ret = nxt['h'] / p['px'] - 1
        results.append({'name': p.get('name'), 'code': p.get('code'),
                        'px': p.get('px'), 'p': p.get('p'),
                        'next_date': nxt['d'], 'ret': ret,
                        'hit': ret >= 0.05})
    tp = sum(1 for r in results if r['hit'])
    # 滚动准确率口径: Top1 (与模型 Top1 精度口径一致)
    rolling_hits = [1 if results[0]['hit'] else 0] if results else []
    return {'date': date, 'rule': f"{pred.get('label', 'rank')} p>={pred.get('thr', 0):.4f}",
            'n': len(results), 'tp': tp, 'results': results,
            'rolling_hits': rolling_hits, 'top1_hit': rolling_hits[0] if rolling_hits else 0}


def data_ok(pred):
    """rank 文件必须是有候选的高置信日, 否则不算预测 (弃权)"""
    if not pred.get('high_conf'):
        return False
    return bool(pred.get('rank'))


def append_log(settled):
    if not settled:
        return
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        if new:
            f.write("# 📊 预测准确率台账 — 次日涨 5%+ 候选\n\n")
        for s in settled:
            f.write(f"## {s['date']} -> {s['results'][0]['next_date']}\n\n")
            f.write(f"规则: {s['rule']} | 预测 {s['n']} 只 | 命中 {s['tp']} | "
                    f"准确率 {s['tp']/s['n']*100:.1f}%\n\n")
            if 'top1_hit' in s:
                f.write(f"滚动口径 (Top1 命中): {s['top1_hit']} | "
                        f"Top1 {'✅' if s['top1_hit'] else '❌'}\n\n")
            f.write("| 股票 | 预测价 | 次日 | 最高涨幅 | 命中 |\n|---|---|---|---|---|\n")
            for r in s['results']:
                f.write(f"| {r['name']} | {r['px']} | {r['next_date']} | "
                        f"{r['ret']*100:+.2f}% | {'✅' if r['hit'] else '❌'} |\n")
            f.write("\n")


def rolling_accuracy(state):
    r = state.get('rolling', [])
    if not r:
        return None, 0, 0
    w = r[-ROLL_WINDOW:]
    tp = sum(x for x in w)
    return tp / len(w), tp, len(w)


def do_refit(state, reason):
    """用全部历史重拟合, 新规则样本外达标才替换"""
    today = datetime.now().strftime('%Y%m%d')
    if today in state.get('refits_today', []):
        return state, None, '今日已重拟合过, 跳过'
    state.setdefault('refits_today', []).append(today)
    print(f"[refit] 触发重拟合: {reason}")
    r = subprocess.run([py(), os.path.join(SCRIPTS, 'fit_final_rule.py')],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return state, None, f'重拟合脚本失败: {r.stderr[-300:]}'
    try:
        new_rule = load_rule()
    except Exception as e:
        return state, None, f'规则文件读取失败: {e}'
    if new_rule.get('abstain') or not new_rule.get('conds'):
        return state, None, '重拟合未找到合格规则 (样本外>=70% + n>=20), 保持原规则'
    oos = new_rule.get('oos_precision', 0)
    n_out = new_rule.get('oos_n', 0)
    old = load_rule()
    if oos < GOAL or n_out < MIN_OUT_N:
        return state, None, (f'新规则样本外 {oos*100:.1f}% (n={n_out}) 未达标 '
                              f'(需 >=70% 且 n>=20), 保持原规则')
    # 替换
    new_rule['refit_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_rule['refit_reason'] = reason
    with open(RULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_rule, f, ensure_ascii=False, indent=1)
    state['active_rule'] = new_rule['name']
    state.setdefault('history', []).append({
        'at': new_rule['refit_at'], 'from': old.get('name'), 'to': new_rule['name'],
        'oos': oos, 'n': n_out, 'reason': reason})
    return state, new_rule, (f"✅ 已换规则: {old.get('name')} → {new_rule['name']} "
                             f"(样本外 {oos*100:.1f}%, n={n_out})")


def main():
    args = sys.argv[1:] or ['--all']
    state = load_state()
    rule = load_rule()
    state.setdefault('active_rule', rule.get('name'))
    msg = []

    if '--score' in args or '--all' in args:
        settled = score_pending()
        if settled:
            append_log(settled)
            for s in settled:
                if 'rolling_hits' in s:
                    state['rolling'].extend(s['rolling_hits'])
                else:
                    for r in s['results']:
                        state['rolling'].append(1 if r['hit'] else 0)
            print(f"[score] 结算 {len(settled)} 天预测")
        else:
            print("[score] 无新结算")

    if '--check' in args or '--all' in args:
        acc, tp, n = rolling_accuracy(state)
        if acc is None:
            print("[check] 尚无滚动数据")
        else:
            print(f"[check] 滚动最近 {n} 次: {tp}/{n} = {acc*100:.1f}%")
            if n < MIN_ROLL_EVAL:
                print(f"[check] 样本不足 {n} < {MIN_ROLL_EVAL}, 暂不判定 (不触发重拟合)")
                state['degraded_streak'] = 0
            elif acc < GOAL:
                if state.get('rule_locked'):
                    msg.append(f"🔴 滚动准确率 {acc*100:.1f}% < 70%, 规则已锁定, 需人工介入")
                else:
                    state['degraded_streak'] = state.get('degraded_streak', 0) + 1
                    print(f"[check] ⚠️ 低于 {GOAL*100:.0f}%, 连续第 {state['degraded_streak']} 次")
                    if state['degraded_streak'] >= DEGRADE_STREAK_LIMIT:
                        state['rule_locked'] = True
                        msg.append(f"🔴 连续 {state['degraded_streak']} 次重拟合未达标, 规则已锁定")
                    else:
                        state, new_rule, note = do_refit(
                            state, f'滚动准确率 {acc*100:.1f}% < 70%')
                        msg.append(f"⚠️ 滚动准确率 {acc*100:.1f}% < 70% → {note}")
            else:
                state['degraded_streak'] = 0
                print(f"[check] ✅ 滚动准确率 {acc*100:.1f}% 达标")

    if '--predict' in args:
        r = subprocess.run([py(), os.path.join(SCRIPTS, 'predict_next_day.py'), '--predict'],
                           capture_output=True, text=True, timeout=600)
        out = (r.stdout or '') + (r.stderr or '')
        print(out.strip())

    save_state(state)
    if msg:
        print("\n=== 告警 ===")
        for m in msg:
            print(m)
    # 机器可读状态 (给 cron 判断要不要告警)
    print(f"\n[STATE] active_rule={state.get('active_rule')} "
          f"rolling_n={len(state.get('rolling', []))} "
          f"locked={state.get('rule_locked')} "
          f"acc={(rolling_accuracy(state)[0] or 0)*100:.1f}%")


if __name__ == '__main__':
    main()
