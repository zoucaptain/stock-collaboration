#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
make_digest.py — 复盘报告微信摘要 (2026-10-23)

为什么需要:
  iLink 给 bot 的主动消息配额 ≈ 用户发言数。Hermes 每次对话结束还自动发 1 条
  background_review, 复盘报告全文 12.9KB 又被切成 ~8 条微信消息 -> 配额瞬间烧光,
  15:30/15:40 定时推送直接被 iLink 拒 (ret=-2 prepare failed)。

修法: 微信只发 1 条短摘要 (<=600 字) + 1 个完整报告文档附件 = 2 条消息。
      全文仍在 GitHub (OpenClaw 可读)。

用法: python make_digest.py [报告路径]
输出: 摘要正文 (stdout), 报告绝对路径写到 stderr
"""
import os
import re
import sys

DEFAULT = r'C:\Users\yanyan.zou\stock-collaboration\post_market_review.md'


def grab(text, pattern, default='-'):
    m = re.search(pattern, text)
    return m.group(1).strip() if m else default


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.exists(path):
        print('❌ 报告不存在: ' + path)
        return
    t = open(path, encoding='utf-8').read()

    idx = {c: grab(t, r'\| ' + c + r' \| ([\d.]+) \| ([+-][\d.]+)%') for c in
           ('上证指数', '深证成指', '创业板指', '科创50')}
    vals = {}
    for c in ('上证指数', '深证成指', '创业板指', '科创50'):
        m = re.search(r'\| ' + c + r' \| ([\d.]+) \| ([+-][\d.]+)%', t)
        vals[c] = (m.group(1), m.group(2)) if m else ('-', '-')

    limit_up = grab(t, r'\*\*涨停家数\*\*: (\d+)')
    limit_dn = grab(t, r'\*\*跌停家数\*\*: (\d+)')
    bomb = grab(t, r'\*\*炸板家数\*\*: (\d+)')
    bomb_rate = grab(t, r'\*\*炸板率\*\*: ([\d.]+)%')
    ratio_m = re.search(r'涨停/跌停比 = \d+/\d+ = ([\d.]+) : 1', t)
    ratio = ratio_m.group(1) + ':1' if ratio_m else '-'
    premium = grab(t, r'\*\*平均溢价率: ([+-][\d.]+)%')
    max_board = grab(t, r'\*\*最高板\*\*: (\d+)板')
    break_gap = grab(t, r'\*\*断层\*\*: ([^\n]+)')

    # 风向标 (只从"风向标清单"小节里取)
    watch_names = []
    wm = re.search(r'### 风向标清单.*?\n\n(.*?)(?:\n>|\n---|\n## )', t, re.S)
    if wm:
        for line in wm.group(1).splitlines():
            mm = re.match(r'\|\s*([^|]+?)\s*\|\s*(\d{6})\s*\|\s*([^|]+?)\s*\|', line)
            if mm:
                watch_names.append(f"{mm.group(1).strip()}({mm.group(3).strip()})")
            if len(watch_names) >= 6:
                break

    # 成交额 TOP3  —— 表格: | 名称 | 代码 | 现价 | 涨跌% | 成交额(亿) |
    amt = re.findall(
        r'\| (?:\U0001F7E2 |\U0001F534 )?([^|]+?) \| (\d{6}) \| ([\d.]+) \| ([+-][\d.]+)% \| ([\d.]+) \|',
        t)
    top_amt = [f'{n.strip()} {p}' for n, _c, _px, p, _a in amt[:3]]

    # 涨停行业 TOP3
    ind = re.findall(r'\| \d+ \| ([^|]+?) \| (\d+) \|', t)
    top_ind = [f'{n.strip()}×{c}' for n, c in ind[:3]]

    lines = []
    lines.append('📊 A股收盘复盘 ' + grab(t, r'# 收盘复盘报告 - (\d{4}-\d{2}-\d{2})'))
    lines.append(f"指数: 上证 {vals['上证指数'][0]}({vals['上证指数'][1]}%) | "
                 f"深成 {vals['深证成指'][0]}({vals['深证成指'][1]}%) | "
                 f"创业板 {vals['创业板指'][0]}({vals['创业板指'][1]}%) | "
                 f"科创50 {vals['科创50'][0]}({vals['科创50'][1]}%)")
    lines.append(f"情绪: 涨停 {limit_up} | 跌停 {limit_dn} | 炸板 {bomb} ({bomb_rate}%) | "
                 f"涨跌停比 {ratio} | 昨涨停溢价 {premium}%")
    lines.append(f"高度: 最高 {max_board}板 | {break_gap}")
    if top_ind:
        lines.append('涨停板块: ' + ' / '.join(top_ind))
    if top_amt:
        lines.append('成交额: ' + ' / '.join(top_amt))
    if watch_names:
        lines.append('风向标: ' + ' / '.join(watch_names))
    lines.append('完整报告见附件 (全文已推 GitHub)')

    body = '\n'.join(lines)
    if len(body) > 900:
        body = body[:880] + '…'
    print(body)
    print('REPORT_PATH=' + os.path.abspath(path), file=sys.stderr)


if __name__ == '__main__':
    main()
