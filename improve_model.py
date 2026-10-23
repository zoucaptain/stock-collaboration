#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
improve_model.py — 预测准确率提升实验 (2026-10-23)

用户问: "怎样提高预测准确率?"

诊断 (基于 10/22->10/23 实际):
  - Top1 命中 +7.00% (皇台酒业) 但大洋电机 +9.77% 模型只排第 7
  - 根因: 当前模型标签是 "next_high_ret > 0" (会不会涨)
          但目标是 "next_high_ret >= +5%" (能不能涨 5%)
  - 涨 5% 的样本与"只是上涨"的样本特征完全不同 (c5/lu/量能/位置)

本脚本做 4 项改动, 全部 walk-forward 实测, 只认 OOS:
  1. 标签: 改为直接学 +5% (并保留 +3% / 上涨 做对比)
  2. 特征+: 市场情绪 (池内涨跌家数/涨停数/均涨幅) + 指数多周期位置
  3. 特征+: 弹性因子 (c5 + lu + 量比) -> 动量票排序提前
  4. 样本: 历史从 2 年拉到 ~3.5 年 (1200 天)

输出: 各种标签/特征组合的 OOS 对比表 -> 选最优 -> 存新模型
"""
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predict_next_day import _pool_from_json, sina_kline

CACHE = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'cache', 'scratch',
    'improve_data.json'))
MODEL = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'cache', 'scratch',
    'improve_model.json'))
DAYS = 1200


# ---------------------------------------------------------------- 取数
def tx_kline_long(code, days=DAYS):
    """长历史: 腾讯优先 -> 东财 fqt=1 -> 新浪
    腾讯最多只给 ~641 根, 不足则并入新浪的更长序列"""
    p = 'sh' if code.startswith('6') else 'sz'
    best = []
    for u in (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={p}{code},day,,,{days},qfq',
              f'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={p}{code},day,,,{days},qfq'):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=25).read())
            kl = (d['data'][p + code].get('qfqday') or d['data'][p + code].get('day') or [])
            out = []
            for x in kl:
                try:
                    out.append({'d': x[0], 'o': float(x[1]), 'c': float(x[2]),
                                'h': float(x[3]), 'l': float(x[4]), 'v': float(x[5])})
                except Exception:
                    pass
            if len(out) > len(best):
                best = out
        except Exception:
            pass
    if len(best) < 900:
        alt = sina_kline(code, days)
        if len(alt) > len(best):
            best = alt
    return best


def tx_index(code, days=DAYS):
    for u in (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq',
              f'https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,,,{days}'):
        try:
            req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
            d = json.loads(urllib.request.urlopen(req, timeout=25).read())
            node = d['data'].get(code) or {}
            kl = (node.get('qfqday') or node.get('day') or [])
            out = []
            for x in kl:
                try:
                    out.append({'d': x[0], 'c': float(x[2]), 'h': float(x[3]), 'l': float(x[4])})
                except Exception:
                    pass
            if len(out) > 200:
                return out
        except Exception:
            pass
    return []


# ---------------------------------------------------------------- 特征
BASE_FEATS = ['c1', 'c3', 'c5', 'c10', 'c20', 'c30', 'c60', 'gap', 'closepos',
              'vratio', 'vrel20', 'pos30', 'pos90', 'dist_hi250', 'amp30', 'amp5',
              'amp_ratio', 'ma_bull', 'ma20_gap', 'ma5_gap', 'lu', 'updays',
              'downdays']
IDX_FEATS = ['sh_1d', 'cyb_1d', 'sh_c5', 'cyb_c5', 'sh_c20', 'cyb_c20',
             'sh_pos30', 'cyb_pos30', 'sh_pos90', 'cyb_pos90']
# 新增: 弹性因子 + 市场情绪
ELASTIC = ['el_c5', 'el_lu', 'el_vr', 'el_score', 'el_ma20gap', 'el_cpos']
SENTI = ['mkt_upratio', 'mkt_limitup', 'mkt_mean', 'mkt_range', 'mkt_idx_up']


def build():
    if os.path.exists(CACHE):
        with open(CACHE, encoding='utf-8') as f:
            b = json.load(f)
        return b['klines'], b['index']
    pool = _pool_from_json()
    print(f'股票池 {len(pool)} 只, 取 {DAYS} 天历史...')
    klines = {}
    for code, name in pool:
        k = tx_kline_long(code)
        print(f'  {code} {name}: {len(k)} 根')
        if len(k) > 200:
            klines[code] = {'name': name, 'k': k}
    index = {}
    for code, tag in (('sh000001', 'sh'), ('sz399006', 'cyb')):
        k = tx_index(code)
        print(f'  指数 {code}: {len(k)} 根')
        if len(k) > 200:
            index[tag] = {x['d']: x for x in k}
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump({'klines': klines, 'index': index}, f)
    return klines, index


def features_from(klines, index, include_last=False):
    """生成样本: features dict + meta
    include_last=True -> 包含每只股票最后一行 (用于生产预测, 无需次日标签)"""
    rows = []
    for code, blob in klines.items():
        k = blob['k']
        c = [x['c'] for x in k]; h = [x['h'] for x in k]
        l = [x['l'] for x in k]; v = [x['v'] for x in k]; o = [x['o'] for x in k]
        end = len(k) if include_last else len(k) - 1
        for i in range(250, end):
            w30 = slice(max(0, i - 29), i + 1)
            w90 = slice(max(0, i - 89), i + 1)
            w250 = slice(max(0, i - 249), i + 1)
            rng = h[i] - l[i]
            v5 = sum(v[i - 5:i]) / 5; v20 = sum(v[i - 20:i]) / 20
            lo30, hi30 = min(l[w30]), max(h[w30])
            lo90, hi90 = min(l[w90]), max(h[w90])
            ma5 = sum(c[i - 4:i + 1]) / 5; ma10 = sum(c[i - 9:i + 1]) / 10
            ma20 = sum(c[i - 19:i + 1]) / 20; ma60 = sum(c[i - 59:i + 1]) / 60
            lb = 0
            for j in range(i, 0, -1):
                if (c[j] - c[j - 1]) / c[j - 1] >= 0.095: lb += 1
                else: break
            up = 0
            for j in range(i, 0, -1):
                if c[j] > c[j - 1]: up += 1
                else: break
            dn = 0
            for j in range(i, 0, -1):
                if c[j] < c[j - 1]: dn += 1
                else: break
            c5 = (c[i] - c[i - 5]) / c[i - 5] * 100
            vr = v[i] / v5 if v5 else 1
            cpos = (c[i] - l[i]) / rng * 100 if rng > 0 else 50
            magap = (c[i] / ma20 - 1) * 100
            rows.append({
                'code': code, 'name': blob['name'], 'date': k[i]['d'],
                'next_date': k[i + 1]['d'] if i + 1 < len(k) else k[i]['d'],
                'closepos': cpos, 'vratio': vr, 'vrel20': v[i] / v20 if v20 else 1,
                'pos30': (c[i] - lo30) / (hi30 - lo30) * 100 if hi30 > lo30 else 50,
                'pos90': (c[i] - lo90) / (hi90 - lo90) * 100 if hi90 > lo90 else 50,
                'dist_hi250': (c[i] / max(h[w250]) - 1) * 100,
                'amp30': sum(h[j] - l[j] for j in range(i - 29, i + 1)) / 30,
                'amp5': sum(h[j] - l[j] for j in range(i - 4, i + 1)) / 5,
                'amp_ratio': (sum(h[j] - l[j] for j in range(i - 4, i + 1)) / 5) /
                             max(sum(h[j] - l[j] for j in range(i - 29, i + 1)) / 30, 1e-9),
                'ma_bull': 1.0 if (ma5 > ma10 > ma20 > ma60) else 0.0,
                'ma20_gap': magap, 'ma5_gap': (c[i] / ma5 - 1) * 100,
                'c1': (c[i] - c[i - 1]) / c[i - 1] * 100,
                'c3': (c[i] - c[i - 3]) / c[i - 3] * 100,
                'c5': c5, 'c10': (c[i] - c[i - 10]) / c[i - 10] * 100,
                'c20': (c[i] - c[i - 20]) / c[i - 20] * 100,
                'c30': (c[i] - c[i - 30]) / c[i - 30] * 100,
                'c60': (c[i] - c[i - 60]) / c[i - 60] * 100,
                'gap': (o[i] / c[i - 1] - 1) * 100,
                'lu': lb, 'updays': up, 'downdays': dn,
                'px': c[i],
                'next_high_ret': (h[i + 1] / c[i] - 1) if i + 1 < len(k) else 0.0})
    # ---- 弹性因子 (排序用)
    for r in rows:
        r['el_c5'] = r['c5']
        r['el_lu'] = r['lu']
        r['el_vr'] = r['vratio']
        r['el_ma20gap'] = r['ma20_gap']
        r['el_cpos'] = r['closepos']
        # 弹性分: 动量 + 连板 + 放量 + 强收盘, 归一到 0~1
        s = (min(r['c5'] / 30, 2.0) * 1.0 + min(r['lu'], 3) * 0.8
             + min(r['vratio'], 3.0) * 0.4 + max(r['ma20_gap'], 0) / 20 * 0.6
             + r['closepos'] / 100 * 0.5)
        r['el_score'] = s
    # ---- 市场情绪 (按日聚合)
    bydate = {}
    for r in rows:
        bydate.setdefault(r['date'], []).append(r)
    for d, rs in bydate.items():
        n = len(rs)
        ups = sum(1 for x in rs if x['c1'] > 0)
        lus = sum(1 for x in rs if x['c1'] >= 9.5)
        mean = sum(x['c1'] for x in rs) / n
        rng = (max(x['c1'] for x in rs) - min(x['c1'] for x in rs))
        for x in rs:
            x['mkt_upratio'] = ups / n
            x['mkt_limitup'] = lus
            x['mkt_mean'] = mean
            x['mkt_range'] = rng
            x['mkt_idx_up'] = 1.0 if mean > 0 else 0.0
    # ---- 指数特征
    for tag, dat in index.items():
        cl = [dat[d]['c'] for d in sorted(dat)]
        hd = [dat[d]['h'] for d in sorted(dat)]
        ld = [dat[d]['l'] for d in sorted(dat)]
        dd = [d for d in sorted(dat)]
        pos = {d: i for i, d in enumerate(dd)}
        for r in rows:
            i = pos.get(r['date'])
            if i is None or i < 90:
                continue
            c = cl[i]; h = hd[i]; l = ld[i]
            w30 = slice(max(0, i - 29), i + 1); w90 = slice(max(0, i - 89), i + 1)
            lo30, hi30 = min(ld[w30]), max(hd[w30])
            lo90, hi90 = min(ld[w90]), max(hd[w90])
            r[f'{tag}_1d'] = (c - cl[i - 1]) / cl[i - 1] * 100
            r[f'{tag}_c5'] = (c - cl[i - 5]) / cl[i - 5] * 100
            r[f'{tag}_c20'] = (c - cl[i - 20]) / cl[i - 20] * 100
            r[f'{tag}_pos30'] = (c - lo30) / (hi30 - lo30) * 100 if hi30 > lo30 else 50
            r[f'{tag}_pos90'] = (c - lo90) / (hi90 - lo90) * 100 if hi90 > lo90 else 50
    return rows


# ---------------------------------------------------------------- 模型
def fit_logreg(X, y, l2=1.0, epochs=350, lr=0.4):
    n, d = X.shape
    Xb = np.hstack([X, np.ones((n, 1))])
    w0 = np.zeros(d + 1)
    for _ in range(epochs):
        z = Xb @ w0
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        g = Xb.T @ (p - y) / n
        g[1:] += l2 * w0[1:] / n
        w0 -= lr * g
    return w0


def proba(X, w0):
    z = np.hstack([X, np.ones((len(X), 1))]) @ w0
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def run(Xs, y, dates, day_idx, n_days, target_label, feature_set, tag, nhr):
    """walk-forward: 每月重训, 出 Top1/Top3
    评判口径**统一**: Top1/Top3 是否次日涨 +5% (业务目标), 与训练标签无关"""
    months = sorted({d[:7] for d in dates})
    day_to_s = {d: np.flatnonzero(day_idx == d) for d in range(n_days)}
    month_s = {}
    for mo in months:
        idxs = [i for i, d in enumerate(dates) if d[:7] == mo]
        month_s[mo] = np.concatenate([day_to_s[i] for i in idxs])
    oos = []
    for mi, mo in enumerate(months):
        hist = np.concatenate([month_s[m] for m in months[:mi]]) if mi else np.array([], int)
        if len(hist) < 800:
            continue
        w0 = fit_logreg(Xs[hist], y[hist])
        for d in np.unique(day_idx[month_s[mo]]):
            sel = month_s[mo][day_idx[month_s[mo]] == d]
            p = proba(Xs[sel], w0)
            order = np.argsort(-p)
            for rank in (1, 3):
                tsel = sel[order[:rank]]
                for i in tsel:
                    oos.append({'mo': mo, 'date': dates[d], 'rank': rank,
                                'hi5': bool(nhr[i] >= 0.05),
                                'up': bool(nhr[i] > 0),
                                'ret': float(nhr[i]),
                                'labelhit': bool(y[i])})
    top1 = [x for x in oos if x['rank'] == 1]
    top3 = [x for x in oos if x['rank'] == 3]
    n1 = len(top1); h1 = sum(x['hi5'] for x in top1)
    n3 = len(top3)
    h3 = 0
    byd = {}
    for x in top3:
        byd.setdefault(x['date'], []).append(x['hi5'])
    h3 = sum(1 for v in byd.values() if any(v))
    n3d = len(byd)
    return {'tag': tag, 'n1': n1, 'h1': h1, 'p1': h1 / n1 if n1 else 0,
            'n3': n3d, 'h3': h3, 'p3': h3 / n3d if n3d else 0,
            'up1': sum(x['up'] for x in top1) / n1 if n1 else 0,
            'lab1': sum(x['labelhit'] for x in top1) / n1 if n1 else 0,
            'oos': top1}


def main():
    t0 = time.time()
    klines, index = build()
    rows = features_from(klines, index)
    rows = [r for r in rows if r.get('sh_1d') is not None and r.get('cyb_1d') is not None]
    print(f'样本 {len(rows)} 行 | {rows[0]["date"]} ~ {rows[-1]["date"]}')

    dates = sorted({r['date'] for r in rows})
    di = {d: i for i, d in enumerate(dates)}
    day_idx = np.array([di[r['date']] for r in rows])
    n_days = len(dates)
    nhr = np.array([r['next_high_ret'] for r in rows])

    base = BASE_FEATS + IDX_FEATS
    sets = {
        'A 旧版(上涨标签,基础特征)': (base, (nhr > 0).astype(float)),
        'B 上涨标签+新特征': (base + ELASTIC + SENTI, (nhr > 0).astype(float)),
        'C +3%标签+新特征': (base + ELASTIC + SENTI, (nhr >= 0.03).astype(float)),
        'D +5%标签+新特征': (base + ELASTIC + SENTI, (nhr >= 0.05).astype(float)),
        'E +5%标签+仅弹性': (ELASTIC + SENTI + ['c5', 'lu', 'vratio', 'closepos', 'pos30'],
                             (nhr >= 0.05).astype(float)),
    }
    print(f'\n{"配置":<28}{"Top1涨5%":>11}{"n":>7}{"Top3含涨5%":>12}{"n":>7}{"Top1上涨":>11}')
    results = {}
    for tag, (feats, y) in sets.items():
        X = np.column_stack([np.nan_to_num(np.array([r.get(f, 0.0) for r in rows]),
                                           nan=0.0) for f in feats])
        mu, sd = X.mean(0), X.std(0); sd[sd == 0] = 1
        Xs = (X - mu) / sd
        res = run(Xs, y, dates, day_idx, n_days, tag, feats, tag, nhr)
        results[tag] = (res, feats, mu, sd, y)
        print(f"{tag:<28}{res['p1']*100:>10.1f}%{res['n1']:>7}{res['p3']*100:>11.1f}%{res['n3']:>7}"
              f"{res['up1']*100:>10.1f}%")

    # 基线
    base_rate = float((nhr >= 0.05).mean())
    print(f"\n基线 (池内任一只次日涨5%): {base_rate*100:.1f}%")

    # 最优
    best_tag = max(results, key=lambda t: results[t][0]['p1'])
    res, feats, mu, sd, y = results[best_tag]
    print(f"\n🏆 最优 (按 Top1 涨5% 精度): {best_tag}")
    print(f"   Top1 涨5% 精度 {res['p1']*100:.1f}% (n={res['n1']}, 基线 {base_rate*100:.1f}%, 提升 {res['p1']/base_rate:.1f}x)")
    print(f"   Top3 至少1只涨5% {res['p3']*100:.1f}% (n={res['n3']})")
    print(f"   Top1 次日上涨 {res['up1']*100:.1f}%")

    # 逐月
    print(f"\n{'月份':<9}{'天':>5}{'Top1涨5%命中':>13}{'精度':>9}")
    bym = {}
    for x in res['oos']:
        bym.setdefault(x['mo'], []).append(x['hi5'])
    for mo in sorted(bym):
        v = bym[mo]
        print(f"{mo:<9}{len(v):>5}{sum(v):>13}{sum(v)/len(v)*100:>8.0f}%")

    # ---- 精度/覆盖曲线: 找 precision>=70% 的最大覆盖操作点
    print('\n' + '=' * 76)
    print('【精度-覆盖曲线】(用 E 配置: +5%标签+弹性, 903 个 OOS 日)')
    print('  按模型给 Top1 的概率从高到低排, 逐档看精度/覆盖')
    print('=' * 76)
    for tag in ['E +5%标签+仅弹性', 'D +5%标签+新特征']:
        res, feats, mu, sd, y = results[tag]
        # 重跑一次拿到 p
        X = np.column_stack([np.nan_to_num(np.array([r.get(f, 0.0) for r in rows]), nan=0.0)
                              for f in feats])
        Xs = (X - mu) / sd
        pts = []
        months = sorted({d[:7] for d in dates})
        day_to_s = {d: np.flatnonzero(day_idx == d) for d in range(n_days)}
        month_s = {mo: np.concatenate([day_to_s[i] for i in range(n_days)
                                       if dates[i][:7] == mo]) for mo in months}
        for mi, mo in enumerate(months):
            hist = np.concatenate([month_s[m] for m in months[:mi]]) if mi else np.array([], int)
            if len(hist) < 800:
                continue
            w0 = fit_logreg(Xs[hist], y[hist])
            for d in np.unique(day_idx[month_s[mo]]):
                sel = month_s[mo][day_idx[month_s[mo]] == d]
                p = proba(Xs[sel], w0)
                i0 = sel[np.argmax(p)]
                pts.append((float(p.max()), bool(nhr[i0] >= 0.05)))
        pts.sort(key=lambda x: -x[0])
        N = len(pts)
        print(f'\n--- {tag} ---')
        print(f"{'取前%':>8}{'天数':>6}{'命中':>6}{'精度':>9}")
        best70 = None
        for frac in (1.0, 0.6, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05):
            k = max(1, int(N * frac))
            sub = pts[:k]
            hp = sum(1 for _, h in sub if h)
            p = hp / k
            star = ''
            if p >= 0.70 and best70 is None:
                best70 = (frac, k, p)
                star = '  <= 首个 >=70%'
            print(f"{frac*100:>7.0f}%{k:>6}{hp:>6}{p*100:>8.1f}%{star}")
        if best70:
            print(f"  🎯 满足 >=70% 的最大覆盖: 取前 {best70[0]*100:.0f}% "
                  f"({best70[1]}/{N} 天), 精度 {best70[2]*100:.1f}%")
            # 把阈值换算成**概率值** (可跨时间用, 不是历史分位)
            thr = pts[best70[1] - 1][0]
            curve = []
            for frac in (1.0, 0.6, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1, 0.05):
                k = max(1, int(N * frac))
                sub = pts[:k]
                hp = sum(1 for _, h in sub if h)
                curve.append({'frac': frac, 'days': k, 'hit': hp,
                              'prec': hp / k, 'p_thr': pts[k - 1][0]})
            print(f"     对应概率阈值 p >= {thr:.4f}  (覆盖 {best70[0]*100:.0f}% 交易日)")
            results[f'_curve_{tag}'] = curve
            results[f'_thr_{tag}'] = thr
        else:
            print('  ❌ 即使只取概率最高的 5% 也达不到 70%')
            results[f'_curve_{tag}'] = []
            results[f'_thr_{tag}'] = 0.0

    # 存模型 (全部历史重训)
    # 注意: 上面 curve 循环里 res/feats 被覆盖成最后一个 config, 这里必须取回最优
    res, feats, mu, sd, y = results[best_tag]
    X = np.column_stack([np.nan_to_num(np.array([r.get(f, 0.0) for r in rows]), nan=0.0)
                          for f in feats])
    Xs = (X - mu) / sd
    w0 = fit_logreg(Xs, y)
    json.dump({'feats': feats, 'mu': mu.tolist(), 'sd': sd.tolist(), 'w0': w0.tolist(),
               'label': best_tag, 'thr': results.get(f'_thr_{best_tag}', 0.0),
               'curve': results.get(f'_curve_{best_tag}', []),
               'oos': {'p1': res['p1'], 'n1': res['n1'],
                       'p3': res['p3'], 'n3': res['n3'],
                       'up1': res['up1'],
                       'base_rate': base_rate}},
              open(MODEL, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n模型 {MODEL} | 用时 {time.time()-t0:.0f}s')


if __name__ == '__main__':
    main()
