"""简单均线交叉回测引擎。"""
from datetime import date
from typing import Dict, List

from ..data.models import DailyQuote
from ..screening.indicators import calc_ma


def backtest_ma_cross(
    quotes: List[DailyQuote],
    fast_period: int,
    slow_period: int,
) -> Dict:
    """均线交叉回测。

    策略规则：
    - 金叉（MA_fast上穿MA_slow）：买入
    - 死叉（MA_fast下穿MA_slow）：卖出
    - 初始资金：10万元
    """
    if len(quotes) < slow_period + 5:
        return {"error": "数据不足，无法回测"}

    closes = [q.close for q in quotes]
    ma_fast = calc_ma(closes, fast_period)
    ma_slow = calc_ma(closes, slow_period)

    initial_cash = 100000.0
    cash = initial_cash
    position = 0.0  # 持股数量
    shares = 0
    trades = []  # 记录交易
    capital_curve = [initial_cash]
    buy_hold_return = 0.0

    # 买入持有收益
    first_price = closes[slow_period]
    last_price = closes[-1]
    buy_hold_return = (last_price - first_price) / first_price * 100

    in_position = False
    buy_price = 0.0

    for i in range(slow_period, len(closes)):
        # 金叉
        if ma_fast[i] > ma_slow[i] and ma_fast[i-1] <= ma_slow[i-1] and not in_position:
            price = closes[i]
            shares = int(cash / price / 100) * 100  # 按手买
            if shares > 0:
                cost = shares * price
                cash -= cost
                position = shares
                in_position = True
                buy_price = price
                trades.append({"action": "buy", "date": quotes[i].date, "price": price, "shares": shares})

        # 死叉
        elif ma_fast[i] < ma_slow[i] and ma_fast[i-1] >= ma_slow[i-1] and in_position:
            price = closes[i]
            proceeds = position * price
            cash += proceeds
            ret = (price - buy_price) / buy_price * 100
            trades.append({"action": "sell", "date": quotes[i].date, "price": price, "shares": position, "return": ret})
            position = 0
            in_position = False

        # 记录资金曲线（按收盘价计算）
        if in_position:
            capital_curve.append(cash + position * closes[i])
        else:
            capital_curve.append(cash)

    # 最后如果还持有，按最后价格平仓
    final_value = cash
    if in_position:
        final_value += position * last_price
        ret = (last_price - buy_price) / buy_price * 100
        trades.append({"action": "sell", "date": quotes[-1].date, "price": last_price, "shares": position, "return": ret})

    strategy_return = (final_value - initial_cash) / initial_cash * 100

    # 计算最大回撤
    max_value = capital_curve[0]
    max_drawdown = 0.0
    for v in capital_curve:
        if v > max_value:
            max_value = v
        dd = (max_value - v) / max_value * 100
        if dd > max_drawdown:
            max_drawdown = dd

    # 胜率
    sell_trades = [t for t in trades if t["action"] == "sell"]
    wins = len([t for t in sell_trades if t.get("return", 0) > 0])
    win_rate = wins / len(sell_trades) * 100 if sell_trades else 0

    return {
        "strategy_return": round(strategy_return, 2),
        "buy_hold_return": round(buy_hold_return, 2),
        "excess_return": round(strategy_return - buy_hold_return, 2),
        "total_trades": len(trades),
        "buy_count": len([t for t in trades if t["action"] == "buy"]),
        "sell_count": len(sell_trades),
        "win_rate": round(win_rate, 1),
        "max_drawdown": round(max_drawdown, 2),
        "final_value": round(final_value, 2),
        "initial_cash": initial_cash,
        "trades": trades,
        "capital_curve": capital_curve,
        "dates": [q.date for q in quotes[slow_period:]],
    }


def format_backtest(result: Dict) -> str:
    if "error" in result:
        return f"回测失败: {result['error']}"

    lines = [
        "=" * 50,
        "  均线交叉回测报告",
        "=" * 50,
        "",
        f"初始资金：{result['initial_cash']:.2f} 元",
        f"最终价值：{result['final_value']:.2f} 元",
        "",
        f"策略收益：{result['strategy_return']:+.2f}%",
        f"买入持有：{result['buy_hold_return']:+.2f}%",
        f"超额收益：{result['excess_return']:+.2f}%",
        "",
        f"交易次数：{result['total_trades']} 次（买{result['buy_count']}/卖{result['sell_count']}）",
        f"胜率：{result['win_rate']:.1f}%",
        f"最大回撤：{result['max_drawdown']:.2f}%",
    ]

    # 最近5笔交易
    recent = result["trades"][-5:]
    if recent:
        lines.append("")
        lines.append("最近交易：")
        for t in recent:
            if t["action"] == "buy":
                lines.append(f"  {t['date']} 买入 {t['shares']}股 @{t['price']:.2f}")
            else:
                lines.append(f"  {t['date']} 卖出 {t['shares']}股 @{t['price']:.2f}  收益率{t.get('return', 0):+.2f}%")

    # 资金曲线（每隔N期取一个点，控制宽度）
    curve = result.get("capital_curve", [])
    dates = result.get("dates", [])
    if curve and dates:
        # 每隔 max(1, len(curve)//20) 期取一个点，最多20个点
        step = max(1, len(curve) // 20)
        # dates 长度 = curve 长度 - 1（dates从第0期开始，curve从初始资金开始）
        points = []
        for i in range(0, len(curve) - 1, step):  # -1 因为curve比dates多一个初始资金
            points.append((dates[i].strftime('%m-%d') if hasattr(dates[i], 'strftime') else str(dates[i]), curve[i]))
        # 最后一期必含
        last_date_str = dates[-1].strftime('%m-%d') if hasattr(dates[-1], 'strftime') else str(dates[-1])
        if points[-1][0] != last_date_str:
            points.append((last_date_str, curve[-1]))

        max_val = max(curve)
        min_val = min(curve)
        val_range = max_val - min_val if max_val != min_val else 1

        lines.append("")
        lines.append("资金曲线：")
        # 打印时间+资金值+迷你柱状图
        for date_str, val in points:
            bar_len = int((val - min_val) / val_range * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"  {date_str}  {val:>10.0f}  {bar}")

    lines.append("=" * 50)
    return "\n".join(lines)
