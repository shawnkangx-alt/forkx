"""数据Provider抽象基类。"""
from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List

from .models import DailyQuote, FinancialReport, Stock, StockRealtime


class DataProvider(ABC):
    """数据提供者抽象接口。"""

    @abstractmethod
    def list_stocks(self) -> List[Stock]:
        """返回股票列表。"""
        ...

    @abstractmethod
    def get_realtime(self, codes: List[str]) -> Dict[str, StockRealtime]:
        """批量获取实时行情。"""
        ...

    @abstractmethod
    def get_daily_quotes(self, stock_code: str, start: date, end: date) -> List[DailyQuote]:
        """获取单只股票历史日线。"""
        ...

    @abstractmethod
    def get_batch_quotes(self, codes: List[str], start: date, end: date) -> Dict[str, List[DailyQuote]]:
        """批量获取多只股票历史日线。"""
        ...

    @abstractmethod
    def get_financials(self, stock_code: str) -> FinancialReport:
        """获取单只股票财务数据。"""
        ...
