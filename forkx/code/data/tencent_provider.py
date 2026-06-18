"""腾讯实时行情Provider。"""
import re
import urllib.request
from datetime import date
from typing import Dict, List

from .models import DailyQuote, FinancialReport, Stock, StockRealtime
from .provider import DataProvider

_TIMEOUT = 10
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.qq.com/",
}


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read()
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError:
                return data.decode("gbk", errors="replace")
    except Exception as e:
        raise RuntimeError(f"HTTP请求失败 {url}: {e}")


def _tencent_code(code: str) -> str:
    code = code.strip()
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _parse_tencent_record(raw: str) -> StockRealtime:
    """解析腾讯行情单条记录。"""
    m = re.search(r'v_\w+="([^"]+)"', raw)
    if not m:
        raise ValueError(f"无法解析腾讯行情: {raw[:50]}")
    fields = m.group(1).split("~")
    if len(fields) < 40:
        raise ValueError(f"腾讯行情字段不足: {len(fields)}")

    price = float(fields[3])
    prev_close = float(fields[4])
    pct_chg = (price - prev_close) / prev_close * 100 if prev_close else 0.0

    return StockRealtime(
        code=fields[2],
        name=fields[1],
        price=price,
        prev_close=prev_close,
        open=float(fields[5]),
        high=float(fields[33]) if fields[33] else price,
        low=float(fields[34]) if fields[34] else price,
        volume=float(fields[6]),
        turnover=float(fields[37]) if len(fields) > 37 and fields[37] else 0.0,
        pe=float(fields[39]) if len(fields) > 39 and fields[39] else 0.0,
        pb=float(fields[46]) if len(fields) > 46 and fields[46] else 0.0,
        pct_chg=round(pct_chg, 2),
    )


class TencentProvider(DataProvider):
    """腾讯实时行情Provider。"""

    def __init__(self):
        self._stock_cache: List[Stock] = []
        self._stock_fetch_time = 0.0

    def list_stocks(self) -> List[Stock]:
        # FORKX不依赖全市场股票列表，只服务用户自选股
        # 如果需要股票名称，用 get_realtime 反查
        return []

    def get_realtime(self, codes: List[str]) -> Dict[str, StockRealtime]:
        if not codes:
            return {}
        # 腾讯批量接口每次最多约200只
        results: Dict[str, StockRealtime] = {}
        for i in range(0, len(codes), 150):
            batch = codes[i:i + 150]
            results.update(self._fetch_batch(batch))
        return results

    def _fetch_batch(self, codes: List[str]) -> Dict[str, StockRealtime]:
        joined = ",".join(_tencent_code(c) for c in codes)
        url = f"https://qt.gtimg.cn/q={joined}"
        text = _http_get(url)
        results: Dict[str, StockRealtime] = {}
        for line in text.split("\n"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            try:
                rt = _parse_tencent_record(line)
                results[rt.code] = rt
            except Exception:
                continue
        return results

    def get_daily_quotes(self, stock_code: str, start: date, end: date) -> List[DailyQuote]:
        # 日线由 SinaProvider 负责
        return []

    def get_batch_quotes(self, codes: List[str], start: date, end: date) -> Dict[str, List[DailyQuote]]:
        return {}

    def get_financials(self, stock_code: str) -> FinancialReport:
        # 财务数据由 BaoStockProvider 负责
        return FinancialReport(stock_code=stock_code)

    def get_order_book(self, code: str) -> dict:
        """获取五档买卖数据。

        Returns:
            dict: {
                'bid1': [price, volume], 'ask1': [price, volume], ...
                'bid_total': float, 'ask_total': float
            }
        """
        tc = _tencent_code(code)
        url = f"https://qt.gtimg.cn/q={tc}"
        text = _http_get(url)
        m = re.search(r'v_\w+="([^"]+)"', text)
        if not m:
            return {}

        fields = m.group(1).split("~")
        if len(fields) < 50:
            return {}

        # 腾讯五档顺序（字段索引）：
        # 买1-5: [9,11,13,15,17] 价格；[10,12,14,16,18] 量（手）
        # 卖1-5: [19,21,23,25,27] 价格；[20,22,24,26,28] 量（手）
        result = {}
        for i in range(1, 6):
            bid_price_idx = 9 + (i - 1) * 2
            bid_vol_idx = 10 + (i - 1) * 2
            ask_price_idx = 19 + (i - 1) * 2
            ask_vol_idx = 20 + (i - 1) * 2

            if bid_price_idx < len(fields) and fields[bid_price_idx]:
                result[f'bid{i}'] = [float(fields[bid_price_idx]), int(fields[bid_vol_idx])]
            if ask_price_idx < len(fields) and fields[ask_price_idx]:
                result[f'ask{i}'] = [float(fields[ask_price_idx]), int(fields[ask_vol_idx])]

        return result
