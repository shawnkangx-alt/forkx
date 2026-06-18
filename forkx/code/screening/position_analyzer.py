"""持仓分析 + 买卖建议生成。

结合持仓成本、模型预测、风险提示，
给出具体的操作建议（加/减/持有）。

使用方式：
    from .position_analyzer import analyze_position
    advice = analyze_position("002371", current_price=721.04, pred_up_prob=0.94, risk_level="中")
"""
from typing import Optional, Dict, List
from ..trading.log_store import get_positions, list_trades


def get_position(stock_code: str) -> Optional[Dict]:
    """获取单只股票的当前持仓（含成本均价）。"""
    positions = get_positions()
    for p in positions:
        if p["stock_code"] == stock_code:
            return p
    return None


def calc_pnl(volume: float, avg_cost: float, current_price: float) -> Dict:
    """计算盈亏。"""
    cost = volume * avg_cost
    value = volume * current_price
    pnl = value - cost
    pnl_pct = (pnl / cost * 100) if cost > 0 else 0
    return {
        "cost": round(cost, 2),
        "value": round(value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "per_share": round(current_price - avg_cost, 2),
    }


def get_trade_history(stock_code: str) -> List[Dict]:
    """获取交易历史（买入/卖出明细）。"""
    trades = list_trades(stock_code)
    return [
        {
            "date": t.date.isoformat(),
            "action": t.action,
            "price": t.price,
            "volume": t.volume,
            "amount": round(t.price * t.volume, 2),
        }
        for t in trades
    ]


def analyze_position(
    stock_code: str,
    current_price: float,
    pred_up_prob: float = 0.5,
    pred_confidence: str = "低",
    rsi: float = 50.0,
    bollinger_pos: float = 0.5,
    trend: str = "震荡",
    fund_flow_net: float = 0.0,
    support: float = 0.0,
    pressure: float = 0.0,
) -> Dict:
    """综合分析并生成操作建议。

    返回结构：
    {
        "has_position": bool,
        "position": {...} | None,       # 有持仓时返回
        "pnl": {...} | None,            # 盈亏计算
        "advice": str,                   # 操作建议（持有/加仓/减仓/观望）
        "signal": str,                   # 信号（做多/做空/中性）
        "reason": [...],                 # 理由列表
        "risk": str,                     # 风险等级（高/中/低）
        "summary": str,                  # 一句话总结
    }
    """
    pos = get_position(stock_code)
    has_position = pos is not None

    advice = "观望"
    signal = "中性"
    reason = []
    risk = "中"
    summary = ""

    if has_position:
        volume = pos["volume"]
        avg_cost = pos["avg_cost"]
        pnl = calc_pnl(volume, avg_cost, current_price)

        # === 持仓分析 ===
        pnl_pct = pnl["pnl_pct"]
        per_share = pnl["per_share"]

        # 盈亏状态
        if pnl_pct > 0:
            reason.append(f"持仓盈利 +{pnl_pct:.1f}%（{pnl['pnl']:.0f}元）")
        else:
            reason.append(f"持仓亏损 {pnl_pct:.1f}%（{pnl['pnl']:.0f}元）")

        # 成本附近判断
        distance_from_cost = abs(current_price - avg_cost) / avg_cost * 100
        if distance_from_cost < 1:
            reason.append(f"当前价与成本价接近（差距{distance_from_cost:.1f}%）")

        # === 操作建议逻辑 ===
        # 上涨概率高 + 持仓盈利/成本附近 → 持有/加仓
        # 上涨概率低 + 持仓盈利 → 考虑减仓
        # 上涨概率低 + 持仓亏损 → 持有等反弹/止损
        # 超买区域 + 任何情况 → 谨慎

        if pred_up_prob >= 0.75:
            if pnl_pct > 5:
                advice = "持有 + 逢低加仓"
                signal = "做多"
                risk = "中"
                reason.append(f"预测上涨概率{pred_up_prob:.0%}，均线多头，可继续持有")
            elif pnl_pct > 0:
                advice = "持有"
                signal = "做多"
                risk = "低"
                reason.append(f"预测上涨概率{pred_up_prob:.0%}，持仓微盈，持有待涨")
            else:
                advice = "持有 + 逢低加仓"
                signal = "做多"
                risk = "中"
                reason.append(f"预测上涨概率{pred_up_prob:.0%}，持仓浮亏，建议逢低补仓摊薄成本")

        elif pred_up_prob >= 0.55:
            if pnl_pct > 3:
                advice = "持有"
                signal = "中性偏多"
                risk = "低"
                reason.append(f"预测上涨概率{pred_up_prob:.0%}，持仓盈利，可继续持有")
            elif pnl_pct > 0:
                advice = "持有"
                signal = "中性"
                risk = "低"
            else:
                advice = "观望"
                signal = "中性"
                risk = "中"
                reason.append("预测方向不明，持仓浮亏，暂不操作")

        elif pred_up_prob < 0.40:
            if pnl_pct > 5:
                advice = "考虑减仓"
                signal = "做空"
                risk = "高"
                reason.append(f"预测上涨概率仅{pred_up_prob:.0%}，持仓大盈，建议减仓锁定利润")
            elif pnl_pct > 0:
                advice = "持有观察"
                signal = "中性偏空"
                risk = "中"
                reason.append(f"预测上涨概率低{pred_up_prob:.0%}，持仓微盈，关注跌破支撑")
            else:
                advice = "止损参考"
                signal = "做空"
                risk = "高"
                reason.append(f"预测下跌概率高，持仓浮亏，关注{support:.0f}元支撑，跌破考虑止损")

        else:
            advice = "观望"
            signal = "中性"
            risk = "中"

        # === 风险提示叠加 ===
        if rsi > 75:
            reason.append(f"⚠️ RSI={rsi:.0f} 严重超买，注意回调风险")
            risk = "高"
        elif rsi > 68:
            reason.append(f"⚠️ RSI={rsi:.0f} 偏强但未超买，谨慎追高")
            if risk == "低":
                risk = "中"

        if bollinger_pos > 0.9:
            reason.append("⚠️ 布林带上轨，注意回落风险")
        elif bollinger_pos < 0.1:
            reason.append("⚠️ 布林带下轨超卖，关注反弹机会")

        if fund_flow_net < -50000:
            reason.append(f"⚠️ 主力净流出{fund_flow_net/10000:.0f}万，谨慎")
        elif fund_flow_net > 50000:
            reason.append(f"✓ 主力强势净流入{fund_flow_net/10000:.0f}万，支撑强")

        # 支撑/压力
        if support > 0 and current_price < support * 1.05:
            reason.append(f"📍 支撑位 {support:.0f}元，密切关注")
        if pressure > 0 and current_price > pressure * 0.95:
            reason.append(f"📍 压力位 {pressure:.0f}元，突破后可看高一线")

        # 一句话总结
        if advice.startswith("持有"):
            summary = f"建议【{advice}】，{'盈利' if pnl_pct > 0 else '亏损'}{abs(pnl_pct):.1f}%，{signal}"
        else:
            summary = f"建议【{advice}】，{signal}，风险{risk}"

        return {
            "has_position": True,
            "position": {**pos, **pnl},
            "pnl": pnl,
            "advice": advice,
            "signal": signal,
            "reason": reason,
            "risk": risk,
            "summary": summary,
        }

    else:
        # === 无持仓分析 ===
        if pred_up_prob >= 0.75 and pred_confidence in ("高", "中"):
            advice = "关注"
            signal = "做多"
            risk = "中"
            reason.append(f"预测上涨概率{pred_up_prob:.0%}（{pred_confidence}置信度），值得关注")
            if rsi < 60:
                reason.append(f"RSI={rsi:.0f} 未超买，有上涨空间")
            if fund_flow_net > 30000:
                reason.append(f"✓ 主力净流入{fund_flow_net/10000:.0f}万，强势信号")
            summary = f"暂无持仓，预测看涨（{pred_up_prob:.0%}），{'可关注' if advice == '关注' else advice}"
        elif pred_up_prob < 0.40:
            advice = "观望"
            signal = "做空"
            risk = "高"
            reason.append(f"预测上涨概率仅{pred_up_prob:.0%}，方向偏空，暂不入场")
            summary = "暂无持仓，预测方向不乐观，观望为主"
        else:
            advice = "观望"
            signal = "中性"
            risk = "中"
            reason.append(f"预测上涨概率{pred_up_prob:.0%}，方向不明，继续等待")
            summary = "暂无持仓，方向不明，观望"

        if rsi > 70:
            reason.append(f"⚠️ RSI={rsi:.0f} 已超买，当前不适合买入")
            risk = "高"
            summary += "（RSI超买，谨慎）"

        return {
            "has_position": False,
            "position": None,
            "pnl": None,
            "advice": advice,
            "signal": signal,
            "reason": reason,
            "risk": risk,
            "summary": summary,
        }


def format_position_advice(result: Dict, stock_code: str, current_price: float) -> str:
    """格式化持仓建议为可读字符串。"""
    lines = []
    lines.append(f"{'═' * 54}")
    lines.append(f"  持仓建议  {stock_code}")
    lines.append(f"{'═' * 54}")

    if result["has_position"]:
        pnl = result["pnl"]
        pos = result["position"]
        lines.append(f"  持仓      {pos['volume']:.0f} 股 @ {pos['avg_cost']:.2f} 元")
        pnl_emoji = "📈" if pnl["pnl"] >= 0 else "📉"
        lines.append(f"  盈亏      {pnl_emoji} {pnl['pnl']:+.0f} 元（{pnl['pnl_pct']:+.1f}%）")
        lines.append(f"  当前价    {current_price} 元（{'盈利' if pnl['per_share'] > 0 else '亏损'}{abs(pnl['per_share']):.2f}元/股）")
        lines.append(f"{'─' * 54}")

    # 建议
    advice_color = {
        "持有 + 逢低加仓": "🟢",
        "持有": "🟢",
        "持有观察": "🟡",
        "考虑减仓": "🔴",
        "止损参考": "🔴",
        "观望": "⚪",
        "关注": "🟢",
    }.get(result["advice"], "⚪")

    lines.append(f"  操作建议  {advice_color} {result['advice']}")
    lines.append(f"  信号      {result['signal']}  风险 {result['risk']}")
    lines.append(f"{'─' * 54}")

    for r in result["reason"]:
        lines.append(f"  • {r}")

    lines.append(f"{'─' * 54}")
    lines.append(f"  总结      {result['summary']}")
    lines.append(f"{'═' * 54}")
    return "\n".join(lines)
