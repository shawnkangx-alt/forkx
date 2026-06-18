---
name: FORKX
description: >
  个人炒股助理，面向 A 股市场。
  核心理念：不是选股工具，而是对用户持有的/关注的股票做好服务。
  核心功能：
  1. watch — 股池监控（我的自选股现在怎么样）
  2. analyze — 结构化个股分析报告（趋势/价位/基本面/判断）
  3. alert — 关键价位与指标提醒设置
  4. chart — K线图
  5. log — 交易记录与胜率分析
  6. backtest — 简单均线交叉回测
  数据源：腾讯实时行情 + 新浪日K + BaoStock财务（不降级）。
  触发：用户说"看看我的股"、"分析XX股票"、"设置提醒"、"记录买入"、"回测"。
  命令入口：/Users/shawnkangx/projects/forkx/bin/forkx
---

# FORKX — 个人炒股助理

## 产品定位

**不是选股工具，而是炒股助理。**

服务对象：个人A股投资者，有自己的自选股池，不需要从5000只里找机会。

核心价值：把用户关注的那些股票（最多20-30只）的分析质量做透，让每一只股票的分析都能直接指导操作。

---

## 交互命令

### watch — 股池监控（最常用）
展示用户自选股的实时状态总览。

```
forkx watch
```

输出：
- 股票名称、当前价、涨跌幅
- RSI(14) 所处区间（超买/中性/超卖）
- MA5/MA20 均线状态（金叉/死叉/纠缠）
- 趋势方向（上升/下降/震荡）
- 数据新鲜度

### analyze — 结构化个股分析
单股深度分析，输出可操作的决策参考。

```
forkx analyze <股票代码> [--start YYYY-MM-DD] [--end YYYY-MM-DD]
```

输出：
- **趋势判断**：上升/下降/震荡 + 依据
- **关键价位**：支撑位、压力位
- **均线状态**：MA5/MA20/MA60 多空排列
- **RSI**：当前值 + 区间判断
- **基本面**：PE/PB/ROE 在行业/全市场分位
- **性价比**：贵/合理/便宜（结合行业对比）
- **风险点**：需要注意的事项
- **综合判断**：买入/持有/观望/回避

### alert — 关键价位提醒
设置提醒，价格或指标触发时通知。

```
forkx alert add <股票代码> --type price|rsi|volume --threshold <值> [--note "备注"]
forkx alert list
forkx alert remove <id>
```

提醒类型：
- `price_below`：跌破指定价格
- `price_above`：突破指定价格
- `rsi_overbought`：RSI进入超买区（>70）
- `rsi_oversold`：RSI进入超卖区（<30）
- `volume_surge`：放量异常（量比>2倍）

### chart — K线图
生成个股K线图。

```
forkx chart <股票代码> [--period daily|weekly] [--indicators ma,kdj,bollinger]
```

输出：K线图保存到本地，用默认图片查看器打开。

### log — 交易记录
记录买卖操作，支持后续分析。

```
forkx log add --stock <代码> --action buy|sell --price <价格> --volume <数量> --date YYYY-MM-DD [--note "备注"]
forkx log list [--stock <代码>]
forkx log stats
```

输出：
- 历史交易列表
- 持仓汇总（成本、盈亏）
- 胜率统计

### backtest — 简单回测
均线交叉历史验证。

```
forkx backtest <股票代码> --fast <快线周期> --slow <慢线周期> [--start YYYY-MM-DD] [--end YYYY-MM-DD]
```

输出：
- 策略盈亏（买入持有 vs 均线交叉）
- 交易次数
- 胜率
- 最大回撤
- 资金曲线

---

## 数据模型

### 核心数据模型

```python
# 股票
Stock(code: str, name: str, market: str)

# 日线行情
DailyQuote(stock_code, date, open, high, low, close, volume, amount)

# 财务数据
FinancialReport(stock_code, report_date, pe, pb, roe, revenue_yoy, net_profit_yoy, debt_ratio)

# 交易记录
TradeRecord(id, stock_code, action: buy|sell, price, volume, date, note, created_at)

# 提醒记录
Alert(id, stock_code, alert_type, threshold, note, enabled, created_at)
```

---

## 数据源策略

**单一主力数据源，不降级。**

- 实时行情：腾讯 `qt.gtimg.cn`（PE/PB + 实时价格）
- 历史K线：新浪 `money.finance.sina.com.cn`（不复权日K，计算复权在客户端做）
- 财务数据：腾讯实时行情PE/PB + BaoStock（年度财务）

