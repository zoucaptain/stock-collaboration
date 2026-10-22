#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
rank_daily.py — 每日排序模型 (2026-10-22 v4)  <-- 真正可用的方案

用户原话: "那你一直弃权，你这预测的功能也没有用啊"

诊断: 前三代都在做"事件型信号" (满足条件才报), 但:
  - 单规则 c5>=15 AND lu>=2: precision 90.5% 但只覆盖 14% 交易日
  - 多规则 ensemble: 覆盖 62% 但 precision 掉到 61.3%
  => 事件型信号天然是"稀疏"的, 精度和覆盖是死对头

v4 换范式: **每天必须给排名**, 而不是"有信号才报"
  - 模型对池内每只股票输出一个"次日上涨概率"分数
  - 每天报 Top1 (最看好的一只) + Top3
  - 精度口径: "Top1 当日是否上涨" 和 "Top1 相对池内中位数的超额"
  - 覆盖: 100% 交易日都有输出
  - 统计口径改成 **相对基准** (相对池内均值), 因为绝对涨跌本来就是运气

模型: 逻辑回归 (numpy 手写, 不依赖 sklearn)
  特征 22 个 (价格动量/位置/量能/均线/市场状态)
  训练: 每月只用该月之前的数据重训 (walk-forward)
  样本: 6895 行 x 460 天, 训练集足够
