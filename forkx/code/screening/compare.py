"""多日博弈状态对比。

对比近N日关键博弈指标的变化趋势：
- 主力资金净流入（日级）
- 五档买卖比
- 集合竞价开盘幅度
- RSI
- 量价异动类型
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from ..data.sina_provider import SinaProvider
from ..data.tencent_provider import TencentProvider
from .fund_flow_provider import FundFlowProvider, _get_today_minute_flow
from .game_analyzer import detect_consolidation, detect_volume_anomaly


@dataclass
class DayCompare:
    date: date
    main_net_wan: float          # 主力净流入（万元）
    buy_pressure_ratio: float    # 买卖比
    auction_open_pct: float       # 竞价开盘幅度%
    rsi: float                   # RSI(14)
    vol_ratio: float             # 量比
    vol_anomaly_type: str        # 量价异动类型
    breakout: str                # 横盘突破方向


class CompareReport:
    stock_code: str
    days: List[DayCompare]
    trend: str                   # 总体趋势判断
    changes: List[str]           # 环比变化说明

    def __init__(self, stock_code: str, days: List[DayCompare], trend: str, changes: List[str]):
        self.stock_code = stock_code
        self.days = days
        self.trend = trend
        self.changes = changes


def compare_game_trend(code: str, days: int = 5) -> CompareReport:
    """对比近N日博弈状态。"""
    end = date.today()
    start = date(end.year, end.month - 2, 1) if end.month > 2 else date(end.year - 1, 11, 1)

    sina = SinaProvider()
    quotes = sina.get_daily_quotes(code, start, end)
    if not quotes:
        return CompareReport(code, [], "数据不足", [])

    # 取最近N个有数据的交易日
    trading_days = sorted(set(q.date for q in quotes))
    target_days = trading_days[-days:] if len(trading_days) >= days else trading_days

    # 当日五档数据（实时）
    tencent = TencentProvider()
    rt_data = tencent.get_realtime([code])
    rt = rt_data.get(code)

    # 当日efinance资金流
    today_rec = _get_today_minute_flow(code)

    day_compares = []
    for d in target_days:
        d_idx = trading_days.index(d)
        # 历史窗口：从 d_idx-20 到 d_idx（含当天）
        hist_start = max(0, d_idx - 20)
        hist_quotes = quotes[hist_start:d_idx + 1]
        if not hist_quotes:
            continue

        today_q = hist_quotes[-1]
        prev_q = hist_quotes[-2] if len(hist_quotes) >= 2 else None

        # RSI（用历史窗口内的收盘价）
        rsi = _calc_rsi([q.close for q in hist_quotes]) if len(hist_quotes) >= 15 else None

        # 量比（相对前5日均量，不含当天）
        vol_closes = [q.volume for q in hist_quotes[-6:-1]]
        avg_vol = sum(vol_closes) / len(vol_closes) if vol_closes else 1
        vol_ratio = today_q.volume / avg_vol if avg_vol > 0 else 1.0

        # 量价异动（用历史窗口）
        vol_anomaly = detect_volume_anomaly(hist_quotes)

        # 竞价开盘幅度
        auction_open_pct = ((today_q.open - prev_q.close) / prev_q.close * 100) if prev_q else 0

        # 横盘检测（用历史窗口）
        consolidation = detect_consolidation(hist_quotes)

        # 主力净流入（今日用efinance，历史用fund_flow_provider）
        if d == date.today() and today_rec:
            main_net_wan = today_rec.main_net_wan
        else:
            from .fund_flow_provider import _get_historical_fund_flow
            hist = _get_historical_fund_flow(code, 30)
            match = next((r for r in hist if r.date == d), None)
            main_net_wan = match.main_net_wan if match else 0.0

        day_compares.append(DayCompare(
            date=d,
            main_net_wan=main_net_wan,
            buy_pressure_ratio=0.0,
            auction_open_pct=round(auction_open_pct, 2),
            rsi=round(rsi, 1) if rsi else 0.0,
            vol_ratio=round(vol_ratio, 2),
            vol_anomaly_type=vol_anomaly.anomaly_type if vol_anomaly else "无异动",
            breakout=consolidation.breakout_direction if consolidation.consolidation_days >= 3 else "—",
        ))

    # 今日补充实时买卖比
    if rt and day_compares and day_compares[-1].date == date.today():
        try:
            bid_total = sum(float(v) for k, v in rt.__dict__.items() if k.startswith('bid'))
            ask_total = sum(float(v) for k, v in rt.__dict__.items() if k.startswith('ask'))
            if ask_total > 0:
                day_compares[-1] = dataclass_replace(day_compares[-1],
                    buy_pressure_ratio=round(bid_total / ask_total, 1))
        except Exception:
            pass

    # 生成趋势判断
    trend, changes = _summarize_changes(code, day_compares)
    return CompareReport(code, day_compares, trend, changes)


def _calc_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def dataclass_replace(obj, **kwargs):
    """纯Python dataclass浅拷贝+替换字段。"""
    import dataclasses
    return dataclasses.replace(obj, **kwargs)


def _summarize_changes(code: str, days: List[DayCompare]) -> tuple:
    if len(days) < 2:
        return "数据不足", []

    changes = []
    recent = days[-1]
    prev = days[-2]

    # 主力净流入变化
    net_chg = recent.main_net_wan - prev.main_net_wan
    if abs(net_chg) > 1000:
        arrow = "↑↑" if net_chg > 0 else "↓↓"
        changes.append(f"主力净流入较昨日{arrow} {abs(net_chg):+.0f}万")

    # RSI变化
    if recent.rsi and prev.rsi:
        rsi_chg = recent.rsi - prev.rsi
        if abs(rsi_chg) > 3:
            changes.append(f"RSI {prev.rsi:.0f}→{recent.rsi:.0f}（{'偏强' if rsi_chg > 0 else '偏弱'}）")

    # 量比变化
    if recent.vol_ratio > 2.0:
        changes.append(f"量比放大至{recent.vol_ratio:.1f}倍（放量）")
    elif recent.vol_ratio < 0.6:
        changes.append(f"量比缩至{recent.vol_ratio:.1f}倍（缩量）")

    # 量价异动
    if recent.vol_anomaly_type != "无异动":
        changes.append(f"量价异动：{recent.vol_anomaly_type}")

    # 竞价
    if abs(recent.auction_open_pct) > 2.0:
        direction = "高开" if recent.auction_open_pct > 0 else "低开"
        changes.append(f"竞价{direction}{abs(recent.auction_open_pct):.1f}%")

    # 突破方向
    if recent.breakout not in ("—", "待定"):
        changes.append(f"横盘突破方向：{recent.breakout}")

    # 总体判断
    buy_days = sum(1 for d in days if d.main_net_wan > 1000)
    if buy_days >= len(days) * 0.7:
        trend = f"持续买入（{buy_days}/{len(days)}天净流入）"
    elif buy_days <= len(days) * 0.3:
        trend = f"持续卖出（{buy_days}/{len(days)}天净流入）"
    elif net_chg > 3000:
        trend = "资金加速流入"
    elif net_chg < -3000:
        trend = "资金加速流出"
    else:
        trend = "资金来回拉扯"

    return trend, changes


def format_compare_report(report: CompareReport) -> str:
    """格式化对比报告。"""
    if not report.days:
        return f"  {report.stock_code} 无对比数据"

    days = report.days
    lines = []
    date_strs = [d.date.strftime('%m-%d') for d in days]

    # 表头
    lines.append(f"{'═' * 56}")
    lines.append(f"  博弈状态对比  {report.stock_code}")
    lines.append(f"{'═' * 56}")

    # 第一行：日期
    lines.append(f"{'':8}  " + "  ".join(f"{s:>8}" for s in date_strs))
    lines.append(f"{'-' * 56}")

    # 主力净流入
    net_vals = [f"{'▲' if d.main_net_wan > 0 else '▼' if d.main_net_wan < 0 else '―'}{abs(d.main_net_wan):>7.0f}" for d in days]
    lines.append(f"{'主力万':8}  " + "  ".join(f"{s:>8}" for s in net_vals))

    # 买卖比
    pr_vals = [f"{d.buy_pressure_ratio:>8.1f}" if d.buy_pressure_ratio > 0 else f"{'—':>8}" for d in days]
    lines.append(f"{'买卖比':8}  " + "  ".join(pr_vals))

    # RSI
    rsi_vals = [f"{d.rsi:>8.1f}" if d.rsi > 0 else f"{'—':>8}" for d in days]
    lines.append(f"{'RSI':8}  " + "  ".join(rsi_vals))

    # 量比
    vr_vals = [f"{d.vol_ratio:>8.1f}" for d in days]
    lines.append(f"{'量比':8}  " + "  ".join(vr_vals))

    # 量价异动（只显示非"无异动"的）
    va_vals = []
    for d in days:
        if d.vol_anomaly_type == "无异动":
            va_vals.append(f"{'—':>8}")
        elif len(d.vol_anomaly_type) <= 6:
            va_vals.append(f"{d.vol_anomaly_type:>8}")
        else:
            va_vals.append(f"{d.vol_anomaly_type[:6]:>8}")
    lines.append(f"{'量价异动':8}  " + "  ".join(va_vals))

    # 竞价开盘
    ao_vals = [f"{'+' if d.auction_open_pct > 0 else '' if d.auction_open_pct == 0 else ''}{d.auction_open_pct:>7.1f}%" for d in days]
    lines.append(f"{'竞价%':8}  " + "  ".join(f"{s:>8}" for s in ao_vals))

    lines.append(f"{'═' * 56}")
    lines.append(f"  趋势：{report.trend}")

    if report.changes:
        lines.append(f"  变化：{' | '.join(report.changes)}")

    return "\n".join(lines)
