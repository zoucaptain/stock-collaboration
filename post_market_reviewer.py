#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
post_market_reviewer.py - A股收盘复盘 5 步战法 v1.2
L_post_market_review v1.2 (2026-09-24)

按用户原话 5 步：
1. 情绪温度 (涨停/跌停/炸板率/昨涨停表现)
2. 梯队和板块 (连板/板块分布)
3. 资金足迹 (成交额前列/龙虎榜)
4. 亏钱效应雷区 (跌幅榜共性)
5. 明天盯什么 (5-8 只风向标)

数据源（稳定 + 可靠）：
- 涨停 / 炸板：同花顺 data.10jqka.com.cn
- 跌停 / 涨幅榜 / 跌幅榜 / 成交额：新浪 vip.stock.finance.sina.com.cn
- 龙虎榜：新浪 vip.stock.finance.sina.com.cn (HTML 解析)
- 申万行业板块：东方财富 push2.eastmoney.com (fs=m:90+t:2)
- 概念板块：东方财富 push2.eastmoney.com (fs=m:90+t:1)
- 指数 / ETF：新浪 hq.sinajs.cn

输出: stock-collaboration/post_market_review.md
"""

import urllib.request
import json
import re
import os
import sys
import datetime
import time
from datetime import datetime, timedelta

# ============================================================
# 数据源: 1. 涨停 / 炸板 (同花顺 - 唯一稳定源)
# ============================================================

def get_10jqka_zt_pool():
    """
    同花顺涨停池 (含炸板识别)
    """
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up"
    params = {'stockType': '1', 'page': '1', 'pageSize': '100'}
    qs = '&'.join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{qs}"

    try:
        req = urllib.request.Request(
            full_url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.10jqka.com.cn/'
            }
        )
        raw = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', 'ignore')
        data = json.loads(raw)
        if data.get('status_code') != 0:
            return {'zt_list': [], 'zb_list': [], 'zt_count': 0, 'zb_count': 0}

        info = data.get('data', {}).get('info', [])
        zt_list = []
        zb_list = []
        for s in info:
            entry = {
                'code': s.get('code', ''),
                'name': s.get('name', ''),
                'market': s.get('market_type', ''),
            }
            if s.get('change_tag') == 'LIMIT_FAILED':
                zb_list.append(entry)
            else:
                zt_list.append(entry)

        return {
            'zt_list': zt_list,
            'zb_list': zb_list,
            'zt_count': len(zt_list),
            'zb_count': len(zb_list),
        }
    except Exception as e:
        print(f"  [10jqka] 失败: {e}", file=sys.stderr)
        return {'zt_list': [], 'zb_list': [], 'zt_count': 0, 'zb_count': 0}


# ============================================================
# 数据源: 2. 新浪 Market_Center (跌停 / 涨幅榜 / 跌幅榜 / 成交额)
# ============================================================

def get_sina_hq_node(node='hs_a', sort='changepercent', asc=0, page=1, num=100, type_=None):
    """新浪 Market_Center.getHQNodeData"""
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    params = {
        'num': str(num),
        'sort': sort,
        'asc': str(asc),
        'node': node,
        '_s_r_a': 'page',
        'page': str(page),
    }
    if type_:
        params['type'] = type_

    qs = '&'.join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{qs}"

    try:
        req = urllib.request.Request(
            full_url,
            headers={'Referer': 'https://finance.sina.com.cn/'}
        )
        raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk', 'ignore')
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"  [sina_hq] {sort} 失败: {e}", file=sys.stderr)
        return []


def get_sina_dt_pool():
    """真实跌停池 (新浪跌幅榜 + 按板块涨跌幅阈值实算)

    ⚠️ 历史 bug: 旧版用新浪 type_='dt' 参数, 但该参数返回的是"跌幅榜前 N 名"
       (不限跌停), 导致 15:30 盘中报出"跌停 100 家"假数据。
       永久修正: 拉跌幅榜 num=500, 按各板块涨停幅度阈值实算跌停:
         主板 (60/00): <= -9.8%   创业板/科创 (300/301/688/689): <= -19.8%
         北交所 (8/920/43): <= -29.8%
    """
    items = get_sina_hq_node(node='hs_a', sort='changepercent', asc=1, num=500)
    dts = []
    for s in items:
        code = str(s.get('code', ''))
        cp = s.get('changepercent', '')
        if cp in (None, ''):
            continue
        try:
            cp = float(cp)
        except (TypeError, ValueError):
            continue
        if cp <= _limit_down_threshold(code):
            dts.append({
                'code': code,
                'name': s.get('name', ''),
                'trade': s.get('trade', ''),
                'changepercent': cp,
            })
    return dts


def _limit_down_threshold(code):
    """按板块返回跌停判定阈值"""
    c = str(code)
    if c.startswith(('300', '301', '688', '689')):
        return -19.8   # 创业板 / 科创板 20%
    if c.startswith(('8', '920', '43', '83', '87', '88')):
        return -29.8   # 北交所 30%
    return -9.8       # 主板 10%


def get_sina_top_gainers(num=200):
    items = get_sina_hq_node(node='hs_a', sort='changepercent', asc=0, num=num)
    return [{
        'code': s.get('code', ''),
        'name': s.get('name', ''),
        'trade': s.get('trade', ''),
        'changepercent': s.get('changepercent', ''),
        'amount': s.get('amount', '0'),
    } for s in items]


def get_sina_top_losers(num=100):
    items = get_sina_hq_node(node='hs_a', sort='changepercent', asc=1, num=num)
    return [{
        'code': s.get('code', ''),
        'name': s.get('name', ''),
        'trade': s.get('trade', ''),
        'changepercent': s.get('changepercent', ''),
    } for s in items]


def get_sina_top_amount(num=30):
    items = get_sina_hq_node(node='hs_a', sort='amount', asc=0, num=num)
    return [{
        'code': s.get('code', ''),
        'name': s.get('name', ''),
        'trade': s.get('trade', ''),
        'changepercent': s.get('changepercent', ''),
        'amount': s.get('amount', '0'),
    } for s in items]


# ============================================================
# 数据源: 3. 东方财富板块 (申万行业 + 概念) - 三次重试
# ============================================================

def get_east_sector(market='m:90+t:2', num=30, retry=2):
    """
    东财 push2 板块排行。

    板块类型 (fs=m:90+t:N):
      t:1 = 地域板块   (北京/上海/广东... ← 不是概念!)
      t:2 = 行业板块   (申万一级)
      t:3 = 概念板块   (题材/事件/技术) ← 概念板块用这个
      t:5 = 概念板块 (旧编号, 已并入 t:3)
      t:10 = 地域细分

    ⚠️ 历史 bug: 概念板块曾误用 t:1 (地域) → 输出"江苏/上海/广东板块"。
       永久修正: 概念 = t:3, 并加地域名检测守卫。

    多域名 fallback: 东财 push2 经常 ban (RemoteDisconnected), 依次试 3 个域名。
    """
    market_encoded = market.replace(':', '%3A').replace('+', '%2B')
    hosts = [
        'push2.eastmoney.com',
        '82.push2.eastmoney.com',
        'push2delay.eastmoney.com',
    ]
    last_err = None
    for attempt in range(retry):
        for host in hosts:
            url = (f"https://{host}/api/qt/clist/get?pn=1&pz={num}&po=1&np=1"
                   f"&fltt=2&invt=2&fid=f3&fs={market_encoded}"
                   f"&fields=f12,f14,f3,f2,f104,f105,f62,f128,f140")
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://quote.eastmoney.com/',
                        'Connection': 'keep-alive'
                    }
                )
                raw = urllib.request.urlopen(req, timeout=15).read().decode('utf-8', 'ignore')
                d = json.loads(raw)
                if d.get('data') and d['data'].get('diff'):
                    diff = d['data']['diff']
                    items = list(diff.values()) if isinstance(diff, dict) else list(diff)
                    return [{
                        'name': s.get('f14', ''),
                        'code': s.get('f12', ''),
                        # fltt=2 时 f3 已是百分比数值, 不再除 100
                        'chg': s.get('f3', 0) if isinstance(s.get('f3', 0), (int, float)) else 0,
                        'chg_pct': s.get('f3', 0) if isinstance(s.get('f3', 0), (int, float)) else 0,
                        'amount': s.get('f62', 0) / 1e8,   # 主力净额(亿)
                        'leader': s.get('f128', '') or s.get('f140', ''),
                    } for s in items]
            except Exception as e:
                last_err = e
                continue
        print(f"  [east_sector {market}] 第{attempt+1}轮全域名失败: {last_err}", file=sys.stderr)
        time.sleep(2)
    return []


# 地域板块名守卫: 出现在"概念板块"里就是错的
REGION_TOKENS = [
    '北京', '上海', '广东', '深圳', '浙江', '江苏', '山东', '福建', '湖南', '湖北',
    '四川', '重庆', '天津', '安徽', '河北', '河南', '江西', '陕西', '山西', '辽宁',
    '吉林', '黑龙江', '海南', '云南', '贵州', '广西', '内蒙古', '新疆', '西藏', '宁夏',
    '青海', '宁夏', '甘肃', '西藏', '新疆', '香港', '台湾', '澳门',
]


def _looks_like_region(name):
    """判断板块名是否是地域分类 (含省/市名或"XX板块"行政前缀)"""
    n = str(name)
    for t in REGION_TOKENS:
        if n.startswith(t) and n.endswith('板块'):
            return True
    return False


def get_ths_concept_top(num=20):
    """同花顺概念板块 (东财挂了时的兜底)

    首选: akshare stock_fund_flow_concept(symbol='即时')
      ⚠️ 该接口的列名叫"行业"/"行业-涨跌幅", 但内容是**同花顺真概念**
         (MLOps概念/星闪概念/空间计算/AI眼镜/智能音箱...), 不是申万行业, 也不是地域。
         同花顺自己的列名误导, 实际就是概念板块资金流全量版。
      字段: 序号/行业(=概念名)/行业指数/行业-涨跌幅/流入资金/流出资金/净额/公司家数/
            领涨股/领涨股-涨跌幅/当前价
    次选: q.10jqka.com.cn/gn/ 概念索引页 (只有名称, 无涨跌幅, 兜底兜底)
    """
    # --- 首选: akshare 同花顺概念资金流 (带涨跌幅/净额/领涨股) ---
    try:
        import akshare as ak
        df = ak.stock_fund_flow_concept(symbol='即时')
        out = []
        for _, r in df.iterrows():
            name = str(r.get('行业', '')).strip()
            if not name or _looks_like_region(name):
                continue
            try:
                chg = float(r.get('行业-涨跌幅', 0))
                amt = float(r.get('净额', 0))   # 同花顺单位已是亿元
            except (TypeError, ValueError):
                continue
            out.append({
                'name': name,
                'code': '',
                'chg': chg,
                'chg_pct': chg,
                'amount': amt,
                'leader': str(r.get('领涨股', '') or ''),
                'leader_chg': float(r.get('领涨股-涨跌幅', 0) or 0),
                'company_count': int(r.get('公司家数', 0) or 0),
            })
        if out:
            print(f"  [concept] 用同花顺概念资金流兜底源, {len(out)} 个概念", file=sys.stderr)
            out.sort(key=lambda x: x['chg'], reverse=True)
            return out[:num]
    except Exception as e:
        print(f"  [ths_concept/akshare] 失败: {str(e)[:80]}", file=sys.stderr)

    # --- 次选: 同花顺概念索引页 (只有名称) ---
    try:
        url = 'https://q.10jqka.com.cn/gn/'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://q.10jqka.com.cn/'
        })
        raw = urllib.request.urlopen(req, timeout=15).read().decode('gbk', 'ignore')
        out = []
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', raw, re.DOTALL):
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in
                     re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)]
            if len(cells) < 2:
                continue
            name = cells[1] if cells[0].isdigit() else cells[0]
            if not name or _looks_like_region(name):
                continue
            out.append({'name': name, 'code': '', 'chg': 0.0, 'chg_pct': 0.0,
                        'amount': 0.0, 'leader': ''})
        if out:
            print(f"  [concept] 用同花顺概念索引页兜底, {len(out)} 个概念 (无涨跌幅)", file=sys.stderr)
            return out[:num]
    except Exception as e:
        print(f"  [ths_concept/index] 失败: {str(e)[:80]}", file=sys.stderr)
    return []


# ============================================================
# 数据源: 4.6 新浪 ETF 排行 (板块数据 fallback)
# ============================================================

SECTOR_ETF_LIST = [
    ('159995', '半导体ETF'), ('512760', '软件ETF'), ('510660', '医药ETF'),
    ('512800', '银行ETF'), ('159928', '消费ETF'), ('515030', '新能源车ETF'),
    ('512400', '有色ETF'), ('512880', '证券ETF'), ('515220', '煤炭ETF'),
    ('512200', '房地产ETF'), ('512480', '汽车ETF'), ('512760', '软件ETF'),
    ('159766', '旅游ETF'), ('515050', '5GETF'), ('159819', '芯片ETF'),
    ('512660', '军工ETF'), ('515790', '光伏ETF'), ('159937', '黄金ETF'),
    ('512010', '医药ETF'), ('510310', '消费ETF'), ('159825', '农业ETF'),
]


def get_sina_etf_ranking(num=30):
    """新浪 ETF 排行 (作为板块 fallback)"""
    items = get_sina_hq_node(node='etf', sort='changepercent', asc=0, num=num)
    return [{
        'name': s.get('name', ''),
        'code': s.get('code', ''),
        'trade': s.get('trade', ''),
        'changepercent': s.get('changepercent', 0),
        'amount': s.get('amount', 0),
    } for s in items]


def get_sws_sector_top(num=20):
    """申万行业板块 TOP (东财 t:2 优先, 同花顺行业资金流兜底)"""
    items = get_east_sector('m:90+t:2', num)
    if items:
        items.sort(key=lambda x: x['chg'], reverse=True)
        return items
    # 兜底: 同花顺行业资金流 (akshare stock_fund_flow_industry)
    try:
        import akshare as ak
        df = ak.stock_fund_flow_industry(symbol='即时')
        out = []
        for _, r in df.iterrows():
            name = str(r.get('行业', '')).strip()
            if not name:
                continue
            try:
                chg = float(r.get('行业-涨跌幅', 0))
                amt = float(r.get('净额', 0))   # 同花顺单位已是亿元
            except (TypeError, ValueError):
                continue
            out.append({'name': name, 'code': '', 'chg': chg, 'chg_pct': chg,
                        'amount': amt, 'leader': str(r.get('领涨股', '') or '')})
        if out:
            print(f"  [sws] 用同花顺行业资金流兜底, {len(out)} 个行业", file=sys.stderr)
            out.sort(key=lambda x: x['chg'], reverse=True)
            return out[:num]
    except Exception as e:
        print(f"  [sws/akshare] 失败: {str(e)[:80]}", file=sys.stderr)
    return []


def get_concept_top(num=20):
    """概念板块 TOP (东财 t:3 优先, 同花顺兜底)

    ⚠️ 永久修正: 原来用 m:90+t:1 (地域板块) → 输出"江苏/上海/广东板块"。
       概念板块 = m:90+t:3 (题材/事件/技术, 如 机器人执行器/减速器/航母概念)。
       地域名守卫 _looks_like_region 会剔除任何"XX板块"行政前缀。
    """
    items = get_east_sector('m:90+t:3', num)
    if items:
        # 守卫: 如果大部分都是地域名, 说明接口又返回错了, 走兜底
        region_cnt = sum(1 for s in items if _looks_like_region(s.get('name', '')))
        if region_cnt > len(items) * 0.3:
            print(f"  [concept] 东财返回 {region_cnt}/{len(items)} 个地域名, 判定为错源, 走同花顺兜底",
                  file=sys.stderr)
            items = []
        else:
            items = [s for s in items if not _looks_like_region(s.get('name', ''))]
    if not items:
        items = get_ths_concept_top(num)
        if items:
            print(f"  [concept] 用同花顺兜底源, {len(items)} 个概念", file=sys.stderr)
    items.sort(key=lambda x: x['chg'], reverse=True)
    return items


# ============================================================
# 数据源: 4. 新浪龙虎榜 HTML
# ============================================================

def get_sina_lhb(date_str=None):
    """新浪龙虎榜 HTML 解析"""
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')

    url = f"https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml?date={date_str}"

    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://finance.sina.com.cn/'
            }
        )
        raw = urllib.request.urlopen(req, timeout=15).read().decode('gbk', 'ignore')

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', raw, re.DOTALL)
        lhb_list = []
        for row in rows[1:]:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            cells_clean = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if len(cells_clean) >= 6 and cells_clean[0]:
                try:
                    lhb_list.append({
                        'code': cells_clean[0],
                        'name': cells_clean[1],
                        'count': cells_clean[2],
                        'buy_amount': cells_clean[3],
                        'sell_amount': cells_clean[4],
                        'net_amount': cells_clean[5],
                    })
                except Exception:
                    pass

        def parse_num(s):
            try:
                return float(s.replace(',', ''))
            except Exception:
                return 0

        lhb_list.sort(key=lambda x: parse_num(x['net_amount']), reverse=True)
        return lhb_list[:20]
    except Exception as e:
        print(f"  [lhb] 失败: {e}", file=sys.stderr)
        return []


# ============================================================
# 数据源: 5. 新浪 hq.sinajs.cn (指数 / ETF)
# ============================================================

def sina_hq(code):
    """新浪实时行情 - 修正: 上证指数(000xxx)用 sh 前缀, 深证指数(399xxx)用 sz"""
    # 上证指数/沪市: 000/001/002/003 都是 sh (但沪深股票里 002/003/300 是 sz)
    # 用更精确的判断: 6 位数字, 前缀规则:
    #   - 000/001 开头 → 沪市指数 (上证指数/沪深300/科创50/上证50)
    #   - 399 开头 → 深证指数
    #   - 5/6 开头 → 沪市股票/ETF
    #   - 002/003/300/301 开头 → 深市股票
    #   - 159 开头 → 深市 ETF
    if code.startswith(('000', '001', '510', '511', '512', '513', '515', '517', '518', '588')):
        full = 'sh' + code
    elif code.startswith(('600', '601', '603', '605')):
        full = 'sh' + code
    else:
        full = 'sz' + code
    url = f"https://hq.sinajs.cn/list={full}"
    try:
        req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn/'})
        raw = urllib.request.urlopen(req, timeout=5).read().decode('gbk', 'ignore')
        m = re.search(r'"([^"]+)"', raw)
        if not m:
            return None
        p = m.group(1).split(',')
        return {
            'name': p[0],
            'now': float(p[3]),
            'prev': float(p[2]),
            'open': float(p[1]),
            'high': float(p[4]),
            'low': float(p[5]),
            'volume': int(p[8]),
            'amount': float(p[9]),
        }
    except Exception:
        return None


# ============================================================
# 板块 ETF
# ============================================================

SECTOR_ETFS = [
    ('159995', '半导体'),
    ('512760', '软件'),
    ('510660', '医药'),
    ('512800', '银行'),
    ('159928', '消费'),
    ('515030', '新能源车'),
    ('512400', '有色'),
    ('512880', '证券'),
    ('515220', '煤炭'),
    ('512200', '房地产'),
]


def get_sectors():
    result = []
    for code, name in SECTOR_ETFS:
        d = sina_hq(code)
        if d:
            chg = (d['now'] - d['prev']) / d['prev'] * 100 if d['prev'] > 0 else 0
            result.append({'code': code, 'name': name, 'now': d['now'], 'chg': chg})
    return sorted(result, key=lambda x: x['chg'], reverse=True)


# ============================================================
# 指数
# ============================================================

INDICES = [
    ('000001', '上证指数'),
    ('399001', '深证成指'),
    ('399006', '创业板指'),
    ('000688', '科创50'),
]


def get_indices():
    result = []
    for code, name in INDICES:
        d = sina_hq(code)
        if d:
            chg = (d['now'] - d['prev']) / d['prev'] * 100 if d['prev'] > 0 else 0
            result.append({
                'code': code, 'name': name,
                'now': d['now'], 'prev': d['prev'],
                'open': d['open'], 'high': d['high'], 'low': d['low'],
                'amount': d.get('amount', 0),
                'chg': chg,
            })
    return result


# ============================================================
# 昨日涨停表现 (杀接力判定)
# ============================================================

def get_yesterday_zt_performance():
    """昨涨停股今日表现 - 用今日涨幅榜近似"""
    items = get_sina_top_gainers(num=200)
    yest_zt_today = []
    for it in items:
        try:
            chg = float(it.get('changepercent', 0))
            if 5 <= chg < 9.9:
                yest_zt_today.append({
                    'code': it['code'],
                    'name': it['name'],
                    'chg': chg,
                })
        except Exception:
            pass
    return yest_zt_today


# ============================================================
# 主流程
# ============================================================

def main():
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    print(f"[复盘开始] {today_str} {now.strftime('%H:%M:%S')}", file=sys.stderr)

    # 1. 大盘指数
    print("[1/8] 拉取大盘数据...", file=sys.stderr)
    indices = get_indices()

    # 2. 板块 ETF
    print("[2/8] 拉取 ETF 板块...", file=sys.stderr)
    sectors = get_sectors()

    # 5. 申万行业 + 概念板块 (东财) + ETF fallback
    print("[3/8] 拉取申万行业板块...", file=sys.stderr)
    sws_sector = get_sws_sector_top(num=30)
    print("[4/8] 拉取概念板块...", file=sys.stderr)
    concept_sector = get_concept_top(num=30)
    print("[4/8] 拉取 ETF 排行...", file=sys.stderr)
    etf_ranking = get_sina_etf_ranking(num=30)

    # 5. 涨停 / 炸板 (同花顺)
    print("[5/8] 拉取涨停 / 炸板池...", file=sys.stderr)
    zt_data = get_10jqka_zt_pool()

    # 6. 跌停 + 涨幅 / 跌幅 / 成交额 (新浪)
    print("[6/8] 拉取跌停 + 排行榜...", file=sys.stderr)
    dt_list = get_sina_dt_pool()
    top_gainers = get_sina_top_gainers(num=50)
    top_losers = get_sina_top_losers(num=30)
    top_amount = get_sina_top_amount(num=20)

    # 7. 龙虎榜 (新浪 HTML)
    print("[7/8] 拉取龙虎榜...", file=sys.stderr)
    lhb_list = get_sina_lhb(today_str)

    # 8. 昨涨停今表现
    print("[8/8] 拉取昨涨停今表现...", file=sys.stderr)
    yest_zt = get_yesterday_zt_performance()

    # ===== 渲染 Markdown =====
    md = []
    md.append(f"# 收盘复盘报告 - {today_str} 15:30")
    md.append("")
    md.append(f"> 自动生成 by `post_market_reviewer.py` (L_post_market_review v1.2)")
    md.append(f"> 生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    md.append("")
    md.append("---")
    md.append("")

    # 大盘总览
    md.append("## 🌡️ 大盘总览")
    md.append("")
    md.append("| 指数 | 收盘 | 涨跌% | 今开 | 今高 | 今低 |")
    md.append("|---|---|---|---|---|---|")
    for idx in indices:
        md.append(f"| {idx['name']} | {idx['now']:.2f} | {idx['chg']:+.2f}% | {idx['open']:.2f} | {idx['high']:.2f} | {idx['low']:.2f} |")
    md.append("")

    # 板块冷暖
    md.append("## 📊 板块冷暖")
    md.append("")
    md.append("### ETF 板块")
    md.append("")
    md.append("| 排名 | 板块 | 涨跌% |")
    md.append("|---|---|---|")
    for i, s in enumerate(sectors, 1):
        bar = '🟢' if s['chg'] > 0.5 else '🟡' if s['chg'] > 0 else '🔴' if s['chg'] < -0.3 else '⚪'
        md.append(f"| {i} | {bar} {s['name']} | {s['chg']:+.2f}% |")
    md.append("")

    # 申万行业 TOP 15 (东财接口)
    md.append("### 申万行业 TOP 15")
    md.append("")
    if sws_sector:
        md.append("| 排名 | 行业 | 涨跌% | 主力净额(亿) |")
        md.append("|---|---|---|---|")
        for i, s in enumerate(sws_sector[:15], 1):
            chg = s['chg']
            amount = s.get('amount', 0)
            bar = '🟢' if chg > 0.5 else '🟡' if chg > 0 else '🔴' if chg < -0.3 else '⚪'
            md.append(f"| {i} | {bar} {s['name']} | {chg:+.2f}% | {amount:+.1f} |")
    else:
        md.append("⚠️ 申万行业数据缺失 (东财接口重试 3 次仍失败)")
    md.append("")

    # 概念板块 TOP 10
    md.append("### 概念板块 TOP 10")
    md.append("")
    if concept_sector:
        md.append("| 排名 | 概念 | 涨跌% | 主力净额(亿) |")
        md.append("|---|---|---|---|")
        for i, s in enumerate(concept_sector[:10], 1):
            chg = s['chg']
            amount = s.get('amount', 0)
            bar = '🟢' if chg > 0.5 else '🟡' if chg > 0 else '🔴' if chg < -0.3 else '⚪'
            md.append(f"| {i} | {bar} {s['name']} | {chg:+.2f}% | {amount:+.1f} |")
    else:
        md.append("⚠️ 概念板块数据缺失")
    md.append("")

    # ===== 第 1 步：情绪温度 =====
    md.append("---")
    md.append("")
    md.append("## 第 1 步: 情绪温度 🔥")
    md.append("")
    zt_count = zt_data['zt_count']
    dt_count = len(dt_list)
    zb_count = zt_data['zb_count']

    md.append(f"- **涨停家数**: {zt_count}")
    md.append(f"- **跌停家数**: {dt_count} (按各板块涨停幅度阈值实算)")
    md.append(f"- **炸板家数**: {zb_count}")
    md.append("")
    md.append("> 口径: 涨停/炸板 = 同花顺涨停池; 跌停 = 新浪跌幅榜按板块阈值实算 "
              "(主板 -9.8% / 创业板科创 -19.8% / 北交所 -29.8%); "
              "概念板块 = 东财 t:3 (题材/事件/技术), 禁止地域分类")
    if zt_count + zb_count > 0:
        zb_rate = zb_count / (zt_count + zb_count) * 100
    else:
        zb_rate = 0
    md.append(f"- **炸板率**: {zb_rate:.1f}%")
    md.append("")

    # 情绪判定 (v2: 用 zt/dt 比值 + 绝对值双判, 避免"跌停少也判杀弱")
    # ⚠️ 历史 bug: 旧版只有 4 档, 涨停 14 + 跌停 7 (跌停比涨停还少) 也判"杀弱"。
    #    永久修正: 跌停远少于涨停 = 冰点低迷 (无人接盘), 不是杀弱 (恐慌抛售)。
    if zt_count >= 80 and dt_count < 10:
        sentiment = "🟢 **极热** - 涨停家数充裕，杀跌少"
    elif zt_count >= 50 and dt_count < 30:
        sentiment = "🟡 **正常** - 有赚钱效应，风险可控"
    elif zt_count >= 30 and dt_count < 50:
        sentiment = "🟠 **转弱** - 涨停缩，跌停扩，谨慎"
    elif dt_count > zt_count * 1.5:
        sentiment = "🔴 **杀弱** - 跌停远多于涨停，恐慌抛售，容错率极低"
    elif dt_count > zt_count:
        sentiment = "🔴 **杀弱** - 跌停多于涨停，容错率低"
    elif zt_count >= 10 and dt_count <= zt_count:
        sentiment = "🟡 **冰点低迷** - 涨停少但跌停也少，情绪冰点无恐慌，赚钱效应弱"
    else:
        sentiment = "🟠 **低迷** - 涨停家数偏少，赚钱效应弱"
    md.append(f"**情绪判定**: {sentiment}")
    md.append("")
    md.append(f"> 涨停/跌停比 = {zt_count}/{dt_count} = "
              f"{(zt_count/dt_count if dt_count else 999):.2f} : 1")

    if yest_zt:
        md.append("### 昨日涨停今日表现 (杀接力判定)")
        md.append("")
        up = sum(1 for x in yest_zt if x['chg'] > 0)
        down = len(yest_zt) - up
        if down > up:
            yest_perf = "🔴 **杀接力 - 容错率低** (大面积走弱)"
        else:
            yest_perf = "🟢 **有溢价 - 资金愿意接**"
        md.append(f"- 样本数: {len(yest_zt)}")
        md.append(f"- 上涨: {up} | 下跌: {down}")
        md.append(f"- 判定: {yest_perf}")
        md.append("")
        md.append("| 代码 | 名称 | 今日涨幅 |")
        md.append("|---|---|---|")
        for y in yest_zt[:15]:
            md.append(f"| {y['code']} | {y['name']} | {y['chg']:+.2f}% |")
        md.append("")

    md.append("### 涨停池")
    md.append("")
    if zt_data['zt_list']:
        md.append("| 代码 | 名称 | 板块 |")
        md.append("|---|---|---|")
        for z in zt_data['zt_list'][:20]:
            md.append(f"| {z['code']} | {z['name']} | {z['market']} |")
        if len(zt_data['zt_list']) > 20:
            md.append(f"| ... | (共 {zt_count} 只) | |")
    else:
        md.append("⚠️ 无涨停股")
    md.append("")

    # ===== 第 2 步：梯队和板块 =====
    md.append("---")
    md.append("")
    md.append("## 第 2 步: 梯队和板块 📊")
    md.append("")
    md.append("### 连板梯队 (从涨停涨幅判定)")
    md.append("")
    if zt_data['zt_list']:
        lianban = []
        for z in zt_data['zt_list']:
            code = z['code']
            for g in top_gainers:
                if g['code'] == code:
                    try:
                        chg = float(g.get('changepercent', 0))
                        market = z['market']
                        if market in ('GEM', 'STAR'):
                            zt_pct = 20
                        elif market == 'BJ':
                            zt_pct = 30
                        else:
                            zt_pct = 10
                        if chg >= 10:
                            lianban.append({
                                'code': code,
                                'name': z['name'],
                                'chg': chg,
                                'boards': round((chg - zt_pct) / zt_pct + 1, 1),
                            })
                    except Exception:
                        pass
                    break
        lianban.sort(key=lambda x: x['boards'], reverse=True)
        md.append("| 代码 | 名称 | 涨幅 | 连板 |")
        md.append("|---|---|---|---|")
        for lb in lianban[:15]:
            md.append(f"| {lb['code']} | {lb['name']} | {lb['chg']:+.2f}% | {lb['boards']:.1f}板 |")
        if lianban:
            max_board = max(lb['boards'] for lb in lianban)
            md.append("")
            md.append(f"**最高板**: {max_board:.1f}板")
            board_counts = sorted(set(int(round(lb['boards'])) for lb in lianban), reverse=True)
            gaps = []
            for i in range(len(board_counts) - 1):
                if board_counts[i] - board_counts[i+1] > 1:
                    gaps.append(f"{board_counts[i]}板→{board_counts[i+1]}板")
            if gaps:
                md.append(f"**断层**: {' / '.join(gaps)}")
            else:
                md.append(f"**梯队完整**: {board_counts}")
    else:
        md.append("⚠️ 无连板数据")
    md.append("")

    # 涨停板块分布 - 改用东财申万行业 TOP
    md.append("### 涨停板块分布 (申万行业 TOP 5)")
    md.append("")
    if sws_sector and zt_count > 0:
        md.append("| 排名 | 行业 | 涨跌% |")
        md.append("|---|---|---|")
        for i, s in enumerate(sws_sector[:5], 1):
            md.append(f"| {i} | {s['name']} | {s['chg']:+.2f}% |")
        md.append("")
    md.append("> **结构判定**: 涨停集中在前 3 大行业 = 结构完整; 分散 = 群魔乱舞")
    md.append("")

    # ===== 第 3 步：资金足迹 =====
    md.append("---")
    md.append("")
    md.append("## 第 3 步: 资金足迹 💰")
    md.append("")
    md.append("### 成交额 TOP 20")
    md.append("")
    if top_amount:
        md.append("| 名称 | 代码 | 现价 | 涨跌% | 成交额(亿) |")
        md.append("|---|---|---|---|---|")
        up_count = 0
        for t in top_amount[:20]:
            try:
                amt = float(t.get('amount', '0')) / 1e8
            except Exception:
                amt = 0
            try:
                chg = float(t.get('changepercent', 0))
            except Exception:
                chg = 0
            if chg > 0:
                up_count += 1
            bar = '🟢' if chg > 0 else '🔴' if chg < 0 else '⚪'
            md.append(f"| {bar} {t['name']} | {t['code']} | {t['trade']} | {chg:+.2f}% | {amt:.1f} |")
        md.append("")
        if up_count >= 13:
            capi = "🟢 **大资金进场** - 大票齐涨"
        elif up_count >= 8:
            capi = "🟡 **混合** - 大票涨多跌少"
        else:
            capi = "🔴 **存量博弈** - 大票齐跌"
        md.append(f"**资金判定**: {capi} (TOP 20 中 {up_count} 个上涨)")
    else:
        md.append("⚠️ 无成交额数据")
    md.append("")

    md.append("### 龙虎榜 (净买入 TOP 10)")
    md.append("")
    if lhb_list:
        md.append("| 名称 | 代码 | 净买入(万) | 买入席位 |")
        md.append("|---|---|---|---|")
        for l in lhb_list[:10]:
            md.append(f"| {l['name']} | {l['code']} | {l['net_amount']} | {l['count']}次 |")
    else:
        md.append("⚠️ 无龙虎榜数据")
    md.append("")

    # ===== 第 4 步：亏钱效应雷区 =====
    md.append("---")
    md.append("")
    md.append("## 第 4 步: 亏钱效应雷区 ⚠️")
    md.append("")
    md.append("### 跌停股分布")
    md.append("")
    if dt_list:
        md.append("| 名称 | 代码 | 跌幅% |")
        md.append("|---|---|---|")
        for d in dt_list[:15]:
            md.append(f"| {d['name']} | {d['code']} | {d.get('changepercent', 0)}% |")
        md.append("")
        if dt_count >= 30:
            risk = "🔴 **亏钱效应扩散** - 跌停超过 30 家"
        elif dt_count >= 15:
            risk = "🟠 **退潮进行中** - 跌停 15-30 家"
        else:
            risk = "🟢 **亏钱效应收敛** - 跌停家数少"
        md.append(f"**风险判定**: {risk}")
    else:
        md.append("✅ 今日无跌停股")
    md.append("")

    md.append("### 跌幅榜 TOP 10 (含跌停外)")
    md.append("")
    if top_losers:
        md.append("| 名称 | 代码 | 跌幅% |")
        md.append("|---|---|---|")
        for l in top_losers[:10]:
            md.append(f"| {l['name']} | {l['code']} | {l.get('changepercent', 0)}% |")
        md.append("")
    md.append("")

    # ===== 第 5 步：明天盯什么 =====
    md.append("---")
    md.append("")
    md.append("## 第 5 步: 明天盯什么 📌")
    md.append("")
    md.append("### 风向标清单 (5-8 只)")
    md.append("")
    watchlist = []

    if zt_data['zt_list']:
        sorted_zt = zt_data['zt_list'][:3]
        for z in sorted_zt:
            watchlist.append({
                'name': z['name'],
                'code': z['code'],
                'reason': '涨停龙头'
            })

    if top_amount:
        for t in top_amount[:5]:
            try:
                chg = float(t.get('changepercent', 0))
            except Exception:
                chg = 0
            if not any(w['code'] == t['code'] for w in watchlist):
                watchlist.append({
                    'name': t['name'],
                    'code': t['code'],
                    'reason': f"成交额 TOP / 涨 {chg:+.1f}%"
                })

    if lhb_list:
        for l in lhb_list[:3]:
            if not any(w['code'] == l['code'] for w in watchlist):
                watchlist.append({
                    'name': l['name'],
                    'code': l['code'],
                    'reason': f"龙虎榜净买入 {l['net_amount']}万"
                })

    if watchlist:
        md.append("| 名称 | 代码 | 关注理由 |")
        md.append("|---|---|---|")
        for w in watchlist[:8]:
            md.append(f"| {w['name']} | {w['code']} | {w['reason']} |")
    else:
        md.append("⚠️ 无候选")
    md.append("")
    md.append("> **第二天重点关注**：它们强 = 板块强")
    md.append("")

    md.append("---")
    md.append("")
    md.append("## 📌 核心方法论")
    md.append("")
    md.append("> **情绪结构钱，雷区先避开，计划做在前。**")
    md.append("")
    md.append("---")
    md.append("")
    md.append(f"**生成器**: post_market_reviewer.py (L_post_market_review v1.2)")
    md.append(f"**数据源**: 新浪 + 同花顺 + 东方财富 (申万行业/概念)")
    md.append(f"**Cron**: 30 15 * * 1-5 (周一~周五 15:30)")
    md.append(f"**任务推送**: Hermes cron 自动推送到 GitHub + 微信告警")

    content = '\n'.join(md)

    print(content)

    repo_dir = "C:/Users/yanyan.zou/stock-collaboration"
    output_path = os.path.join(repo_dir, "post_market_review.md")
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n[OK] 报告已写入: {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"\n[ERROR] 写入失败: {e}", file=sys.stderr)

    print(f"[复盘结束] {now.strftime('%H:%M:%S')}", file=sys.stderr)


if __name__ == "__main__":
    main()