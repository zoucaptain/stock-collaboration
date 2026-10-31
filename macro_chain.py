#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
macro_chain.py — 外围宏观链条每日审视 (2026-10-22)

用户给的逻辑链 (原话整理):
  1. 美联储加息 -> 美元变贵; 降息 -> 美元变便宜
  2. 美元便宜 -> 钱往外流 -> 新兴市场热闹; 美元贵 -> 钱回流 -> 别处资产缺钱
  3. 美元强 -> 高风险资产承压; 美元弱 -> 钱有胆子往外冲
  4. 10Y 美债收益率强 -> 风险资产小心; 弱 -> 钱敢往外冲
  5. 美元 / 美债 / 黄金 = 跷跷板
  6. 美股强 -> 风险偏好高; 美股弱 -> 全球资金避险
  7. 石油贵 -> 通胀 -> 加息压通胀 -> 压制股市 (尤其成本敏感行业)
  8. 完整链条: 油价涨 -> 通胀升 -> 美联储加息 -> 美元走强 -> 风险资产承压 -> 黄金受压

本脚本把 8 条链**量化**成信号, 落到 A股大盘 + 板块方向:
  - 数据: Yahoo (美股/美债/美元指数/原油/黄金/VIX/离岸人民币) + 新浪 (原油黄金兜底)
  - 输出: 每条链的判定 + 净信号 + 大盘倾向 + 受益/承压板块
  - 落盘: macro_chain_YYYYMMDD.md (给 OpenClaw) + stdout 摘要 (给 cron 投递)

**关键**: 8:00 跑 -> 覆盖"昨夜"信息 (美股收盘 + 欧盘 + 当日原油/黄金开盘),
美股隔夜数据在 A股开盘前已完整落地。
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

CST = timezone(timedelta(hours=8))
REPO = r"C:\Users\yanyan.zou\stock-collaboration"
SCRIPTS = os.path.dirname(os.path.abspath(__file__))

# ---------------- 数据源
YF = {
    'dxy':  ('DX-Y.NYB', '美元指数'),
    'tnx':  ('^TNX', '10Y美债收益率'),
    'spx':  ('^GSPC', '标普500'),
    'ixic': ('^IXIC', '纳斯达克'),
    'dji':  ('^DJI', '道琼斯'),
    'vix':  ('^VIX', 'VIX恐慌指数'),
    'wti':  ('CL=F', 'WTI原油'),
    'brent': ('BZ=F', '布伦特原油'),
    'gold': ('GC=F', '纽约黄金'),
    'cnh':  ('CNY=X', '离岸人民币(美元兑人民币)'),
    'nikkei': ('^N225', '日经225'),
    'hsi':  ('^HSI', '恒生指数'),
}


def yf_series(sym, tries=2):
    for host in ('query1', 'query2'):
        for _ in range(tries):
            try:
                u = (f'https://{host}.finance.yahoo.com/v8/finance/chart/'
                     f'{urllib.parse.quote(sym)}?range=3mo&interval=1d')
                req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
                d = json.loads(urllib.request.urlopen(req, timeout=20).read())
                r = d['chart']['result'][0]
                cl = r['indicators']['quote'][0]['close']
                ts = r['timestamp']
                # 2026-10-30 修: 日期必须按**交易所当地时区**算, 不能统一套 UTC。
                # Yahoo 的日 bar timestamp 用交易所当地午夜表示, 套 UTC 会让
                # 日经/恒生等亚洲市场整体错位 1 天 (10/30 报告里"日经 63954" 实为 10-27 收盘)。
                try:
                    tzname = r['meta'].get('exchangeTimezoneName') or 'UTC'
                    tz = ZoneInfo(tzname)
                except Exception:
                    tz = timezone.utc
                rows = [(datetime.fromtimestamp(t, tz).strftime('%Y-%m-%d'), c)
                        for t, c in zip(ts, cl) if c is not None]
                if len(rows) >= 2:
                    return rows
            except Exception:
                time.sleep(0.6)
    return []


def sina_hf(code):
    """新浪全球期货兜底: hf_CL 纽约原油, hf_GC 纽约黄金, hf_OIL 布伦特"""
    try:
        u = f'https://hq.sinajs.cn/list={code}'
        req = urllib.request.Request(u, headers={
            'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn'})
        t = urllib.request.urlopen(req, timeout=15).read().decode('gbk', 'ignore')
        body = t.split('="', 1)[1].rsplit('"', 1)[0]
        p = body.split(',')
        return float(p[0]), p[12] if len(p) > 12 else ''
    except Exception:
        return None, ''