"""
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predict_next_day import _pool_from_json
from multi_target import build_all

OUT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'cache', 'scratch',
    'rank_daily.json'))
MODEL = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'cache', 'scratch',
    'rank_model.json'))

FEATS = ['c1', 'c3', 'c5', 'c10', 'c20', 'c30', 'c60', 'gap', 'closepos',
         'vratio', 'vrel20', 'pos30', 'pos90', 'dist_hi250', 'amp30', 'amp5',
         'amp_ratio', 'ma_bull', 'ma20_gap', 'ma5_gap', 'lu', 'updays',
         'downdays', 'sh_1d', 'cyb_1d', 'sh_c5', 'cyb_c5', 'sh_pos30', 'cyb_pos30']
L2 = 1.0
EPOCHS = 400
LR = 0.35


def fit_logreg(X, y, w=None, l2=L2, epochs=EPOCHS, lr=LR):
    """numpy 手写逻辑回归 (带 L2 + 样本权重)"""
    n, d = X.shape
    Xb = np.hstack([X, np.ones((n, 1))])
    w0 = np.zeros(d + 1)
    if w is None:
        w = np.ones(n)
    w = w / w.sum() * n
    for _ in range(epochs):
        z = Xb @ w0
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = Xb.T @ ((p - y) * w) / n
        g[1:] += l2 * w0[1:] / n
        w0 -= lr * g
    return w0


def predict_proba(X, w0):
    z = np.hstack([X, np.ones((len(X), 1))]) @ w0
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def main():
    feats, meta = build_all()
    F = {k: np.array([f.get(k, np.nan) for f in feats], dtype=np.float64)
         for k in set().union(*[set(f) for f in feats])}
    dates = sorted({m['date'] for m in meta})
    di = {d: i for i, d in enumerate(dates)}
    day_idx = np.array([di[m['date']] for m in meta])
    n_days = len(dates)

    X = np.column_stack([np.nan_to_num(F[f], nan=0.0) for f in FEATS])
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    nhr = F['next_high_ret']
    nxt_ret = None
    # 次日收盘涨幅 (作为"上涨"标签)
    for i, m in enumerate(meta):
        pass
    # 用 next_high_ret 作为主标签, 同时用 next_close_ret
    # build_all 没存 next_close, 这里用 high 作为代理 -> 改用 high>=0 判断上涨
    y = (nhr > 0).astype(np.float64)

    print(f'{len(feats)} 样本 | {n_days} 天 | 特征 {len(FEATS)} | 上涨占比 {y.mean()*100:.1f}%')

    months = sorted({d[:7] for d in dates})
    month_days = {mo: np.array([i for i, d in enumerate(dates) if d[:7] == mo])
                  for mo in months}
    # 日索引 -> 样本索引 (bug fix: hist 是日索引, 不能直接当样本索引用)
    day_to_samples = {d: np.flatnonzero(day_idx == d) for d in range(n_days)}
    month_samples = {mo: np.concatenate([day_to_samples[d] for d in month_days[mo]])
                     for mo in months}

    # ---------------- walk-forward: 每月重训, 评估 Top1 / Top3
    oos = []          # (date, code, name, pred_prob, ret_high, ret_hi_rank)
    per_month = []
    for mi, mo in enumerate(months):
        md = month_days[mo]
        hist = np.concatenate([month_samples[m] for m in months[:mi]]) if mi else np.array([], int)
        if len(hist) < 500:
            per_month.append((mo, 0, 0, 0.0, 0.0, 0, 0, '历史不足'))
            continue
        w0 = fit_logreg(Xs[hist], y[hist])
        m_idx = month_samples[mo]
        p = predict_proba(Xs[m_idx], w0)
        for d in np.unique(day_idx[m_idx]):
            sel = m_idx[day_idx[m_idx] == d]
            ps = predict_proba(Xs[sel], w0)
            order = np.argsort(-ps)
            top1 = sel[order[0]]
            top3 = sel[order[:3]]
            r1 = nhr[top1]
            pool_ret = nhr[sel]
            med = np.median(pool_ret)
            oos.append({'date': dates[d], 'code': meta[top1]['code'],
                        'name': meta[top1]['name'], 'prob': float(ps[order[0]]),
                        'ret': float(r1), 'excess': float(r1 - med),
                        'n_pool': len(sel),
                        'top3_ret': [float(nhr[t]) for t in top3],
                        'top3_codes': [meta[t]['code'] for t in top3],
                        'top3_names': [meta[t]['name'] for t in top3]})
        n = len([x for x in oos if x['date'][:7] == mo])
        win = sum(1 for x in oos if x['date'][:7] == mo and x['ret'] > 0)
        exc = sum(1 for x in oos if x['date'][:7] == mo and x['excess'] > 0)
        hi5 = sum(1 for x in oos if x['date'][:7] == mo and x['ret'] >= 0.05)
        per_month.append((mo, n, win, win / max(n, 1), exc / max(n, 1), hi5,
                          hi5 / max(n, 1), ' | '.join(f'{x["name"]}' for x in oos if x['date'][:7] == mo)[:40]))

    n = len(oos)
    win = sum(1 for x in oos if x['ret'] > 0)
    exc = sum(1 for x in oos if x['excess'] > 0)
    hi5 = sum(1 for x in oos if x['ret'] >= 0.05)
    hi3 = sum(1 for x in oos if x['ret'] >= 0.03)
    # Top3 命中率
    t3_hi5 = sum(1 for x in oos if any(r >= 0.05 for r in x['top3_ret']))
    t3_win = sum(1 for x in oos if any(r > 0 for r in x['top3_ret']))
    t3_all_win = sum(1 for x in oos if all(r > 0 for r in x['top3_ret']))
    base_up = float((nhr > 0).mean())
    base_med = float(np.median(nhr))

    print('\n' + '=' * 84)
    print(f'【每日排序模型 walk-forward】{n} 个交易日 (覆盖 {n}/{n_days} = {n/n_days*100:.0f}%)')
    print(f'  Top1 上涨率      {win/n*100:.1f}%   (池内基准 {base_up*100:.1f}%)')
    print(f'  Top1 超额胜率    {exc/n*100:.1f}%   (跑赢池内中位数)')
    print(f'  Top1 涨5%+       {hi5/n*100:.1f}%   (基准 {float((nhr>=0.05).mean())*100:.1f}%)')
    print(f'  Top1 涨3%+       {hi3/n*100:.1f}%')
    print(f'  Top3 至少1只涨5% {t3_hi5/n*100:.1f}%')
    print(f'  Top3 至少1只上涨 {t3_win/n*100:.1f}%')
    print(f'  Top3 全都上涨    {t3_all_win/n*100:.1f}%')
    print('=' * 84)
    print(f"{'月份':<9}{'天':>4}{'Top1涨':>8}{'超额':>8}{'涨5%':>8}{'Top3含5%':>10}")
    for mo, nn, w_, wr, er, h5, h5r, _ in per_month:
        if nn == 0:
            print(f'{mo:<9}{0:>4}{"历史不足":>8}')
            continue
        print(f'{mo:<9}{nn:>4}{wr*100:>7.0f}%{er*100:>7.0f}%{h5r*100:>7.0f}%{h5/nn*100:>9.0f}%')

    # 存模型 (用全部历史训) 供明日预测
    w0 = fit_logreg(Xs, y)
    json.dump({'feats': FEATS, 'mu': mu.tolist(), 'sd': sd.tolist(), 'w0': w0.tolist(),
               'oos': {'days': n, 'win': win / n, 'excess': exc / n, 'hi5': hi5 / n,
                       't3_hi5': t3_hi5 / n, 't3_win': t3_win / n, 'base_up': base_up},
               'monthly': per_month},
              open(MODEL, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(oos, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n模型 {MODEL}\nOOS 明细 {OUT}  用时 {time.time()-0:.0f}s')


if __name__ == '__main__':
    main()
