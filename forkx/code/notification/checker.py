"""提醒触发检查器。"""
from datetime import date
from typing import Dict, List

from ..data.tencent_provider import TencentProvider
from ..data.sina_provider import SinaProvider
from ..notification.alert_store import list_alerts
from ..screening.game_analyzer import (
    detect_consolidation, classify_intraday_pattern,
    analyze_order_pressure, detect_volume_anomaly,
)
from ..screening.fund_flow_provider import _get_today_minute_flow


def check_alerts() -> Dict:
    """检查所有启用提醒，返回触发的提醒列表。

    提醒类型：
    - price_below: 当前价跌破阈值
    - price_above: 当前价突破阈值
    - rsi_overbought: RSI > 70
    - rsi_oversold: RSI < 30
    - volume_surge: 量比 > 2
    """
    alerts = list_alerts(enabled_only=True)
    if not alerts:
        return {"triggered": [], "checked": 0}

    # 收集所有涉及股票
    codes = list({a.stock_code for a in alerts})
    rt_data = TencentProvider().get_realtime(codes)

    # K线数据（取最近30天算RSI/量比）
    end = date.today()
    start = date(end.year - 1, end.month, end.day)
    quotes_map = {}
    for code in codes:
        try:
            quotes = SinaProvider().get_daily_quotes(code, start, end)
            quotes_map[code] = quotes[-30:] if len(quotes) > 30 else quotes
        except Exception:
            quotes_map[code] = []

    # 指标计算
    def calc_rsi(closes: List[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def calc_vol_ratio(volumes: List[float]) -> float:
        if len(volumes) < 5:
            return 1.0
        avg_vol = sum(volumes[-5:-1]) / 4
        if avg_vol == 0:
            return 1.0
        return volumes[-1] / avg_vol

    triggered = []
    checked = 0

    for alert in alerts:
        checked += 1
        code = alert.stock_code
        rt = rt_data.get(code)
        quotes = quotes_map.get(code, [])
        closes = [q.close for q in quotes]
        volumes = [q.volume for q in quotes]

        price = rt.price if rt else None
        rsi = calc_rsi(closes) if len(closes) > 14 else None
        vol_ratio = calc_vol_ratio(volumes) if volumes else 1.0

        fired = False
        reason = ""

        if alert.alert_type == "price_below":
            if price is not None and price <= alert.threshold:
                fired = True
                reason = f"当前价 {price:.2f} ≤ 阈值 {alert.threshold}"

        elif alert.alert_type == "price_above":
            if price is not None and price >= alert.threshold:
                fired = True
                reason = f"当前价 {price:.2f} ≥ 阈值 {alert.threshold}"

        elif alert.alert_type == "rsi_overbought":
            if rsi is not None and rsi > alert.threshold:
                fired = True
                reason = f"RSI {rsi:.1f} > {alert.threshold}（超买）"

        elif alert.alert_type == "rsi_oversold":
            if rsi is not None and rsi < alert.threshold:
                fired = True
                reason = f"RSI {rsi:.1f} < {alert.threshold}（超卖）"

        elif alert.alert_type == "volume_surge":
            if vol_ratio > alert.threshold:
                fired = True
                reason = f"量比 {vol_ratio:.2f}x > {alert.threshold}x（放量）"

        # ── 博弈信号 ───────────────────────────────────────────────────────
        elif alert.alert_type == "consolidation_break":
            # 横盘突破：当前处于横盘，且今日涨幅超过阈值
            consolidation = detect_consolidation(quotes)
            if consolidation.consolidation_days >= 5 and price is not None and rt is not None:
                prev_close = rt.prev_close
                today_chg = (price - prev_close) / prev_close * 100 if prev_close else 0
                if today_chg >= alert.threshold:
                    fired = True
                    reason = f"横盘{consolidation.consolidation_days}日后突破 +向上{today_chg:.2f}%"

        elif alert.alert_type == "tail_swing":
            # 尾盘偷袭：今日分时形态为尾盘偷袭
            from ..data.sina_provider import SinaProvider
            import os
            os.environ.pop('http_proxy', None); os.environ.pop('https_proxy', None)
            today_min = SinaProvider().get_minute_quotes(code)
            if today_min:
                pattern = classify_intraday_pattern(code, today_min)
                if pattern.pattern_type == "尾盘偷袭":
                    fired = True
                    reason = f"分时出现尾盘偷袭（{pattern.interpretation[:40]}）"

        elif alert.alert_type == "main_inflow_surge":
            # 主力大幅净买入：efinance今日主力净流入 > 阈值（万元）
            today_rec = _get_today_minute_flow(code)
            if today_rec and today_rec.main_net_wan >= alert.threshold:
                fired = True
                reason = f"主力净流入 {today_rec.main_net_wan:.0f}万 > {alert.threshold:.0f}万"

        elif alert.alert_type == "main_inflow_reversal":
            # 资金由卖转买：今日盘中曾净流出，但当前已转为净买入
            today_rec = _get_today_minute_flow(code)
            if today_rec and today_rec.minute_records and len(today_rec.minute_records) >= 10:
                # 取前10分钟和最近10分钟对比
                first_net = sum(r.main_net for r in today_rec.minute_records[:10])
                last_net = sum(r.main_net for r in today_rec.minute_records[-10:])
                if first_net < 0 and last_net > 0:
                    fired = True
                    reason = f"资金由空转多（早盘{first_net/10000:.0f}万 → 尾盘{last_net/10000:.0f}万）"

        elif alert.alert_type == "buy_pressure_surge":
            # 五档买卖比飙升
            if rt is not None:
                bid_total = sum(float(v) for k, v in rt.__dict__.items() if k.startswith('bid')) if hasattr(rt, '__dict__') else 0
                ask_total = sum(float(v) for k, v in rt.__dict__.items() if k.startswith('ask')) if hasattr(rt, '__dict__') else 0
                if ask_total > 0:
                    ratio = bid_total / ask_total
                    if ratio >= alert.threshold:
                        fired = True
                        reason = f"买卖比 {ratio:.1f} ≥ {alert.threshold}（买盘主导）"

        elif alert.alert_type == "volume_anomaly":
            # 量价异动：检测到非"无异动"的异常
            vol_anomaly = detect_volume_anomaly(quotes)
            if vol_anomaly.anomaly_type != "无异动" and vol_anomaly.quality != "正常":
                fired = True
                reason = f"量价异动：{vol_anomaly.anomaly_type}（{vol_anomaly.quality}）"

        if fired:
            triggered.append({
                "alert_id": alert.id,
                "stock_code": code,
                "name": rt.name if rt else code,
                "type": alert.alert_type,
                "threshold": alert.threshold,
                "reason": reason,
                "note": alert.note,
                "price": price,
            })

    return {"triggered": triggered, "checked": checked}


def format_alert_check(result: Dict) -> str:
    triggered = result["triggered"]
    checked = result["checked"]

    if not triggered:
        return f"已检查 {checked} 条提醒，无触发"

    lines = [f"⚠️  触发提醒（共 {len(triggered)} 条）："]
    for t in triggered:
        lines.append(f"  [{t['alert_id']}] {t['name']}（{t['stock_code']}）")
        lines.append(f"    {t['reason']}")
        if t["note"]:
            lines.append(f"    备注：{t['note']}")

    return "\n".join(lines)
