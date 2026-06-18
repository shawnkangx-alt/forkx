"""自选股重大变化预警系统。

预警条件：
  1. 暴涨暴跌  — 单日涨跌 ≥ ±5%
  2. RSI极端   — RSI > 75（超买）或 RSI < 30（超卖）
  3. 技术破位  — 跌破支撑 或 突破压力
  4. 主力异动  — 单日净流入 ≥ 1亿 或 净流出 ≥ 5000万
  5. 量能异常   — 量比 ≥ 3x 或 ≤ 0.3x
  6. 趋势信号  — 均线金叉/死叉
  7. 预测剧变  — 次日预测概率单日变化 ≥ 30%
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import date, timedelta
from ..data.models import DailyQuote
from .indicators import calc_rsi, calc_bollinger
from .feature_engineering import calc_support_resistance, detect_ma_cross
from .fund_flow_provider import FundFlowProvider
from .history_store import get_records, get_prediction_summary, get_prediction_records
from .predictor import calc_all_features
import baostock as bs


@dataclass
class Alert:
    stock_code: str
    stock_name: str
    level: str  # 🔴 重大  🟡 注意  ⚪ 参考
    category: str
    title: str
    detail: str
    value: float
    threshold: str


@dataclass
class AlertReport:
    stock_code: str
    stock_name: str
    current_price: float
    pct_chg: float
    rsi: float
    alerts: List[Alert] = field(default_factory=list)

    @property
    def has_alerts(self) -> bool:
        return len(self.alerts) > 0

    @property
    def max_level(self) -> str:
        if any(a.level == "🔴" for a in self.alerts):
            return "🔴"
        if any(a.level == "🟡" for a in self.alerts):
            return "🟡"
        return "⚪"


def scan_stock_alerts(stock_code: str, stock_name: str = "") -> AlertReport:
    """扫描单只股票的预警情况，返回报告。"""
    today = date.today()
    end = today.isoformat()
    start = (today - timedelta(days=90)).isoformat()

    # 取K线数据
    records = get_records(stock_code, days=90)
    if not records:
        return AlertReport(stock_code, stock_name or stock_code, 0, 0, 0)

    quotes: List[DailyQuote] = []
    for r in records:
        try:
            q = DailyQuote(
                stock_code=r["stock_code"],
                date=r["date"],
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=r["volume"],
            )
            quotes.append(q)
        except Exception:
            continue

    if len(quotes) < 5:
        return AlertReport(stock_code, stock_name or stock_code, 0, 0, 0)

    quotes.sort(key=lambda x: x.date)
    latest = quotes[-1]
    prev = quotes[-2] if len(quotes) >= 2 else latest
    current_price = latest.close
    pct_chg = (latest.close - prev.close) / prev.close * 100 if prev.close else 0

    # RSI
    closes = [q.close for q in quotes]
    rsi_vals = calc_rsi(closes)
    rsi = rsi_vals[-1] if rsi_vals else 50

    # 布林带
    boll = calc_bollinger(closes)
    upper = boll["upper"]
    lower = boll["lower"]

    # 支撑压力
    sr = calc_support_resistance(quotes)
    support = sr.get("support")
    pressure = sr.get("pressure")

    # 均线金叉死叉
    ma_cross = detect_ma_cross(quotes) if len(quotes) >= 30 else {}

    # 主力资金
    fund_flow_net = 0
    fund_flow_today = 0
    try:
        ff = FundFlowProvider()
        flow_data = ff.get_fund_flow(stock_code, days=5)
        if flow_data and len(flow_data) >= 1:
            fund_flow_today = flow_data[-1].get("net", 0)
        if flow_data and len(flow_data) >= 2:
            fund_flow_net = sum(f.get("net", 0) for f in flow_data)
    except Exception:
        pass

    # 量比
    vol_avg = sum(q.volume for q in quotes[-20:]) / min(20, len(quotes)) if len(quotes) >= 5 else 1
    vol_ratio = latest.volume / vol_avg if vol_avg > 0 else 1

    # 预测概率（近两日对比）
    pred_prob_change = 0
    try:
        pred_records = get_prediction_records(stock_code, days=5)
        if len(pred_records) >= 2:
            latest_pred = pred_records[0].get("up_prob", 0.5)
            prev_pred = pred_records[1].get("up_prob", 0.5)
            pred_prob_change = abs(latest_pred - prev_pred)
    except Exception:
        pass

    alerts: List[Alert] = []

    # === 1. 暴涨暴跌 ===
    if abs(pct_chg) >= 5:
        level = "🔴" if abs(pct_chg) >= 8 else "🟡"
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level=level,
            category="暴涨暴跌",
            title=f"{'暴涨' if pct_chg > 0 else '暴跌'} {pct_chg:+.2f}%",
            detail=f"单日{'上涨' if pct_chg > 0 else '下跌'}幅度超过5%，{'注意回调风险' if pct_chg > 0 else '关注是否止跌'}",
            value=pct_chg,
            threshold="±5%",
        ))

    # === 2. RSI极端 ===
    if rsi > 75:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🔴",
            category="RSI极端",
            title=f"RSI超买 {rsi:.0f}",
            detail="RSI超过75，短期涨幅过大，警惕回调风险",
            value=rsi,
            threshold=">75",
        ))
    elif rsi < 30:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🟡",
            category="RSI极端",
            title=f"RSI超卖 {rsi:.0f}",
            detail="RSI低于30，卖压过重，关注反弹机会",
            value=rsi,
            threshold="<30",
        ))

    # === 3. 技术破位 ===
    if support and current_price < support:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🔴",
            category="技术破位",
            title=f"跌破支撑 {support:.2f}",
            detail=f"现价{current_price:.2f}跌破支撑位{support:.2f}，下跌空间打开",
            value=current_price,
            threshold=f"<{support:.2f}",
        ))
    elif pressure and current_price > pressure:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🟡",
            category="技术破位",
            title=f"突破压力 {pressure:.2f}",
            detail=f"现价{current_price:.2f}突破压力位{pressure:.2f}，有望继续上行",
            value=current_price,
            threshold=f">{pressure:.2f}",
        ))

    # === 4. 主力异动 ===
    if fund_flow_today >= 100_000_000:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🔴",
            category="主力异动",
            title=f"主力强势吸筹 +{fund_flow_today/100_000_000:.1f}亿",
            detail="主力单日净流入过亿，大资金建仓信号",
            value=fund_flow_today,
            threshold="≥1亿",
        ))
    elif fund_flow_today <= -50_000_000:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🔴",
            category="主力异动",
            title=f"主力大幅派发 {fund_flow_today/100_000_000:.1f}亿",
            detail="主力单日净流出超5000万，警惕主力出逃",
            value=fund_flow_today,
            threshold="≤-5000万",
        ))

    # === 5. 量能异常 ===
    if vol_ratio >= 3:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🟡",
            category="量能异常",
            title=f"巨量 {vol_ratio:.1f}x",
            detail="量能是均量的3倍以上，资金大幅进出，关注方向确认",
            value=vol_ratio,
            threshold="≥3x",
        ))
    elif vol_ratio <= 0.3:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="⚪",
            category="量能异常",
            title=f"地量 {vol_ratio:.1f}x",
            detail="量能极度萎缩，可能见底或横盘整理",
            value=vol_ratio,
            threshold="≤0.3x",
        ))

    # === 6. 趋势信号 ===
    if ma_cross.get("type") == "golden":
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🟡",
            category="趋势信号",
            title="均线金叉",
            detail=f"MA{ma_cross.get('short')}上穿MA{ma_cross.get('long')}，中期趋势转多",
            value=1,
            threshold="金叉",
        ))
    elif ma_cross.get("type") == "death":
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🟡",
            category="趋势信号",
            title="均线死叉",
            detail=f"MA{ma_cross.get('short')}下穿MA{ma_cross.get('long')}，中期趋势转空",
            value=-1,
            threshold="死叉",
        ))

    # === 7. 预测概率剧变 ===
    if pred_prob_change >= 0.30:
        alerts.append(Alert(
            stock_code=stock_code,
            stock_name=stock_name or stock_code,
            level="🟡",
            category="预测剧变",
            title=f"预测概率剧变 {pred_prob_change:.0%}",
            detail="模型预测概率单日变化超过30%，信号不稳定性高",
            value=pred_prob_change,
            threshold="≥30%",
        ))

    return AlertReport(
        stock_code=stock_code,
        stock_name=stock_name or stock_code,
        current_price=current_price,
        pct_chg=pct_chg,
        rsi=rsi,
        alerts=alerts,
    )


def format_alert_report(reports: List[AlertReport]) -> str:
    """格式化预警报告。"""
    lines = []
    lines.append("=" * 60)
    lines.append("  康小赚 · 自选股重大变化预警")
    lines.append("=" * 60)

    # 概览
    total_stocks = len(reports)
    stocks_with_alerts = sum(1 for r in reports if r.has_alerts)
    red_alerts = sum(1 for r in reports for a in r.alerts if a.level == "🔴")
    yellow_alerts = sum(1 for r in reports for a in r.alerts if a.level == "🟡")

    lines.append(f"\n  自选股 {total_stocks} 只，{stocks_with_alerts} 只触发预警")
    if red_alerts:
        lines.append(f"  🔴 重大预警 {red_alerts} 条  🟡 注意预警 {yellow_alerts} 条")
    else:
        lines.append(f"  🟡 注意预警 {yellow_alerts} 条")
    lines.append("")

    # 分类展示
    for rpt in reports:
        if not rpt.has_alerts:
            lines.append(f"  {rpt.stock_code}  {rpt.stock_name or rpt.stock_code}  无异常")
            continue

        max_level = rpt.max_level
        lines.append(f"  {max_level} {rpt.stock_code}  {rpt.stock_name or rpt.stock_code}  {rpt.current_price:.2f}元  {rpt.pct_chg:+.2f}%")
        for a in rpt.alerts:
            lines.append(f"     {a.level} [{a.category}] {a.title}")
            lines.append(f"        {a.detail}")
        lines.append("")

    if all(not r.has_alerts for r in reports):
        lines.append("  ✅ 今日自选股无重大变化，继续跟踪")
    else:
        lines.append("  ───────────────────────────────────────")
        lines.append("  温馨提示：预警仅供参考，不构成投资建议")

    lines.append("=" * 60)
    return "\n".join(lines)


def get_stock_name(stock_code: str) -> str:
    """通过 baostock 获取股票名称。"""
    try:
        bs.login()
        # 判断交易所前缀
        if stock_code.startswith("sh.") or stock_code.startswith("sz."):
            bs_code = stock_code
        elif stock_code.startswith("6"):
            bs_code = f"sh.{stock_code}"
        elif stock_code.startswith(("0", "3")):
            bs_code = f"sz.{stock_code}"
        else:
            bs_code = f"sh.{stock_code}"
        rs = bs.query_stock_basic(code=bs_code)
        name = ""
        while rs.next():
            row = rs.get_row_data()
            if len(row) >= 2:
                name = row[1]
        bs.logout()
        return name if name else stock_code
    except Exception:
        return stock_code
