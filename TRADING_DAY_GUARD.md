# 交易日守卫 (2026-10-31)

用户要求：**周六周日休市，相关任务暂停，到开市再正常启动**。

## 两层拦截

### 第 1 层：cron 表达式（挡周末）

| Job | 调度 | 说明 |
|---|---|---|
| macro-chain-daily | `0 8 * * 1-5` | 周一~周五 08:00（原先 `0 8 * * *` 每日）|
| next-day-5pct-predict | `40 15 * * 1-5` | 周一~周五 15:40 |
| post-market-review | `30 15 * * 1-5` | 周一~周五 15:30 |
| stock-scheduler-update | `35 9 * * 1-5` | 周一~周五 09:35 |
| stock-position-update | `50 19 * * 1-5` | 周一~周五 19:50 |
| stock-cron-healthcheck | `5 20 * * 1-5` | 周一~周五 20:05 |
| overnight-news | `0 2 * * 1-5` | 周一~周五 02:00 |
| harmonic-warmup-list | `9 * * 1-5` | 周一~周五 09:09 |
| stock-longterm-weekly | `0 10 * * 1` | 周一 10:00 |
| **stock-weekly-outlook** | `15 20 * * 5` | **周五 20:15**（原先 `0 20 * * 0` 周日 20:00）|

不停：ensure-deps-retry（环境自愈）、push-retry-noagent（投递兜底）——与开市无关。

### 第 2 层：交易日守卫（挡法定节假日）

`1-5` 挡不住春节/国庆。所有市场类 wrapper 开头调用：

```bash
_TD=$(bash "C:/Users/yanyan.zou/AppData/Local/hermes/scripts/is_trading_day.sh" 2>/dev/null || echo CLOSED)
if [ "$_TD" != "TRADING" ]; then
  echo "非交易日 ($(date '+%Y-%m-%d %A')), 本次任务跳过"
  exit 0
fi
```

已注入 9 个 wrapper：macro / predict / post-market-review / position / scheduler / harmonic / overnight / weekly(用 --week 变体) / healthcheck。

`is_trading_day.py` 取数：主源 akshare `tool_trade_date_hist_sina()`，兜底腾讯上证日K最后一根日期 == 今天；取数失败 fail-open（按开市处理，不误杀正常交易日）。

**周报用 `--week` 变体**：周五遇法定节假日时，本周最后交易日是周四，周报仍应生成 → 判据是「本周内有交易日」而非「今天有交易日」。

## 生效时间
2026-11-02（周一）恢复正常执行。
