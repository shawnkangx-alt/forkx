# 康小赚（FORKX）

A股每日分析助手，专注于帮你读懂持仓股的市场博弈。

**商品名**：康小赚
**自选股**：002371 北方华创、688012 中微公司

---

## 功能一览

### `forkx watch`
自选股今日行情一览：价格、涨跌、RSI、均线状态。

### `forkx analyze <code>`
结构化博弈分析：
- 集合竞价信号（试盘/护盘/派发/诱多）
- 分时形态（脉冲/瀑布/震荡）
- 五档买卖博弈（买盘/卖盘比）
- 主力资金流向（近20日净流入）
- 支撑/压力位、综合建议

### `forkx predict <code>`
次日涨跌预测（贝叶斯 + 特征系数）：

```
上涨概率  ██████████████████░  94%
预测结果  上涨  （置信度：高·160天样本）

特征拆解（↑=看涨 ↓=看跌）
🔼 rsi above 50           +0.109
🔼 ma bullish arrangement   +0.081
🔼 momentum accelerating    +0.156
```

### `forkx log`
交易记录管理：

```
forkx log add --code 002371 --action buy --price 680 --volume 100
forkx log signals   # 查看信号胜率统计
forkx log weights   # 查看信号权重
forkx log records   # 查看交易记录
```

---

## 安装

```bash
git clone https://github.com/shawnkangx-alt/forkx.git
cd forkx
pip install -r requirements.txt
```

**requirements.txt** 依赖：
- `efinance` — 财务数据
- `baostock` — 历史K线
- `requests` — HTTP 请求

---

## 使用

```bash
bin/forkx watch              # 查看自选股
bin/forkx analyze 002371     # 博弈分析
bin/forkx predict 002371    # 次日预测
bin/forkx log add ...       # 记录交易
bin/forkx log signals       # 信号胜率
```

---

## 数据存储

| 文件 | 内容 |
|------|------|
| `~/.forkx/history.db` | 每日分析存档 |
| `~/.forkx/trades.db` | 交易记录 |
| `~/.forkx/signal_weights.json` | 信号权重（基于历史胜率） |
| `~/.forkx/feature_coefficients.json` | 预测特征系数（自动重训练） |

---

## 预测模型原理

**77维特征体系**：

| 类别 | 维度 |
|------|------|
| MA均线 | 9（多头排列/空头排列/乖离率/金叉死叉） |
| RSI | 13（数值/5档区间/背离） |
| MACD | 5（快线/柱方向/金叉死叉） |
| 布林带 | 4（position/碰轨/收缩） |
| ATR + OBV + 动量 | 6 |
| 量能 | 5（量比/背离） |
| 位置 | 6（连续涨跌/振幅/距高低点） |
| 大盘相对强弱 | 1 |
| 支撑压力 | 2 |
| 信号标签 | 26 |

**学习闭环**：
- 每日 `predict` → 存档预测结果
- 次日 `analyze` → 对照预测 vs 实际涨跌
- 正确 +0.05 / 错误 -0.10 → 更新信号权重

**自动重训练**：
- 每满 60 条已学习预测记录，自动触发重训练
- 从历史存档重建特征，计算每维特征的真实贡献系数
- 系数叠加到贝叶斯预测概率上，动态调整预测方向

---

## 命令速查

```
watch              自选股行情一览
analyze <code>     博弈分析
predict <code>     次日涨跌预测
log add            记录交易
log signals        信号胜率统计
log weights        信号权重
log records        交易记录
```

---

## 项目结构

```
forkx/
├── bin/forkx              CLI 入口
└── forkx/code/
    ├── main.py            命令解析
    ├── data/              数据源（新浪/腾讯/baostock）
    │   ├── sina_provider.py
    │   ├── tencent_provider.py
    │   └── models.py
    └── screening/         分析模块
        ├── indicators.py          技术指标
        ├── signal_extractor.py    信号提取
        ├── game_analyzer.py       博弈分析
        ├── feature_engineering.py  特征计算
        ├── predictor.py           预测模型
        ├── signal_weights.py      权重调优
        ├── history_store.py       历史存档
        └── backfill.py           数据回填
```

---

## 数据来源优先级

| 数据 | 来源 |
|------|------|
| 日K线 | baostock（352+天，无代理） |
| 财务数据 | efinance |
| 五档行情 | 腾讯 |
| 集合竞价/分时 | 新浪 |

---

## 康小赚能做什么

- 告诉你今日市场在做什么（是吸筹还是派发）
- 告诉你明日大概率怎么走（概率+置信度）
- 告诉你该信什么信号、该忽略什么信号
- 随着交易记录增多，预测越来越准

**不能做什么**：不提供买卖建议，不保证盈利，决策权始终在你。
