#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
verify_rule.py — 定稿规则的独立复核 (不看搜索过程, 只用最终规则重算)

2026-10-22 立。
目的: 防止"搜索出来的高 precision 是选择偏差"。
复核项:
  1. 全期 / 训练 / 样本外 三段 precision 独立重算
  2. 逐月 + 逐季 precision (看是否有断崖月份)
  3. 分股票 (哪类票贡献了命中, 哪类全是误报)
  4. 基准对照: 同天"全池随机选同数量" 的期望命中数
  5. Top1 截断后的 precision (每天只出 1 只, 实战只押 1 只)
  6. 用规则跑今天 (10/22) 会选哪几只 + 明天预测
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
        time.sleep(0.2)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    return out


def features(k, i):
    if i < 120:
        return None
    c = [x['c'] for x in k]; h = [x['h'] for x in k]
    l = [x['l'] for x in k]; v = [x['v'] for x in k]
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
    return {'closepos': closepos, 'vratio': v[i] / v5 if v5 else 1,
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
            'next_high_ret': h[i + 1] / c[i] - 1,
            'next_close_ret': c[i + 1] / c[i] - 1}


def main():
    with open(os.path.join(REPO, 'predict_rule.json'), encoding='utf-8') as f:
        rule = json.load(f)
    print(f"规则: {rule['name']}")
    print(f"  条件: {' AND '.join(f'{a}{o}{t}' for a, o, t in rule['conds'])}\n")

    data = load_klines()
    rows = []
    for code, blob in data.items():
        k = blob['k']
        for i in range(120, len(k) - 1):
            f = features(k, i)
            if f:
                f['name'] = blob['name']
                f['date'] = k[i]['d']
                f['next_date'] = k[i + 1]['d']
                rows.append(f)

    def ok(f):
        for (feat, op, th) in rule['conds']:
            v = f[feat]
            if (op == '>=' and not v >= th) or (op == '<=' and not v <= th):
                return False
        return True

    picked = [f for f in rows if ok(f)]
    hit = [f for f in picked if f['next_high_ret'] >= TARGET]
    print("=" * 76)
    print(f"【独立复核】全期 {len(picked)} 次预测, 命中 {len(hit)} = {len(hit)/max(len(picked),1)*100:.1f}%")
    base = sum(1 for f in rows if f['next_high_ret'] >= TARGET) / len(rows)
    print(f"  基线 {base*100:.2f}%  |  提升 {len(hit)/max(len(picked),1)/base:.1f} 倍")
    print("=" * 76)

    dates = sorted({f['date'] for f in rows})
    split_i = int(len(dates) * 0.6)
    tr = [f for f in picked if f['date'] < dates[split_i]]
    ou = [f for f in picked if f['date'] >= dates[split_i]]
    for nm, sub in (("训练段", tr), ("样本外", ou), ("全期", picked)):
        t = sum(1 for f in sub if f['next_high_ret'] >= TARGET)
        print(f"  {nm:<8} {t}/{len(sub)} = {t/max(len(sub),1)*100:.1f}%")

    print("\n=== 逐季 precision (查断崖) ===")
    q = {}
    for f in picked:
        y, m = f['date'][:4], int(f['date'][5:7])
        kq = f"{y}Q{(m-1)//3+1}"
        q.setdefault(kq, []).append(f)
    for kq in sorted(q):
        sub = q[kq]
        t = sum(1 for f in sub if f['next_high_ret'] >= TARGET)
        print(f"  {kq}: {t}/{len(sub)} = {t/max(len(sub),1)*100:.0f}%")

    print("\n=== 逐股票 (命中来自谁) ===")
    per = {}
    for f in picked:
        per.setdefault(f['name'], []).append(f)
    for nm, sub in sorted(per.items(), key=lambda x: -len(x[1])):
        t = sum(1 for f in sub if f['next_high_ret'] >= TARGET)
        print(f"  {nm:<10} {t}/{len(sub)} = {t/len(sub)*100:>5.1f}%")

    print("\n=== Top1 截断 (每天只出 1 只) ===")
    byday = {}
    for f in picked:
        byday.setdefault(f['date'], []).append(f)
    for K in (1, 2):
        tp = n = 0
        for d, lst in byday.items():
            lst.sort(key=lambda x: -x['next_high_ret'])
            # 排序用当日可知信息: c5 + lu (动量强度)
            lst.sort(key=lambda x: -(x['c5'] + x['lu'] * 10))
            for f in lst[:K]:
                n += 1
                if f['next_high_ret'] >= TARGET:
                    tp += 1
        print(f"  每日 Top{K}: {tp}/{n} = {tp/max(n,1)*100:.1f}%  (覆盖 {len(byday)} 个有信号日)")

    print("\n=== 规则命中日分布 ===")
    print(f"  有信号的交易日: {len(byday)} / {len(dates)} ({len(byday)/len(dates)*100:.0f}%)")
    print(f"  平均每日命中数: {len(picked)/len(byday):.2f} 只")

    # 今天 (最新) 会选谁
    last_date = max(d for d in byday)
    print(f"\n=== 最近有信号的交易日: {last_date} ===")
    for f in sorted(byday[last_date], key=lambda x: -(x['c5'] + x['lu'] * 10)):
        print(f"  {f['name']:<10} c5={f['c5']:>6.1f}% lu={f['lu']} c10={f['c10']:>6.1f}% "
              f"-> 次日最高 {f['next_high_ret']*100:>+6.2f}% "
              f"{'✅命中' if f['next_high_ret']>=TARGET else '❌'}")

    # 今天收盘状态 (最新一根) 会不会入选
    print("\n=== 最新交易日 (今日收盘) 状态 ===")
    today = max(f['date'] for f in rows)
    today_rows = [f for f in rows if f['date'] == today]
    tpicks = [f for f in today_rows if ok(f)]
    print(f"  日期 {today} | 池内 {len(today_rows)} 只 | 符合规则 {len(tpicks)} 只")
    for f in tpicks:
        print(f"    {f['name']:<10} c5={f['c5']:>6.1f}% lu={f['lu']} c10={f['c10']:>6.1f}% "
              f"c30={f['c30']:>6.1f}% px={f['px']}")
    if not tpicks:
        print("    ⛔ 无符合 -> 按规则弃权")

    out = {'rule': rule['name'], 'full_n': len(picked), 'full_hits': len(hit),
           'full_prec': len(hit) / max(len(picked), 1), 'baseline': base,
           'train_prec': sum(1 for f in tr if f['next_high_ret'] >= TARGET) / max(len(tr), 1),
           'out_prec': sum(1 for f in ou if f['next_high_ret'] >= TARGET) / max(len(ou), 1),
           'train_n': len(tr), 'out_n': len(ou),
           'quarterly': {k: (sum(1 for f in v if f['next_high_ret'] >= TARGET), len(v))
                         for k, v in q.items()},
           'signal_days': len(byday), 'total_days': len(dates),
           'today': today, 'today_picks': [f['name'] for f in tpicks]}
    with open(os.path.abspath(os.path.join(os.path.dirname(CACHE), 'verify_result.json')),
              'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n保存 verify_result.json")


if __name__ == '__main__':
    main()