def fetch_all():
    out = {}
    for key, (sym, cn) in YF.items():
        rows = yf_series(sym)
        if not rows:
            out[key] = {'name': cn, 'err': '取数失败'}
            continue
        c1 = rows[-1][1]; c0 = rows[-2][1]
        c5 = rows[-6][1] if len(rows) >= 6 else rows[0][1]
        c20 = rows[-21][1] if len(rows) >= 21 else rows[0][1]
        out[key] = {'name': cn, 'sym': sym, 'date': rows[-1][0],
                    'last': c1, 'd1': (c1 / c0 - 1) * 100,
                    'd5': (c1 / c5 - 1) * 100, 'd20': (c1 / c20 - 1) * 100,
                    'prev': c0, 'd1_pts': c1 - c0,
                    'd5_pts': c1 - c5, 'd20_pts': c1 - c20}
    # 新浪兜底 (原油/黄金)
    for key, sc in (('wti', 'hf_CL'), ('brent', 'hf_OIL'), ('gold', 'hf_GC')):
        if out.get(key, {}).get('err'):
            v, d = sina_hf(sc)
            if v:
                out[key] = {'name': YF[key][1], 'last': v, 'd1': 0.0, 'd5': 0.0,
                            'd20': 0.0, 'd1_pts': 0.0, 'prev': v, 'date': d,
                            'note': '新浪兜底, 无涨跌'}
    return out


# ---------------- 数据新鲜度 (2026-10-30 加)
def _lag_days(date_str, ref=None):
    """bar 日期比"最近已收盘交易日"(默认昨天, 北京时区)落后多少天。>0 = 数据滞后。"""
    if not date_str:
        return 0
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d').date()
    except Exception:
        return 0
    if ref is None:
        ref = datetime.now(timezone(timedelta(hours=8))).date() - timedelta(days=1)
    return (ref - d).days


# ---------------- 标签自检 (2026-10-30 加)
def validate_chain_labels(m, ch):
    """标签必须与打印出来的数字一致。10/30 事故: 三大指数 3/3 全跌却标'涨跌互现'。
    本函数在每次生成报告前跑一遍, 不一致直接抛错 —— 这类错不允许再静默出报告。"""
    g = lambda k, f='d1': m.get(k, {}).get(f, 0.0)
    d = {name: verdict for name, verdict, _s, _w in ch}
    errs = []

    if '美股' in d and 'err' not in m.get('spx', {}):
        legs = (g('spx'), g('ixic'), g('dji'))
        n_up = sum(1 for x in legs if x > 0)
        n_dn = sum(1 for x in legs if x < 0)
        v = d['美股']
        if v == '涨跌互现' and not (n_up >= 1 and n_dn >= 1):
            errs.append(f"美股标'涨跌互现'但数字非有涨有跌: {legs}")
        _avg = sum(legs) / 3
        if v in ('全线小跌', '全线走弱') and n_dn != 3:
            errs.append(f"美股标'{v}'但并非三腿全跌: {legs}")
        if v in ('全线小涨', '全线走强') and n_up != 3:
            errs.append(f"美股标'{v}'但并非三腿全涨: {legs}")
        if v == '全线走弱' and not (_avg < -0.8 and n_dn == 3):
            errs.append(f"美股标'全线走弱'但均值 {_avg:+.2f}% 不 < -0.8 或非全跌: {legs}")
        if v == '全线走强' and not (_avg > 0.8 and n_up == 3):
            errs.append(f"美股标'全线走强'但均值 {_avg:+.2f}% 不 > 0.8 或非全涨: {legs}")
        if v == '全线持平' and (n_up or n_dn):
            errs.append(f"美股标'全线持平'但存在涨跌腿: {legs}")

    if '原油' in d and 'err' not in m.get('wti', {}) and 'err' not in m.get('brent', {}):
        oil = (g('wti') + g('brent')) / 2
        v = d['原油']
        if v == '油价上涨' and oil <= 1.5:
            errs.append(f"原油标'油价上涨'但均值 {oil:+.2f}% 不 > 1.5")
        if v == '油价下跌' and oil >= -1.5:
            errs.append(f"原油标'油价下跌'但均值 {oil:+.2f}% 不 < -1.5")
        if v == '油价平稳' and abs(oil) > 1.5:
            errs.append(f"原油标'油价平稳'但均值 {oil:+.2f}% 超阈")

    if '亚太' in d and 'err' not in m.get('hsi', {}) and 'err' not in m.get('nikkei', {}):
        h1, n1 = g('hsi'), g('nikkei')
        avg = (h1 + n1) / 2
        v = d['亚太']
        if v == '亚太走弱' and avg >= -1.0:
            errs.append(f"亚太标'走弱'但均值 {avg:+.2f}% 不 < -1.0")
        if v == '亚太走强' and avg <= 1.0:
            errs.append(f"亚太标'走强'但均值 {avg:+.2f}% 不 > 1.0")

    if errs:
        raise AssertionError('链条标签与数字不一致:\n  - ' + '\n  - '.join(errs))


