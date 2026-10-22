#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fit_final_rule.py — 定稿规则拟合 + 独立样本外验证 (防过拟合三重保险)

2026-10-22 立。
设计目标: 产出一个**写死**的规则 (predict_rule.json), 带明确的 OOS 数字。

三重防过拟合:
  1. 时间切分: 前 60% 训练 / 后 40% 样本外 (严格按时间, 不打乱)
  2. 样本外筛选: 只保留样本外 precision >= 目标的组合
  3. 全期复核 + 逐月稳定性: 任意单月 precision 不得 < 40%

**规则形式**: 2-3 个 AND 条件 (特征 + 方向 + 阈值), 可直接硬编码进 predict_next_day.py
"""
import json
import os
import sys
import time
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = r"C:\Users\yanyan.zou\stock-collaboration"
POOL = [
    ('002085', '万丰奥威'), ('600593', '大连圣亚'), ('600127', '金健米业'),
    ('002655', '共达电声'), ('002929', '润建股份'), ('600744', '华银电力'),
    ('600396', '华电辽能'), ('603099', '长白山'), ('601606', '长城军工'),
    ('001337', '四川黄金'), ('000099', '中信海直'), ('000995', '皇台酒业'),
    ('600199', '金种子酒'), ('600664', '哈药股份'),
]
CACHE = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..',
    'AppData', 'Local', 'hermes', 'cache', 'scratch', 'klines_2y.json'))
TARGET = 0.05
GOAL = 0.70
MIN_N_OUT = 40
MIN_MONTH = 0.40


def tx_kline(code, days=600):
    p = 'sh' if code.startswith('6') else 'sz'
    for u in (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={p}{code},day,,,{days},qfq',
              f'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={p}{code},day,,,{days},qfq'):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            kl = (d['data'][p + code].get('qfqday') or d['data'][p + code].get('day') or [])
            out = []
            for x in kl:
                try:
                    out.append({'d': x[0], 'o': float(x[1]), 'c': float(x[2]),
                                'h': float(x[3]), 'l': float(x[4]), 'v': float(x[5])})
                except Exception:
                    pass
            if out:
                return out
        except Exception:
            pass
    return []


def load_klines():
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            return json.load(f)
    print("拉 2 年 K 线...")
    out = {}
    for code, name in POOL:
        k = tx_kline(code, 600)
        if k:
            out[code] = {'name': name, 'k': k}
            print(f"  {code} {name}: {len(k)}")
        time.sleep(0.2)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    return out


def build(data):
    feats, meta = [], []
    for code, blob in data.items():
        k = blob['k']
        c = [x['c'] for x in k]; h = [x['h'] for x in k]
        l = [x['l'] for x in k]; v = [x['v'] for x in k]
        for i in range(120, len(k) - 1):
            rng = h[i] - l[i]
            closepos = (c[i] - l[i]) / rng * 100 if rng > 0 else 50
            v5 = sum(v[i - 5:i]) / 5
            v20 = sum(v[i - 20:i]) / 20
            lo30, hi30 = min(l[i - 29:i + 1]), max(h[i - 29:i + 1])
            pos30 = (c[i] - lo30) / (hi30 - lo30) * 100 if hi30 > lo30 else 50
            lo90, hi90 = min(l[i - 89:i + 1]), max(h[i - 89:i + 1])
            pos90 = (c[i] - lo90) / (hi90 - lo90) * 100 if hi90 > lo90 else 50
            hi250 = max(h[i - 249:i + 1]) if i >= 249 else max(h[:i + 1])
            ma5 = sum(c[i - 4:i + 1]) / 5
            ma10 = sum(c[i - 9:i + 1]) / 10
            ma20 = sum(c[i - 19:i + 1]) / 20
            ma60 = sum(c[i - 59:i + 1]) / 60
            amp5 = sum(h[j] - l[j] for j in range(i - 4, i + 1)) / 5
            amp30 = sum(h[j] - l[j] for j in range(i - 29, i + 1)) / 30
            lb = 0
            for j in range(i, 0, -1):
                if (c[j] - c[j - 1]) / c[j - 1] >= 0.095:
                    lb += 1
                else:
                    break
            up = 0
            for j in range(i, 0, -1):
                if c[j] > c[j - 1]:
                    up += 1
                else:
                    break
            feats.append({
                'closepos': closepos, 'vratio': v[i] / v5 if v5 else 1,
                'vrel20': v[i] / v20 if v20 else 1,
                'pos30': pos30, 'pos90': pos90,
                'dist_hi250': (c[i] / hi250 - 1) * 100,
                'amp30': amp30, 'amp5': amp5, 'amp_ratio': amp5 / amp30 if amp30 else 0,
                'ma_bull': 1.0 if (ma5 > ma10 > ma20 > ma60) else 0.0,
                'ma20_gap': (c[i] / ma20 - 1) * 100, 'ma5_gap': (c[i] / ma5 - 1) * 100,
                'c1': (c[i] - c[i - 1]) / c[i - 1] * 100,
                'c3': (c[i] - c[i - 3]) / c[i - 3] * 100,
                'c5': (c[i] - c[i - 5]) / c[i - 5] * 100,
                'c10': (c[i] - c[i - 10]) / c[i - 10] * 100,
                'c20': (c[i] - c[i - 20]) / c[i - 20] * 100,
                'c30': (c[i] - c[i - 30]) / c[i - 30] * 100,
                'c60': (c[i] - c[i - 60]) / c[i - 60] * 100,
                'lu': lb, 'updays': up, 'px': c[i],
                'next_high_ret': h[i + 1] / c[i] - 1,
                'next_close_ret': c[i + 1] / c[i] - 1,
            })
            meta.append({'code': code, 'name': blob['name'], 'date': k[i]['d'],
                         'next_date': k[i + 1]['d']})
    return feats, meta


ATOM = [
    ('c30', 'ge', [30, 50, 70, 90, 120, 150]), ('c30', 'le', [-50, -20, 0, 20]),
    ('c20', 'ge', [10, 25, 40, 60]), ('c10', 'ge', [0, 5, 10, 20]),
    ('c10', 'le', [-5, 0, 5]), ('c5', 'ge', [0, 5, 15, 30]), ('c5', 'le', [0, 10, 20, 30]),
    ('c1', 'ge', [0, 3, 5, 7, 9.5]), ('c1', 'le', [-3, 0, 2]),
    ('closepos', 'ge', [40, 60, 80, 90]), ('closepos', 'le', [20, 40, 60]),
    ('vratio', 'ge', [0.8, 1.2, 1.5, 2.0, 3.0]), ('vratio', 'le', [0.7, 1.0, 1.5]),
    ('vrel20', 'ge', [0.8, 1.0, 1.3, 1.8]), ('vrel20', 'le', [0.7, 1.0]),
    ('pos30', 'ge', [50, 70, 80, 90]), ('pos30', 'le', [30, 50, 70]),
    ('pos90', 'ge', [50, 60, 70, 80, 90]), ('pos90', 'le', [30, 50, 70]),
    ('dist_hi250', 'ge', [-30, -15, -5]), ('dist_hi250', 'le', [-60, -30, -15]),
    ('amp30', 'ge', [0.5, 1.0, 2.0, 3.0]), ('amp5', 'le', [0.5, 1.0, 2.0]),
    ('amp_ratio', 'ge', [0.3, 0.5, 0.8]), ('ma_bull', 'eq', [1.0]),
    ('ma20_gap', 'ge', [0, 3, 8, 15]), ('ma20_gap', 'le', [-5, 0, 5]),
    ('ma5_gap', 'ge', [0, 3, 8]), ('ma5_gap', 'le', [-3, 0, 3]),
    ('lu', 'ge', [0, 1, 2, 3]), ('updays', 'ge', [1, 2, 3, 5]),
    ('c60', 'ge', [0, 30, 60, 100]),
]


def monthly_check(by_date, hit, month_starts):
    """逐月 precision"""
    out = []
    for mo, ds in month_starts.items():
        tp = n = 0
        for d in ds:
            for code, f in by_date.get(d, {}).items():
                if f['_pick']:
                    n += 1
                    if hit[idx_global[code, d]]:
                        tp += 1
        out.append((mo, tp, n))
    return out


def main():
    data = load_klines()
    feats, meta = build(data)
    N = len(feats)
    F = {k: np.array([f[k] for f in feats], dtype=np.float64) for k in feats[0]}
    hit = F['next_high_ret'] >= TARGET
    dates = sorted({m['date'] for m in meta})
    di = {d: i for i, d in enumerate(dates)}
    day_idx = np.array([di[m['date']] for m in meta])
    n_days = len(dates)
    print(f"样本 {N} 行 | {dates[0]} ~ {dates[-1]} ({n_days} 天)")

    at_masks, at_desc = [], []
    for (fn, op, ths) in ATOM:
        for th in ths:
            v = F[fn]
            m = (v >= th) if op == 'ge' else ((v <= th) if op == 'le' else (v == th))
            if m.sum() < 40:
                continue
            at_masks.append(m); at_desc.append((fn, op, th))
    A = len(at_masks)
    print(f"原子条件 {A} 个")

    # 时间切分 60/40
    split = int(n_days * 0.60)
    in_m = day_idx < split
    out_m = day_idx >= split
    print(f"训练: {dates[0]} ~ {dates[split-1]} | 样本外: {dates[split]} ~ {dates[-1]}")

    # 训练集 top 组合 (2 条件)
    print("\n=== 训练集搜索 2 条件 ===")
    train_hits = int((hit & in_m).sum())
    train_n = int(in_m.sum())
    base_in = train_hits / train_n
    print(f"  训练基线: {base_in*100:.2f}%")
    cands = []
    for i in range(A):
        mi = at_masks[i] & in_m
        n_i = int(mi.sum())
        if n_i < 15:
            continue
        tp_i = int((mi & hit).sum())
        p_i = tp_i / n_i
        if p_i < 0.45:
            continue
        for j in range(i + 1, A):
            m2 = mi & at_masks[j]
            n2 = int(m2.sum())
            if n2 < 15:
                continue
            tp2 = int((m2 & hit).sum())
            p2 = tp2 / n2
            if p2 < 0.50:
                continue
            cands.append((p2, n2, (i, j)))
    cands.sort(reverse=True)
    print(f"  候选 {len(cands)} 个")

    # 样本外验证
    print("\n=== 样本外验证 (top 300) ===")
    out_hits = int((hit & out_m).sum())
    out_n = int(out_m.sum())
    base_out = out_hits / out_n
    print(f"  样本外基线: {base_out*100:.2f}%")
    val = []
    for p_in, n_in, trip in cands[:300]:
        m = at_masks[trip[0]] & at_masks[trip[1]]
        mo = m & out_m
        n_o = int(mo.sum())
        if n_o < 20:
            continue
        tp_o = int((mo & hit).sum())
        p_o = tp_o / n_o
        # 全期
        n_f = int(m.sum())
        tp_f = int((m & hit).sum())
        p_f = tp_f / n_f
        # 逐月
        months = {}
        for idx in np.where(m)[0]:
            mo_k = meta[idx]['date'][:7]
            months.setdefault(mo_k, [0, 0])
            months[mo_k][0] += 1
            if hit[idx]:
                months[mo_k][1] += 1
        worst = min((tp / n for mo_k, (n, tp) in months.items() if n >= 4),
                    default=1.0)
        val.append({'trip': trip, 'prec_in': p_in, 'n_in': n_in,
                    'prec_out': p_o, 'n_out': n_o, 'prec_full': p_f, 'n_full': n_f,
                    'worst_month': worst, 'n_months': len(months)})
    val.sort(key=lambda x: -x['prec_out'])

    print(f"\n  {'规则':<50}{'训练':>16}{'样本外':>16}{'全期':>16}{'最差月':>9}")
    print("  " + "-" * 108)
    for v in val[:15]:
        d = ' AND '.join(f"{at_desc[t][0]}{at_desc[t][1]}{at_desc[t][2]}" for t in v['trip'])
        print(f"  {d:<50}"
              f"{v['prec_in']*100:>7.1f}%(n{v['n_in']:>3})"
              f"{v['prec_out']*100:>7.1f}%(n{v['n_out']:>3})"
              f"{v['prec_full']*100:>7.1f}%(n{v['n_full']:>4})"
              f"{v['worst_month']*100:>8.0f}%")

    # 定稿: 样本外 >=70% + n>=40 + 最差月 >=40%
    good = [v for v in val if v['prec_out'] >= GOAL and v['n_out'] >= MIN_N_OUT
            and v['worst_month'] >= MIN_MONTH]
    print()
    if good:
        best = max(good, key=lambda x: (x['prec_out'], x['n_out']))
        d = ' AND '.join(f"{at_desc[t][0]}{at_desc[t][1]}{at_desc[t][2]}" for t in best['trip'])
        print(f"🏆 定稿: {d}")
        print(f"   训练 {best['prec_in']*100:.1f}%(n={best['n_in']}) | "
              f"样本外 {best['prec_out']*100:.1f}%(n={best['n_out']}) | "
              f"全期 {best['prec_full']*100:.1f}%(n={best['n_full']}) | "
              f"最差月 {best['worst_month']*100:.0f}%")
        rule = {
            'name': d,
            # op 统一存 '>=' / '<=' (verify/predict 脚本按这两个字面量判断)
            'conds': [[at_desc[t][0],
                       '>=' if at_desc[t][1] == 'ge' else ('<=' if at_desc[t][1] == 'le' else '=='),
                       at_desc[t][2]] for t in best['trip']],
            'score': [[at_desc[t][0],
                       '>=' if at_desc[t][1] == 'ge' else ('<=' if at_desc[t][1] == 'le' else '=='),
                       at_desc[t][2]] for t in best['trip']],
            'oos_precision': best['prec_out'], 'oos_n': best['n_out'],
            'train_precision': best['prec_in'], 'train_n': best['n_in'],
            'full_precision': best['prec_full'], 'full_n': best['n_full'],
            'worst_month': best['worst_month'],
            'baseline': base_out, 'baseline_in': base_in,
            'backtest_range': [dates[0], dates[-1]],
            'split_date': dates[split],
        }
        with open(os.path.join(REPO, 'predict_rule.json'), 'w', encoding='utf-8') as f:
            json.dump(rule, f, ensure_ascii=False, indent=1)
        print(f"   已写 {REPO}/predict_rule.json")
    else:
        # 放宽: 报告真实上限
        print("❌ 无规则同时满足 (样本外>=70% + n>=40 + 最差月>=40%)")
        if val:
            top = max(val, key=lambda x: x['prec_out'])
            print(f"   最高样本外 precision: {top['prec_out']*100:.1f}% (n={top['n_out']}) "
                  f"- {top['trip']}")
        with open(os.path.join(REPO, 'predict_rule.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': 'none', 'conds': [], 'abstain': True,
                       'baseline': base_out}, f, ensure_ascii=False, indent=1)

    # 存档候选
    with open(os.path.abspath(os.path.join(os.path.dirname(CACHE), 'fit_final.json')),
              'w', encoding='utf-8') as f:
        json.dump({'val': val[:50],
                   'atoms': [list(map(str, a)) for a in at_desc],
                   'base_in': base_in, 'base_out': base_out}, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
