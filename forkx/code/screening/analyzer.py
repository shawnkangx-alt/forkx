"""结构化个股分析报告生成器。"""
from datetime import date, datetime, timedelta
from typing import Dict, List

from ..data.models import DailyQuote, FinancialReport, StockRealtime
from .indicators import (
    bollinger_zone,
    calc_kdj,
    calc_macd,
    calc_rsi,
    calc_volume_ratio,
    find_support_resistance,
    kdj_status,
    macd_signal,
    ma_status,
    rsi_zone,
    rsi_oversold_with_main_inflow,
    rsi_overbought_duration,
)


class Analyzer:
    """生成结构化个股分析报告。"""

    def __init__(self, quotes: List[DailyQuote], fin: FinancialReport, rt: StockRealtime):
        self.quotes = quotes
        self.fin = fin
        self.rt = rt
        self.closes = [q.close for q in quotes]

    def analyze(self) -> Dict:
        if not self.quotes:
            return {"error": "无行情数据"}

        latest = self.quotes[-1]
        prev = self.quotes[-2] if len(self.quotes) > 1 else latest

        # 技术面
        ma = ma_status(self.quotes)
        rsi_vals = calc_rsi(self.closes)
        rsi = rsi_vals[-1] if rsi_vals else 0
        macd_data = calc_macd(self.closes)
        macd = macd_signal(macd_data)
        kdj_data = calc_kdj(self.quotes) if len(self.quotes) >= 9 else None
        bb = bollinger_zone(self.quotes)
        sr = find_support_resistance(self.quotes)
        vol_ratio = calc_volume_ratio(self.quotes)

        # 趋势判断
        trend = self._judge_trend(ma, rsi, macd, kdj_data)

        # RSI超买持续时间
        rsi_overbought = rsi_overbought_duration(rsi_vals)

        # 性价比判断
        value = self._judge_value()

        # 综合判断
        verdict = self._make_verdict(trend, rsi, bb, value, vol_ratio, rsi_overbought)

        return {
            "stock_code": self.rt.code,
            "stock_name": self.rt.name,
            "date": str(latest.date),
            "price": self.rt.price,
            "pct_chg": self.rt.pct_chg,
            "realtime_fetch_time": self.rt.fetch_time,
            "financial_fetch_time": self.fin.fetch_time,
            "kline_start": str(self.quotes[0].date),
            "kline_end": str(latest.date),
            "trend": trend,
            "rsi": {
                "value": round(rsi, 1),
                "zone": rsi_zone(rsi),
            },
            "ma": ma,
            "macd": macd,
            "kdj": kdj_status(kdj_data) if kdj_data else "数据不足",
            "bollinger": bb,
            "support_resistance": sr,
            "volume_ratio": vol_ratio,
            "rsi_overbought": rsi_overbought,
            "financial": {
                "pe": self.fin.pe,
                "pb": self.fin.pb,
                "roe": self.fin.roe,
                "revenue_yoy": self.fin.revenue_yoy,
                "net_profit_yoy": self.fin.net_profit_yoy,
                "debt_ratio": self.fin.debt_ratio,
            },
            "value": value,
            "verdict": verdict,
        }

    def _judge_trend(self, ma: Dict, rsi: float, macd: str, kdj_data) -> Dict:
        """判断趋势方向。"""
        score = 0
        signals = []

        # 均线权重
        if "多头" in ma["alignment"]:
            score += 2
            signals.append("均线多头")
        elif "空头" in ma["alignment"]:
            score -= 2
            signals.append("均线空头")

        # MA金叉死叉
        if ma["cross"] == "金叉":
            score += 1
            signals.append("MA金叉")
        elif ma["cross"] == "死叉":
            score -= 1
            signals.append("MA死叉")

        # RSI
        if rsi > 60:
            score += 1
            signals.append("RSI偏强")
        elif rsi < 40:
            score -= 1
            signals.append("RSI偏弱")

        # MACD
        if "金叉" in macd:
            score += 1
            signals.append("MACD金叉")
        elif "死叉" in macd:
            score -= 1
            signals.append("MACD死叉")

        if score >= 2:
            direction = "上升趋势"
        elif score <= -2:
            direction = "下降趋势"
        else:
            direction = "震荡整理"

        return {"direction": direction, "signals": signals, "score": score}

    def _judge_value(self) -> Dict:
        """判断性价比。"""
        pe = self.fin.pe
        pb = self.fin.pb
        roe = self.fin.roe

        # 简单判断逻辑
        if pe <= 0 or pb <= 0:
            level = "无法判断"
            comment = "PE/PB无效（亏损或数据缺失）"
        elif pe > 80 or pb > 15:
            level = "偏贵"
            comment = f"PE={pe:.1f} PB={pb:.1f}，估值偏高"
        elif pe < 0 or (pe < 20 and pb < 3 and roe > 10):
            level = "偏低"
            comment = f"PE={pe:.1f} PB={pb:.1f} ROE={roe:.1f}%，估值偏低或合理"
        else:
            level = "合理"
            comment = f"PE={pe:.1f} PB={pb:.1f}，处于合理区间"

        return {"level": level, "comment": comment}

    def _make_verdict(self, trend: Dict, rsi: float, bb: Dict, value: Dict, vol_ratio: float,
                       rsi_overbought: dict) -> str:
        """综合判断：买入/持有/观望/回避。

        新增逻辑（2026-06-25）：
        - RSI超买持续 < 3 天 → 忽略，视为正常多头延续
        - RSI超买持续 3-5 天 → 关注但不警示
        - RSI超买持续 ≥ 5 天 → 警示，注意利润锁定
        """
        trend_score = trend["score"]
        rsi_val = rsi
        bb_zone = bb.get("zone", "")
        value_level = value["level"]
        overbought_duration = rsi_overbought.get("duration", 0)
        overbought_alert = rsi_overbought.get("alert_level", "正常")

        # 风险信号
        if rsi_val > 85:
            return "观望（RSI严重超买）"
        if rsi_val < 15:
            return "观望（RSI严重超卖，可能反弹）"

        # RSI超买持续时间权重（2026-06-25 新增）
        # RSI>70 持续 ≥5 天才警示（之前被误判为空头陷阱）
        if overbought_alert == "警示":
            return "持有（注意利润锁定：RSI≥70持续超买）"

        # 买入条件
        buy_conditions = (
            trend_score >= 1
            and 30 < rsi_val < 70
            and ("偏宜" in bb_zone or "中轨" in bb_zone)
            and value_level in ("偏低", "合理")
        )
        if buy_conditions:
            return "可买入"

        # 持有条件
        hold_conditions = (
            trend_score >= 0
            and 40 < rsi_val < 70
        )
        if hold_conditions:
            if trend_score < 0:
                return "持有（注意趋势转弱）"
            return "持有"

        # 回避条件
        if trend_score <= -2 or (value_level == "偏贵" and trend_score <= 0):
            return "回避"

        return "观望（等待明确信号）"


