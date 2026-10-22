#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
multi_target_v2.py — 按"规则历史实盘表现"选规则 (2026-10-22 v3)

v2 的问题: 贪心 ensemble 在训练集上拟合 -> OOS precision 掉到 61.3% (涨5%目标),
           虽覆盖 62% 但精度破线。

v3 的修法 (真 OOS 选规则):
  选第 M 月的规则时, **只允许用第 M 月之前已经实现的实盘表现**来评分:
    hist_prec[r] = 规则 r 在 M 月之前所有日子里的实际 precision
  只有 hist_prec >= 0.75 (留 5pp 缓冲) 且历史信号数 >= 12 的规则才有资格入选
  再贪心 union, 但精度地板用**历史实盘**算, 不是训练集内拟合
  -> 选规则这个动作本身也是 OOS 的

输出: 每个目标 (涨5%/3%/2%/0%) 的 (OOS precision, 覆盖天数)
"""
import json
import os
import sys
import time
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predict_next_day import _pool_from_json
from multi_target import (build_all, ATOM, CACHE)

OUT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '..',
    'AppData', 'Local', 'hermes', 'cache', 'scratch', 'multi_target_v2.json'))

PREC_FLOOR = 0.70
QUAL_PREC = 0.75          # 入选门槛 (留缓冲)
MIN_HIST_SIGNALS = 12
MAX_ENSEMBLE = 12
TARGETS = [0.05, 0.03, 0.02]


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

    t0 = time.time()
    cnt = np.zeros((R, n_days), dtype=np.int32)
    for r in range(R):
        cnt[r] = np.bincount(day_idx[np.flatnonzero(rule_masks[r])], minlength=n_days)
    print(f'cnt {time.time()-t0:.0f}s')

    months = sorted({d[:7] for d in dates})
    month_days = {mo: np.array([i for i, d in enumerate(dates) if d[:7] == mo])
                  for mo in months}

    out = {}
    for tgt in TARGETS:
        hit = nhr >= tgt
        hitd = np.zeros((R, n_days), dtype=np.int32)
        for r in range(R):
            hitd[r] = np.bincount(day_idx[np.flatnonzero(rule_masks[r] & hit)],
                                  minlength=n_days)
        base = int(hit.sum()) / len(hit)
        oos = []
        per_month = []
        for mi, mo in enumerate(months):
            md = month_days[mo]
            hist = np.concatenate([month_days[m] for m in months[:mi]]) if mi else np.array([], dtype=int)
            if len(hist) < 60:
                per_month.append((mo, [], 0, 0, 0.0, 0, '历史不足->弃权'))
                continue
            hc = cnt[:, hist].sum(1); hh = hitd[:, hist].sum(1)
            with np.errstate(invalid='ignore', divide='ignore'):
                hp = np.where(hc > 0, hh / np.maximum(hc, 1), 0.0)
            cand = np.flatnonzero((hp >= QUAL_PREC) & (hc >= MIN_HIST_SIGNALS))
            if cand.size == 0:
                per_month.append((mo, [], 0, 0, 0.0, 0, '无历史达标规则->弃权'))
                continue
            # 贪心 union (用历史实盘算精度地板, 覆盖优先)
            sel = []
            uc = np.zeros(n_days, dtype=np.int32)
            uh = np.zeros(n_days, dtype=np.int32)
            for _ in range(MAX_ENSEMBLE):
                best = None; best_score = (-1, -1.0, -1)
                for r in cand:
                    if r in sel:
                        continue
                    tc = (uc + cnt[r])[hist].sum(); th = (uh + hitd[r])[hist].sum()
                    if tc < MIN_HIST_SIGNALS or th / tc < PREC_FLOOR:
                        continue
                    new_days = int((((uc == 0) & (cnt[r] > 0))[hist]).sum())
                    score = (new_days, th / tc, tc)
                    if score > best_score:
                        best_score = score; best = r
                if best is None:
                    break
                sel.append(int(best)); uc = uc + cnt[best]; uh = uh + hitd[best]
            if not sel:
                per_month.append((mo, [], 0, 0, 0.0, 0, '无合格组合->弃权'))
                continue
            um = np.zeros(len(feats), dtype=bool)
            for r in sel:
                um |= rule_masks[r]
            m_idx = np.array([i for i in range(len(feats)) if day_idx[i] in set(md.tolist())])
            chosen = m_idx[um[m_idx]]
            n_sig = len(chosen); ex = int(hit[chosen].sum())
            cov = int((cnt[sel][:, md].sum(0) > 0).sum())
            rs = ' | '.join(' & '.join(rule_desc[r]) for r in sel[:2])
            per_month.append((mo, sel, n_sig, ex, ex / n_sig if n_sig else 0, cov, rs))
            for i in chosen:
                oos.append({'date': meta[i]['date'], 'code': meta[i]['code'],
                            'name': meta[i]['name'], 'hit': bool(hit[i]), 'rule': rs})
        n = len(oos); tp = sum(1 for x in oos if x['hit'])
        sig_days = len({x['date'] for x in oos})
        out[tgt] = {'n': n, 'tp': tp, 'prec': tp / n if n else 0, 'base': base,
                    'sig_days': sig_days, 'total_days': n_days,
                    'monthly': [(m, ns, ex, p, cov, rs) for m, s, ns, ex, p, cov, rs in per_month],
                    'rules_used': Counter(x['rule'] for x in oos).most_common(12),
                    'oos': oos}
        print(f'\n涨{tgt*100:.0f}%: 信号 {n} | 命中 {tp} | precision {tp/max(n,1)*100:.1f}% '
              f'| 有信号 {sig_days}/{n_days} 天 ({sig_days/n_days*100:.0f}%) | 基线 {base*100:.1f}%')

    print('\n' + '=' * 92)
    print(f"{'目标':<9}{'OOS精度':>10}{'信号':>8}{'命中':>8}{'有信号天':>10}{'覆盖%':>8}{'基线':>8}{'提升':>8}")
    for tgt, r in out.items():
        print(f"{'涨'+format(tgt*100,'.0f')+'%':<9}{r['prec']*100:>9.1f}%{r['n']:>8}{r['tp']:>8}"
              f"{r['sig_days']:>6}/{r['total_days']:<4}{r['sig_days']/r['total_days']*100:>7.0f}%"
              f"{r['base']*100:>7.1f}%{r['prec']/max(r['base'],1e-9):>7.1f}x")
    print('=' * 92)

    for tgt in TARGETS:
        r = out[tgt]
        if r['prec'] < PREC_FLOOR:
            print(f"\n涨{tgt*100:.0f}% 精度未达 70%, 逐月:")
            for mo, ns, ex, p, cov, rs in r['monthly']:
                print(f'  {mo}: 信号 {ns:>3} 命中 {ex:>3} 精度 {p*100:>5.0f}% 覆盖天 {cov:>3}  {rs[:50]}')

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({str(k): {kk: vv for kk, vv in v.items() if kk != 'oos'}
                   for k, v in out.items()}, f, ensure_ascii=False, indent=1)
    print(f'\n{OUT}  用时 {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
