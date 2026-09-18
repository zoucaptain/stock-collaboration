# 🎯 Logic Pool Index — 逻辑池智能索引（v1.0）

> **用途**：Hermes/OpenClaw 从 GitHub 拉逻辑时，**用 1-2 个问题锁定适用逻辑**
> **创建日期**：2026-08-30
> **适用场景**：当用户说"选股"、"看 K 线"、"做 T"、"找支撑位"等任何股票相关问题

---

## 🚀 快速使用流程

```
用户提问
   ↓
【问题 1】你的决策场景是什么？
   ↓
【问题 2】你的持仓状态？（仅做T/离场时需要）
   ↓
锁定 → 调用对应逻辑文件
```

---

## 📋 问题 1：你的决策场景是什么？

### 🅰️ 选股类（用户问"选股"、"找票"、"哪只票"）

| 关键词 | 锁定逻辑 | 文件 |
|---|---|---|
| "选股"、"找票"、"选哪只" | **L_six_step**（盘中 6 步选股）| `L_six_step_method.md` |
| "4 板"、"4 连板"、"涨停票" | **L_4board**（4 板入场战法）| `L_4board_entry.md` |
| "共振"、"金叉"、"5 条件" | **L_resonance**（5 条件共振）| `L_resonance_five_condition.md` |
| "MACD"、"绿翻红"、"红柱缩短" | **L_macd**（MACD 柱状图）| `L_macd_histogram.md` |

### 🅱️ 决策类（用户问"该不该动"、"等什么信号"）

| 关键词 | 锁定逻辑 | 文件 |
|---|---|---|
| "该不该动"、"择时"、"主线" | **L_core**（三句诀操作法）| `L_core_three_line_doctrine.md` |
| "什么行情"、"震荡"、"反弹"、"突破" | **L_market**（五种行情）| `L_market_five_states.md` |

### 🅲️ 持仓操作类（用户问"做 T"、"降低成本"、"离场"）

| 关键词 | 锁定逻辑 | 文件 |
|---|---|---|
| "做 T"、"日内"、"降低成本" | **L_t0**（做 T战法）| `L_t0_trading.md` |
| "找支撑位"、"压力位"、"关键位" | **L_top_bottom**（顶底公式）| `L_top_bottom_formula.md` |
| "放量"、"缩量"、"量能"、"量价" | **L_volume**（量能逻辑）| `L_volume_doctrine.md` |

---

## 📋 问题 2（仅持仓操作时）：你的持仓状态？

### 🅰️ 持仓状态判断（用于做 T/离场决策）

| 用户关键词 | 持仓状态 | 建议逻辑组合 |
|---|---|---|
| "上涨趋势"、"涨了"、"行情好" | 🟢 **上涨** | L_macd（绿→红）+ L_t0（正T）|
| "下跌趋势"、"跌了"、"被套" | 🔴 **下跌** | L_macd（红柱缩短）+ L_t0（反T）|
| "震荡"、"横盘"、"方向不明" | 🟡 **震荡** | L_top_bottom（找支撑）+ L_volume（看量能）|

---

## 🎯 一键决策树

```
┌────────────────────────────────────────────────────────────┐
│  Q1: 你的决策场景是什么？                                  │
└────────────────────────────────────────────────────────────┘
         ↓
    ┌────┴────┬──────────┬──────────┐
    │         │          │          │
  选股类   决策类    持仓操作类
    │         │          │          │
    ↓         ↓          ↓
┌──────┐ ┌──────┐  ┌──────────┐
│ 选股 │ │ 决策 │  │  持仓   │
└──────┘ └──────┘  └──────────┘
    │         │          │
    ↓         ↓          ↓
  6步选股   行情识别   做T/支撑/量能
    │         │          │
    ↓         ↓          ↓
┌──────────────────────────────────────┐
│  Q2: 持仓状态？                        │
│  🟢上涨 / 🔴下跌 / 🟡震荡            │
└──────────────────────────────────────┘
    │         │          │
    ↓         ↓          ↓
  持仓观察  减仓/清仓  找支撑/等信号
```

