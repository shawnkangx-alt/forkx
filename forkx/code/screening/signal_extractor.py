"""自动信号标签提取器。

从 analyze 结果（表层技术信号 + 深层博弈推断）中提取交易信号标签，
供 log 记录使用。

使用方式：
    from .signal_extractor import extract_current_signals
    signals = extract_current_signals('002371')
    # → ["主力强势吸筹", "RSI偏强", "横盘向上突破"]
"""
from dataclasses import dataclass
from typing import List, Optional

from ..data.models import SignalLabel
from .indicators import rsi_zone
from .game_analyzer import (
    AuctionSignal, ConsolidationSignal, VolumePriceAnomaly,
    IntradayPattern, OrderBookPressure, GameAnalysisReport
)


def extract_signals_from_analysis(
    rsi: float,
    ma_status: dict,
    macd_signal: str,
    rsi_zone_label: str,
    auction: Optional[AuctionSignal],
    intraday: Optional[IntradayPattern],
    order_pressure: Optional[OrderBookPressure],
    volume_anomaly: Optional[VolumePriceAnomaly],
    consolidation: Optional[ConsolidationSignal],
    fund_flow_trend: Optional[str] = None,
    fund_flow_quality: Optional[str] = None,
    today_minutes: Optional[list] = None,
) -> List[str]:
    """从分析结果中提取信号标签列表。"""
    signals = []

    # === 趋势 ===
    if ma_status:
        alignment = ma_status.get("alignment", "")
        cross = ma_status.get("cross", "")
        if alignment == "多头排列":
            signals.append(_label("TREND_STRONG"))
        elif alignment == "空头排列":
            signals.append(_label("TREND_WEAK"))
        if cross and cross != "无信号":
            signals.append(_label("TREND_REVERSAL"))

    # === RSI ===
    if rsi_zone_label:
        signals.append(rsi_zone_label)  # "RSI超卖" / "RSI偏弱" 等文字标签

    # === MACD ===
    if macd_signal:
        if "金叉" in macd_signal:
            signals.append("MACD金叉")
        elif "死叉" in macd_signal:
            signals.append("MACD死叉")

    # === 资金流 ===
    if fund_flow_trend:
        if "强吸筹" in fund_flow_trend or "持续买入" in fund_flow_trend:
            if fund_flow_quality and "估算" not in fund_flow_quality:
                signals.append(_label("MAIN_INFLOW_STRONG"))
            else:
                signals.append(_label("MAIN_INFLOW_WEAK"))
        elif "派发" in fund_flow_trend or "持续卖出" in fund_flow_trend:
            signals.append(_label("MAIN_OUTFLOW"))

        # 今日资金由卖转买反转
        if today_minutes and len(today_minutes) >= 2:
            half = len(today_minutes) // 2
            first_half_net = sum(
                getattr(m, 'net_inflow_wan', 0) for m in today_minutes[:half]
            )
            second_half_net = sum(
                getattr(m, 'net_inflow_wan', 0) for m in today_minutes[half:]
            )
            if first_half_net < -500 and second_half_net > 500:
                signals.append(_label("MAIN_REVERSAL"))

    # === 形态 ===
    if intraday:
        pattern = intraday.pattern_type or ""
        if "尾盘偷袭" in pattern:
            signals.append(_label("TAIL_SWING"))
        elif "瀑布" in pattern:
            signals.append(_label("WATERFALL"))
        elif "脉冲" in pattern:
            signals.append(_label("PUMP_DUMP"))

    # === 量价异动 ===
    if volume_anomaly:
        anomaly = volume_anomaly.anomaly_type or ""
        if "无异动" == anomaly or not anomaly:
            pass
        elif "缩量" in anomaly:
            signals.append(_label("VOLUME_SHRINK"))
        else:
            signals.append(_label("VOLUME_SURGE"))

    # === 横盘突破 ===
    if consolidation and consolidation.consolidation_days >= 5:
        direction = consolidation.breakout_direction or ""
        if "向上" in direction:
            signals.append(_label("CONSOLIDATION_BREAK_UP"))
        elif "向下" in direction:
            signals.append(_label("CONSOLIDATION_BREAK_DOWN"))

    # === 集合竞价 ===
    if auction:
        signal = auction.signal or ""
        signal_lower = signal.lower()
        if signal in ("试盘/拉升",):
            signals.append(_label("AUCTION_TEST"))
        elif signal in ("诱多嫌疑",):
            signals.append(_label("AUCTION_DISTRIBUTE"))
        elif signal in ("最后一杀", "主动砸盘"):
            signals.append(_label("AUCTION_SUPPORT"))
        elif "高开回落" in signal:
            signals.append(_label("AUCTION_HIGHEXT"))

    # === 综合买入/卖出信号 ===
    buy_score = _count_buy_signals(signals)
    sell_score = _count_sell_signals(signals)
    if buy_score >= 3:
        signals.append(_label("BUY_SIGNAL"))
    elif sell_score >= 3:
        signals.append(_label("SELL_SIGNAL"))

    return signals


