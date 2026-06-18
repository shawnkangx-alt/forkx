"""BaoStock财务数据Provider。

单位说明（实测验证）：
- netProfit: 元
- totalShare: 股（不是万股！北方华创5.36亿股=533608487）
- epsTTM: 元/股（PE = price / epsTTM，最准确）
- dupontROE: 小数，×100得%
- liabilityToAsset: 小数，×100得%
- currentRatio: 流动比率

Growth表YOY字段是季度累计同比，不适合直接展示。
改为用相邻年profit表计算同比。
"""
from datetime import date, timedelta
from typing import Dict, List

from .models import FinancialReport, Stock
from .provider import DataProvider


class BaoStockProvider(DataProvider):

    def __init__(self):
        self._logged_in = False

    def _ensure_login(self):
        if self._logged_in:
            return
        try:
            import baostock as bs
            bs.login()
            self._logged_in = True
        except ImportError:
            raise RuntimeError("请安装 baostock: pip install baostock")

    def _bs_code(self, code: str) -> str:
        prefix = "sh." if code.startswith(("6", "9")) else "sz."
        return prefix + code

    def _query(self, query_fn, *args, **kwargs) -> Dict:
        rs = query_fn(*args, **kwargs)
        result = {}
        if rs.error_code == "0":
            while rs.next():
                result = dict(zip(rs.fields, rs.get_row_data()))
        return result

    def list_stocks(self) -> List[Stock]:
        return []

    def get_realtime(self, codes: List[str]) -> Dict:
        return {}

    def get_daily_quotes(self, stock_code: str, start: date, end: date) -> List:
        return []

    def get_batch_quotes(self, codes: List[str], start: date, end: date) -> Dict:
        return {}

    def get_financials(self, stock_code: str, year: int = None) -> FinancialReport:
        self._ensure_login()
        import baostock as bs

        bs_code = self._bs_code(stock_code)
        year = year or (date.today().year - 1)

        # ── 1. 利润表（年报Q4）───────────────────────────────
        profit = self._query(bs.query_profit_data, bs_code, year, 4)
        # ── 2. 杜邦分析（年报Q4）──────────────────────────────
        dupont = self._query(bs.query_dupont_data, bs_code, year, 4)
        # ── 3. 资产负债表（年报Q4，兜底Q3/Q2/Q1）────────────
        balance = {}
        for q in [4, 3, 2, 1]:
            b = self._query(bs.query_balance_data, bs_code, year, q)
            if b:
                balance = b
                break

        # ── 4. 增长率：相邻年profit对比 ─────────────────────
        # growth表YOY字段是季度累计同比，不直观；改用年报直接对比
        prev_profit = self._query(bs.query_profit_data, bs_code, year - 1, 4)

        # EPS TTM（用于PE计算）
        eps_ttm = float(profit.get("epsTTM") or 0)

        # 总股本（股）
        total_share = float(profit.get("totalShare") or 0)

        # 当前收盘价（最新，不复权）
        rs_quote = bs.query_history_k_data_plus(
            bs_code, "date,close",
            start_date="2025-01-01", end_date="2026-12-31",
            frequency="d", adjustflag="3",
        )
        latest_close = None
        if rs_quote.error_code == "0":
            rows = []
            while rs_quote.next():
                rows.append(rs_quote.get_row_data())
            for row in reversed(rows):
                if row[1] and row[1] != "":
                    latest_close = float(row[1])
                    break

        # ── PE（最优方法：股价/EPS TTM）─────────────────────
        pe = 0.0
        pb = 0.0
        if latest_close and eps_ttm > 0:
            pe = round(latest_close / eps_ttm, 2)

        # ── PB：市值/净资产 ─────────────────────────────────
        if latest_close and total_share > 0:
            net_profit_yuan = float(profit.get("netProfit") or 0)
            roe_for_pb = float(dupont.get("dupontROE", 0) or 0) * 100
            if roe_for_pb <= 0:
                roe_for_pb = float(profit.get("roeAvg", 0) or 0) * 100
            if net_profit_yuan > 0 and roe_for_pb > 0:
                market_cap_yi = latest_close * total_share / 1e8  # 亿元
                net_assets_yi = (net_profit_yuan / 1e8) / (roe_for_pb / 100)
                pb = round(market_cap_yi / net_assets_yi, 2) if net_assets_yi > 0 else 0.0

        # ── ROE ────────────────────────────────────────────
        roe = 0.0
        if dupont.get("dupontROE"):
            roe = round(float(dupont["dupontROE"]) * 100, 2)
        elif profit.get("roeAvg"):
            roe = round(float(profit["roeAvg"]) * 100, 2)

        # ── 营收/净利润增长率（直接对比两年年报）─────────────
        revenue_yoy = 0.0
        net_profit_yoy = 0.0
        curr_rev = float(profit.get("MBRevenue") or 0)
        prev_rev = float(prev_profit.get("MBRevenue") or 0)
        curr_np = float(profit.get("netProfit") or 0)
        prev_np = float(prev_profit.get("netProfit") or 0)
        if prev_rev > 0:
            revenue_yoy = round((curr_rev - prev_rev) / prev_rev * 100, 2)
        if prev_np > 0:
            net_profit_yoy = round((curr_np - prev_np) / prev_np * 100, 2)

        # ── 负债率/流动比率（取最新季度）─────────────────────
        debt_ratio = 0.0
        current_ratio = 0.0
        if balance.get("liabilityToAsset"):
            debt_ratio = round(float(balance["liabilityToAsset"]) * 100, 2)
        if balance.get("currentRatio"):
            current_ratio = round(float(balance["currentRatio"]), 2)

        # 报告期
        stat_date_str = (
            profit.get("statDate")
            or dupont.get("statDate")
            or f"{year}-12-31"
        )
        stat_date = date.fromisoformat(stat_date_str) if stat_date_str else date(year, 12, 31)

        return FinancialReport(
            stock_code=stock_code,
            report_date=stat_date,
            pe=pe,
            pb=pb,
            roe=roe,
            revenue_yoy=revenue_yoy,
            net_profit_yoy=net_profit_yoy,
            debt_ratio=debt_ratio,
            current_ratio=current_ratio,
        )

    def get_minute_quotes(self, stock_code: str, freq: int = 5, days: int = 5) -> List[dict]:
        """获取分钟K线数据。

        Args:
            stock_code: 股票代码如 002371
            freq: 周期（5/15/30/60分钟）
            days: 取最近N个交易日
        """
        self._ensure_login()
        import baostock as bs

        bs_code = self._bs_code(stock_code)
        end_date = date.today().strftime("%Y-%m-%d")
        start_date = (date.today() - timedelta(days=days * 3)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency=str(freq),
            adjustflag="3",
        )
        results = []
        if rs.error_code == "0":
            while rs.next():
                results.append(dict(zip(rs.fields, rs.get_row_data())))
        return results