def format_analysis(report: Dict) -> str:
    """将分析报告格式化为可读字符串。"""
    if "error" in report:
        return f"分析失败: {report['error']}"

    # 数据时间
    rt_time = report.get("realtime_fetch_time")
    fin_time = report.get("financial_fetch_time")
    rt_time_str = rt_time.strftime("%m-%d %H:%M") if rt_time else "—"
    fin_time_str = fin_time.strftime("%Y-%m-%d") if fin_time else "—"

    lines = [
        "=" * 50,
        f"  {report['stock_name']}（{report['stock_code']}）  {report['date']}  收盘 {report['price']}",
        "=" * 50,
        "",
        f"【数据】实时行情 {rt_time_str} | 日K {report.get('kline_start','?')}～{report.get('kline_end','?')} | 财务 {fin_time_str}",
        "",
        f"【价格】{report['price']} 元  涨跌幅 {report['pct_chg']:+.2f}%",
        "",
        f"【趋势】{report['trend']['direction']}",
    ]
    if report['trend']['signals']:
        lines.append(f"  信号：{' | '.join(report['trend']['signals'])}")
    lines.append("")

    # 均线
    ma = report["ma"]
    lines.append(f"【均线】MA5={ma['ma5']}  MA20={ma['ma20']}" + (f"  MA60={ma['ma60']}" if ma.get("ma60") else ""))
    lines.append(f"  排列：{ma['alignment']}  交叉：{ma['cross']}")
    lines.append("")

    # RSI超买持续时间
    rsi_ob = report.get("rsi_overbought", {})
    if rsi_ob.get("duration", 0) >= 3:
        ob_dur = rsi_ob.get("duration", 0)
        ob_level = rsi_ob.get("alert_level", "")
        ob_interp = rsi_ob.get("interpretation", "")
        lines.append(f"【RSI持续】{ob_dur}天 {ob_level} | {ob_interp}")
    else:
        lines.append(f"【RSI持续】{rsi_ob.get('duration', 0)}天（暂无异常）")
    lines.append("")

    # RSI
    lines.append(f"【RSI(14)】{report['rsi']['value']}  —  {report['rsi']['zone']}")
    lines.append("")

    # MACD
    lines.append(f"【MACD】{report['macd']}")
    lines.append("")

    # KDJ
    lines.append(f"【KDJ】{report['kdj']}")
    lines.append("")

    # 布林带
    bb = report["bollinger"]
    if bb.get("upper"):
        lines.append(f"【布林带】{bb['zone']}")
        lines.append(f"  上轨={bb['upper']}  中轨={bb['middle']}  下轨={bb['lower']}")
    else:
        lines.append(f"【布林带】{bb['zone']}")
    lines.append("")

    # 支撑压力
    sr = report["support_resistance"]
    if sr.get("support"):
        lines.append(f"【价位】支撑 {sr['support']}  压力 {sr['resistance']}  当前 {sr['current']}")
    lines.append("")

    # 量比
    lines.append(f"【量比】{report['volume_ratio']}x（1x为正常量能）")
    lines.append("")

    # 基本面
    fin = report["financial"]
    lines.append(f"【基本面】PE={fin['pe']:.1f}  PB={fin['pb']:.1f}  ROE={fin['roe']:.1f}%")
    lines.append(f"  营收增长={fin['revenue_yoy']:.1f}%  净利润增长={fin['net_profit_yoy']:.1f}%")
    lines.append(f"  负债率={fin['debt_ratio']:.1f}%")
    lines.append("")

    # 性价比
    val = report["value"]
    lines.append(f"【性价比】{val['level']}  {val['comment']}")
    lines.append("")

    # 综合判断
    lines.append("=" * 50)
    lines.append(f"  综合判断：{report['verdict']}")
    lines.append("=" * 50)

    return "\n".join(lines)