---

## 📚 完整 9 大逻辑一览

| ID | 决策场景 | 核心问题 | 文件 |
|---|---|---|---|
| **L_core** | 决策 | "该不该动？"| `L_core_three_line_doctrine.md` |
| **L_market** | 决策 | "等什么信号？"| `L_market_five_states.md` |
| **L_resonance** | 选股 | "动哪只？"| `L_resonance_five_condition.md` |
| **L_4board** | 选股 | "4 板票怎么入场？"| `L_4board_entry.md` |
| **L_macd** | 持仓 | "何时进出？"| `L_macd_histogram.md` |
| **L_six_step** | 选股 | "盘中怎么实时选股？"| `L_six_step_method.md` |
| **L_t0** | 持仓 | "如何做 T？"| `L_t0_trading.md` |
| **L_top_bottom** | 持仓 | "关键支撑位在哪？"| `L_top_bottom_formula.md` |
| **L_volume** | 持仓 | "量能信号是什么？"| `L_volume_doctrine.md` |

---

## 🚨 实战使用示例

### 示例 1：用户问"明天该买什么？"

```
Q1: 你的决策场景是什么？
→ 选股

Q2: 你的持仓状态？（可选）
→ 无持仓

锁定逻辑：L_six_step（盘中选股）
         + L_4board（4 板入场）
         + L_resonance（5 条件共振）
```

### 示例 2：用户问"我被套了，要不要割肉？"

```
Q1: 你的决策场景是什么？
→ 持仓操作

Q2: 你的持仓状态？
→ 🔴 下跌趋势

锁定逻辑：L_macd（红柱缩短 = 清仓信号）
         + L_volume（缩量下跌还会下跌 = 减仓信号）
         + L_t0（反T 降低成本）
```

### 示例 3：用户问"现在行情怎么看？"

```
Q1: 你的决策场景是什么？
→ 决策

锁定逻辑：L_core（该不该动？）
         + L_market（什么行情？等什么信号？）
```

### 示例 4：用户问"MACD 怎么看？"

```
Q1: 你的决策场景是什么？
→ 选股 / 持仓操作

锁定逻辑：L_macd（MACD 柱状图战法）
```

### 示例 5：用户问"做 T 怎么操作？"

```
Q1: 你的决策场景是什么？
→ 持仓操作

Q2: 你的持仓状态？
→ 🟢 上涨 → L_t0（正T）
→ 🔴 下跌 → L_t0（反T）
→ 🟡 震荡 → L_top_bottom（找支撑）
```

---

## 📌 关键判定原则

### 1️⃣ **1-2 个问题足够**

**不需要问太多**——只要问清楚"场景 + 持仓状态"就能锁定。

### 2️⃣ **关键词触发**

如果用户用了明确关键词，**直接锁定**：
- "MACD" → L_macd
- "4 板" → L_4board
- "做 T" → L_t0
- "支撑位" → L_top_bottom
- "放量/缩量" → L_volume

### 3️⃣ **组合调用**

实战可同时调多个逻辑：
```
场景：选股 + 上涨趋势
→ L_4board + L_macd + L_volume（看量能确认）
```

### 4️⃣ **不要硬套**

如果用户问题不明确，**直接列出所有 9 个逻辑**让用户选。

---

## 🔧 OpenClaw 调用建议