def _label(signal_name: str) -> str:
    """把 SignalLabel 枚举名转成中文标签。"""
    try:
        return SignalLabel[signal_name].value
    except KeyError:
        return signal_name


def _count_buy_signals(signals: List[str]) -> int:
    buy_tags = {
        "趋势强势", "趋势反转", "RSI超卖", "RSI偏弱",
        "主力强势吸筹", "主力温和吸筹", "资金由卖转买",
        "横盘向上突破", "放量异动", "缩量整理", "竞价试盘", "竞价护盘",
        "MACD金叉",
    }
    return sum(1 for s in signals if s in buy_tags)


def _count_sell_signals(signals: List[str]) -> int:
    sell_tags = {
        "趋势弱势", "趋势反转", "RSI超买", "RSI偏强",
        "主力派发", "横盘向下突破", "尾盘偷袭", "放量异动",
        "竞价派发", "高开回落", "瀑布式下跌", "脉冲后回落",
        "MACD死叉",
    }
    return sum(1 for s in signals if s in sell_tags)


# ===================================================================
# 便捷入口：对单只股票跑完整分析并提取当前信号
# ===================================================================
def extract_current_signals(stock_code: str) -> List[str]:
    """对单只股票跑完整分析，返回当前信号标签列表。

    等价于：forkx analyze + 自动提取标签
    """
    from datetime import date
    from ..data.sina_provider import SinaProvider
    from ..data.tencent_provider import TencentProvider
    from .game_analyzer import build_game_report
    from .fund_flow_provider import FundFlowProvider
    from .indicators import calc_rsi, ma_status

    sina = SinaProvider()
    tencent = TencentProvider()

    # 实时行情
    rt_data = tencent.get_realtime([stock_code])
    rt = rt_data.get(stock_code)
    if not rt:
        return []

    # 日K
    quotes = sina.get_daily_quotes(stock_code, date(2024, 1, 1), date.today())
    if len(quotes) < 20:
        return []

    closes = [q.close for q in quotes]
    rsi_vals = calc_rsi(closes)
    rsi = rsi_vals[-1] if rsi_vals else 50.0
    ma = ma_status(quotes)

    # 博弈分析
    minute_quotes = sina.get_minute_quotes(stock_code, freq=5, days=5)
    bid_data = tencent.get_order_book(stock_code)
    game: GameAnalysisReport = build_game_report(stock_code, rt.name, quotes, minute_quotes, bid_data)

    # 资金流
    ff = FundFlowProvider().get_fund_flow(stock_code, days=20)

    # 今日分钟数据：从 records 最后一条取 hourly
    today_minutes = None
    if ff and ff.records:
        last = ff.records[-1]
        if last.date == date.today() and hasattr(last, 'hourly') and last.hourly:
            today_minutes = last.hourly
    return extract_signals_from_analysis(
        rsi=rsi,
        ma_status=ma,
        macd_signal=game.composite_signal or "",
        rsi_zone_label=rsi_zone(rsi),
        auction=game.auction,
        intraday=game.intraday_pattern,
        order_pressure=game.order_pressure,
        volume_anomaly=game.volume_anomaly,
        consolidation=game.consolidation,
        fund_flow_trend=ff.trend if ff else None,
        fund_flow_quality=ff.quality if ff else None,
        today_minutes=today_minutes,
    )
