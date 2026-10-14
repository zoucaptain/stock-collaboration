"""
hermes stock data source - v2.0
统一数据入口 + 多源校验
位置: ~/.hermes/scripts/stock_data_source.py

用法:
    from stock_data_source import StockData
    
    # 单票双源验证
    data = StockData.fetch_verified('002422')
    print(data['name'], data['now'], data['chg_pct'])
    
    # 大盘指数双源验证
    indices = StockData.fetch_indices_verified()
    print(indices['上证指数']['now'], indices['上证指数']['chg_pct'])
"""
import urllib.request
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class DataError(Exception):
    """数据错误异常"""
    pass


class StockData:
    """统一股票数据接口"""
    
    # 上证代码段 (沪深主板/科创板/上证指数/上证 ETF)
    SH_PREFIX_RULES = (
        '600', '601', '603', '605', '688', '689',  # 股票
        '510', '511', '512', '513', '515', '517', '518', '588',  # ETF
    )
    # 上证指数 (代码段)
    SH_INDEX_CODES = {
        '000001': '上证指数',
        '000300': '沪深300',
        '000688': '科创50',
        '000852': '中证1000',
        '000905': '中证500',
        '000016': '上证50',
        '000010': '上证180',
        '000009': '上证380',
        '000006': '上证50',
        '000003': 'Ｂ股指数',
        '000002': 'Ａ股指数',
    }
    # 深证股票 (主板/中小板/创业板/深证 ETF/深证指数)
    SZ_PREFIX_RULES = (
        '002', '003', '300', '301',  # 股票
        '150', '151', '159', '160', '161', '162', '163', '164', '165', '166', '167', '168', '169',  # ETF
        '399',  # 深证指数
    )

    @staticmethod
    def _smart_prefix(code: str) -> str:
        """智能判断股票前缀"""
        # 1. 先看上证指数白名单
        if code in StockData.SH_INDEX_CODES:
            return 'sh'
        # 2. 上证前缀
        for rule in StockData.SH_PREFIX_RULES:
            if code.startswith(rule):
                return 'sh'
        # 3. 深证前缀
        for rule in StockData.SZ_PREFIX_RULES:
            if code.startswith(rule):
                return 'sz'
        # 4. 默认深证
        return 'sz'

    @staticmethod
    def _tx_fetch(code: str) -> Optional[Dict]:
        """腾讯接口拉单票 (v2.1 - 加量比/市值/换手率/5日均价)

        字段实测 (2026-10-09):
          p[3] 当前价 (元)
          p[4] 昨收 (元)
          p[5] 今开 (元)
          p[6] 累计成交 (手)
          p[33] 今日最高 (元)
          p[34] 今日最低 (元)
          p[37] 累计成交额 (万元)
          p[38] 换手率 (%)
          p[43] 振幅 (%)
          p[44] 流通市值 (亿)
          p[45] 总市值 (亿)
          p[49] 量比 (倍) — 同花顺口径
          p[50] PE
          p[51] 5日均价 (元)
        """
        prefix = StockData._smart_prefix(code)
        full = f"{prefix}{code}"
        url = f"https://qt.gtimg.cn/q={full}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk', 'ignore')
            m = re.search(r'"([^"]+)"', raw)
            if not m:
                return None
            p = m.group(1).split('~')
            if len(p) < 52:
                return None

            def fnum(i):
                try:
                    return float(p[i])
                except (ValueError, IndexError):
                    return 0.0

            return {
                'source': 'tx',
                'code': code,
                'name': p[1],
                'now': fnum(3),
                'prev': fnum(4),
                'open': fnum(5),
                'volume_hand': fnum(6),
                'high': fnum(33),
                'low': fnum(34),
                'chg_dot': fnum(31),
                'chg_pct': fnum(32),
                'amount_yi': fnum(37) / 10000,
                'turnover_pct': fnum(38),
                'amplitude_pct': fnum(43),
                'flow_mv_yi': fnum(44),
                'total_mv_yi': fnum(45),
                'liangbi': fnum(49),
                'pe': fnum(50),
                'avg_5d': fnum(51),
            }
        except Exception as e:
            return {'source': 'tx', 'code': code, 'error': str(e)}

    @staticmethod
    def kline_tx_nf(code: str, lmt: int = 35) -> Optional[Dict]:
        """腾讯不复权 K 线 (修复版 v2.1)

        必用这个而不是 six_step_picker.py 的 qfqday
        qfqday 会处理掉历史涨停, 不复权 day 才是真实涨幅

        Returns:
            {
                'klines': [[日期, 开, 收, 高, 低, 成交量], ...],
                'zt_count_30': 30天内涨停次数,
                'source': 'tx',
            }
        """
        qcode = "sh" + code if code.startswith(("5","6")) else "sz" + code
        # 用 /kline/kline 接口 (不带 fq 前缀) 拿不复权数据
        url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={qcode},day,,,{lmt}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            sd = data.get("data", {}).get(qcode, {})
            klines = sd.get("day", [])
            if not klines:
                return None
            # 字段: [日期, 开, 收, 高, 低, 成交量]
            # 涨停 = (收 - 开) / 开 >= 9.95%
            parsed = []
            zt = 0
            for k in klines:
                if len(k) >= 5:
                    try:
                        op = float(k[1])
                        cl = float(k[2])
                        chg = (cl - op) / op * 100 if op > 0 else 0
                        parsed.append({
                            'date': k[0], 'open': op, 'close': cl,
                            'high': float(k[3]), 'low': float(k[4]),
                            'vol': float(k[5]),
                            'change_pct': chg,
                        })
                        if chg >= 9.95:
                            zt += 1
                    except (ValueError, IndexError):
                        pass
            return {
                'source': 'tx',
                'code': code,
                'klines': parsed,
                'zt_count_total': zt,
                'zt_count_30': sum(1 for k in parsed[-30:] if k['change_pct'] >= 9.95),
            }
        except Exception as e:
            return {'source': 'tx', 'code': code, 'error': str(e)}

    @staticmethod
    def _sina_fetch(code: str) -> Optional[Dict]:
        """新浪接口拉单票"""
        prefix = StockData._smart_prefix(code)
        full = f"{prefix}{code}"
        url = f"https://hq.sinajs.cn/list={full}"
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://finance.sina.com.cn/',
            })
            raw = urllib.request.urlopen(req, timeout=8).read().decode('gbk', 'ignore')
            m = re.search(r'"([^"]+)"', raw)
            if not m:
                return None
            p = m.group(1).split(',')
            if len(p) < 6:
                return None
            now = float(p[3])
            prev = float(p[2])
            return {
                'source': 'sina',
                'code': code,
                'name': p[0],
                'now': now,
                'prev': prev,
                'high': float(p[4]),
                'low': float(p[5]),
                'chg_pct': (now - prev) / prev * 100 if prev > 0 else 0,
                'chg_dot': now - prev,
            }
        except Exception as e:
            return {'source': 'sina', 'code': code, 'error': str(e)}

    @staticmethod
    def fetch_verified(code: str, strict: bool = True) -> Dict:
        """
        双源验证拉单票数据。
        
        Args:
            code: 6 位股票代码
            strict: True=严格模式 (双源不一致抛异常), False=宽松 (返回 tx)
        
        Returns:
            dict 包含 tx + sina + verified 字段
        
        Raises:
            DataError: 当 strict=True 且双源不一致时
        """
        tx_d = StockData._tx_fetch(code)
        sn_d = StockData._sina_fetch(code)
        
        result = {
            'code': code,
            'tx': tx_d,
            'sina': sn_d,
            'verified': False,
            'data': None,
        }
        
        if tx_d and not tx_d.get('error') and sn_d and not sn_d.get('error'):
            # 双源都有
            diff_pct = abs(tx_d['chg_pct'] - sn_d['chg_pct'])
            diff_price = abs(tx_d['now'] - sn_d['now'])
            
            if diff_pct < 0.01 and diff_price < 0.05:
                result['verified'] = True
                result['data'] = tx_d
            elif strict:
                raise DataError(
                    f"双源不一致 [{code}]: "
                    f"tx {tx_d['now']}/{tx_d['chg_pct']:+.2f}% vs "
                    f"sina {sn_d['now']}/{sn_d['chg_pct']:+.2f}% "
                    f"差 {diff_price:.2f}元 / {diff_pct:.2f}%"
                )
            else:
                # 宽松模式: 取 tx
                result['data'] = tx_d
                result['warning'] = f"双源不一致 差 {diff_price:.2f}元 / {diff_pct:.2f}%"
        elif tx_d and not tx_d.get('error'):
            result['data'] = tx_d
            result['warning'] = '仅 tx 单源'
        elif sn_d and not sn_d.get('error'):
            result['data'] = sn_d
            result['warning'] = '仅 sina 单源'
        else:
                    tx_err = (tx_d or {}).get('error', '无响应') if tx_d else '无响应'
                    sn_err = (sn_d or {}).get('error', '无响应') if sn_d else '无响应'
                    raise DataError(f"所有源都失败: tx={tx_err}, sina={sn_err}")
        
        return result

    @staticmethod
    def fetch_batch_verified(codes: List[str], strict: bool = False) -> List[Dict]:
        """批量双源验证拉多只股票"""
        results = []
        for code in codes:
            try:
                r = StockData.fetch_verified(code, strict=strict)
                results.append(r)
            except DataError as e:
                results.append({'code': code, 'error': str(e)})
        return results

    @staticmethod
    def fetch_indices_verified() -> Dict[str, Dict]:
        """拉所有主要指数并双源验证"""
        indices = [
            ('000001', '上证指数'),
            ('000300', '沪深300'),
            ('000016', '上证50'),
            ('000688', '科创50'),
            ('000852', '中证1000'),
            ('000905', '中证500'),
            ('399001', '深证成指'),
            ('399006', '创业板指'),
        ]
        result = {}
        for code, name in indices:
            try:
                d = StockData.fetch_verified(code, strict=False)
                result[name] = {
                    'code': code,
                    'data': d['data'],
                    'verified': d['verified'],
                    'warning': d.get('warning'),
                }
            except DataError as e:
                result[name] = {'code': code, 'error': str(e)}
        return result

    @staticmethod
    def get_all_a_share_codes():
        """全 A 股代码列表 (akshare 5574 只, 缓存 4h)"""
        import time as _t
        from pathlib import Path as _P
        cache = _P.home() / ".hermes" / "cache" / "a_share_codes.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists() and _t.time() - cache.stat().st_mtime < 14400:
            try:
                with open(cache, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if len(cached) >= 5000:
                    return cached
            except: pass
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            codes = df["code"].astype(str).str.zfill(6).tolist()
            if len(codes) >= 5000:
                try:
                    with open(cache, "w", encoding="utf-8") as f:
                        json.dump(codes, f)
                except: pass
            return codes
        except Exception as e:
            if cache.exists():
                try:
                    with open(cache, "r", encoding="utf-8") as f:
                        return json.load(f)
                except: pass
            return []

    @staticmethod
    def scan_increase_range(low=3.0, high=5.0, limit=30):
        """全市场涨 [low, high] 区间扫描 (akshare)"""
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot()
            df["涨跌幅"] = df["涨跌幅"].astype(float)
            cands = df[(df["涨跌幅"] >= low) & (df["涨跌幅"] <= high)].copy()
            cands = cands.sort_values("涨跌幅", ascending=False).head(limit)
            results = []
            for _, r in cands.iterrows():
                code = str(r["代码"]).replace("sz", "").replace("sh", "").replace("bj", "").zfill(6)
                results.append({
                    "code": code,
                    "name": r["名称"],
                    "now": r["最新价"],
                    "chg_pct": r["涨跌幅"],
                    "amount_yi": (r.get("成交额", 0) or 0) / 1e8,
                    "liangbi": 0,
                    "total_mv_yi": 0,
                })
            return results
        except: return []

    @staticmethod
    def get_market_summary():
        """大盘全市场快照 (akshare)"""
        result = {}
        try:
            import akshare as ak
            from datetime import datetime as _dt
            index_map = [
                ("sh000001", "sh"),
                ("sz399001", "sz"),
                ("sz399006", "cyb"),
                ("sh000688", "kc50"),
            ]
            for code, name in index_map:
                try:
                    df_idx = ak.stock_zh_index_daily(symbol=code)
                    if df_idx is not None and len(df_idx) > 0:
                        row = df_idx.iloc[-1]
                        result[name] = {
                            "now": float(row.get("close", 0)),
                            "chg_pct": float(row.get("change_pct", 0)) if row.get("change_pct") is not None else 0,
                        }
                except: pass
            today = _dt.now().strftime("%Y%m%d")
            try: result["limit_ups"] = len(ak.stock_zt_pool_em(date=today))
            except: result["limit_ups"] = 0
            try: result["limit_downs"] = len(ak.stock_zt_pool_dtgc_em(date=today))
            except: result["limit_downs"] = 0
            try: result["limit_breaks"] = len(ak.stock_zt_pool_zbgc_em(date=today))
            except: result["limit_breaks"] = 0
        except: pass
        return result

    @staticmethod
    def get_zt_pool(date: str = None) -> list:
        """涨停池 (akshare)"""
        try:
            import akshare as ak
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_em(date=date)
            results = []
            if df is not None:
                for _, r in df.iterrows():
                    results.append({
                        'code': str(r.get('代码', '')).zfill(6),
                        'name': r.get('名称', ''),
                        'now': r.get('最新价', 0),
                    })
            return results
        except: return []

    @staticmethod
    def get_dt_pool(date: str = None) -> list:
        """跌停池 (akshare)"""
        try:
            import akshare as ak
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_dtgc_em(date=date)
            results = []
            if df is not None:
                for _, r in df.iterrows():
                    results.append({
                        'code': str(r.get('代码', '')).zfill(6),
                        'name': r.get('名称', ''),
                    })
            return results
        except: return []

    @staticmethod
    def get_zb_pool(date: str = None) -> list:
        """炸板池 (akshare)"""
        try:
            import akshare as ak
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_zbgc_em(date=date)
            results = []
            if df is not None:
                for _, r in df.iterrows():
                    results.append({
                        'code': str(r.get('代码', '')).zfill(6),
                        'name': r.get('名称', ''),
                    })
            return results
        except: return []

    @staticmethod
    def get_hk_quote(code: str) -> dict:
        """港股实时行情 (腾讯 hkxxxxx, 0.07-0.11s)"""
        try:
            code = str(code).zfill(5)
            url = f"http://qt.gtimg.cn/q=hk{code}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read().decode('gbk')
            parts = raw.split('=')[1].strip(';').strip('"').split('~')
            if len(parts) < 33:
                raise DataError(f"港股返回字段不足: {len(parts)}")
            return {
                'source': 'tx_hk', 'code': code, 'name': parts[1],
                'now': float(parts[3]) if parts[3] else 0,
                'prev_close': float(parts[4]) if parts[4] else 0,
                'open': float(parts[5]) if parts[5] else 0,
                'high': float(parts[33]) if parts[33] else 0,
                'low': float(parts[34]) if parts[34] else 0,
                'chg_pct': float(parts[32]) if parts[32] else 0,
                'volume': int(float(parts[6])) if parts[6] else 0,
            }
        except Exception as e:
            raise DataError(f"港股失败: {e}")

    @staticmethod
    def get_hk_kline(code: str, days: int = 30) -> list:
        """港股 K 线 (腾讯 hkxxxxx)"""
        try:
            code = str(code).zfill(5)
            url = f"http://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=hk{code},day,,,{days},,"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            kdata = data.get('data', {}).get(f'hk{code}', {}).get('day', [])
            results = []
            for row in kdata:
                if len(row) >= 6:
                    results.append({
                        'date': row[0],
                        'open': float(row[1]) if row[1] else 0,
                        'close': float(row[2]) if row[2] else 0,
                        'high': float(row[3]) if row[3] else 0,
                        'low': float(row[4]) if row[4] else 0,
                        'volume': float(row[5]) if row[5] else 0,
                    })
            return results
        except Exception as e:
            raise DataError(f"港股 K 线失败: {e}")

    @staticmethod
    def get_hk_spot_akshare() -> list:
        """港股全市场 (akshare stock_hk_spot, 2812 只, 7s)"""
        try:
            import akshare as ak
            df = ak.stock_hk_spot()
            results = []
            for _, r in df.iterrows():
                results.append({
                    'code': str(r.get('代码', '')),
                    'name': r.get('名称', ''),
                    'now': r.get('最新价', 0),
                    'chg_pct': r.get('涨跌幅', 0),
                })
            return results
        except: return []

    @staticmethod
    def get_us_quote(code: str) -> dict:
        """美股实时行情 (腾讯 usxxxxx, 0.05-0.08s)"""
        try:
            url = f"http://qt.gtimg.cn/q=us{code.upper()}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read().decode('gbk')
            parts = raw.split('=')[1].strip(';').strip('"').split('~')
            if len(parts) < 33:
                raise DataError(f"美股返回字段不足: {len(parts)}")
            return {
                'source': 'tx_us', 'code': code.upper(), 'name': parts[1],
                'now': float(parts[3]) if parts[3] else 0,
                'prev_close': float(parts[4]) if parts[4] else 0,
                'open': float(parts[5]) if parts[5] else 0,
                'high': float(parts[33]) if parts[33] else 0,
                'low': float(parts[34]) if parts[34] else 0,
                'chg_pct': float(parts[32]) if parts[32] else 0,
                'volume': int(float(parts[6])) if parts[6] else 0,
            }
        except Exception as e:
            raise DataError(f"美股失败: {e}")

    @staticmethod
    def get_us_kline(code: str, days: int = 30) -> list:
        """美股 K 线 (腾讯 usxxxxx)"""
        try:
            url = f"http://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=us{code.upper()},day,,,{days},,"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            kdata = data.get('data', {}).get(f'us{code.upper()}', {}).get('day', [])
            results = []
            for row in kdata:
                if len(row) >= 6:
                    results.append({
                        'date': row[0],
                        'open': float(row[1]) if row[1] else 0,
                        'close': float(row[2]) if row[2] else 0,
                        'high': float(row[3]) if row[3] else 0,
                        'low': float(row[4]) if row[4] else 0,
                        'volume': float(row[5]) if row[5] else 0,
                    })
            return results
        except Exception as e:
            raise DataError(f"美股 K 线失败: {e}")

    @staticmethod
    def get_a_kline_baostock(code: str, days: int = 60) -> list:
        """A 股 K 线 (baostock, 26+ 条/月)"""
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != '0':
                raise DataError(f"baostock 登录失败: {lg.error_msg}")
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days+10)).strftime('%Y-%m-%d')
            if code.startswith(('6', '5', '9')):
                market = 'sh'
            elif code.startswith(('8', '92', '43')):
                market = 'bj'
            else:
                market = 'sz'
            rs = bs.query_history_k_data_plus(
                f'{market}.{code}',
                'date,open,high,low,close,volume,amount',
                start_date=start_date, end_date=end_date,
                frequency='d', adjustflag='2'
            )
            results = []
            while rs.next():
                row = rs.get_row_data()
                results.append({
                    'date': row[0],
                    'open': float(row[1]) if row[1] else 0,
                    'high': float(row[2]) if row[2] else 0,
                    'low': float(row[3]) if row[3] else 0,
                    'close': float(row[4]) if row[4] else 0,
                    'volume': float(row[5]) if row[5] else 0,
                    'amount': float(row[6]) if row[6] else 0,
                })
            bs.logout()
            return results
        except Exception as e:
            raise DataError(f"baostock K 线失败: {e}")

    @staticmethod
    def get_financial_abstract(code: str) -> dict:
        """财务摘要 (akshare stock_financial_abstract, 80+ 行)"""
        try:
            import akshare as ak
            df = ak.stock_financial_abstract(symbol=code)
            result = {'raw_rows': 0, 'indicators': {}}
            if df is not None and len(df) > 0:
                result['raw_rows'] = len(df)
                for _, r in df.iterrows():
                    name = r.get('指标', '')
                    if not name:
                        continue
                    result['indicators'][name] = {}
                    for col in df.columns:
                        if col not in ['选项', '指标']:
                            result['indicators'][name][str(col)] = r[col]
            return result
        except Exception as e:
            raise DataError(f"财报失败: {e}")

    @staticmethod
    def get_fund_flow_10jqka(code: str) -> dict:
        """同花顺个股资金流 (HTML)"""
        try:
            url = f'http://data.10jqka.com.cn/funds/ggzjl/field/zdf/order/desc/ajax/1/code/{code}/'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode('gbk', errors='ignore')
            dates = re.findall(r'(\d{4}-\d{2}-\d{2})', html)
            return {
                'source': '10jqka', 'code': code,
                'has_data': '个' in html,
                'records': len(set(dates)),
            }
        except Exception as e:
            return {'source': '10jqka', 'error': str(e)[:60]}





