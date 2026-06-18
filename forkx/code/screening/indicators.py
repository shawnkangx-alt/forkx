"""技术面指标计算。所有函数为纯函数。"""
from typing import Dict, List, Tuple

from ..data.models import DailyQuote


# ===== 均线 =====
def calc_ma(closes: List[float], period: int) -> List[float]:
    if len(closes) < period:
        return [0.0] * len(closes)
    result = [0.0] * (period - 1)
    window_sum = sum(closes[:period])
    result.append(round(window_sum / period, 4))
    for i in range(period, len(closes)):
        window_sum += closes[i] - closes[i - period]
        result.append(round(window_sum / period, 4))
    return result


def ma_status(quotes: List[DailyQuote]) -> Dict:
    """均线状态分析。"""
    closes = [q.close for q in quotes]
    if len(closes) < 20:
        return {"status": "数据不足", "alignment": "unknown"}

    ma5 = calc_ma(closes, 5)
    ma20 = calc_ma(closes, 20)
    ma60 = calc_ma(closes, 60) if len(closes) >= 60 else None

    latest = len(closes) - 1
    p = latest

    # 多空排列
    if ma60:
        if ma5[-1] > ma20[-1] > ma60[-1]:
            alignment = "多头排列"
        elif ma5[-1] < ma20[-1] < ma60[-1]:
            alignment = "空头排列"
        else:
            alignment = "混乱排列"
    else:
        if ma5[-1] > ma20[-1]:
            alignment = "短多"
        elif ma5[-1] < ma20[-1]:
            alignment = "短空"
        else:
            alignment = "纠缠"

    # 金叉死叉检测
    cross = "无信号"
    if p >= 1:
        if ma5[p-1] <= ma20[p-1] and ma5[p] > ma20[p]:
            cross = "金叉"
        elif ma5[p-1] >= ma20[p-1] and ma5[p] < ma20[p]:
            cross = "死叉"

    return {
        "alignment": alignment,
        "cross": cross,
        "ma5": round(ma5[-1], 2),
        "ma20": round(ma20[-1], 2),
        "ma60": round(ma60[-1], 2) if ma60 else None,
    }


# ===== RSI =====
def calc_rsi(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) < period + 1:
        return [0.0] * len(closes)
    result = [0.0] * period
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(diff if diff > 0 else 0.0)
        losses.append(abs(diff) if diff < 0 else 0.0)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
    result.append(round(100.0 - 100.0 / (1 + rs), 2))
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = diff if diff > 0 else 0.0
        loss = abs(diff) if diff < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        result.append(round(100.0 - 100.0 / (1 + rs), 2))
    return result


def rsi_zone(rsi: float) -> str:
    """RSI区间判断。"""
    if rsi > 70:
        return "超买"
    elif rsi < 30:
        return "超卖"
    elif rsi > 60:
        return "偏强"
    elif rsi < 40:
        return "偏弱"
    return "中性"


# ===== MACD =====
def _ema(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return [0.0] * len(values)
    multiplier = 2.0 / (period + 1)
    result = [0.0] * (period - 1)
    start = sum(values[:period]) / period
    ema_vals = [start]
    for v in values[period:]:
        ema_vals.append((v - ema_vals[-1]) * multiplier + ema_vals[-1])
    result.extend(round(e, 4) for e in ema_vals)
    return result


def calc_macd(closes: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, List[float]]:
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [0.0] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] != 0 and ema_slow[i] != 0:
            dif[i] = round(ema_fast[i] - ema_slow[i], 4)
    dea = _ema(dif[max(slow - 1, 0):], signal)
    dea_full = [0.0] * (len(closes) - len(dea)) + dea
    macd = [0.0] * len(closes)
    for i in range(len(closes)):
        macd[i] = round((dif[i] - dea_full[i]) * 2, 4) if dif[i] != 0 else 0.0
    return {"dif": dif, "dea": dea_full, "macd": macd}


def macd_signal(macd_data: Dict[str, List[float]]) -> str:
    dif = macd_data["dif"]
    dea = macd_data["dea"]
    macd = macd_data["macd"]
    # 找最近非零点
    for i in range(len(dif) - 1, -1, -1):
        if dif[i] == 0:
            continue
        if i == 0:
            return "横盘"
        # 金叉死叉判断
        if macd[i] > 0 and macd[i-1] <= 0:
            return "MACD金叉"
        if macd[i] < 0 and macd[i-1] >= 0:
            return "MACD死叉"
        # 柱状方向
        if macd[i] > macd[i-1]:
            return "MACD柱扩大"
        return "MACD柱收缩"


