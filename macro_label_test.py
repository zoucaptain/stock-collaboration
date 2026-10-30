#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""macro_label_test.py — 链条标签分支全覆盖测试 (2026-10-30)

背景: 10/30 报告把 3/3 全跌的三大指数标成"涨跌互现"。本测试用合成数据
穷举所有分支, 并验证 validate_chain_labels() 能抓到不一致的标签。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macro_chain as mc


def mk(d1=0.0, d5=0.0, d20=0.0, last=100.0, d1_pts=0.0, d5_pts=0.0):
    return {'last': last, 'd1': d1, 'd5': d5, 'd20': d20,
            'd1_pts': d1_pts, 'd5_pts': d5_pts}


def base_m(**kw):
    m = {'dxy': mk(), 'tnx': mk(last=4.0), 'spx': mk(), 'ixic': mk(), 'dji': mk(),
         'vix': mk(last=17.0), 'wti': mk(last=100.0), 'brent': mk(last=100.0),
         'gold': mk(last=4000.0), 'cnh': mk(last=6.65), 'hsi': mk(), 'nikkei': mk()}
    for k, v in kw.items():
        m[k] = v
    return m


CASES = [
    # (名称, m, 期望标签, 期望分数)
    ('美股 三腿全跌 均值-1.5%',
     base_m(spx=mk(d1=-2.0), ixic=mk(d1=-2.0), dji=mk(d1=-1.0)), '全线走弱', -2),
    ('美股 三腿全跌 均值-0.64% (10/30 实际)',
     base_m(spx=mk(d1=-0.30), ixic=mk(d1=-1.38), dji=mk(d1=-0.25)), '全线小跌', -1),
    ('美股 三腿全涨 均值+1.5%',
     base_m(spx=mk(d1=2.0), ixic=mk(d1=2.0), dji=mk(d1=1.0)), '全线走强', 2),
    ('美股 三腿全涨 均值+0.25% (10/29 实际)',
     base_m(spx=mk(d1=0.28), ixic=mk(d1=0.27), dji=mk(d1=0.19)), '全线小涨', 1),
    ('美股 有涨有跌',
     base_m(spx=mk(d1=1.0), ixic=mk(d1=-0.5), dji=mk(d1=0.2)), '涨跌互现', 0),
    ('美股 两跌一涨',
     base_m(spx=mk(d1=-0.3), ixic=mk(d1=-0.4), dji=mk(d1=0.9)), '涨跌互现', 0),
    ('原油 均值+2%',
     base_m(wti=mk(d1=2.0), brent=mk(d1=2.0)), '油价上涨', -1),
    ('原油 均值-1.7% (10/30 实际, WTI/布伦特背离)',
     base_m(wti=mk(d1=-0.04), brent=mk(d1=-3.39)), '油价下跌', 1),
    ('原油 均值0%',
     base_m(wti=mk(d1=0.5), brent=mk(d1=-0.5)), '油价平稳', 0),
    ('亚太 均值+1.5%',
     base_m(hsi=mk(d1=2.0), nikkei=mk(d1=1.0)), '亚太走强', 1),
    ('亚太 均值-2%',
     base_m(hsi=mk(d1=-2.0), nikkei=mk(d1=-2.0)), '亚太走弱', -1),
    ('亚太 中性',
     base_m(hsi=mk(d1=0.2), nikkei=mk(d1=1.0)), '中性', 0),
]


def main():
    fails = []
    for name, m, exp_v, exp_s in CASES:
        ch = mc.chains(m)
        d = {n: (v, s) for n, v, s, _w in ch}
        chain_name = None
        for cn in ('美股', '原油', '亚太'):
            if exp_v in ('全线走弱', '全线走强', '全线小跌', '全线小涨', '涨跌互现') and cn == '美股':
                chain_name = cn
            elif exp_v in ('油价上涨', '油价下跌', '油价平稳') and cn == '原油':
                chain_name = cn
            elif exp_v in ('亚太走强', '亚太走弱', '中性') and cn == '亚太':
                chain_name = cn
        got_v, got_s = d[chain_name]
        ok = (got_v == exp_v and got_s == exp_s)
        print(f"  {'✅' if ok else '❌'} {name:<42} 期望 {exp_v}/{exp_s:+d}  实得 {got_v}/{got_s:+d}")
        if not ok:
            fails.append(name)

    # 验证器必须能抓到错误标签
    print()
    bad = base_m(spx=mk(d1=-0.30), ixic=mk(d1=-1.38), dji=mk(d1=-0.25))
    ch = list(mc.chains(bad))
    for i, (n, v, s, w) in enumerate(ch):
        if n == '美股':
            ch[i] = ('美股', '涨跌互现', 0, w)   # 人为注入 10/30 事故
    try:
        mc.validate_chain_labels(bad, ch)
        print('  ❌ 验证器没能抓到 "3/3全跌标涨跌互现"')
        fails.append('validator')
    except AssertionError as e:
        print(f'  ✅ 验证器抓到注入的错误标签: {str(e).splitlines()[-1].strip()}')

    print()
    if fails:
        print(f'❌ {len(fails)} 项失败: {fails}')
        return 1
    print(f'✅ 全部 {len(CASES)} 个分支 + 验证器测试通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