# ---------------- 链条判定
def chains(m):
    """8 条链 -> 每条给出 判定 + 对A股方向打分 (-2..+2, 正=利好A股风险偏好)"""
    g = lambda k, f='d1': m.get(k, {}).get(f, 0.0)
    has = lambda k: 'err' not in m.get(k, {})
    c = []

    # 1 美元强弱 (核心)
    dxy1, dxy5 = g('dxy', 'd1'), g('dxy', 'd5')
    if has('dxy'):
        if dxy1 > 0.3 and dxy5 > 0.5:
            c.append(('美元', '美元走强', -2,
                      f"美元指数 {m['dxy']['last']:.2f}, 日 {dxy1:+.2f}% / 5日 {dxy5:+.2f}% -> 钱回流美国, 新兴市场缺钱, 高风险资产承压"))
        elif dxy1 < -0.3 and dxy5 < -0.5:
            c.append(('美元', '美元走弱', +2,
                      f"美元指数 {m['dxy']['last']:.2f}, 日 {dxy1:+.2f}% / 5日 {dxy5:+.2f}% -> 钱往外流, 新兴市场受益, 风险偏好回升"))
        else:
            c.append(('美元', '美元震荡', 0,
                      f"美元指数 {m['dxy']['last']:.2f}, 日 {dxy1:+.2f}% / 5日 {dxy5:+.2f}% -> 方向不明, 无显著流动性冲击"))
    else:
        c.append(('美元', '数据缺失', 0, '美元指数取数失败, 该链条不参与评分'))

    # 2 美债 10Y (强则风险资产小心)
    t1, t5 = g('tnx', 'd1_pts'), g('tnx', 'd5_pts')
    if has('tnx'):
        if t1 > 0.03:
            c.append(('美债', '收益率上行', -2,
                      f"10Y 美债 {m['tnx']['last']:.3f}%, 日 {t1*100:+.0f}bp / 5日 {t5*100:+.0f}bp -> 无风险利率抬升, 风险资产估值承压"))
        elif t1 < -0.03:
            c.append(('美债', '收益率下行', +2,
                      f"10Y 美债 {m['tnx']['last']:.3f}%, 日 {t1*100:+.0f}bp / 5日 {t5*100:+.0f}bp -> 钱敢往外冲, 流动性宽松"))
        else:
            c.append(('美债', '收益率持平', 0,
                      f"10Y 美债 {m['tnx']['last']:.3f}%, 日 {t1*100:+.0f}bp -> 中性"))
    else:
        c.append(('美债', '数据缺失', 0, '10Y 美债取数失败'))

    # 3 美股 (风险偏好温度计)
    # 2026-10-30 修: 标签必须与数字一致。原 else 分支把 avg 落在 [-1.0,+0.8] 的所有情况
    # 都写成"涨跌互现", 导致 3/3 全跌(10/30) 和 3/3 全涨(10/29) 都被误标。
    spx, ixic, dji = g('spx'), g('ixic'), g('dji')
    if has('spx'):
        legs = (spx, ixic, dji)
        avg = sum(legs) / 3
        n_up = sum(1 for x in legs if x > 0)
        n_dn = sum(1 for x in legs if x < 0)
        detail = (f"标普 {spx:+.2f}% / 纳指 {ixic:+.2f}% / 道指 {dji:+.2f}% "
                  f"(均值 {avg:+.2f}%, {n_up}涨{n_dn}跌)")
        if avg < -0.8 and n_dn == 3:
            c.append(('美股', '全线走弱', -2, detail + " -> 全球资金避险"))
        elif avg > 0.8 and n_up == 3:
            c.append(('美股', '全线走强', +2, detail + " -> 全球风险偏好高"))
        elif n_dn == 3:
            c.append(('美股', '全线小跌', -1, detail + " -> 三大指数同步下跌, 风险偏好小幅降温"))
        elif n_up == 3:
            c.append(('美股', '全线小涨', +1, detail + " -> 三大指数同步上涨, 风险偏好小幅回暖"))
        elif n_up == 0 and n_dn == 0:
            c.append(('美股', '全线持平', 0, detail + " -> 三大指数均无变动, 无方向"))
        else:
            c.append(('美股', '涨跌互现', 0, detail + " -> 涨跌不一, 无明确方向"))
    else:
        c.append(('美股', '数据缺失', 0, '美股指数取数失败'))

    # 4 VIX
    v1, v5 = g('vix'), g('vix', 'd5')
    if has('vix'):
        if v1 > 8 or m['vix']['last'] > 25:
            c.append(('恐慌指数', '恐慌升温', -2,
                      f"VIX {m['vix']['last']:.2f}, 日 {v1:+.2f}% -> 风险偏好骤降, 高波动资产承压"))
        elif v1 < -5:
            c.append(('恐慌指数', '恐慌回落', +1,
                      f"VIX {m['vix']['last']:.2f}, 日 {v1:+.2f}% -> 风险偏好修复"))
        else:
            c.append(('恐慌指数', '平稳', 0, f"VIX {m['vix']['last']:.2f}, 日 {v1:+.2f}%"))
    else:
        c.append(('恐慌指数', '数据缺失', 0, 'VIX 取数失败'))

    # 5 原油 -> 通胀 -> 加息 (完整链条的起点)
    w1, b1 = g('wti'), g('brent')
    oil = (w1 + b1) / 2
    if has('wti') and has('brent'):
        # 2026-10-30 修: 两条腿方向背离时必须显式标注, 不能只报均值
        div = abs(w1 - b1)
        div_note = f" [WTI/布伦特背离 {div:.2f}pp, 均值口径失真风险]" if div > 1.5 else ""
        if oil > 1.5:
            c.append(('原油', '油价上涨', -1,
                      f"WTI {m['wti']['last']:.2f} ({w1:+.2f}%) / 布伦特 {m['brent']['last']:.2f} ({b1:+.2f}%) "
                      f"-> 通胀升 -> 加息预期 -> 美元走强 -> 风险资产承压; 但石油石化/油服/煤炭直接受益{div_note}"))
        elif oil < -1.5:
            c.append(('原油', '油价下跌', +1,
                      f"WTI {m['wti']['last']:.2f} ({w1:+.2f}%) / 布伦特 {m['brent']['last']:.2f} ({b1:+.2f}%) "
                      f"-> 通胀压力缓解, 成本敏感行业(航空/化工/物流/轮胎)受益, 加息预期降温{div_note}"))
        else:
            c.append(('原油', '油价平稳', 0,
                      f"WTI {m['wti']['last']:.2f} ({w1:+.2f}%) / 布伦特 {m['brent']['last']:.2f} ({b1:+.2f}%)"))
    else:
        c.append(('原油', '数据缺失', 0, '原油取数失败'))

    # 6 黄金 (与美元/美债跷跷板)
    gd1 = g('gold')
    if has('gold'):
        if dxy1 < -0.3 and gd1 > 0.5:
            c.append(('黄金', '美元弱金强', +1,
                      f"黄金 {m['gold']['last']:.1f} ({gd1:+.2f}%) 美元 {dxy1:+.2f}% -> 跷跷板正常, 避险与宽松预期同时存在"))
        elif dxy1 > 0.3 and gd1 < -0.5:
            c.append(('黄金', '美元强金弱', -1,
                      f"黄金 {m['gold']['last']:.1f} ({gd1:+.2f}%) 美元 {dxy1:+.2f}% -> 美元抽血压制黄金, 贵金属股承压"))
        else:
            c.append(('黄金', '跷跷板不明显', 0,
                      f"黄金 {m['gold']['last']:.1f} ({gd1:+.2f}%) 美元 {dxy1:+.2f}%"))
    else:
        c.append(('黄金', '数据缺失', 0, '黄金取数失败'))

    # 7 人民币 (外资流向)
    cn1, cn5 = g('cnh'), g('cnh', 'd5')
    if has('cnh'):
        if cn1 < -0.15:
            c.append(('人民币', '离岸走弱', -1,
                      f"美元兑人民币 {m['cnh']['last']:.4f} ({cn1:+.2f}%) -> 人民币贬值, 外资流出压力, 北向资金谨慎"))
        elif cn1 > 0.15:
            c.append(('人民币', '离岸走强', +1,
                      f"美元兑人民币 {m['cnh']['last']:.4f} ({cn1:+.2f}%) -> 人民币升值, 外资流入友好"))
        else:
            c.append(('人民币', '平稳', 0, f"美元兑人民币 {m['cnh']['last']:.4f} ({cn1:+.2f}%)"))
    else:
        c.append(('人民币', '数据缺失', 0, '离岸人民币取数失败'))

    # 8 亚太 (港股/日经, 隔夜情绪)
    h1, n1 = g('hsi'), g('nikkei')
    if has('hsi') and has('nikkei'):
        avg = (h1 + n1) / 2
        if avg < -1.0:
            c.append(('亚太', '亚太走弱', -1, f"恒生 {h1:+.2f}% / 日经 {n1:+.2f}% -> 隔夜亚太情绪拖累 A股开盘"))
        elif avg > 1.0:
            c.append(('亚太', '亚太走强', +1, f"恒生 {h1:+.2f}% / 日经 {n1:+.2f}% -> 亚太情绪正面"))
        else:
            c.append(('亚太', '中性', 0, f"恒生 {h1:+.2f}% / 日经 {n1:+.2f}%"))
    else:
        c.append(('亚太', '数据缺失', 0, '亚太指数取数失败'))
    validate_chain_labels(m, c)
    return c


