#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
predict_next_day.py — 次日涨 5%+ 候选预测 (定稿规则) + 自动对账

2026-10-22 立。
背景: 10/21 我用拍脑袋的规则给"明天涨5%+"候选, 4 只全错 (0/4)。
      用 2 年历史做规则搜索 + walk-forward 验证, 选出可复现的定稿规则。

**核心纪律**:
  1. 规则必须有 OOS precision 数据支撑, 达不到就**弃权** (输出"无符合标的")
  2. 每天自动对账昨日预测, 累计真实准确率台账 -> accuracy_log.md
  3. 预测与事实严格分离: 预测只写 predict_YYYYMMDD.md, 事实写 accuracy_log.md

用法:
  python predict_next_day.py --predict     # 预测下一交易日
  python predict_next_day.py --score       # 对账昨日预测
  python predict_next_day.py --all         # 两个都做
  python predict_next_day.py --rule-info   # 打印规则 + OOS 准确率
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', '..', '..', '..', '..',
                                    'stock-collaboration'))
REPO = r"C:\Users\yanyan.zou\stock-collaboration"
SCRIPTS = os.path.dirname(os.path.abspath(__file__))
PRED_DIR = os.path.join(REPO, 'predictions')
LOG_FILE = os.path.join(REPO, 'accuracy_log.md')
RULE_FILE = os.path.join(REPO, 'predict_rule.json')

POOL = [
    ('002085', '万丰奥威'), ('600593', '大连圣亚'), ('600127', '金健米业'),
    ('002655', '共达电声'), ('002929', '润建股份'), ('600744', '华银电力'),
    ('600396', '华电辽能'), ('603099', '长白山'), ('601606', '长城军工'),
    ('001337', '四川黄金'), ('000099', '中信海直'), ('000995', '皇台酒业'),
    ('600199', '金种子酒'), ('600664', '哈药股份'),
]
TARGET = 0.05


# ---------------------------------------------------------------- 数据
def tx_kline(code, days=260):
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


def features(k, i):
    """用 <= i 的数据算特征 (无未来函数)"""
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
    return {
        'c1': (c[i] - c[i - 1]) / c[i - 1] * 100,
        'c5': (c[i] - c[i - 5]) / c[i - 5] * 100,
        'c10': (c[i] - c[i - 10]) / c[i - 10] * 100,
        'c20': (c[i] - c[i - 20]) / c[i - 20] * 100,
        'c30': (c[i] - c[i - 30]) / c[i - 30] * 100,
        'c60': (c[i] - c[i - 60]) / c[i - 60] * 100,
        'closepos': closepos, 'vratio': v[i] / v5 if v5 else 1,
        'vrel20': v[i] / v20 if v20 else 1,
        'pos30': pos30, 'pos90': pos90,
        'dist_hi250': (c[i] / hi250 - 1) * 100,
        'amp5': amp5, 'amp30': amp30, 'amp_ratio': amp5 / amp30 if amp30 else 0,
        'ma_bull': 1 if (ma5 > ma10 > ma20 > ma60) else 0,
        'ma20_gap': (c[i] / ma20 - 1) * 100, 'ma5_gap': (c[i] / ma5 - 1) * 100,
        'lu': lb, 'updays': up, 'px': c[i], 'date': k[i]['d'],
    }


