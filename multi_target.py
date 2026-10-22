#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
multi_target.py — 多目标 + 多规则体系 (2026-10-22 v2)

用户原话: "那你一直弃权，你这预测的功能也没有用啊"
= 只做 "次日涨5%+" 单目标, 覆盖太低 (弃权 86%)。

v2 改动:
  1. 修 numpy 计数 bug: np.add.reduceat 在"某日无样本"时错位 -> 改 np.bincount
  2. **多目标扫描**: 涨5% / 涨3% / 涨2% / 不跌, 各自找最优规则
  3. **覆盖优先的 ensemble 贪心**: 优先选"能覆盖还没覆盖的日子"的规则
  4. 输出: 每个目标的 (precision, 有信号交易日占比) -> 用户挑

核心指标:
  precision >= 70%          (用户硬门槛)
  signal_days_pct           (有信号交易日 / 总交易日)  <- "有没有用"
"""
import json
import os
import sys
import time
import urllib.request
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predict_next_day import tx_kline, _pool_from_json

CACHE = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'cache', 'scratch',
    'multi_regime_data.json'))
OUT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..',
    'AppData', 'Local', 'hermes', 'cache', 'scratch', 'multi_target.json'))

PREC_FLOOR = 0.70
MIN_TRAIN_SIGNALS = 8
MAX_ENSEMBLE = 10
TARGETS = [0.05, 0.03, 0.02, 0.00]
MONTHS_BACK = 24


# ---------------------------------------------------------------- 特征
def build_all():
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            b = json.load(f)
        return b['feats'], b['meta']
    pool = _pool_from_json()
    print(f'股票池 {len(pool)} 只')
    feats, meta = [], []
    for code, name in pool:
        k = tx_kline(code, 600)
        if len(k) < 250:
            print(f'  skip {code} {name} ({len(k)})')
            continue
        c = [x['c'] for x in k]; h = [x['h'] for x in k]
        l = [x['l'] for x in k]; v = [x['v'] for x in k]; o = [x['o'] for x in k]
        for i in range(120, len(k) - 1):
            w30 = slice(max(0, i-29), i+1); w90 = slice(max(0, i-89), i+1)
            w250 = slice(max(0, i-249), i+1)
            rng = h[i]-l[i]
            v5 = sum(v[i-5:i])/5; v20 = sum(v[i-20:i])/20
            lo30, hi30 = min(l[w30]), max(h[w30])
            lo90, hi90 = min(l[w90]), max(h[w90])
            ma5 = sum(c[i-4:i+1])/5; ma10 = sum(c[i-9:i+1])/10
            ma20 = sum(c[i-19:i+1])/20; ma60 = sum(c[i-59:i+1])/60
            lb = 0
            for j in range(i, 0, -1):
                if (c[j]-c[j-1])/c[j-1] >= 0.095: lb += 1
                else: break
            up = 0
            for j in range(i, 0, -1):
                if c[j] > c[j-1]: up += 1
                else: break
            dn = 0
            for j in range(i, 0, -1):
                if c[j] < c[j-1]: dn += 1
                else: break
            feats.append({
                'closepos': (c[i]-l[i])/rng*100 if rng > 0 else 50,
                'vratio': v[i]/v5 if v5 else 1, 'vrel20': v[i]/v20 if v20 else 1,
                'pos30': (c[i]-lo30)/(hi30-lo30)*100 if hi30 > lo30 else 50,
                'pos90': (c[i]-lo90)/(hi90-lo90)*100 if hi90 > lo90 else 50,
                'dist_hi250': (c[i]/max(h[w250])-1)*100,
                'amp30': sum(h[j]-l[j] for j in range(i-29, i+1))/30,
                'amp5': sum(h[j]-l[j] for j in range(i-4, i+1))/5,
                'ma_bull': 1.0 if (ma5 > ma10 > ma20 > ma60) else 0.0,
                'ma20_gap': (c[i]/ma20-1)*100, 'ma5_gap': (c[i]/ma5-1)*100,
                'c1': (c[i]-c[i-1])/c[i-1]*100, 'c3': (c[i]-c[i-3])/c[i-3]*100,
                'c5': (c[i]-c[i-5])/c[i-5]*100, 'c10': (c[i]-c[i-10])/c[i-10]*100,
                'c20': (c[i]-c[i-20])/c[i-20]*100, 'c30': (c[i]-c[i-30])/c[i-30]*100,
                'c60': (c[i]-c[i-60])/c[i-60]*100,
                'gap': (o[i]/c[i-1]-1)*100,
                'lu': lb, 'updays': up, 'downdays': dn, 'px': c[i],
                'next_high_ret': h[i+1]/c[i]-1,
                'next_close_ret': c[i+1]/c[i]-1})
            meta.append({'code': code, 'name': name, 'date': k[i]['d'],
                         'next_date': k[i+1]['d']})
    # 指数
    for code, tag in (('sh000001', 'sh'), ('sz399006', 'cyb')):
        k = tx_index(code, 520)
        if not k:
            print(f'  指数 {code} 失败')
            continue
        c = [x['c'] for x in k]; h = [x['h'] for x in k]; l = [x['l'] for x in k]
        for i in range(60, len(k)):
            w30 = slice(max(0, i-29), i+1); w90 = slice(max(0, i-89), i+1)
            lo30, hi30 = min(l[w30]), max(h[w30])
            lo90, hi90 = min(l[w90]), max(h[w90])
            d = k[i]['d']
            for j, mm in enumerate(meta):
                if mm['date'] == d:
                    feats[j][f'{tag}_1d'] = (c[i]-c[i-1])/c[i-1]*100
                    feats[j][f'{tag}_c5'] = (c[i]-c[i-5])/c[i-5]*100
                    feats[j][f'{tag}_c20'] = (c[i]-c[i-20])/c[i-20]*100
                    feats[j][f'{tag}_pos30'] = (c[i]-lo30)/(hi30-lo30)*100 if hi30 > lo30 else 50
                    feats[j][f'{tag}_pos90'] = (c[i]-lo90)/(hi90-lo90)*100 if hi90 > lo90 else 50
                    break
    keep = [i for i in range(len(feats)) if feats[i].get('sh_1d') is not None
            and feats[i].get('cyb_1d') is not None]
    feats = [feats[i] for i in keep]; meta = [meta[i] for i in keep]
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump({'feats': feats, 'meta': meta}, f)
    print(f'样本 {len(feats)}')
    return feats, meta


def tx_index(code, days=520):
    for u in (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq',
              f'https://ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,,,{days}'):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            node = d['data'].get(code) or {}
            kl = (node.get('qfqday') or node.get('day') or [])
            out = []
            for x in kl:
                try:
                    out.append({'d': x[0], 'c': float(x[2]), 'h': float(x[3]), 'l': float(x[4])})
                except Exception:
                    pass
            if out:
                return out
        except Exception:
            pass
    return []


ATOM = [
    ('c30', 'ge', [30, 50, 70, 90, 120, 150]), ('c30', 'le', [-50, -20, 0, 20]),
    ('c20', 'ge', [10, 25, 40, 60]), ('c20', 'le', [-20, -10, 0, 10]),
    ('c10', 'ge', [0, 5, 10, 20]), ('c10', 'le', [-5, 0, 5]),
    ('c5', 'ge', [0, 5, 15, 30]), ('c5', 'le', [-30, -20, -10, -5, 0, 10, 20, 30]),
    ('c3', 'ge', [0, 3, 5, 7]), ('c3', 'le', [-10, -5, 0]),
    ('c1', 'ge', [0, 2, 3, 5, 7, 9.5]), ('c1', 'le', [-3, 0, 2]),
    ('gap', 'ge', [0, 1, 2, 3]), ('gap', 'le', [-2, -1, 0]),
    ('closepos', 'ge', [40, 60, 80, 90]), ('closepos', 'le', [20, 40, 60]),
    ('vratio', 'ge', [0.8, 1.2, 1.5, 2.0, 3.0]), ('vratio', 'le', [0.7, 1.0, 1.5]),
    ('vrel20', 'ge', [0.8, 1.0, 1.3, 1.8]), ('vrel20', 'le', [0.7, 1.0]),
    ('pos30', 'ge', [50, 70, 80, 90]), ('pos30', 'le', [30, 50, 70]),
    ('pos90', 'ge', [50, 60, 70, 80, 90]), ('pos90', 'le', [30, 50, 70]),
    ('dist_hi250', 'ge', [-30, -15, -5]), ('dist_hi250', 'le', [-60, -30, -15]),
    ('amp30', 'ge', [0.5, 1.0, 2.0, 3.0]), ('amp5', 'le', [0.5, 1.0, 2.0]),
    ('amp_ratio', 'ge', [0.3, 0.5, 0.8]),
    ('ma_bull', 'eq', [1.0]),
    ('ma20_gap', 'ge', [0, 3, 8, 15]), ('ma20_gap', 'le', [-5, 0, 5]),
    ('ma5_gap', 'ge', [0, 3, 8]), ('ma5_gap', 'le', [-3, 0, 3]),
    ('lu', 'ge', [0, 1, 2, 3]), ('lu', 'le', [0, 1]),
    ('updays', 'ge', [1, 2, 3, 5]), ('downdays', 'ge', [1, 2, 3, 5]),
    ('c60', 'ge', [0, 30, 60, 100]),
    ('sh_1d', 'ge', [0, 0.5, 1.0]), ('sh_1d', 'le', [-1.0, -0.5, 0]),
    ('cyb_1d', 'ge', [0, 0.5, 1.0]), ('cyb_1d', 'le', [-1.0, -0.5, 0]),
    ('sh_c5', 'ge', [0, 2, 5]), ('sh_c5', 'le', [-3, -1, 0]),
    ('cyb_c5', 'ge', [0, 2, 5]), ('cyb_c5', 'le', [-3, -1, 0]),
    ('sh_pos30', 'ge', [50, 70]), ('sh_pos30', 'le', [30, 50]),
    ('cyb_pos30', 'ge', [50, 70]), ('cyb_pos30', 'le', [30, 50]),
]


def main():
    feats, meta = build_all()
    F = {k: np.array([f.get(k, np.nan) for f in feats], dtype=np.float64)
         for k in set().union(*[set(f) for f in feats])}
    nhr = F['next_high_ret']
    dates = sorted({m['date'] for m in meta})
    di = {d: i for i, d in enumerate(dates)}
    day_idx = np.array([di[m['date']] for m in meta])
    n_days = len(dates)
    print(f'{len(feats)} 样本 | {dates[0]} ~ {dates[-1]} | {n_days} 天')

    masks, desc = [], []
    for (fn, op, ths) in ATOM:
        if fn not in F:
            continue
        v = F[fn]
        for th in ths:
            m = np.nan_to_num((v >= th) if op == 'ge' else (
                (v <= th) if op == 'le' else (v == th)), nan=False)
            if m.sum() < 30:
                continue
            masks.append(m); desc.append(f"{fn}{op}{th}")
    A = len(masks)

    rule_masks, rule_desc = [], []
    for i in range(A):
        rule_masks.append(masks[i]); rule_desc.append([desc[i]])
    for i in range(A):
        mi = masks[i]
        for j in range(i + 1, A):
            m2 = mi & masks[j]
            if m2.sum() < 15:
                continue
            rule_masks.append(m2); rule_desc.append([desc[i], desc[j]])
    R = len(rule_masks)
    print(f'原子 {A} | 规则 {R}')

    # ---- bincount 计数 (修 reduceat 空日 bug)
    t0 = time.time()
    day_of = day_idx
    cnt = np.zeros((R, n_days), dtype=np.int32)
    for r in range(R):
        idx = np.flatnonzero(rule_masks[r])
        cnt[r] = np.bincount(day_of[idx], minlength=n_days)
    print(f'  cnt {time.time()-t0:.0f}s')

    months = sorted({d[:7] for d in dates})[-MONTHS_BACK:]
    results = {}

    for tgt in TARGETS:
        hit = nhr >= tgt
        hitd = np.zeros((R, n_days), dtype=np.int32)
        for r in range(R):
            idx = np.flatnonzero(rule_masks[r] & hit)
            hitd[r] = np.bincount(day_of[idx], minlength=n_days)
        base = int(hit.sum()) / len(hit)

        oos = []      # (date, code, name, hit, rule)
        per_month = []
        for mo in months:
            d_idx = [i for i, d in enumerate(dates) if d[:7] == mo]
            if not d_idx:
                continue
            d_end = d_idx[-1] + 1
            tr = np.arange(d_end)
            if d_end < 40:
                continue
            c_tr = cnt[:, tr].sum(1); h_tr = hitd[:, tr].sum(1)
            with np.errstate(invalid='ignore', divide='ignore'):
                prec = np.where(c_tr > 0, h_tr / np.maximum(c_tr, 1), 0.0)
            cand = np.flatnonzero((prec >= PREC_FLOOR) & (c_tr >= MIN_TRAIN_SIGNALS))
            if cand.size == 0:
                per_month.append((mo, [], 0, 0, 0.0, 0)); continue
            # 覆盖优先贪心
            sel = []
            uc = np.zeros(n_days, dtype=np.int32)
            uh = np.zeros(n_days, dtype=np.int32)
            for _ in range(MAX_ENSEMBLE):
                best = None
                best_score = (-1, -1.0, -1)
                for r in cand:
                    if r in sel:
                        continue
                    tc = (uc + cnt[r])[tr].sum(); th = (uh + hitd[r])[tr].sum()
                    if tc < MIN_TRAIN_SIGNALS or th / tc < PREC_FLOOR:
                        continue
                    new_days = int((((uc == 0) & (cnt[r] > 0))[tr]).sum())
                    score = (new_days, th / tc, tc)
                    if score > best_score:
                        best_score = score; best = r
                if best is None:
                    break
                sel.append(int(best)); uc = uc + cnt[best]; uh = uh + hitd[best]
            if not sel:
                per_month.append((mo, [], 0, 0, 0.0, 0)); continue
            um = np.zeros(len(feats), dtype=bool)
            for r in sel:
                um |= rule_masks[r]
            m_idx = np.array([i for i in range(len(feats)) if day_idx[i] in d_idx])
            chosen = m_idx[um[m_idx]]
            n_sig = len(chosen); ex = int(hit[chosen].sum())
            cov = int((cnt[sel][:, d_idx].sum(0) > 0).sum())
            per_month.append((mo, sel, n_sig, ex, ex / n_sig if n_sig else 0, cov))
            for i in chosen:
                oos.append({'date': meta[i]['date'], 'code': meta[i]['code'],
                            'name': meta[i]['name'], 'hit': bool(hit[i]),
                            'rule': ' & '.join(' & '.join(rule_desc[r]) for r in sel[:2])})
        n = len(oos); tp = sum(1 for x in oos if x['hit'])
        sig_days = len({x['date'] for x in oos})
        results[tgt] = {'n': n, 'tp': tp, 'prec': tp / n if n else 0, 'base': base,
                        'sig_days': sig_days, 'total_days': n_days,
                        'monthly': per_month, 'oos': oos,
                        'rules_used': Counter(x['rule'] for x in oos).most_common(10)}
        print(f'\n目标 涨{tgt*100:.0f}%: 信号 {n} | 命中 {tp} | precision {tp/max(n,1)*100:.1f}% '
              f'| 有信号 {sig_days}/{n_days} 天 ({sig_days/n_days*100:.0f}%) | 基线 {base*100:.1f}%')

    # ---- 打印最优
    print('\n' + '=' * 92)
    print('【目标对比】')
    print(f"{'目标':<10}{'precision':>11}{'信号':>8}{'命中':>8}{'有信号天数':>12}{'覆盖%':>9}{'基线':>8}{'提升':>7}")
    for tgt, r in results.items():
        print(f"{'涨'+format(tgt*100,'.0f')+'%':<10}{r['prec']*100:>10.1f}%{r['n']:>8}{r['tp']:>8}"
              f"{r['sig_days']:>8}/{r['total_days']:<4}{r['sig_days']/r['total_days']*100:>8.0f}%"
              f"{r['base']*100:>7.1f}%{r['prec']/max(r['base'],1e-9):>6.1f}x")
    print('=' * 92)

    best = max(results.items(), key=lambda kv: (kv[1]['prec'] >= PREC_FLOOR,
                                                kv[1]['sig_days']))
    bt, br = best
    print(f"\n推荐目标: 涨{bt*100:.0f}% | precision {br['prec']*100:.1f}% | "
          f"有信号 {br['sig_days']}/{br['total_days']} 天 ({br['sig_days']/br['total_days']*100:.0f}%)")
    print('\n各月表现:')
    for mo, sel, ns, ex, p, cov in br['monthly']:
        rs = ' | '.join(' & '.join(str(x) for x in sel[:2]) for sel2 in [sel]) if sel else '弃权'
        print(f'  {mo}: 信号 {ns:>3} 命中 {ex:>3} 精度 {p*100:>5.0f}% 覆盖天 {cov:>3}  {rs[:56]}')

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({str(k): {kk: vv for kk, vv in v.items() if kk != 'oos'}
                   for k, v in results.items()}, f, ensure_ascii=False, indent=1)
    print(f'\n{OUT}  用时 {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
