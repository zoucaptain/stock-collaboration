#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""is_trading_day.py — A股交易日守卫 (2026-10-31)

用途: cron 的 `1-5` 只能挡周末, 挡不住法定节假日 (春节/国庆)。
      所有市场类 wrapper 在开头调用本脚本, 非交易日直接安静退出,
      实现用户要求"周六周日休市暂停, 到开市再正常启动"。

退出码:
    0 = 今天开市 (TRADING)
    1 = 今天休市 (周末 / 法定节假日)
    2 = 交易日历取数失败 -> 按开市处理 (fail-open, 不误杀正常交易日)

主源: akshare tool_trade_date_hist_sina() (交易所官方交易日历)
兜底: 腾讯上证指数日K最后一根日期 == 今天
"""
import datetime
import json
import sys
import urllib.request

CAL_CACHE = r"C:\Users\yanyan.zou\AppData\Local\hermes\cache\scratch\trade_calendar.json"


def _today():
    return datetime.date.today()


def _by_akshare():
    import akshare as ak
    df = ak.tool_trade_date_hist_sina()
    return _today() in set(df['trade_date'])


def _by_kline():
    """兜底: 上证指数最后一根日K的日期 == 今天 -> 开市"""
    u = ('https://web.ifzq.gtimg.cn/appstock/app/kline/kline'
         '?param=sh000001,day,,,5')
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0'})
    d = json.loads(urllib.request.urlopen(req, timeout=12).read())
    kl = d['data']['sh000001']['day']
    return kl[-1][0] == _today().strftime('%Y-%m-%d')


def _week_has_trading_day():
    """本周(周一~周日)内是否存在交易日 —— 给"周报"类任务用。
    周五遇法定节假日时, 本周最后交易日是周四, 周报仍应生成。"""
    import akshare as ak
    df = ak.tool_trade_date_hist_sina()
    cal = set(df['trade_date'])
    t = _today()
    monday = t - datetime.timedelta(days=t.weekday())
    return any(d in cal for d in (monday + datetime.timedelta(days=i) for i in range(7)))


def main():
    t = _today()
    if '--week' in sys.argv:
        try:
            ok = _week_has_trading_day()
        except Exception as e:
            print(f'周交易日历不可用 ({e}) -> fail-open')
            return 2
        print(f'{t} 本周交易日 -> {"TRADING" if ok else "CLOSED"}')
        return 0 if ok else 1
    # 周末直接判休, 不浪费一次网络请求
    if t.weekday() >= 5:
        print(f'{t} {t.strftime("%A")} -> CLOSED (周末)')
        return 1
    src = 'akshare交易日历'
    try:
        ok = _by_akshare()
    except Exception:
        try:
            ok = _by_kline()
            src = '腾讯上证日K'
        except Exception as e:
            print(f'交易日历不可用 ({e}) -> fail-open, 按开市处理')
            return 2
    print(f'{t} {t.strftime("%A")} -> {"TRADING" if ok else "CLOSED"} ({src})')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