def load_rule():
    if os.path.exists(RULE_FILE):
        with open(RULE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return None


def apply_rule(f, rule):
    """rule = {'conds': [[feat, op, th], ...], 'score': [{feat, dir, th}, ...]}"""
    for (feat, op, th) in rule['conds']:
        v = f[feat]
        ok = (v >= th) if op == '>=' else (v <= th)
        if not ok:
            return False
    return True


def score_rank(f, rule):
    """打分: 用于 Top1/Top2 排序"""
    s = 0.0
    for (feat, d, th) in rule.get('score', []):
        v = f[feat]
        if d == '>=':
            s += min(max((v - th) / max(th * 0.2, 1), 0), 3)
        else:
            s += min(max((th - v) / max(abs(th) * 0.2, 1), 0), 3)
    return s


# ---------------------------------------------------------------- 预测
def do_predict():
    rule = load_rule()
    if not rule:
        print("[predict] ⚠️ 无定稿规则 (predict_rule.json 缺失) -> 弃权, 不输出预测")
        return None
    print(f"[predict] 规则: {rule['name']} | OOS precision {rule['oos_precision']*100:.1f}% "
          f"(n={rule['oos_n']}, 基线 {rule['baseline']*100:.1f}%)")
    picks = []
    allf = []
    for code, name in POOL:
        k = tx_kline(code, 260)
        if len(k) < 125:
            continue
        f = features(k, len(k) - 1)
        if not f:
            continue
        f['code'] = code
        f['name'] = name
        allf.append(f)
        if apply_rule(f, rule):
            picks.append(f)
    if not picks:
        print("[predict] ⛔ 无股票满足规则 -> 弃权 (不硬凑)")
        out = {'date': datetime.now().strftime('%Y%m%d'), 'picks': [], 'abstain': True,
               'rule': rule['name']}
        os.makedirs(PRED_DIR, exist_ok=True)
        with open(os.path.join(PRED_DIR, f"predict_{out['date']}.json"), 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        return out
    picks.sort(key=lambda f: -score_rank(f, rule))
    print(f"[predict] 命中 {len(picks)} 只:")
    for f in picks:
        print(f"   {f['name']:<10} c30={f['c30']:>6.1f}% c5={f['c5']:>6.1f}% "
              f"c10={f['c10']:>6.1f}% lu={f['lu']} pos90={f['pos90']:>3.0f}% "
              f"amp5={f['amp5']:.2f} score={score_rank(f, rule):.2f}")
    out = {'date': datetime.now().strftime('%Y%m%d'),
           'picks': [{'code': f['code'], 'name': f['name'], 'px': f['px'],
                      'c30': round(f['c30'], 2), 'c5': round(f['c5'], 2),
                      'c10': round(f['c10'], 2), 'lu': f['lu'],
                      'pos90': round(f['pos90'], 1), 'amp5': round(f['amp5'], 2),
                      'score': round(score_rank(f, rule), 2)} for f in picks],
           'abstain': False, 'rule': rule['name']}
    os.makedirs(PRED_DIR, exist_ok=True)
    with open(os.path.join(PRED_DIR, f"predict_{out['date']}.json"), 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"[predict] 已写 {PRED_DIR}/predict_{out['date']}.json")
    return out


# ---------------------------------------------------------------- 对账
def do_score():
    """对账最近一个已有后续行情的预测"""
    if not os.path.isdir(PRED_DIR):
        print("[score] 无预测目录")
        return
    files = sorted([f for f in os.listdir(PRED_DIR) if f.startswith('predict_') and f.endswith('.json')])
    if not files:
        print("[score] 无预测文件")
        return
    # 找最近一个"次日已有行情"的预测
    for fn in reversed(files):
        with open(os.path.join(PRED_DIR, fn), encoding='utf-8') as fh:
            pred = json.load(fh)
        if not pred.get('picks'):
            print(f"[score] {fn}: 弃权日 (无预测), 跳过")
            continue
        results = []
        for p in pred['picks']:
            k = tx_kline(p['code'], 40)
            if len(k) < 2:
                continue
            base = p['px']
            # 预测日之后的第一个交易日
            nxt = None
            for x in k:
                if x['d'] > pred['date']:
                    nxt = x
                    break
            if not nxt:
                results.append({**p, 'next_date': None, 'ret': None, 'hit': None})
                continue
            ret = nxt['h'] / base - 1
            results.append({**p, 'next_date': nxt['d'], 'ret': ret,
                            'hit': ret >= TARGET})
        if all(r['hit'] is None for r in results):
            print(f"[score] {fn}: 次日行情未出, 跳过")
            continue
        # 写 accuracy_log
        tp = sum(1 for r in results if r['hit'])
        n = len(results)
        write_log(pred, results, tp, n)
        return
    print("[score] 没有可对账的预测")


def write_log(pred, results, tp, n):
    os.makedirs(REPO, exist_ok=True)
    new = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        if new:
            f.write("# 📊 预测准确率台账 — 次日涨 5%+ 候选\n\n")
            f.write("> 规则: `predict_rule.json` (2年历史 walk-forward 定稿)\n")
            f.write("> 判定: 次日**最高价**涨幅 >= 5% (盘中触及即算)\n")
            f.write("> 累计准确率 = 命中数 / 预测数\n\n")
        f.write(f"## {pred['date']} -> {results[0].get('next_date') or '待定'}\n\n")
        f.write(f"规则: {pred.get('rule','?')} | 预测 {n} 只 | **命中 {tp}** | "
                f"准确率 **{tp/n*100:.1f}%**\n\n")
        f.write("| 股票 | 预测价 | 次日 | 最高涨幅 | 命中 |\n|---|---|---|---|---|\n")
        for r in results:
            if r['hit'] is None:
                f.write(f"| {r['name']} | {r['px']} | 待定 | - | ⏳ |\n")
            else:
                f.write(f"| {r['name']} | {r['px']} | {r['next_date']} | "
                        f"{r['ret']*100:+.2f}% | {'✅' if r['hit'] else '❌'} |\n")
        f.write("\n")
    print(f"[score] 已对账 {pred['date']}: {tp}/{n} = {tp/n*100:.1f}%, 写入 {LOG_FILE}")


def rule_info():
    rule = load_rule()
    if not rule:
        print("[rule] 无规则文件")
        return
    print(f"规则名: {rule['name']}")
    print(f"条件: {' AND '.join(f'{a}{o}{t}' for a, o, t in rule['conds'])}")
    print(f"OOS precision: {rule['oos_precision']*100:.1f}% (n={rule['oos_n']})")
    print(f"基线: {rule['baseline']*100:.1f}%")
    print(f"提升: {rule['oos_precision']/rule['baseline']:.1f} 倍")
    print(f"回测区间: {rule.get('backtest_range','?')}")


if __name__ == '__main__':
    args = sys.argv[1:] or ['--all']
    if '--rule-info' in args:
        rule_info()
    elif '--predict' in args:
        do_predict()
    elif '--score' in args:
        do_score()
    else:
        do_score()
        do_predict()
