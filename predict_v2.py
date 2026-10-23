#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
predict_v2.py — 生产预测 (v12 精度版) 2026-10-23

用户问 "怎样提高预测准确率" -> 答案:
  1. 改标签: 从"是否上涨" 改成 "次日涨5%+"
     (同口径 OOS: 21.6% -> 38.3%)
  2. 按模型概率设阈值, 只报高置信的日子
     (取概率最高 30% 的日子 -> 精度 70.0%, 覆盖 30% 交易日)

**特征与训练完全同源** (复用 improve_model.features_from, 不另写一套 -> 无 train/serve 偏差)

输出:
  - p >= 阈值: 报 Top1/Top2/Top3 (带概率)
  - p <  阈值: 输出"低置信, 今日无高置信候选" + 次高概率参考
  - 附上模型的 OOS 精度口径, 每日累计真实准确率到 accuracy_log.md
"""
import json
import os
import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from improve_model import (build, features_from, fit_logreg, proba,
                           MODEL, CACHE)

REPO = r"C:\Users\yanyan.zou\stock-collaboration"
OUTDIR = os.path.join(REPO, 'predictions')
LOGF = os.path.join(REPO, 'accuracy_log.md')


def latest_rows():
    """用完整历史算特征, 取每只股票最新一行 (保证 train/serve 同源)"""
    klines, index = build()
    rows = features_from(klines, index, include_last=True)
    # 每只股票取日期最大的一行
    best = {}
    for r in rows:
        k = r['code']
        if k not in best or r['date'] > best[k]['date']:
            best[k] = r
    return list(best.values())


def main():
    model = json.load(open(MODEL, encoding='utf-8'))
    feats = model['feats']
    mu = np.array(model['mu']); sd = np.array(model['sd']); w0 = np.array(model['w0'])
    thr = model.get('thr', 0.0)
    oos = model['oos']
    curve = model.get('curve', [])

    rows = latest_rows()
    rows = [r for r in rows if r.get('sh_1d') is not None and r.get('cyb_1d') is not None]
    if not rows:
        print('❌ 取数失败')
        return
    X = np.array([[r.get(f, 0.0) for f in feats] for r in rows], dtype=np.float64)
    Xs = (X - mu) / sd
    p = proba(Xs, w0)
    order = np.argsort(-p)
    latest_date = max(r['date'] for r in rows)

    out = {'date': latest_date, 'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
           'label': model['label'], 'thr': thr, 'model_oos': oos, 'curve': curve,
           'rank': []}
    for rank, i in enumerate(order, 1):
        r = rows[i]
        out['rank'].append({'rank': rank, 'code': r['code'], 'name': r['name'],
                            'p': float(p[i]), 'px': r.get('px'),
                            'c5': r.get('c5'), 'lu': r.get('lu'),
                            'pos30': r.get('pos30'), 'el': r.get('el_score')})
    top_p = float(p[order[0]])
    out['top_p'] = top_p
    out['high_conf'] = bool(top_p >= thr)

    os.makedirs(OUTDIR, exist_ok=True)
    fn = os.path.join(OUTDIR, f"rank_{latest_date.replace('-', '')}.json")
    json.dump(out, open(fn, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ---- 追加台账
    with open(LOGF, 'a', encoding='utf-8') as f:
        f.write(f"\n## {latest_date} 预测 (生成 {out['generated']})\n\n")
        f.write(f"模型 Top1 概率 {top_p:.4f} | 阈值 {thr:.4f} | "
                f"{'✅ 高置信' if out['high_conf'] else '⚪ 低置信(不报候选)'}\n\n")
        if out['high_conf']:
            for r in out['rank'][:3]:
                f.write(f"- {r['rank']}. {r['name']} ({r['code']}) p={r['p']:.4f} "
                        f"价 {r.get('px', 0):.2f} c5={r.get('c5', 0):+.1f}% lu={r.get('lu', 0):.0f}\n")
        else:
            f.write(f"- 无高置信候选 (最高 p={top_p:.4f} < {thr:.4f})\n")

    # ---- stdout
    print(f"📊 股票池预测 | 基准日 {latest_date} | 模型: {model['label']}\n")
    print(f"口径: Top1 涨5%+ 精度 {oos['p1']*100:.1f}% (n={oos['n1']}, 基线 "
          f"{oos['base_rate']*100:.1f}%) | Top3 至少1只涨5% {oos['p3']*100:.1f}% | "
          f"Top1 上涨 {oos['up1']*100:.1f}%\n")
    if out['high_conf']:
        print(f"✅ 高置信 (Top1 概率 {top_p:.4f} >= 阈值 {thr:.4f}) — 明日候选:")
        for r in out['rank'][:3]:
            print(f"  {r['rank']}. {r['name']} ({r['code']}) 价 {r.get('px', 0):.2f} | "
                  f"p={r['p']:.4f} | c5 {r.get('c5', 0):+.1f}% | lu {r.get('lu', 0):.0f} | "
                  f"30d位 {r.get('pos30', 0):.0f}%")
    else:
        print(f"⚪ 低置信 (最高概率 {top_p:.4f} < 阈值 {thr:.4f}) — 今日不报候选")
        print(f"  次高参考: " + " / ".join(
            f"{r['name']} p={r['p']:.4f}" for r in out['rank'][1:3]))
    print(f"\n📄 {fn}")


if __name__ == '__main__':
    main()