```python
# OpenClaw / Hermes 调用逻辑池的标准流程

def get_logic(user_query):
    # Step 1: 关键词检测
    keywords_to_logic = {
        'macd': 'L_macd_histogram.md',
        '4板': 'L_4board_entry.md',
        '6步': 'L_six_step_method.md',
        '做T': 'L_t0_trading.md',
        '支撑位': 'L_top_bottom_formula.md',
        '量能': 'L_volume_doctrine.md',
        '缩量': 'L_volume_doctrine.md',
        '放量': 'L_volume_doctrine.md',
        '共振': 'L_resonance_five_condition.md',
        '金叉': 'L_resonance_five_condition.md',
        '行情': 'L_market_five_states.md',
        '择时': 'L_core_three_line_doctrine.md',
        '主线': 'L_core_three_line_doctrine.md',
    }
    
    for kw, logic_file in keywords_to_logic.items():
        if kw in user_query:
            return logic_file
    
    # Step 2: 场景判断（如果没有明确关键词）
    if '选股' in user_query or '选哪只' in user_query:
        return ['L_six_step_method.md', 'L_4board_entry.md']
    
    if '做T' in user_query or '降低成本' in user_query:
        return ['L_t0_trading.md', 'L_volume_doctrine.md']
    
    if '该不该' in user_query or '择时' in user_query:
        return ['L_core_three_line_doctrine.md', 'L_market_five_states.md']
    
    # Step 3: 默认返回核心逻辑
    return 'README.md'
```

---

## 📊 决策表速查

### 📌 选股类

| 场景 | 推荐逻辑 |
|---|---|
| 4 板涨停股怎么入场 | **L_4board** |
| 盘中实时选股（14:30 后）| **L_six_step** |
| MACD 进场信号 | **L_macd** |
| 5 条件共振票 | **L_resonance** |

### 📌 决策类

| 场景 | 推荐逻辑 |
|---|---|
| 现在该不该动 | **L_core** |
| 当前是哪种行情 | **L_market** |
| 行情变了该买什么 | **L_market + L_core** |

### 📌 持仓操作类

| 持仓状态 | 推荐逻辑 |
|---|---|
| 上涨趋势 | L_macd + L_t0（正T） |
| 下跌趋势 | L_macd + L_t0（反T）+ L_volume |
| 震荡 | L_top_bottom + L_volume |

---

## 🎯 测试场景（建议 OpenClaw 验证）

### 测试 1：用户问"选股"

```
Input: "今天选什么股？"
Output: L_six_step_method.md (主) + L_4board_entry.md (辅)
```

### 测试 2：用户问"MACD"

```
Input: "MACD 怎么看？"
Output: L_macd_histogram.md
```

### 测试 3：用户问"做T"

```
Input: "京新怎么做T？"
Output: 
  - Q2: 持仓状态？
  - 下跌 → L_t0_trading.md (反T) + L_macd_histogram.md
```

### 测试 4：用户问"支撑位"

```
Input: "科伦的关键支撑位在哪？"
Output: L_top_bottom_formula.md + L_volume_doctrine.md
```

### 测试 5：用户问"行情"

```
Input: "现在是什么行情？"
Output: L_market_five_states.md + L_core_three_line_doctrine.md
```

---

## 📊 决策流程图

```
用户问股票问题
    ↓
[Step 1] 检测关键词
    ├─ 有明确关键词 → 直接锁定逻辑
    └─ 无明确关键词 → 进入 Q1
    ↓
[Q1] 决策场景是什么？
    ├─ 选股 → L_six_step / L_4board / L_macd / L_resonance
    ├─ 决策 → L_core / L_market
    └─ 持仓操作 → 进入 Q2
    ↓
[Q2] 持仓状态？
    ├─ 🟢 上涨 → L_macd + L_t0 (正T)
    ├─ 🔴 下跌 → L_macd + L_t0 (反T) + L_volume
    └─ 🟡 震荡 → L_top_bottom + L_volume
    ↓
返回对应逻辑文件路径
```

---

## 🔧 维护说明

### 📝 何时更新索引

| 触发条件 | 更新内容 |
|---|---|
| 新增逻辑 | 添加新的关键词映射 |
| 修改逻辑文件 | 同步更新文件路径 |
| 用户新增高频问题 | 添加到决策表 |

### 🔄 版本历史

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.0 | 2026-08-30 | 初版：9 大逻辑 + 1-2 问题锁定 |

---

**最后更新**：2026-08-30
**作者**：Hermes Agent
**用途**：Hermes/OpenClaw 智能锁定逻辑池