SECTORS_UP = {
    '美元走弱': ['有色金属', '黄金/贵金属', '券商', '成长科技股', '港股映射', '航空机场'],
    '收益率下行': ['成长科技股', '券商', '地产链', '小盘题材'],
    '全线走强': ['消费电子', '半导体', 'AI算力', '汽车', '传媒'],
    '恐慌回落': ['科技成长', '券商', '地产'],
    '油价下跌': ['航空机场', '物流快递', '化工（成本）', '汽车零部件', '轮胎', '农业'],
    '离岸走强': ['核心资产', '白马龙头', '外资重仓股'],
    '亚太走强': ['港股映射', '消费', '科技'],
    '美元强金弱': ['黄金/贵金属'],
}
SECTORS_DOWN = {
    '美元走强': ['黄金/贵金属', '有色金属', '高估值成长', '券商', '港股映射', '出口链'],
    '收益率上行': ['成长科技股', '地产', '券商', '小盘题材'],
    '全线走弱': ['消费电子', '半导体', 'AI算力', '汽车', '传媒', '所有高Beta'],
    '恐慌升温': ['所有高Beta', '科技成长', '券商', '小盘题材'],
    '油价上涨': ['航空机场', '物流快递', '化工（成本敏感）', '汽车零部件', '轮胎', '农业'],
    '离岸走弱': ['外资重仓股', '核心资产'],
    '亚太走弱': ['港股映射', '消费'],
    '美元弱金强': [],
    '恐慌升温/美元强': [],
}


