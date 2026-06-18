"""新浪历史K线Provider。"""
import json
import re
import urllib.request
from datetime import date, datetime
from typing import Dict, List

from .models import DailyQuote
from .provider import DataProvider

_TIMEOUT = 10
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Referer": "https://finance.sina.com.cn/",
}


def _http_get(url: str) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"HTTP请求失败 {url}: {e}")


def _sina_code(code: str) -> str:
    """股票代码转新浪格式。"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


class SinaProvider(DataProvider):
    """新浪历史K线Provider。"""

    def list_stocks(self) -> List:
        return []

    def get_realtime(self, codes: List[str]) -> Dict:
        return {}

    def get_daily_quotes(self, stock_code: str, start: date, end: date) -> List[DailyQuote]:
        prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
            f"/CN_MarketData.getKLineData?symbol={prefix}{stock_code}"
            f"&scale=240&ma=no&datalen=500"
        )
        try:
            text = _http_get(url)
            data = json.loads(text)
        except Exception:
            return []

        quotes: List[DailyQuote] = []
        for item in data:
            try:
                item_date = datetime.strptime(item["day"], "%Y-%m-%d").date()
                if not (start <= item_date <= end):
                    continue
                quotes.append(DailyQuote(
                    stock_code=stock_code,
                    date=item_date,
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item["volume"]) / 10000.0,  # 股→万股
                    amount=0.0,
                ))
            except (ValueError, KeyError):
                continue
        return quotes

    def get_batch_quotes(self, codes: List[str], start: date, end: date) -> Dict[str, List[DailyQuote]]:
        results: Dict[str, List[DailyQuote]] = {}
        for code in codes:
            results[code] = self.get_daily_quotes(code, start, end)
        return results

    def get_financials(self, stock_code: str):
        return None

    def get_minute_quotes(self, stock_code: str, freq: int = 5, days: int = 5) -> List[dict]:
        """获取新浪分钟K线数据。

        新浪支持 scale=5/15/30/60，返回最近N条。
        返回格式与 baostock 兼容：{'date': 'YYYY-MM-DD', 'time': 'HHMMSS', ...}
        """
        scale_map = {5: 5, 15: 15, 30: 30, 60: 60}
        scale = scale_map.get(freq, 5)
        # datalen 约等于每天48/scale 条 * days天
        datalen = min(500, (48 // scale) * days + 10)

        prefix = "sh" if stock_code.startswith(("6", "9")) else "sz"
        url = (
            f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
            f"/CN_MarketData.getKLineData?symbol={prefix}{stock_code}"
            f"&scale={scale}&ma=no&datalen={datalen}"
        )
        try:
            text = _http_get(url)
            data = json.loads(text)
        except Exception:
            return []

        results = []
        for item in data:
            try:
                # 格式: "2026-06-18 15:00:00"
                dt_str = item["day"]  # "2026-06-18 15:00:00"
                date_part = dt_str.split(" ")[0]   # "2026-06-18"
                time_part = dt_str.split(" ")[1].replace(":", "")  # "150000"
                results.append({
                    "date": date_part,
                    "time": time_part,
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": int(item["volume"]),
                })
            except (ValueError, KeyError):
                continue
        return results
