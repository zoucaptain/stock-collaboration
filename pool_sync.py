#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
pool_sync.py — 加票后全表刷新生成器 (2026-10-27)

按 skill long-term-stock-pool 陷阱 5 (11 处必改) + 陷阱 31 (全表刷到同一天)
生成 pool.md 全文, 并 patch pool.json。

用法: python pool_sync.py
"""
import json
import os
import sys
import urllib.request
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from predict_next_day import tx_kline

REPO = r'C:\Users\yanyan.zou\stock-collaboration'
POOL_JSON = os.path.join(REPO, 'pool.json')
POOL_MD = os.path.join(REPO, 'pool.md')
STAMP = '10/27 午间实测'

NEW = {
    "code": "600838", "name": "上海九百", "industry": "一般零售+静安寺商圈",
    "added_at": "2026-10-27", "added_by": "user_manual_add",
    "is_industry_leader": True,
    "is_exception": True,
    "exception_reason": (
        "**震幅豁免 (大豁免 56%)**: 5 条规则 4/5 通过, 30d 平均震幅 0.44 元 < 1 元 (缺 0.56 元, 缺口 56%)。"
        "行业龙头地位 = 一般零售/商业百货细分龙头, 2025 年年报原文: 前身为 1939 年创建的百乐商场, "
        "1966 年 12 月定名上海市第九百货商店, 1994-02-24 上交所上市; 参股的'上海九百城市广场有限公司'及"
        "'上海久光百货有限公司''成为静安寺商圈地标性商业百货, 长期以来为公司贡献了较为稳定且丰厚的投资收益和现金流, "
        "已成为公司利润的主要来源'。"
        "市值 53.36 亿 (<200) / 股价 13.31 (<50) / 沪主板 600 通过。"
        "⚠️ 风险画像: 今日涨停 13.31 = 5 连板 (10/23 三板 -> 10/26 四板 -> 10/27 五板), "
        "30d 位 100% / 90d 位 100% 顶格, 30d 涨 +48.7% / 90d 涨 +72.9%, 90d 涨停 7 次, PE 114.46。"
        "2025 全年营收 9564.57 万 (+3.17%) / 归母净利 4533.07 万 (+7.85%) / 扣非 4438.16 万 (+6.10%) —— "
        "利润主要来自参股久光百货的投资收益, 公司无自主经营商场; 年报自述风险: "
        "'久光百货市场占有率和盈利能力存在下降风险' + 网购/直播/私域分流。"
        "震幅属沉睡型伪指标: 前 8 日逐日振幅仅 0.35~0.51, 近 2 日才起 (0.87 / 1.05), 10/26 一字板振幅 0.00。"
        "操作: 入池观察, **不追高**, 等回踩 MA5 (11.10) 以下且缩量")
}


def realtime(code):
    p = 'sh' if code.startswith('6') else 'sz'
    req = urllib.request.Request(f'https://qt.gtimg.cn/q={p}{code}',
                                 headers={'User-Agent': 'Mozilla/5.0'})
    d = urllib.request.urlopen(req, timeout=12).read().decode('gbk', 'ignore').split('~')
    return {'px': float(d[3]), 'prev': float(d[4]), 'chg': float(d[32]),
            'turn': d[38], 'pe': d[39], 'mv': float(d[44]) if d[44] else 0.0,
            'volratio': d[49] if len(d) > 49 else '?'}


def metrics(code):
    k = tx_kline(code, 200)
    c = [x['c'] for x in k]; h = [x['h'] for x in k]; l = [x['l'] for x in k]; v = [x['v'] for x in k]
    n = len(c)
    m = {}
    m['amp30'] = sum(h[i] - l[i] for i in range(n - 30, n)) / 30
    m['amp90'] = sum(h[i] - l[i] for i in range(n - 90, n)) / 90
    lo30, hi30 = min(l[-30:]), max(h[-30:]); lo90, hi90 = min(l[-90:]), max(h[-90:])
    m['pos30'] = (c[-1] - lo30) / (hi30 - lo30) * 100 if hi30 > lo30 else 50
    m['pos90'] = (c[-1] - lo90) / (hi90 - lo90) * 100 if hi90 > lo90 else 50
    m['c7'] = (c[-1] / c[-8] - 1) * 100
    m['c30'] = (c[-1] / c[-31] - 1) * 100
    m['c60'] = (c[-1] / c[-61] - 1) * 100
    m['c90'] = (c[-1] / c[-91] - 1) * 100
    # 涨停/跌停统计窗口必须是 **90 天** (与 90d 位置/涨跌/震幅同口径)
    m['lu'] = sum(1 for i in range(n - 90, n) if (c[i] - c[i - 1]) / c[i - 1] >= 0.095)
    m['ld'] = sum(1 for i in range(n - 90, n) if (c[i] - c[i - 1]) / c[i - 1] <= -0.095)
    peak = h[0]; mdd = 0
    for i in range(n):
        if h[i] > peak: peak = h[i]
        dd = (peak - l[i]) / peak * 100
        if dd > mdd: mdd = dd
    m['mdd'] = mdd
    m['ma5'] = sum(c[-5:]) / 5; m['ma10'] = sum(c[-10:]) / 10
    m['ma20'] = sum(c[-20:]) / 20; m['ma60'] = sum(c[-60:]) / 60
    m['date'] = k[-1]['d']
    return m


def trend(px, m):
    if m['ma5'] > m['ma10'] > m['ma20'] and px > m['ma5']:
        return '多头'
    if m['ma5'] < m['ma10'] < m['ma20'] and px < m['ma5']:
        return '空头'
    if abs(m['ma5'] - m['ma20']) / m['ma20'] < 0.02:
        return '震荡'
    return '转换中'


def kzone(p30):
    if p30 > 80: return '高危区'
    if p30 >= 60: return '强势区'
    if p30 >= 40: return '中性区'
    if p30 >= 20: return '弱势区'
    return '低吸区'


def mazone(px, m):
    if px > m['ma5'] > m['ma10'] > m['ma20']: return '多头排列'
    if px < m['ma5'] < m['ma10'] < m['ma20']: return '空头排列'
    if px > m['ma5'] and m['ma5'] < m['ma20']: return '超跌反弹'
    if px < m['ma5'] and m['ma5'] > m['ma20']: return '超买回调'
    return '震荡'


def chip(a):
    if a > 2: return '高活跃'
    if a >= 1: return '活跃'
    return '低活跃'


def tier(a):
    if a > 1: return '🟢'
    if a >= 0.5: return '🟡'
    return '🔴'


def zone90(p):
    if p > 80: return '🚀 顶部区'
    if p >= 60: return '📈 偏高位'
    if p >= 40: return '➖ 中位'
    if p >= 20: return '📉 偏低位'
    return '💎 底部区'


def gen_md(rows, stocks):
    """按 11 处必改清单生成 pool.md 全文 (陷阱 5 + 陷阱 31 全表刷新)"""
    N = len(rows)
    by_amp = sorted(rows, key=lambda r: -r['amp30'])
    strong = [r for r in by_amp if r['amp30'] > 1]
    mid = [r for r in by_amp if 0.5 <= r['amp30'] <= 1]
    weak = [r for r in by_amp if r['amp30'] < 0.5]
    L = []
    A = L.append
    A('# 长期观察股票池\n')
    A('**创建时间**: 2026-10-16 11:25')
    A(f'**版本**: v1.0  |  **当前 {N} 只**  |  **全部表格刷新至 {STAMP}**')
    A('**数据源**: `stock_data_source.py` v2.1.2 + 腾讯实时/K线双源交叉\n')
    A('---\n')
    A('## 📋 规则\n')
    A('### 新添加股票必须满足 (强制 5 条)\n')
    A('| # | 规则 | 标准 |')
    A('|---|---|---|')
    A('| 1 | **行业龙头** | 必须是所属行业龙头 |')
    A('| 2 | **日均震幅** | 过去 30 天平均每天(最高价-最低价)震幅 > 1 元 |')
    A('| 3 | **市值上限** | 总市值 ≤ 200 亿 |')
    A('| 4 | **价格上限** | 股价 ≤ 50 元 |')
    A('| 5 | **🆕 主板限制** | 必须是 **A 股主板** (沪 600/601/603/605 + 深 000/001/002)，**排除** 创业板 300 / 科创板 688 / 北交所 8/920 |\n')
    A('**主板限制说明** (2026-10-16 加入):')
    A('- 主板股票流动性更好，估值更稳定，适合长期观察')
    A('- 创业板/科创板波动大、市值小、估值溢价高')
    A('- 北交所流动性差、关注度低\n')
    A('### 观察频率')
    A('- **每个交易日 15:30 收盘后** 自动跑')
    A('- 输出每只股票的 8 类状态\n')
    A('### 🆕 30d 震幅分级 (2026-10-16 加入)\n')
    A('> **核心理念**: 震幅越大 = 近期越有炒作价值, 板块热时震幅大, 板块冷时震幅小\n')
    A('| 档位 | 标签 | 30d 平均震幅 | 含义 |')
    A('|---|---|---|---|')
    A('| 🟢 强 | **短线机会多** | **> 1 元** | 近期强活跃, 有炒作价值 |')
    A('| 🟡 中 | **观察为主** | 0.5 - 1 元 | 中等活跃 |')
    A('| 🔴 弱 | **长期持有** | **< 0.5 元** | 低活跃, 短线机会少 |\n')
    A(f'### 当前 {N} 只震幅分级 ({STAMP})\n')
    A(f'**🟢 强档 (>1元) - {len(strong)} 只, 近期有炒作价值**:')
    A('| 排名 | 股票 | 30d 震幅 | 现价 |')
    A('|---|---|---|---|')
    for i, r in enumerate(strong, 1):
        med = '🥇' if i == 1 else '🥈' if i == 2 else '🥉' if i == 3 else str(i)
        A(f"| {med} | {r['name']} | **{r['amp30']:.2f} 元** | {r['px']:.2f} |")
    A('')
    A(f'**🟡 中档 (0.5-1元) - {len(mid)} 只, 观察**:')
    A('| 股票 | 30d 震幅 | 现价 |')
    A('|---|---|---|')
    for r in mid:
        A(f"| {r['name']} | {r['amp30']:.2f} 元 | {r['px']:.2f} |")
    A('')
    A(f'**🔴 弱档 (<0.5元) - {len(weak)} 只, 长期持有**:')
    A('| 股票 | 30d 震幅 | 现价 |')
    A('|---|---|---|')
    for r in weak:
        A(f"| {r['name']} | {r['amp30']:.2f} 元 | {r['px']:.2f} |")
    A('\n---\n')
    A(f'## 🐉 当前股票 ({N} 只)\n')
    A('| 代码 | 名称 | 行业 | 添加时间 | 例外 |')
    A('|---|---|---|---|---|')
    for r in rows:
        s = next(x for x in stocks if x['code'] == r['code'])
        ex = '—'
        if s.get('is_exception'):
            er = s.get('exception_reason', '')
            if '震幅豁免' in er:
                gap = er.split('缺口')[1].split(')')[0].split('%')[0].strip()
                ex = f'⚠️ **震幅豁免 ({r["amp30"]:.2f} < 1, 缺口 {gap}%)**'
            elif '价格豁免' in er:
                ex = f'⚠️ **价格豁免 ({r["px"]:.2f} > 50)**'
            elif '市值' in er:
                ex = '⚠️ **市值超限**'
            else:
                ex = '⚠️ **豁免**'
        elif r['px'] > 45:
            ex = f'⚠️ 现价 {r["px"]:.2f} 接近 50'
        elif s.get('note', '').startswith('西南黄金'):
            ex = '✅ 5 条规则全过'
        if r['code'] == '600838':
            ex = '⚠️ **震幅豁免 (0.44 < 1, 缺口 56% 大豁免)**'
        A(f"| {r['code']} | {r['name']} | {s['industry']} | {s['added_at']} | {ex} |")
    A('')
    A('**例外说明**:')
    for s in stocks:
        if s.get('is_exception') and s.get('exception_reason'):
            A(f"- **{s['name']}**: {s['exception_reason']}")
        elif s.get('exception_note'):
            A(f"- **{s['name']}**: {s['exception_note']}")
        elif s.get('note'):
            A(f"- **{s['name']}**: {s['note']}")
    A('\n---\n')
    A(f'## 📊 每日状态 ({STAMP})\n')
    A('| 名称 | 现价 | 涨% | 30d位 | 30d涨跌 | 涨停30d | 趋势 | K线 | 均线 | 筹码 | 状态 |')
    A('|---|---|---|---|---|---|---|---|---|---|---|')
    for r in sorted(rows, key=lambda x: -x['chg']):
        amp = round(r['amp30'], 2)
        lu30 = sum(1 for i in range(1, 31) if 0)  # placeholder
        note = []
        if r['chg'] >= 9.8: note.append('🚀 **涨停**')
        elif r['chg'] <= -9.8: note.append('⚠️ **跌停**')
        if r['pos30'] > 95: note.append('30d位顶格')
        elif r['pos30'] < 10: note.append('💎 30d位极低')
        if abs(r['c30']) > 25: note.append(f"30d {r['c30']:+.1f}%")
        A(f"| {r['name']} | {r['px']:.2f} | {r['chg']:+.2f}% | {r['pos30']:.0f}% | "
          f"{r['c30']:+.1f}% | {r['lu']} | {trend(r['px'], r)} | {kzone(r['pos30'])} | "
          f"{mazone(r['px'], r)} | {chip(amp)} | {' '.join(note) if note else '—'} |")
    A('\n---\n')
    A(f'## 📐 状态判定标准\n')
    A('### 趋势 (4 选 1)')
    A('- **UP_TREND** (多头): `MA5 > MA10 > MA20` 且 `现价 > MA5`')
    A('- **DOWN_TREND** (空头): `MA5 < MA10 < MA20` 且 `现价 < MA5`')
    A('- **SIDEWAYS** (震荡): `|MA5 - MA20| / MA20 < 2%`')
    A('- **TRANSITION** (转换中): 其他\n')
    A('### K 线位置 (5 选 1)')
    A('- **高危区**: 30d位 > 80%')
    A('- **强势区**: 60-80%')
    A('- **中性区**: 40-60%')
    A('- **弱势区**: 20-40%')
    A('- **低吸区**: < 20%\n')
    A('### 均线状态 (5 选 1)')
    A('- **多头排列**: `现价 > MA5 > MA10 > MA20`')
    A('- **空头排列**: `现价 < MA5 < MA10 < MA20`')
    A('- **超跌反弹**: `现价 > MA5` 但 `MA5 < MA20`')
    A('- **超买回调**: `现价 < MA5` 但 `MA5 > MA20`')
    A('- **震荡**: 其他\n')
    A('### 筹码活跃度 (3 选 1, 30d 平均日震幅)')
    A('- **高活跃**: > 2 元')
    A('- **活跃**: 1-2 元')
    A('- **低活跃**: < 1 元\n')
    A('---\n')
    A('## 🔧 工具\n')
    A('### 自动观察脚本')
    A('- 脚本: `C:\\Users\\yanyan.zou\\AppData\\Local\\hermes\\scripts\\pool_observer.py`')
    A('- 生成器: `pool_sync.py` (加票后全表刷新, 11 处一次性同步)')
    A('- 每天 15:30 收盘后跑一次, 输出每只状态\n')
    A('### GitHub 操作')
    A('- 仓库: `https://github.com/zoucaptain/stock-collaboration`')
    A('- 文件: `pool.json` (机器版) + `pool.md` (人类版)')
    A('- 推送: `git add pool.json pool.md && git commit -m "..." && git push`')
    A('- **任何修改直接对 GitHub 股票池操作**\n')
    A('---\n')
    A(f'## 📊 3 个月 (90 天) 周期对比 ({STAMP})\n')
    A('### 完整数据表\n')
    A('| 股票 | 现价 | 涨% | 90d位 | 90d涨跌 | 60d | 30d | 7d | 涨停 | 跌停 | 震幅均 | 最大回撤 | 趋势 |')
    A('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for r in sorted(rows, key=lambda x: x['pos90']):
        A(f"| {r['name']} | {r['px']:.2f} | {r['chg']:+.2f}% | {r['pos90']:.0f}% | {r['c90']:+.1f}% | "
          f"{r['c60']:+.1f}% | {r['c30']:+.1f}% | {r['c7']:+.1f}% | {r['lu']} | {r['ld']} | "
          f"{r['amp90']:.2f} | {r['mdd']:.1f}% | {trend(r['px'], r)} |")
    A('')
    A(f'### 3 个月位置分布 ({N} 只)\n')
    A('| 区域 | 股票 | 数量 |')
    A('|---|---|---|')
    buckets = {'📈 偏高位 (60-80%)': [], '➖ 中位 (40-60%)': [],
               '📉 偏低位 (20-40%)': [], '💎 底部 (<20%)': []}
    for r in sorted(rows, key=lambda x: -x['pos90']):
        p = r['pos90']
        if p >= 80: k = '🚀 顶部区 (>80%)'
        elif p >= 60: k = '📈 偏高位 (60-80%)'
        elif p >= 40: k = '➖ 中位 (40-60%)'
        elif p >= 20: k = '📉 偏低位 (20-40%)'
        else: k = '💎 底部 (<20%)'
        buckets.setdefault(k, []).append(f"{r['name']} {p:.0f}%")
    for k, v in buckets.items():
        if v:
            A(f"| {k} | {' / '.join(v)} | {len(v)} |")
    A('')
    A('### 90d 涨跌排行\n')
    A('| 排名 | 股票 | 90d涨跌 |')
    A('|---|---|---|')
    for i, r in enumerate(sorted(rows, key=lambda x: -x['c90']), 1):
        med = '🥇' if i == 1 else '🥈' if i == 2 else '🥉' if i == 3 else str(i)
        A(f"| {med} | {r['name']} | {r['c90']:+.1f}% |")
    A('')
    A('### 90d 涨停排行\n')
    A('| 股票 | 涨停 | 评价 |')
    A('|---|---|---|')
    for r in sorted(rows, key=lambda x: -x['lu']):
        ev = '🐉 顶级妖股' if r['lu'] >= 11 else ('🐉 妖股' if r['lu'] >= 7 else ('活跃' if r['lu'] >= 4 else '一般'))
        A(f"| {r['name']} | {r['lu']} | {ev} |")
    A('')
    A('### 30d 近期涨跌 (关键信号)\n')
    A('| 股票 | 30d | 信号 |')
    A('|---|---|---|')
    for r in sorted(rows, key=lambda x: -x['c30']):
        sig = '🚀 强势' if r['c30'] > 15 else ('强势' if r['c30'] > 5 else
              ('杀跌' if r['c30'] < -8 else ('深杀' if r['c30'] < -20 else '震荡')))
        A(f"| {r['name']} | {r['c30']:+.1f}% | {sig} |")
    A('')
    A('### 🎯 综合操作建议\n')
    A('| 类别 | 股票 | 操作 |')
    A('|---|---|---|')
    bottom = [r for r in rows if r['pos90'] < 20]
    lowdeep = [r for r in rows if r['pos90'] < 40 and r['c30'] < -20]
    midk = [r for r in rows if 20 <= r['pos90'] < 60]
    highk = [r for r in rows if r['pos90'] >= 60]
    top = [r for r in rows if r['pos30'] > 90]
    if bottom:
        bs = ', '.join('{} ({:.0f}%)'.format(r['name'], r['pos90']) for r in sorted(bottom, key=lambda x: x['pos90']))
        A(f'| 💎 **底部 (<20%)** | {bs} | 🥇 **重点关注低吸** |')
    if lowdeep:
        ls = ', '.join('{} ({:+.1f}%)'.format(r['name'], r['c30']) for r in lowdeep)
        A(f'| 💎 低位 + 30d 深杀 | {ls} | 🥈 **超跌但等企稳** |')
    if midk:
        ms = ', '.join(r['name'] for r in midk)
        A(f'| ➖ 中位/偏低位 | {ms} | 🥉 **观察等止跌** |')
    if highk:
        hs = ', '.join('{} ({:.0f}%)'.format(r['name'], r['pos90']) for r in highk)
        A(f'| 📈 偏高位 | {hs} | ⚠️ **持有不追** |')
    for r in top:
        A('| 🚀 **30d位 {:.0f}% + 今日 {:+.1f}% + MA5 {:.2f}** | **{}** | '
          '🔴 **不追高, 等回踩 MA5 ({:.2f}) 以下且缩量** |'.format(
              r['pos30'], r['chg'], r['ma5'], r['name'], r['ma5']))
    A('\n---\n')
    open(POOL_MD, 'w', encoding='utf-8').write('\n'.join(L))
    print(f'pool.md 已生成 ({len(L)} 行)')


def main():
    pj = json.load(open(POOL_JSON, encoding='utf-8'))
    stocks = pj['stocks']
    if not any(s['code'] == NEW['code'] for s in stocks):
        stocks.append(NEW)
    pj['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    pj['stock_count'] = len(stocks)

    rows = []
    for s in stocks:
        rt = realtime(s['code']); m = metrics(s['code'])
        px = rt['px']
        rows.append({**s, **rt, **m})
    json.dump(rows, open(os.path.join(REPO, '.pool_rows.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    with open(POOL_JSON, 'w', encoding='utf-8') as f:
        json.dump(pj, f, ensure_ascii=False, indent=2)
    gen_md(rows, stocks)
    print(f'pool.json 已更新 -> {len(stocks)} 只')
    for r in rows:
        print(f"  {r['name']:<10}{r['px']:>8.2f}{r['chg']:>8.2f}%  震幅30d {r['amp30']:>5.2f}  "
              f"30d位 {r['pos30']:>5.1f}%  90d位 {r['pos90']:>5.1f}%  涨停90d {r['lu']:>3}")


if __name__ == '__main__':
    main()
