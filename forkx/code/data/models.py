"""FORKX 数据模型。"""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import uuid4


class Market(str, Enum):
    SH = "SH"
    SZ = "SZ"
    BJ = "BJ"


class SignalLabel(str, Enum):
    """交易信号标签（自动从 analyze 结果提取）。

    趋势类
    """
    TREND_STRONG = "趋势强势"       # 均线多头排列 + RSI偏强
    TREND_WEAK = "趋势弱势"        # 均线空头排列 + RSI偏弱
    TREND_REVERSAL = "趋势反转"     # 均线金叉/死叉

    # RSI 类
    RSI_OVERSOLD = "RSI超卖"       # RSI < 30
    RSI_OVERBOUGHT = "RSI超买"      # RSI > 70
    RSI_WEAK = "RSI偏弱"           # RSI 30-40
    RSI_STRONG = "RSI偏强"         # RSI 60-70

    # 资金流类
    MAIN_INFLOW_STRONG = "主力强势吸筹"   # 主力净流入且强度高
    MAIN_INFLOW_WEAK = "主力温和吸筹"    # 主力净流入但强度一般
    MAIN_OUTFLOW = "主力派发"         # 主力净流出
    MAIN_REVERSAL = "资金由卖转买"    # 前卖后买反转

    # 形态类
    CONSOLIDATION_BREAK_UP = "横盘向上突破"  # 横盘后向上突破
    CONSOLIDATION_BREAK_DOWN = "横盘向下突破" # 横盘后向下突破
    TAIL_SWING = "尾盘偷袭"           # 分时尾盘急拉/急杀
    VOLUME_SURGE = "放量异动"         # 量比放大且方向明确
    VOLUME_SHRINK = "缩量整理"       # 缩量横盘
    PUMP_DUMP = "脉冲后回落"         # 早盘脉冲后回落
    waterfall = "瀑布式下跌"         # 盘中快速杀跌

    # 集合竞价类
    AUCTION_TEST = "竞价试盘"        # 高开幅度不大但成交放大
    AUCTION_SUPPORT = "竞价护盘"      # 低开但竞价稳住
    AUCTION_DISTRIBUTE = "竞价派发"   # 高开幅度大且竞价出货
    AUCTION_HIGHEXT = "高开回落"     # 竞价高开后迅速低走

    # 买入/卖出信号（综合）
    BUY_SIGNAL = "买入信号"          # 综合信号：多个维度共振
    SELL_SIGNAL = "卖出信号"         # 综合信号：多个维度共振


@dataclass
class Stock:
    code: str
    name: str
    market: Market


@dataclass
class DailyQuote:
    stock_code: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float  # 万手
    amount: float  # 万元


@dataclass
class FinancialReport:
    stock_code: str
    report_date: Optional[date] = None
    pe: float = 0.0
    pb: float = 0.0
    roe: float = 0.0
    revenue_yoy: float = 0.0
    net_profit_yoy: float = 0.0
    debt_ratio: float = 0.0
    current_ratio: float = 0.0


@dataclass
class StockRealtime:
    """单只股票实时行情。"""
    code: str
    name: str
    price: float
    prev_close: float
    open: float
    high: float
    low: float
    volume: float  # 手
    turnover: float  # 元
    pe: float = 0.0
    pb: float = 0.0
    pct_chg: float = 0.0  # 涨跌幅%


@dataclass
class TradeRecord:
    """交易记录。"""
    stock_code: str
    action: str  # "buy" | "sell"
    price: float
    volume: float  # 股
    date: date
    note: str = ""
    signals: List[str] = field(default_factory=list)  # 自动提取的交易信号标签
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class AlertRecord:
    """提醒记录。"""
    stock_code: str
    alert_type: str  # 传统: "price_below" | "price_above" | "rsi_overbought" | "rsi_oversold" | "volume_surge"
                     # 博弈: "consolidation_break" | "tail_swing" | "main_inflow_surge"
                     #      | "main_inflow_reversal" | "buy_pressure_surge" | "volume_anomaly"
    threshold: float
    note: str = ""
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = field(default_factory=datetime.now)

    # 博弈信号专用字段
    # threshold 的含义因类型而异：
    #   consolidation_break: threshold = 突破涨幅%阈值（默认2%）
    #   tail_swing: threshold = 1（固定触发）
    #   main_inflow_surge: threshold = 主力净流入下限（万元），默认10000
    #   main_inflow_reversal: threshold = 1（固定触发）
    #   buy_pressure_surge: threshold = 买卖比下限，默认3.0
    #   volume_anomaly: threshold = 量比下限，默认2.0
