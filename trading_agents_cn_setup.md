# TradingAgents-CN 完整安装与使用指南

**生成时间**：2026-07-18
**目标**：在 Windows 10 / Linux / macOS 上本地部署 TradingAgents-CN + 接入国产大模型
**推荐模型**：DeepSeek V3（性价比）/ Qwen Plus（高质量）/ 豆包（最便宜）
**OpenClaw 拉取用**

---

## 一、TradingAgents-CN 是什么

基于 UCLA + MIT 开源的 TradingAgents 框架的中文增强版，专为中文用户优化：
- **多智能体协作**：基本面 / 情绪 / 新闻 / 技术 / 多空辩论 / 风控 / 组合经理
- **三市场数据**：A 股 / 港股 / 美股
- **60+ 国产模型**：DeepSeek / Qwen / GLM / 豆包 / 文心 / Kimi / 千帆
- **A 股数据源**：Tushare / AkShare / 通达信
- **代码开源免费**，只付 LLM API 费用

---

## 二、硬件 + 软件要求

### 最低配置
- **操作系统**：Windows 10+ / macOS 12+ / Ubuntu 20.04+
- **Python**：3.10+（3.11 推荐）
- **内存**：8GB+
- **磁盘**：5GB+ 可用
- **网络**：稳定（要访问大模型 API）

### 强烈推荐配置
- **内存**：16GB+（多 Agent 并发跑会吃内存）
- **CPU**：4 核+（Agent 协作有 CPU 密集）
- **GPU**：不需要（推理在云端）

---

## 三、安装步骤（Docker 一键部署，**推荐**）

### 步骤 1：装 Docker Desktop
- Windows / macOS：`https://www.docker.com/products/docker-desktop/`
- Linux：用 `apt install docker.io` 或 `yum install docker`

### 步骤 2：克隆项目
```bash
git clone https://github.com/hsliuping/TradingAgents-CN.git
cd TradingAgents-CN
```

### 步骤 3：配置环境变量
```bash
# 复制模板
cp .env.example .env

# 编辑 .env，填入你的 API key
nano .env   # 或 notepad .env（Windows）
```

`.env` 文件填这个（用 DeepSeek 举例）：
```bash
# ===== LLM 配置 =====
# 主推：DeepSeek V3
DEEPSEEK_API_KEY=sk-你的deepseek-key
DEEPSEEK_ENABLED=true
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 备选 1：通义千问（阿里百炼）
DASHSCOPE_API_KEY=sk-你的百炼-key
QWEN_ENABLED=true
QWEN_MODEL=qwen-plus
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# 备选 2：智谱 GLM
ZHIPU_API_KEY=你的智谱-key
GLM_ENABLED=true
GLM_MODEL=glm-4-plus
ZHIPU_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# ===== 数据源 =====
# A 股用 AkShare（免费）
AKSHARE_ENABLED=true
TUSHARE_TOKEN=                # 可选，没有也能跑
ALPHA_VANTAGE_API_KEY=        # 美股才需要

# ===== 交易执行 =====
# 默认不开启实盘，只跑分析
TRADING_MODE=analysis_only
```

### 步骤 4：Docker 启动
```bash
docker-compose up -d
```

### 步骤 5：访问
- Web UI：`http://localhost:3000`
- API 文档：`http://localhost:8000/docs`

---

## 四、安装步骤（Python 本地部署，备选）

### 步骤 1：克隆
```bash
git clone https://github.com/hsliuping/TradingAgents-CN.git
cd TradingAgents-CN
```

### 步骤 2：建虚拟环境
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 步骤 3：装依赖
```bash
pip install -r requirements.txt
```

### 步骤 4：配 .env（同上）

### 步骤 5：启动
```bash
# Web 界面
python web/app.py

# 或 CLI 命令行
python main.py --stock 002020 --model deepseek
```

---

## 五、获取 API Key

### 推荐：DeepSeek V3
- 注册：`https://platform.deepseek.com`
- **注册送 ¥5 免费额度**（够跑 200+ 次完整分析）
- 控制台 → API Keys → 创建新 Key
- 复制 `sk-` 开头的字符串

### 备选 1：通义千问 Qwen Plus（阿里百炼）
- 注册：`https://dashscope.aliyun.com`
- **新用户有 100 万 token 免费额度**
- 控制台 → API-Key 管理 → 创建

### 备选 2：智谱 GLM-4
- 注册：`https://open.bigmodel.cn`
- **新用户送 2000 万 token**（GLM-4-Flash 永久免费）
- 控制台 → API Keys

### 备选 3：豆包（火山引擎）
- 注册：`https://www.volcengine.com`
- 控制台 → 开通豆包大模型 → 创建 API Key

### 备选 4：MiniMax 开放平台
- 注册：`https://api.minimaxi.com`
- 控制台 → API Keys
- 验证你的 Coding Plan 订阅是否绑定 API Key 权限

---

## 六、使用方法

### 方式 1：Web 界面（最简单）
1. 打开 `http://localhost:3000`
2. 选模型（DeepSeek / Qwen / GLM）
3. 输入股票代码：
   - A 股：`002020`（京新药业）、`600702`（舍得酒业）
   - 港股：`0700.HK`
   - 美股：`AAPL`
4. 选分析深度：快速 / 标准 / 深度
5. 点"开始分析"
6. 等待 3-10 分钟（看 Agent 数量）
7. 查看报告（多空辩论 + 风控 + 建议）
8. 导出 PDF / Word / Markdown