class TradingRules:
    """
    A 股交易规则硬性约束模块
    v13 修订版 - 沪深主板/中小板/创业板买入必须100整数倍
    """
    
    @staticmethod
    def validate_buy_shares(code: str, shares: int) -> tuple[bool, str]:
        """
        验证买入股数是否合法
        
        Returns:
            (is_valid, message)
        """
        # 科创板: 200 股起, 1 股整数倍
        if code.startswith('688') or code.startswith('589'):
            if shares < 200:
                return False, f"科创板 ({code}) 买入最小 200 股, 当前 {shares} 股"
            return True, f"科创板 {shares} 股合法 (200+1股整数倍)"
        
        # 北交所 (8/920 开头)
        if code.startswith('8') or code.startswith('920'):
            if shares < 100:
                return False, f"北交所 ({code}) 买入最小 100 股, 当前 {shares} 股"
            if shares % 100 != 0:
                return False, f"北交所 ({code}) 买入必须 100 整数倍, 当前 {shares} 股"
            return True, f"北交所 {shares} 股合法"
        
        # 沪深主板/中小板/创业板: 100 股起, 100 整数倍
        if shares < 100:
            return False, f"沪深 ({code}) 买入最小 100 股, 当前 {shares} 股"
        if shares % 100 != 0:
            return False, f"沪深 ({code}) 买入必须 100 整数倍, 当前 {shares} 股 (差 {100 - shares % 100} 股)"
        return True, f"沪深 {shares} 股合法 (100 整数倍)"
    
    @staticmethod
    def validate_sell_shares(code: str, total_holdings: int, sell_qty: int) -> tuple[bool, str]:
        """
        验证卖出股数是否合法
        A 股: < 100 股部分必须一次性卖出
        """
        if sell_qty <= 0:
            return False, f"卖出数量必须 > 0"
        if sell_qty > total_holdings:
            return False, f"卖出 {sell_qty} > 持仓 {total_holdings}"
        
        # 剩余股数
        remaining = total_holdings - sell_qty
        
        # 如果剩余 < 100 股, 必须一次性全部卖出
        if remaining > 0 and remaining < 100:
            return False, f"卖出 {sell_qty} 后剩余 {remaining} 股 (< 100), 必须一次性清仓"
        
        return True, f"卖出 {sell_qty} 股合法"
    
    @staticmethod
    def get_min_lot(code: str) -> int:
        """获取最小买入单位"""
        if code.startswith('688') or code.startswith('589'):
            return 200
        return 100
    
    @staticmethod
    def format_action(action: str, code: str, qty: int) -> str:
        """标准化操作建议 (A 股规则校验)"""
        if '买' in action or '加' in action:
            valid, msg = TradingRules.validate_buy_shares(code, qty)
            if not valid:
                # 自动调整为合法数值
                if qty < 100:
                    suggested = 100
                elif code.startswith('688') and qty < 200:
                    suggested = 200
                else:
                    # 调整为 100 整数倍
                    suggested = (qty // 10 + 1) * 100
                return f"{action} ❌ 调整为 {suggested} 股 ({msg})"
            return f"{action} {qty} 股 ✅"


if __name__ == '__main__':
    # 自检
    print("=" * 70)
    print("【TradingRules 自检】")
    print("=" * 70)
    
    test_cases = [
        ('002422', 100, '科伦药业'),  # 沪深 - 100 整数倍 ✅
        ('002422', 50, '科伦药业'),    # 沪深 - 不整倍 ❌
        ('002422', 30, '科伦药业'),    # 沪深 - < 100 ❌
        ('688825', 200, '长鑫科技'),   # 科创板 - 200 起 ✅
        ('688825', 100, '长鑫科技'),   # 科创板 - < 200 ❌
        ('920201', 100, '百瑞吉'),     # 北交所 - 100 ✅
    ]
    
    for code, qty, name in test_cases:
        valid, msg = TradingRules.validate_buy_shares(code, qty)
        flag = '✅' if valid else '❌'
        print(f"  {flag} {code} {name} 买 {qty} 股: {msg}")
    
    print()
    print("【卖出规则测试】")
    sell_cases = [
        ('002020', 100, 50, '京新'),   # 卖 50 剩 50 (< 100) ❌
        ('002020', 100, 100, '京新'),  # 卖 100 剩 0 ✅
        ('002020', 100, 99, '京新'),   # 卖 99 剩 1 (< 100) ❌
    ]
    for code, total, sell, desc in sell_cases:
        valid, msg = TradingRules.validate_sell_shares(code, total, sell)
        flag = '✅' if valid else '❌'
        print(f"  {flag} {desc}: {msg}")

    # ====== 12 项综合自检 (v2.0) ======
    print()
    print('='*70)
    print('StockData v2.0 综合自检')
    print('='*70)
    import time
    print('\n[1] A 股单只 002422 双源验证')
    t0 = time.time()
    d = StockData.fetch_verified('002422', strict=False)
    print(f'  {d["data"]["name"]} 现 {d["data"]["now"]} 涨 {d["data"]["chg_pct"]:+.2f}% verified={d["verified"]} ({time.time()-t0:.2f}s)')

    print('\n[2] 全 A 股代码 (akshare)')
    t0 = time.time()
    codes = StockData.get_all_a_share_codes()
    print(f'  {len(codes)} 只 ({time.time()-t0:.1f}s)')

    print('\n[3] 涨 3-5% 候选')
    t0 = time.time()
    cands = StockData.scan_increase_range(3.0, 5.0, limit=5)
    print(f'  {len(cands)} 只 ({time.time()-t0:.1f}s)')

    print('\n[4] 大盘快照')
    t0 = time.time()
    mkt = StockData.get_market_summary()
    for k in ['sh', 'sz', 'cyb', 'kc50']:
        if k in mkt:
            v = mkt[k]
            print(f'  {k}: {v["now"]:.2f}')
    print(f'  涨停 {mkt.get("limit_ups", 0)} 跌停 {mkt.get("limit_downs", 0)} ({time.time()-t0:.1f}s)')

    print('\n[5] 港股 00700')
    t0 = time.time()
    hk = StockData.get_hk_quote('00700')
    print(f'  {hk["name"]} 现 {hk["now"]} 涨 {hk["chg_pct"]:+.2f}% ({time.time()-t0:.2f}s)')

    print('\n[6] 美股 AAPL')
    t0 = time.time()
    us = StockData.get_us_quote('AAPL')
    print(f'  {us["name"]} 现 {us["now"]} 涨 {us["chg_pct"]:+.2f}% ({time.time()-t0:.2f}s)')

    print('\n[7] A 股 K 线 (baostock 60 天)')
    t0 = time.time()
    k = StockData.get_a_kline_baostock('601139', days=60)
    print(f'  {len(k)} 条 ({time.time()-t0:.2f}s)')
    if k:
        print(f'  最新: {k[-1]["date"]} 收 {k[-1]["close"]}')

    print('\n[8] 港股 K 线 (腾讯 30 天)')
    t0 = time.time()
    hkk = StockData.get_hk_kline('00700', days=30)
    print(f'  {len(hkk)} 条 ({time.time()-t0:.2f}s)')

    print('\n[9] 财报 601139 (akshare)')
    t0 = time.time()
    f = StockData.get_financial_abstract('601139')
    print(f'  {f["raw_rows"]} 行 {len(f["indicators"])} 指标 ({time.time()-t0:.1f}s)')

    print('\n[10] 涨停池 (今日)')
    t0 = time.time()
    zt = StockData.get_zt_pool()
    print(f'  {len(zt)} 只 ({time.time()-t0:.2f}s)')

    print('\n[11] 跌停池 (今日)')
    t0 = time.time()
    dt = StockData.get_dt_pool()
    print(f'  {len(dt)} 只 ({time.time()-t0:.2f}s)')

    print('\n[12] 资金流 601139 (同花顺 HTML)')
    t0 = time.time()
    flow = StockData.get_fund_flow_10jqka('601139')
    print(f'  records: {flow.get("records", "?")} ({time.time()-t0:.2f}s)')

    print('\n' + '='*70)
    print('✅ 12 项综合自检完成')
    print('='*70)