def build_sectors(chain):
    """返回 (受益, 承压, 分歧)
    分歧 = 多条链给出相反方向的板块 (不硬塞进任一边, 单独标出)"""
    up_raw, down_raw = [], []
    for name, verdict, score, _ in chain:
        if score > 0:
            up_raw += SECTORS_UP.get(verdict, [])
            down_raw += SECTORS_DOWN.get(verdict, [])
        elif score < 0:
            down_raw += SECTORS_DOWN.get(verdict, [])
            up_raw += SECTORS_UP.get(verdict, [])
    def dedup(lst):
        seen = set(); out = []
        for x in lst:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    up = dedup(up_raw); down = dedup(down_raw)
    both = [x for x in up if x in down]
    up = [x for x in up if x not in both]
    down = [x for x in down if x not in both]
    return up, down, both


def main():
    now = datetime.now(CST)
    m = fetch_all()
    ch = chains(m)
    net = sum(s for _, _, s, _ in ch)
    maxabs = sum(abs(s) for _, _, s, _ in ch) or 1
    n_active = sum(1 for _, _, s, _ in ch if s != 0)
    # 2026-10-27 修: 归一化用**固定满量程**, 不用实际 sum(|分|) 当分母。
    # 旧算法 bug: 8 条链里只有 2 条给分 (+1/+1) -> net=2, sum|分|=2 -> 归一 +100 (满分偏多),
    # 看起来"极度确信"实际只有 2 条弱信号 -> 10/27 上午 A 股全线跌, 判错。
    # 满量程 = 各链条理论最大绝对分之和 = 2+2+2+2+1+1+1+1 = 12
    FULL_SCALE = 12
    score = int(round(net / FULL_SCALE * 100))
    # 有效链 < 3 -> 方向无统计意义, 强制降级为中性 + 标注低置信
    low_conf = n_active < 3
    if low_conf:
        bias, bias_emoji = '中性震荡（低置信）', '⚪'
    elif score >= 40:
        bias, bias_emoji = '偏多', '🟢'
    elif score >= 15:
        bias, bias_emoji = '震荡偏多', '🟡'
    elif score > -15:
        bias, bias_emoji = '中性震荡', '⚪'
    elif score > -40:
        bias, bias_emoji = '震荡偏空', '🟠'
    else:
        bias, bias_emoji = '偏空', '🔴'
    up, down, conflict = build_sectors(ch)

    # ---- Markdown 报告
    L = []
    L.append(f"# 外围宏观链条审视 - {now.strftime('%Y-%m-%d %H:%M')} (UTC+8)\n")
    L.append(f"> 数据源: Yahoo Finance (美股/美债/美元指数/原油/黄金/VIX/人民币/亚太) + 新浪兜底")
    L.append(f"> 逻辑链: 用户原话 8 条 (美元/美债/美股/油价/黄金跷跷板) 量化落地\n")
    L.append(f"## 🎯 结论: {bias_emoji} **{bias}** (净信号 {net:+d} / 归一 {score:+d} / 有效链 {n_active}/8)\n")
    if low_conf:
        L.append(f"> ⚠️ **低置信**: 8 条链中仅 {n_active} 条给出方向信号 (<3 条), 外围无有效方向判断, "
                 f"A股按自身逻辑走。净信号 {net:+d} 归一 {score:+d} 已按固定满量程 12 计算 (非满分)。\n")
    else:
        L.append(f"> 有效链 {n_active}/8, 净信号 {net:+d}, 归一按固定满量程 12 计算 (非实际 sum|分|)。\n")
    L.append("### 核心链条传导路径\n")
    L.append("```")
    L.append("油价涨 -> 通胀升 -> 美联储加息 -> 美元走强 -> 资金回流美国 -> 新兴市场缺钱")
    L.append("                                        -> 风险资产承压 -> 黄金也受压")
    L.append("美元弱 + 美债弱 + 美股强 => 钱敢往外冲 => A股风险偏好回升")
    L.append("```\n")
    L.append("### 原始数据\n")
    L.append("| 指标 | 数据日期 | 最新 | 日涨跌 | 5日 | 20日 |")
    L.append("|---|---|---|---|---|---|")
    stale = []
    order = ['dxy', 'tnx', 'spx', 'ixic', 'dji', 'vix', 'wti', 'brent', 'gold', 'cnh', 'hsi', 'nikkei']
    for k in order:
        d = m.get(k, {})
        if 'err' in d:
            L.append(f"| {d.get('name', k)} | — | ❌取数失败 | — | — | — |")
            continue
        lag = _lag_days(d.get('date', ''))
        flag = f" ⚠️滞后{lag}天" if lag > 0 else ""
        if lag < 0:
            flag = " 盘中"      # bar 日期 = 今天 = 该品种当日未收盘, 数值是实时价
        if lag > 0:
            stale.append(f"{d.get('name', k)}({lag}天)")
        pts = ''
        if k == 'tnx':
            pts = f" ({d['d1_pts']*100:+.0f}bp)"
        L.append(f"| {d['name']} | {d.get('date', '—')}{flag} | {d['last']:.3f} | "
                 f"{d['d1']:+.2f}%{pts} | {d['d5']:+.2f}% | {d['d20']:+.2f}% |")
    if stale:
        L.append("\n> ⚠️ **数据滞后**: " + " / ".join(stale) +
                 " 的 bar 日期早于最近已收盘交易日, 其涨跌口径可能不是最新隔夜数据, 解读时须扣掉这部分。")
    L.append("\n### 8 条链逐条判定\n")
    L.append("| # | 链条 | 判定 | 信号 | 传导解释 |")
    L.append("|---|---|---|---|---|")
    for i, (name, verdict, s, why) in enumerate(ch, 1):
        mark = {2: '🟢强多', 1: '🟡偏多', 0: '⚪中性', -1: '🟠偏空', -2: '🔴强空'}[s]
        L.append(f"| {i} | {name} | {verdict} | {mark} | {why} |")
    L.append("\n### 对 A股的方向含义\n")
    L.append(f"**大盘倾向: {bias_emoji} {bias}** (净信号 {net:+d}, 归一 {score:+d}, 有效链 {n_active}/8)\n")
    if up:
        L.append("**受益方向:** " + " / ".join(up))
    if down:
        L.append("\n**承压方向:** " + " / ".join(down))
    if conflict:
        L.append("\n**分歧方向 (多链相反, 需结合国内面判断):** " + " / ".join(conflict))
    L.append("\n### 使用方式\n")
    L.append("- 这是**外围环境分**, 不是选股结论。开盘后需叠加国内消息面与资金面。")
    L.append("- 净信号 |score| > 40 时, 对A股大盘方向有较强指示; 15~40 为震荡市, 重个股轻指数;")
    L.append("- **有效链 < 3/8 时一律标注\"低置信\"**, 此时外围无方向, 不作为选股/择时依据;")
    L.append("  |score| < 15 时外围无方向, A股按自身逻辑走。")
    L.append("- 油链条对**板块**的影响是双向的: 油价涨利好石油石化/油服, 同时利空航空/化工/物流。")
    L.append(f"\n**生成**: macro_chain.py @ {now.strftime('%Y-%m-%d %H:%M:%S')}")

    md = '\n'.join(L)
    # MACRO_OUT 可指定输出文件名 (修正版/回溯用), 默认 macro_chain_YYYYMMDD.md
    out_name = os.environ.get('MACRO_OUT') or f"macro_chain_{now.strftime('%Y%m%d')}.md"
    fn = os.path.join(REPO, out_name)
    with open(fn, 'w', encoding='utf-8') as f:
        f.write(md)

    # ---- stdout 摘要 (cron 投递)
    print(f"🌍 外围宏观链条 | {now.strftime('%Y-%m-%d %H:%M')} | {bias_emoji} **{bias}** (净信号 {net:+d}, 归一 {score:+d})\n")
    for i, (name, verdict, s, why) in enumerate(ch, 1):
        mark = {2: '🟢', 1: '🟡', 0: '⚪', -1: '🟠', -2: '🔴'}[s]
        print(f"{mark} {i}. {name} — {verdict}: {why}")
    print(f"\n🟢 受益: {' / '.join(up) if up else '无明确'}")
    print(f"🔴 承压: {' / '.join(down) if down else '无明确'}")
    if conflict:
        print(f"⚠️ 分歧: {' / '.join(conflict)}")
    print(f"\n关键数据: 美元 {m.get('dxy',{}).get('last',0):.2f} ({m.get('dxy',{}).get('d1',0):+.2f}%) | "
          f"10Y {m.get('tnx',{}).get('last',0):.3f}% ({m.get('tnx',{}).get('d1_pts',0)*100:+.0f}bp) | "
          f"标普 {m.get('spx',{}).get('d1',0):+.2f}% | VIX {m.get('vix',{}).get('last',0):.2f} | "
          f"布伦特 {m.get('brent',{}).get('last',0):.2f} ({m.get('brent',{}).get('d1',0):+.2f}%) | "
          f"黄金 {m.get('gold',{}).get('last',0):.1f} ({m.get('gold',{}).get('d1',0):+.2f}%)")
    print(f"\n📄 {fn}")


if __name__ == '__main__':
    main()
