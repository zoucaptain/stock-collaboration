#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
walkforward_monthly.py — 月度重拟合 walk-forward (严格 OOS)

2026-10-22 立。
前一个脚本按"每日重拟合"跑 (485 次 x 6903 组合) -> 跑不动, 改为**每月重拟合**:
  - 每月初: 只用该月之前的数据重新搜索规则
  - 该月整月: 用这个规则出预测
  - 累加所有 OOS 预测 -> 真实可期待准确率

这比"60/40 一次性切分"更严格:
  - 每个月规则都可能不同 (模拟实战迭代)
  - 任何一个月选不出好规则 -> 该月弃权 (不许用别的规则补)
  - 累计 precision 就是真实预期

用 numpy 预计算 2 条件 cumsum, 三条件用 bit-packing 加速。
"""
import json
import os
import sys
import time
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
TRAIN_DAYS = 60          # 至少 60 天训练
MIN_TRAIN_N = 10


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
    out = {}
    for code, name in POOL:
        k = tx_kline(code, 600)
        if k:
            out[code] = {'name': name, 'k': k}
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
                'vrel20': v[i] / v20 if v20 else 1, 'pos30': pos30, 'pos90': pos90,
                'dist_hi250': (c[i] / hi250 - 1) * 100, 'amp30': amp30, 'amp5': amp5,
                'amp_ratio': amp5 / amp30 if amp30 else 0,
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
                'next_high_ret': h[i + 1] / c[i] - 1})
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


def main():
    data = load_klines()
    feats, meta = build(data)
    F = {k: np.array([f[k] for f in feats], dtype=np.float64) for k in feats[0]}
    hit = F['next_high_ret'] >= TARGET
    dates = sorted({m['date'] for m in meta})
    di = {d: i for i, d in enumerate(dates)}
    day_idx = np.array([di[m['date']] for m in meta])
    n_days = len(dates)
    print(f"样本 {len(feats)} 行 | {dates[0]} ~ {dates[-1]} ({n_days} 天)")

    at_masks, at_desc = [], []
    for (fn, op, ths) in ATOM:
        for th in ths:
            v = F[fn]
            m = (v >= th) if op == 'ge' else ((v <= th) if op == 'le' else (v == th))
            if m.sum() < 40:
                continue
            at_masks.append(m); at_desc.append((fn, op, th))
    A = len(at_masks)
    print(f"原子条件 {A}")

    # 月份分组
    months = {}
    for i, m in enumerate(meta):
        months.setdefault(m['date'][:7], []).append(i)

    oos = []      # (month, name, hit, rule_desc)
    monthly_stats = []
    print("\n开始月度 walk-forward...")
    t0 = time.time()
    for mo in sorted(months):
        idxs = months[mo]
        m_dates = sorted({meta[i]['date'] for i in idxs})
        d_end = di[m_dates[-1]] + 1
        if d_end < TRAIN_DAYS:
            continue
        tr = day_idx < d_end
        # 只在训练集上搜 2 条件 (够用, 且快)
        best = None
        for i in range(A):
            mi = at_masks[i] & tr
            n_i = int(mi.sum())
            if n_i < MIN_TRAIN_N:
                continue
            p_i = int((mi & hit).sum()) / n_i
            if p_i < 0.45:
                continue
            for j in range(i + 1, A):
                m2 = mi & at_masks[j]
                n2 = int(m2.sum())
                if n2 < MIN_TRAIN_N:
                    continue
                p2 = int((m2 & hit).sum()) / n2
                if p2 < 0.55:
                    continue
                if best is None or (p2, n2) > (best[2], best[3]):
                    best = (i, j, p2, n2)
        if best is None:
            monthly_stats.append((mo, 0, 0, 0.0, '无合格规则->弃权'))
            continue
        i, j, p_tr, n_tr = best
        rule = at_masks[i] & at_masks[j]
        desc = ' AND '.join(f"{at_desc[t][0]}{at_desc[t][1]}{at_desc[t][2]}" for t in (i, j))
        picks = [ix for ix in idxs if rule[ix]]
        tp = sum(1 for ix in picks if hit[ix])
        for ix in picks:
            oos.append((mo, meta[ix]['name'], bool(hit[ix]), desc))
        monthly_stats.append((mo, len(picks), tp, tp / max(len(picks), 1), desc))

    n = len(oos)
    tp = sum(1 for x in oos if x[2])
    print(f"\n{'='*84}")
    print(f"【月度 walk-forward OOS】{len(monthly_stats)} 个月, 累计预测 {n} 次, 命中 {tp}")
    print(f"  累计 precision: {tp/max(n,1)*100:.1f}%")
    base = int(hit.sum()) / len(hit)
    print(f"  基线: {base*100:.2f}%  |  提升 {tp/max(n,1)/base:.1f} 倍")
    print(f"{'='*84}")
    print(f"{'月份':<10}{'预测':>6}{'命中':>6}{'precision':>11}  规则")
    for mo, np_, t_, p_, d_ in monthly_stats:
        print(f"{mo:<10}{np_:>6}{t_:>6}{p_*100:>10.0f}%  {d_}")

    print("\n=== 用的最多的规则 ===")
    from collections import Counter
    c = Counter(x[3] for x in oos)
    for d_, cnt in c.most_common(8):
        sub = [x for x in oos if x[3] == d_]
        t = sum(1 for x in sub if x[2])
        print(f"  {d_:<44} {cnt:>4} 次, 该规则 {t}/{len(sub)} = {t/len(sub)*100:.0f}%")

    outp = os.path.abspath(os.path.join(os.path.dirname(CACHE), 'wf_monthly.json'))
    with open(outp, 'w', encoding='utf-8') as f:
        json.dump({'n': n, 'tp': tp, 'prec': tp / max(n, 1), 'baseline': base,
                   'monthly': [(m, a, b, p, d) for m, a, b, p, d in monthly_stats],
                   'rules': dict(c)}, f, ensure_ascii=False, indent=1)
    print(f"\n用时 {time.time()-t0:.0f}s | 保存 {outp}")


if __name__ == '__main__':
    main()