### 方式 2：CLI 命令行
```bash
# 分析单只 A 股
python main.py --stock 002020 --model deepseek

# 深度分析
python main.py --stock 002020 --model deepseek --depth deep

# 批量分析（股票池）
python main.py --pool pool.txt --model deepseek --depth standard

# 港股
python main.py --stock 0700.HK --model qwen-plus
```

### 方式 3：Python API（接入你自己的系统）
```python
from tradingagents import TradingAgents

agent = TradingAgents(
    model="deepseek-chat",
    api_key="sk-你的key",
    base_url="https://api.deepseek.com"
)

result = agent.analyze(
    stock_code="002020",
    market="A_SHARE",
    depth="standard"  # quick / standard / deep
)

# 输出结构
print(result.summary)         # 摘要
print(result.bull_case)       # 多方观点
print(result.bear_case)       # 空方观点
print(result.risk_assessment) # 风控评估
print(result.recommendation)  # 建议（仅供参考）
```

### 方式 4：REST API（接入 OpenClaw）
```bash
# 启动 API 服务
python api/server.py  # 默认 :8000

# 调用
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "stock": "002020",
    "model": "deepseek-chat",
    "depth": "standard"
  }'
```

---

## 七、OpenClaw 集成（**你的场景**）

### 选项 A：用 OpenClaw skill 集成
1. 在 OpenClaw 安装 `tradingagents-cn` 技能（如果有发布到 ClawHub）
2. 直接在 OpenClaw 对话里说"分析京新药业"
3. OpenClaw 自动调用 TradingAgents-CN 出报告

### 选项 B：自建 OpenClaw skill 包装
1. 部署 TradingAgents-CN（Docker 或本地）
2. 在 OpenClaw 写一个 wrapper skill：
   ```python
   # ~/.openclaw/skills/trading-cn/main.py
   import requests

   def analyze_stock(code: str, model: str = "deepseek"):
       r = requests.post(
           "http://localhost:8000/api/v1/analyze",
           json={"stock": code, "model": model, "depth": "standard"}
       )
       return r.json()
   ```
3. 在 OpenClaw 系统提示里告诉它有这个 skill

### 选项 C：直接用 Hermes Agent（我）调
我已经能跑数据 + 做基本分析，**但我**：
- ❌ 不能做多空辩论
- ❌ 不能做风控博弈
- ❌ 不能用 LLM 推理
- ✅ 我能做：拉数据 + 长期趋势 + 逻辑框架

**所以**：**我和 TradingAgents 是互补**，不是替代。

---

## 八、成本估算（个人用户）

| 用法 | 频率 | 推荐模型 | 月成本 |
|---|---|---|---|
| **试玩** | 5-10 次/月 | DeepSeek V3 | ¥0.5 - ¥2 |
| **个人日常** | 30-50 次/月 | DeepSeek V3 | ¥3 - ¥10 |
| **活跃用户** | 100-200 次/月 | DeepSeek V3 | ¥10 - ¥30 |
| **重度使用** | 500+ 次/月 | DeepSeek V3 | ¥50 - ¥150 |
| **关键决策** | 10-20 次/月 | Qwen Plus（高质量）| ¥10 - ¥30 |
| **极致省** | 无限次 | 豆包 2.0 | ¥0 - ¥5 |

**对比 GPT-4o / Claude**：**便宜 10-20 倍**

---

## 九、第一次跑：建议步骤

1. **注册 DeepSeek 拿 API key**（5 分钟）
2. **克隆项目 + 配 .env**（10 分钟）
3. **Docker 启动**（5 分钟）
4. **跑京新药业 002020**（5 分钟出报告）
5. **跑舍得酒业 600702**（5 分钟出报告）
6. **对比** TradingAgents 报告 vs 我（Hermes）的长期趋势判断 vs 你自己的判断
7. **跑 1-2 周模拟盘**，看命中率
8. **决定是否长期用**

---

## 十、常见问题

### Q1：必须用 Docker 吗？
- 不是，**Python 本地部署也行**
- 但 Docker 更省事（依赖、环境都打包好）

### Q2：必须用国产模型吗？
- 不是，**海外模型也能用**（OpenAI / Claude / Gemini）
- 但国产**便宜 + 中文能力强 + A 股场景优**

### Q3：能直接实盘交易吗？
- **默认是 analysis_only 模式**（只分析，不交易）
- 想实盘要自己接券商 API（强烈建议先模拟盘跑 1-3 个月）

### Q4：分析报告准不准？
- 学术研究显示 **部分场景能跑赢基准**
- **不是 100% 稳定盈利**
- 当作**辅助参考**，不当作"印钞机"

### Q5：跑一次多久？
- 快速：1-3 分钟
- 标准：3-7 分钟
- 深度：7-15 分钟

### Q6：能跑多个股票吗？
- 可以，**批量分析**功能（股票池模式）
- 但单次 token 消耗会乘以股票数

---

## 十一、GitHub 仓库

| 项 | 值 |
|---|---|
| 仓库 | `https://github.com/hsliuping/TradingAgents-CN` |
| README | `https://github.com/hsliuping/TradingAgents-CN/blob/main/README.md` |
| 配置文档 | `https://github.com/hsliuping/TradingAgents-CN/blob/main/docs/configuration/llm-config.md` |
| Star | 中文社区最活跃 |
| License | MIT（免费商用）|

---

## 十二、关键链接

- DeepSeek：`https://platform.deepseek.com`
- 阿里百炼（Qwen）：`https://dashscope.aliyun.com`
- 智谱 GLM：`https://open.bigmodel.cn`
- 火山引擎（豆包）：`https://www.volcengine.com`
- 月之暗面 Kimi：`https://platform.moonshot.cn`
- MiniMax 开放平台：`https://api.minimaxi.com`
