#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
5 条件共振选股法 - A股主板
基于 1-7 月统计局数据 + 技术指标共振

Usage:
    python stock_picker_5condition.py
    python stock_picker_5condition.py --pool all    # 全市场
    python stock_picker_5condition.py --pool main  # 仅主板（默认）

Author: Hermes
Date: 2026-08-19
"""

import urllib.request
import json
import re
import time
import sys


def get_tx_kl(symbol):
    """腾讯日K接口（前复权）"""
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,60,qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    try:
        data = urllib.request.urlopen(req, timeout=8).read().decode("utf-8")
        j = json.loads(data)
        if "qfqday" in j["data"][symbol]:
            return j["data"][symbol]["qfqday"]
        elif "day" in j["data"][symbol]:
            return j["data"][symbol]["day"]
    except:
        return []
    return []


def get_tx_qt(symbol):
    """腾讯实时行情"""
    url = f"https://qt.gtimg.cn/q={symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        data = urllib.request.urlopen(req, timeout=8).read().decode("gbk", errors="ignore")
        m = re.match(r'v_(\w+)="([^"]+)"', data.strip())
        if m:
            parts = m.group(2).split("~")
            if len(parts) > 6:
                return {
                    "cur": float(parts[3]),
                    "prev_close": float(parts[4]),
                    "volume": float(parts[6]),
                    "name": parts[1],
                }
    except:
        pass
    return None


def calc_macd(closes, fast=12, slow=26, signal=9):
    """MACD 计算（DIF/DEA）"""
    ema_fast = [closes[0]]
    ema_slow = [closes[0]]
    k_f = 2 / (fast + 1)
    k_s = 2 / (slow + 1)
    for c in closes[1:]:
        ema_fast.append(ema_fast[-1] * (1 - k_f) + c * k_f)
        ema_slow.append(ema_slow[-1] * (1 - k_s) + c * k_s)
    dif = [a - b for a, b in zip(ema_fast, ema_slow)]
    dea = [dif[0]]
    k_d = 2 / (signal + 1)
    for d in dif[1:]:
        dea.append(dea[-1] * (1 - k_d) + d * k_d)
    return dif, dea


def calc_kdj(highs, lows, closes, n=9, m1=3, m2=3):
    """KDJ 计算（K/D/J）"""
    k_values = [50]
    d_values = [50]
    for i in range(1, len(closes)):
        prev_k = k_values[-1] if i > 1 else 50
        prev_d = d_values[-1] if i > 1 else 50
        high_n = max(highs[max(0, i - n + 1): i + 1])
        low_n = min(lows[max(0, i - n + 1): i + 1])
        rsv = 50 if high_n == low_n else (closes[i] - low_n) / (high_n - low_n) * 100
        k = (m1 - 1) / m1 * prev_k + 1 / m1 * rsv
        d = (m2 - 1) / m2 * prev_d + 1 / m2 * k
        k_values.append(k)
        d_values.append(d)
    j_values = [3 * k - 2 * d for k, d in zip(k_values, d_values)]
    return k_values, d_values, j_values


def check_5conditions(symbol, info):
    """
    5 条件共振检查
    返回: (是否通过, 信号详情 dict)
    """
    kdata = get_tx_kl(symbol)
    if not kdata or len(kdata) < 25:
        return False, {}

    i = len(kdata) - 1
    closes = [float(d[2]) for d in kdata]
    highs = [float(d[3]) for d in kdata]
    lows = [float(d[4]) for d in kdata]
    vols = [float(d[5]) for d in kdata]

    dif, dea = calc_macd(closes)
    k_vals, d_vals, j_vals = calc_kdj(highs, lows, closes)

    # ===== 5 条件共振 =====
    macd_gold = dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]  # MACD 严格首次金叉
    kdj_gold = k_vals[i] > d_vals[i] and k_vals[i - 1] <= d_vals[i - 1]  # KDJ 严格首次金叉
    j_val = j_vals[i]
    j_ok = j_val < 80  # J 不超买

    avg5_vol = sum(vols[max(0, i - 4): i + 1]) / min(5, i + 1)
    vol_ratio = vols[i] / avg5_vol
    vol_ok = vol_ratio < 1.5  # 量不超 1.5 倍

    m20 = sum(closes[i - 19: i + 1]) / 20
    ma20_ok = closes[i] > m20  # 站上 MA20

    signal = {
        "code": symbol,
        "name": info.get("name", symbol),
        "date": kdata[i][0],
        "price": closes[i],
        "pct": (closes[i] - closes[i - 1]) / closes[i - 1] * 100,
        "macd_dif": dif[i],
        "macd_dea": dea[i],
        "k": k_vals[i],
        "d": d_vals[i],
        "j": j_val,
        "vol_ratio": vol_ratio,
        "ma20": m20,
        "ma20_diff_pct": (closes[i] - m20) / m20 * 100,
        "macd_gold": macd_gold,
        "kdj_gold": kdj_gold,
        "j_ok": j_ok,
        "vol_ok": vol_ok,
        "ma20_ok": ma20_ok,
        "score": sum([macd_gold, kdj_gold, j_ok, vol_ok, ma20_ok]),
    }

    passed = all([macd_gold, kdj_gold, j_ok, vol_ok, ma20_ok])
    return passed, signal


def get_main_board_codes():
    """沪深主板代码库"""
    sh_codes = [f"sh{pre}{n:03d}" for pre in ["600", "601", "603", "605"] for n in range(0, 1000)]
    sz_codes = [f"sz{pre}{n:03d}" for pre in ["000", "001", "002"] for n in range(0, 1000)]
    return list(set(sh_codes + sz_codes))


def filter_stocks(all_live):
    """过滤：股价<100 / 涨停排除 / 仅主板"""
    filtered = {}
    for code, info in all_live.items():
        # 仅主板
        if not (code.startswith("sh60") or (code.startswith("sz") and code[2:5] in ["000", "001", "002"])):
            continue
        # 股价 < 100
        if not (0 < info["cur"] <= 100):
            continue
        # 涨停排除
        if info["pct"] >= 9.5:
            continue
        filtered[code] = info
    return filtered


def main():
    pool = sys.argv[1] if len(sys.argv) > 1 else "main"
    print(f"5 条件共振选股 - {'主板' if pool == 'main' else '全市场'}")

    # 获取代码库
    if pool == "main":
        all_codes = get_main_board_codes()
    else:
        sh_codes = [f"sh{pre}{n:03d}" for pre in ["600", "601", "603", "605", "688"] for n in range(0, 1000)]
        sz_codes = [f"sz{pre}{n:03d}" for pre in ["000", "001", "002", "300", "301"] for n in range(0, 1000)]
        all_codes = list(set(sh_codes + sz_codes))

    print(f"代码库: {len(all_codes)} 只")

    # 拉实时数据
    print("拉取实时数据...")
    batch_size = 50
    all_live = {}
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i: i + batch_size]
        url = "https://qt.gtimg.cn/q=" + ",".join(batch)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            data = urllib.request.urlopen(req, timeout=15).read().decode("gbk", errors="ignore")
        except:
            continue
        for line in data.strip().split("\n"):
            m = re.match(r'v_(\w+)="([^"]+)"', line)
            if m:
                code = m.group(1)
                parts = m.group(2).split("~")
                if len(parts) < 4:
                    continue
                try:
                    cur = float(parts[3])
                    prev_close = float(parts[4])
                    volume = float(parts[6])
                    if prev_close <= 0:
                        continue
                    all_live[code] = {
                        "cur": cur,
                        "prev_close": prev_close,
                        "volume": volume,
                        "name": parts[1],
                        "pct": (cur - prev_close) / prev_close * 100,
                    }
                except:
                    pass

    print(f"实时数据: {len(all_live)} 只")

    # 过滤
    filtered = filter_stocks(all_live)
    print(f"过滤后（股价<100 + 涨停排除）: {len(filtered)} 只")

    # 排序取前 200
    ranked = sorted(filtered.items(), key=lambda x: x[1]["pct"], reverse=True)[:200]
    print(f"涨幅前 200 候选: {len(ranked)}")

    # 5 条件共振检查
    print("=" * 70)
    print("5 条件共振筛选:")
    print("  1) MACD 严格金叉")
    print("  2) KDJ 严格金叉")
    print("  3) J < 80")
    print("  4) 量 < 1.5x 均量")
    print("  5) 站上 MA20")
    print("=" * 70)

    results = []
    for idx, (code, info) in enumerate(ranked):
        time.sleep(0.3)
        passed, signal = check_5conditions(code, info)
        if passed:
            results.append(signal)
        if (idx + 1) % 50 == 0:
            print(f"  已检查 {idx + 1}/{len(ranked)}")

    print(f"\n✅ 5 条件共振买点: {len(results)} 个")
    print("=" * 70)
    for r in sorted(results, key=lambda x: x["pct"], reverse=True):
        flag = "🟢" if r["pct"] >= 5 else ("🟡" if r["pct"] >= 2 else "  ")
        print(
            f"  {flag} {r['code']} {r['name']} {r['date']} "
            f"价{r['price']:.2f} 涨{r['pct']:+.2f}% "
            f"J{r['j']:.1f} 量{r['vol_ratio']:.2f}x "
            f"MA20+{r['ma20_diff_pct']:.2f}%"
        )

    return results


if __name__ == "__main__":
    main()