# ===== KDJ =====
def calc_kdj(quotes: List[DailyQuote], n: int = 9, m1: int = 3, m2: int = 3) -> Dict[str, List[float]]:
    closes = [q.close for q in quotes]
    highs = [q.high for q in quotes]
    lows = [q.low for q in quotes]
    k = [50.0] * len(closes)
    d = [50.0] * len(closes)
    j = [50.0] * len(closes)
    for i in range(n - 1, len(closes)):
        low_n = min(lows[i - n + 1:i + 1])
        high_n = max(highs[i - n + 1:i + 1])
        rsv = (closes[i] - low_n) / (high_n - low_n) * 100 if high_n != low_n else 50
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k[i]
        j[i] = 3 * k[i] - 2 * d[i]
    return {"k": k, "d": d, "j": j}


def kdj_status(kdj: Dict[str, List[float]]) -> str:
    k = kdj["k"]
    d = kdj["d"]
    j = kdj["j"]
    for i in range(len(k) - 1, -1, -1):
        if k[i] == 0:
            continue
        if i == 0:
            return "数据不足"
        if k[i] > 80 or j[i] > 100:
            zone = "超买"
        elif k[i] < 20 or j[i] < 0:
            zone = "超卖"
        else:
            zone = "中性"
        if k[i] > d[i] and k[i-1] <= d[i-1]:
            return f"{zone}（金叉）"
        if k[i] < d[i] and k[i-1] >= d[i-1]:
            return f"{zone}（死叉）"
        return zone


# ===== 布林带 =====
def calc_bollinger(closes: List[float], period: int = 20, std_mult: float = 2.0) -> Dict[str, List[float]]:
    result_upper, result_middle, result_lower = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            result_upper.append(0.0)
            result_middle.append(0.0)
            result_lower.append(0.0)
        else:
            window = closes[i - period + 1:i + 1]
            mid = sum(window) / period
            std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
            result_middle.append(round(mid, 4))
            result_upper.append(round(mid + std_mult * std, 4))
            result_lower.append(round(mid - std_mult * std, 4))
    return {"upper": result_upper, "middle": result_middle, "lower": result_lower}


def bollinger_zone(quotes: List[DailyQuote]) -> Dict:
    closes = [q.close for q in quotes]
    if len(closes) < 20:
        return {"zone": "数据不足"}
    b = calc_bollinger(closes)
    latest = len(closes) - 1
    price = closes[latest]
    upper, middle, lower = b["upper"][latest], b["middle"][latest], b["lower"][latest]
    if upper == 0:
        return {"zone": "数据不足"}
    pct = (price - lower) / (upper - lower) * 100 if upper != lower else 50
    if pct > 80:
        zone = "靠近上轨（偏贵）"
    elif pct < 20:
        zone = "靠近下轨（偏宜）"
    else:
        zone = "中轨附近"
    return {
        "zone": zone,
        "upper": round(upper, 2),
        "middle": round(middle, 2),
        "lower": round(lower, 2),
        "pct": round(pct, 1),
        "price": round(price, 2),
    }


# ===== 支撑/压力位 =====
def find_support_resistance(quotes: List[DailyQuote], lookback: int = 60) -> Dict:
    """简单支撑/压力位识别。"""
    if len(quotes) < 10:
        return {"support": None, "resistance": None}
    recent = quotes[-lookback:] if len(quotes) > lookback else quotes
    highs = [q.high for q in recent]
    lows = [q.low for q in recent]
    closes = [q.close for q in recent]
    current = closes[-1]
    # 近期高低点
    resistance = round(max(highs[:-1]), 2) if highs else None
    support = round(min(lows[:-1]), 2) if lows else None
    return {"support": support, "resistance": resistance, "current": round(current, 2)}


# ===== 量比 =====
def calc_volume_ratio(quotes: List[DailyQuote], period: int = 20) -> float:
    if len(quotes) < period + 1:
        return 1.0
    recent_vol = [q.volume for q in quotes[-period:]]
    avg_vol = sum(recent_vol) / len(recent_vol)
    today_vol = quotes[-1].volume
    return round(today_vol / avg_vol, 2) if avg_vol > 0 else 1.0