不追求全市场覆盖，专注服务用户自选股池（最多50只）。

---

## 技术指标定义

| 指标 | 计算方式 | 说明 |
|------|---------|------|
| MA5/10/20/60 | SMA | 简单移动平均 |
| RSI(14) | Wilder's RSI | 相对强弱 |
| MACD(12,26,9) | EMA差值 | 趋势判断 |
| KDJ(9,3,3) | 随机指标 | 超买超卖 |
| 布林带(20,2σ) | SMA±2*std | 支撑压力 |
| DMI(14) | ADX | 趋势强度 |

---

## 目录结构

```
FORKX/
├── SKILL.md
├── README.md
├── pyproject.toml
├── code/
│   ├── main.py              # CLI入口
│   ├── __init__.py
│   ├── data/
│   │   ├── models.py           # 数据模型
│   │   ├── provider.py         # 数据provider抽象
│   │   ├── tencent_provider.py # 腾讯实时行情
│   │   ├── sina_provider.py    # 新浪历史K线
│   │   └── baostock_provider.py# 财务数据
│   ├── screening/
│   │   ├── indicators.py       # 指标计算
│   │   └── analyzer.py         # 分析报告生成
│   ├── charts/
│   │   └── plotter.py          # K线绘图
│   ├── notification/
│   │   ├── alert_store.py      # 提醒存储
│   │   └── checker.py          # 提醒触发检查
│   ├── trading/
│   │   ├── log_store.py        # 交易记录存储
│   │   └── backtest.py         # 回测引擎
│   └── utils/
│       ├── config.py            # 配置
│       └── watchlist.py         # 自选股管理
```

---

## 设计原则

1. **单一数据源，不降级** — 数据一致性高于可用性
2. **输出可操作** — 每个分析结论都要有操作含义，不是指标堆砌
3. **本地优先** — 所有数据存本地（SQLite），不依赖网络返回历史
4. **无评分排名** — 不给股票打分，给结构化判断
5. **可追溯** — 所有提醒、交易记录本地持久化，可查历史

## 命令测试状态（2026-06-18）

| 命令 | 状态 | 说明 |
|------|------|------|
| `forkx add <code>` | ✅ | 添加自选股 |
| `forkx watch` | ✅ | 股池总览（含RSI/MA/趋势） |
| `forkx analyze <code>` | ✅ | 结构化分析报告（表层+深层） |
| `forkx chart <code>` | ✅ | K线图（含MA+MACD+成交量） |
| `forkx log add/list/positions/stats` | ✅ | 交易记录+持仓+胜率 |
| `forkx backtest <code>` | ✅ | MA5/20交叉回测（含资金曲线） |
| `forkx compare <code> [--days N]` | ✅ | 多日博弈状态对比表 |
| `forkx predict <code>` | ✅ | 次日涨跌预测（贝叶斯概率模型） |
| `forkx log signals` | ✅ | 信号胜率统计（按标签统计买入→卖出胜率） |
| `forkx log weights` | ✅ | 信号权重表（基于历史胜率动态调整） |
| `forkx remove <code>` | ✅ | 移除自选股 |

## analyze 两层分析体系（2026-06-18）

### 表层：技术信号
趋势/RSI/KDJ/MACD/布林带/均线/量比/支撑压力/基本面

### 深层：博弈推断（新增）
| 模块 | 功能 | 数据来源 |
|------|------|---------|
| 集合竞价分析 | 开盘异动信号（试盘/诱多/护盘/派发） | 新浪5分钟K |
| 缩量横盘检测 | 主力控盘横盘识别+突破方向判断 | 日K |
| 分时形态识别 | 当日走势分类（脉冲/尾盘偷袭/瀑布等） | 新浪5分钟K |
| 五档资金博弈 | 实时买卖压力比（大单挂买信号） | 腾讯五档 |
| 量价异动 | 放量滞涨/缩量上涨/天量性质判断 | 日K |
| 主力资金流 | 近20日净流入趋势（吸筹/派发评级）+ 今日逐时流量 | efinance Level2（东方财富）+ 新浪日K估算 |

## 数据质量（北方华创002371）

- 行情：腾讯实时 ✅
- K线：新浪日K ✅
- 财务：BaoStock ✅（PE/PB/ROE/营收增长/负债率/流动比率）
- 均线：MA5/MA20/MA60 ✅
- MACD/KDJ/RSI/布林带 ✅
- 量比 ✅
- 支撑/压力位 ✅
