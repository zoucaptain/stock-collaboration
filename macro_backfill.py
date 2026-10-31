#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""macro_backfill.py — 用修正后的取数与判定逻辑, 回溯重算历史外围结论

2026-10-30: 发现两处系统性错误
  (1) 美股链标签: else 分支把 3/3 全跌 与 3/3 全涨 都标成"涨跌互现"
  (2) Yahoo daily bar 日期套 UTC -> 亚洲市场(日经/恒生/台湾/韩国)整体错位 1 天
本脚本用**修正后**的取数(交易所当地时区) + **修正后**的判定逻辑, 重算每个历史日期,
并与当日存档报告里的结论逐项对比, 列出哪些天的结论被这两次错误影响。

口径: "last bar" = 该品种**本地日期 <= 报告日期-1** 的最后一根 (即 08:00 跑时能拿到的
      "上一完整交易日"), 与 08:00 盘前报告的语义一致。
"""
import os
import re
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macro_chain as mc

REPO = r'C:\Users\yanyan.zou\stock-collaboration'
FULL = 12


def build_series():
    """每个 symbol -> [(local_date, close)] (交易所当地时区)"""
    out = {}
    for k, (sym, cn) in mc.YF.items():
        rows = mc.yf_series(sym)
        if rows:
            out[k] = rows
    return out


def m_for_date(ser, d):
    """构造某个报告日 d 的 m (last bar = 本地日期 <= d-1 的最后一根)"""
    m = {}
    cutoff = d  # 报告日
    for k, rows in ser.items():
        idx = None
        for i, (dt, c) in enumerate(rows):
            if dt < cutoff:
                idx = i
            else:
                break
        if idx is None or idx < 1:
            continue
        c1 = rows[idx][1]; c0 = rows[idx - 1][1]
        c5 = rows[idx - 5][1] if idx >= 5 else rows[0][1]
        c20 = rows[idx - 20][1] if idx >= 20 else rows[0][1]
        m[k] = {'name': mc.YF[k][1], 'last': c1, 'date': rows[idx][0],
                'd1': (c1 / c0 - 1) * 100, 'd5': (c1 / c5 - 1) * 100,
                'd20': (c1 / c20 - 1) * 100, 'prev': c0,
                'd1_pts': c1 - c0, 'd5_pts': c1 - c5, 'd20_pts': c1 - c20}
    return m


def score(m):
    ch = mc.chains(m)
    net = sum(s for _, _, s, _ in ch)
    sc = int(round(net / FULL * 100))
    n = sum(1 for _, _, s, _ in ch if s != 0)
    if n < 3:
        bias = '中性震荡（低置信）'
    elif sc >= 40:
        bias = '偏多'
    elif sc >= 15:
        bias = '震荡偏多'
    elif sc > -15:
        bias = '中性震荡'
    elif sc > -40:
        bias = '震荡偏空'
    else:
        bias = '偏空'
    return ch, net, sc, n, bias


def archived(fn):
    t = open(fn, encoding='utf-8').read()
    m = re.search(r'净信号 ([+-]\d+) / 归一 ([+-]\d+)(?: / 有效链 (\d+)/8)?', t)
    b = re.search(r'## 🎯 结论: [^\n]*?\*\*([^*]+)\*\*', t)
    return (m.group(1), m.group(2), m.group(3), b.group(1).strip() if b else '?') if m else None


def main():
    ser = build_series()
    print(f'取到 {len(ser)}/{len(mc.YF)} 个品种序列\n')
    files = sorted(glob.glob(os.path.join(REPO, 'macro_chain_2026*.md')))
    print(f"{'日期':<12}{'存档 净/归一/有效链':<24}{'存档结论':<18}{'重算 净/归一/有效链':<24}{'重算结论':<18}变化")
    print('-' * 116)
    changed = []
    for fn in files:
        d = os.path.basename(fn)[12:20]
        dt = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        a = archived(fn)
        if not a:
            continue
        m = m_for_date(ser, dt)
        if len(m) < 8:
            print(f'{dt:<12} 数据不足, 跳过')
            continue
        try:
            ch, net, sc, n, bias = score(m)
        except AssertionError as e:
            print(f'{dt:<12} 验证器拦截: {e}')
            continue
        a_net, a_sc, a_n, a_bias = a
        a_n = a_n or '?'
        diff = []
        if a_net != f'{net:+d}': diff.append('净信号')
        if a_sc != f'{sc:+d}': diff.append('归一')
        if a_n != str(n): diff.append('有效链')
        if a_bias != bias: diff.append('结论')
        mark = ('✅ 一致' if not diff else '⚠️ ' + '/'.join(diff))
        if diff:
            changed.append((dt, a_bias, bias, f'净{a_net}→净{net:+d}', f'归{a_sc}→归{sc:+d}',
                            f'链{a_n}→链{n}', mark))
        print(f'{dt:<12}{a_net + "/" + a_sc + "/" + a_n:<24}{a_bias:<18}'
              f'{f"{net:+d}/{sc:+d}/{n}":<24}{bias:<18}{mark}')

    print()
    print(f'=== {len(changed)} 天的结论受影响 ===')
    for c in changed:
        print(f'  {c[0]}  {c[1]} → {c[2]}   ({c[3]}, {c[4]}, {c[5]})')

    out = os.path.join(REPO, 'macro_chain_backfill_20261030.md')
    L = ['# 外围结论回溯修正 (2026-10-30)\n',
         '> 触发: 美股链标签 bug (3/3 全跌/全涨 都被标"涨跌互现") + Yahoo daily bar 日期套 UTC 导致亚洲市场错位 1 天\n',
         '> 口径: 用修正后的取数(交易所当地时区) + 修正后的判定逻辑重算; "last bar" = 本地日期 <= 报告日-1 的最后一根\n',
         '| 日期 | 存档 净/归一/有效链 | 存档结论 | 重算 净/归一/有效链 | 重算结论 | 变化 |',
         '|---|---|---|---|---|---|']
    for c in changed:
        L.append(f'| {c[0]} | {c[3][1:].split("→")[0]} | {c[1]} | {c[3][3:]} | {c[2]} | ⚠️ |')
    L.append('')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'\n已写 {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
