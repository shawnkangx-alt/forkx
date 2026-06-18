"""FORKX 数据模型。"""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class Market(str, Enum):
    SH = "SH"
    SZ = "SZ"
    BJ = "BJ"


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
