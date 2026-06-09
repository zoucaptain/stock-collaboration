# data_provider_dsa

**来源**: [ZhuLinsen/daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) v2026
**复制日期**: 2026-06-09
**许可证**: MIT
**用途**: 给 Hermes stock-collaboration 增补多数据源 fallback 链，**不装 alphasight / 调度层 / LLM**，只借 fetcher 策略模式代码

## 5 分钟实测（公司受限 Windows）

| 数据源 | 历史 K 线 | 实时行情 | 备注 |
|--------|----------|---------|------|
| Sina hq | n/a | ✅ 稳 | 已知唯一稳的实时 |
| Sina quotes 1min | ✅ 稳 | n/a | 分时 |
| Sina 7x24 | n/a | ✅ 稳 | 实时快讯 |
| **baostock** | ✅ 稳（**离线不联网**）| ❌ | 永久兜底，无网也跑 |
| **efinance** | ✅ 稳（专用端点非 push2）| ❌ 走 push2 挂 | 历史数据可用 |
| akshare datacenter | 🟡 间歇挂 | n/a | 资金流/板块 |
| akshare push2 | ❌ 限速 | ❌ 限速 | 公司机全废 |
| tushare | ✅ 需 token | ✅ 需 token | 免费层有限 |
| yfinance | ✅ | ✅ | 美股专用 |

## 解决 6 步选股的硬过滤盲区

之前 6 项硬过滤（PE/市值/股本/上市日/资金流/量比）在公司机全废。
**efinance 历史 K 线 + baostock 财务接口**能补：
- baostock: 上市日、股本、财务、PE/市值
- efinance: 成交额、换手率、振幅（多周期）
- tushare（有 token 时）: 全套基本面

## 集成方式（建议）

1. 保留现有 `em_collector.py` + Sina 链路不动
2. **新增 fallback 层**：当 Sina/akshare datacenter 失败时，按优先级 efinance → baostock → tushare
3. **重点替换** stock-position-collector.py 的 Sina 单一拉取为多源 fallback

## 不要做的事

- ❌ 不要装 alphasift 选股引擎（公司机可能挡 Git pip install）
- ❌ 不要装 LLM 决策仪表盘层（Hermes/OpenClaw 已有）
- ❌ 不要复制 Dockerfile / docker-compose.yml（不需要容器化）
- ❌ 不要装 schedule / exchange-calendars（用现成 Hermes cron）

## 测试命令

```bash
# baostock 验证
python -c "import baostock as bs; lg=bs.login(); print(lg.error_msg); bs.logout()"

# efinance 历史
python -c "import efinance as ef; print(ef.stock.get_quote_history('002491', beg='20260601', end='20260608', klt=101).tail())"
```

## 上游版本同步

- upstream: https://github.com/ZhuLinsen/daily_stock_analysis
- 同步方式: `cd /tmp && git -C daily_stock_analysis pull && cp -r daily_stock_analysis/data_provider stock-collaboration/data_provider_dsa_new && diff -rq ...`
- 不要自动覆盖，每次 sync 先看 diff
