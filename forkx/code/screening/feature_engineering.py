"""技术指标计算器。

提供丰富的技术指标特征，供预测模型使用。
"""
from typing import List, Dict, Optional, Tuple
from ..data.sina_provider import SinaProvider
from ..data.tencent_provider import TencentProvider
from ..data.models import DailyQuote
from datetime import date, timedelta
import sqlite3
from pathlib import Path


def calc_rsi(prices: List[float], period: int = 14) -> List[float]:
    """RSI计算。"""
    if len(prices) < period + 1:
        return []
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_list = []
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_list.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_list.append(100 - 100 / (1 + rs))
    return rsi_list


def calc_ema(prices: List[float], period: int) -> List[float]:
    """EMA计算。"""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for p in prices[period:]:
        ema.append(p * k + ema[-1] * (1 - k))
    return ema


def calc_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[float], List[float], List[float]]:
    """MACD计算。返回 (macd_line, signal_line, hist)。"""
    if len(prices) < slow + signal:
        return [], [], []
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)
    if len(ema_fast) != len(ema_slow):
        min_len = min(len(ema_fast), len(ema_slow))
        ema_fast = ema_fast[-min_len:]
        ema_slow = ema_slow[-min_len:]
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = calc_ema(macd_line, signal)
    # Histogram 需要对齐
    offset = len(macd_line) - len(signal_line)
    hist = []
    for i in range(len(signal_line)):
        idx = offset + i
        hist.append(macd_line[idx] - signal_line[i])
    return macd_line, signal_line, hist


def calc_bollinger(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
    """布林带计算。返回 (upper, middle, lower)。"""
    if len(prices) < period:
        return [], [], []
    result = []
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1:i + 1]
        mid = sum(window) / period
        variance = sum((p - mid) ** 2 for p in window) / period
        std = variance ** 0.5
        result.append((mid + std_dev * std, mid, mid - std_dev * std))
    return [r[0] for r in result], [r[1] for r in result], [r[2] for r in result]


def calc_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """ATR计算。"""
    if len(highs) < 2:
        return []
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i-1]),
            abs(lows[i] - closes[i-1])
        )
        trs.append(tr)
    if len(trs) < period:
        return []
    atr = [sum(trs[:period]) / period]
    for i in range(period, len(trs)):
        atr.append((atr[-1] * (period - 1) + trs[i]) / period)
    return atr


def calc_obv(closes: List[float], volumes: List[float]) -> List[float]:
    """OBV计算。"""
    if len(closes) < 2:
        return []
    obv = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            obv.append(obv[-1] + volumes[i])
        elif closes[i] < closes[i-1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    return obv


def calc_momentum(prices: List[float], period: int = 10) -> List[float]:
    """动量指标。"""
    if len(prices) < period + 1:
        return []
    return [prices[i] - prices[i - period] for i in range(period, len(prices))]


def calc_volume_ratio(volumes: List[float], period: int = 5) -> List[float]:
    """量比。"""
    if len(volumes) < period + 1:
        return [1.0]
    avg = sum(volumes[-period:]) / period
    return [volumes[-1] / avg if avg > 0 else 1.0]


def detect_rsi_divergence(rsi_vals: List[float], prices: List[float]) -> str:
    """RSI背离检测。"""
    if len(rsi_vals) < 10 or len(prices) < 10:
        return ""
    # 看最近N个低点是否创新低但RSI没有
    lookback = 10
    price_trend = prices[-1] - prices[-lookback]
    rsi_trend = rsi_vals[-1] - rsi_vals[-lookback]
    if price_trend < -2 and rsi_trend > 5:
        return "底背离"
    if price_trend > 2 and rsi_trend < -5:
        return "顶背离"
    return ""


def detect_ma_cross(ma5: List[float], ma10: List[float], ma20: List[float]) -> str:
    """均线交叉检测。"""
    if len(ma5) < 2 or len(ma10) < 2:
        return ""
    # 金叉：MA5上穿MA10
    if ma5[-2] <= ma10[-2] and ma5[-1] > ma10[-1]:
        return "MA5金叉MA10"
    # 死叉：MA5下穿MA10
    if ma5[-2] >= ma10[-2] and ma5[-1] < ma10[-1]:
        return "MA5死叉MA10"
    # 多头排列
    if ma5[-1] > ma10[-1] > ma20[-1]:
        return "多头排列"
    if ma5[-1] < ma10[-1] < ma20[-1]:
        return "空头排列"
    return ""


def detect_volume_price_divergence(volumes: List[float], prices: List[float]) -> str:
    """量价背离。"""
    if len(volumes) < 5 or len(prices) < 5:
        return ""
    vol_trend = volumes[-1] - volumes[-5]
    price_trend = prices[-1] - prices[-5]
    if vol_trend > 0 and price_trend < 0:
        return "放量下跌"
    if vol_trend < 0 and price_trend > 0:
        return "缩量上涨"
    if vol_trend > 0 and price_trend > 0:
        return "量价齐升"
    if vol_trend < 0 and price_trend < 0:
        return "量价齐跌"
    return ""


def calc_support_resistance(prices: List[float], period: int = 20) -> Tuple[float, float]:
    """支撑位和压力位（最近period高点/低点）。"""
    if len(prices) < period:
        return prices[-1], prices[-1]
    window = prices[-period:]
    return min(window), max(window)


def calc_consecutive_days(prices: List[float]) -> Tuple[int, int]:
    """连续上涨/下跌天数。"""
    if len(prices) < 2:
        return 0, 0
    up_days = 0
    down_days = 0
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] > prices[i-1]:
            up_days += 1
        elif prices[i] < prices[i-1]:
            down_days += 1
        else:
            break
    return up_days, down_days


def calc_near_high_low(prices: List[float], period: int = 20) -> Tuple[float, float]:
    """距离区间高点的百分比，距离区间低点的百分比。"""
    if len(prices) < period:
        return 0.0, 0.0
    window = prices[-period:]
    high = max(window)
    low = min(window)
    current = prices[-1]
    near_high = (current / high - 1) * 100 if high > 0 else 0
    near_low = (1 - current / low) * 100 if low > 0 else 0
    return near_high, near_low


def calc_amplitude(prices: List[float]) -> float:
    """当日振幅。"""
    if len(prices) < 2:
        return 0.0
    return (max(prices) - min(prices)) / prices[0] * 100


def calc_relative_strength(prices: List[float], market_prices: List[float]) -> float:
    """相对大盘强弱（正=强于大盘）。"""
    if len(prices) < 2 or len(market_prices) < 2:
        return 0.0
    stock_ret = (prices[-1] - prices[-2]) / prices[-2]
    market_ret = (market_prices[-1] - market_prices[-2]) / market_prices[-2]
    return (stock_ret - market_ret) * 100


def get_market_index(code: str = "sh000001") -> List[float]:
    """获取大盘指数历史收盘价（上证指数）。"""
    try:
        provider = SinaProvider()
        today = date.today()
        start = today - timedelta(days=120)
        quotes = provider.get_daily_quotes(code, start, today)
        return [q.close for q in quotes]
    except Exception:
        return []


def calc_all_features(stock_code: str, quotes: List[DailyQuote]) -> dict:
    """计算单只股票的完整特征集（40+维）。

    包含：
    - 趋势类（MA5/10/20排列、交叉、乖离率）
    - 动量类（RSI、MACD、动量）
    - 资金类（OBV、资金流）
    - 波动类（布林带、ATR、振幅）
    - 位置类（距高低点、连续涨跌）
    - 形态类（量价背离、RSI背离）
    - 大盘类（相对强弱）
    """
    f = {}

    if len(quotes) < 20:
        return f

    closes = [q.close for q in quotes]
    highs = [q.high for q in quotes]
    lows = [q.low for q in quotes]
    volumes = [q.volume for q in quotes]
    changes = [(closes[i] - closes[i-1]) / closes[i-1] * 100 if i > 0 else 0 for i in range(len(closes))]

    # === 趋势特征 ===
    # MA
    ma5 = calc_ema(closes, 5)
    ma10 = calc_ema(closes, 10)
    ma20 = calc_ema(closes, 20)
    ma60 = calc_ema(closes, 60) if len(closes) >= 60 else []

    if len(ma5) >= 2:
        f["ma5_above_ma10"] = 1 if ma5[-1] > ma10[-1] else 0
        f["ma5_above_ma20"] = 1 if ma5[-1] > ma20[-1] else 0
        f["ma10_above_ma20"] = 1 if ma10[-1] > ma20[-1] else 0
        f["ma_bull_alignment"] = 1 if ma5[-1] > ma10[-1] > ma20[-1] else 0
        f["ma_bear_alignment"] = 1 if ma5[-1] < ma10[-1] < ma20[-1] else 0
        f["ma5_slope"] = (ma5[-1] - ma5[-2]) / ma5[-2] * 100 if len(ma5) >= 2 else 0
        f["ma20_slope"] = (ma20[-1] - ma20[-2]) / ma20[-2] * 100 if len(ma20) >= 2 else 0
        # 乖离率
        f["price_ma5_deviation"] = (closes[-1] - ma5[-1]) / ma5[-1] * 100
        f["price_ma20_deviation"] = (closes[-1] - ma20[-1]) / ma20[-1] * 100
    else:
        f.update({k: 0 for k in ["ma5_above_ma10", "ma5_above_ma20", "ma10_above_ma20",
                                   "ma_bull_alignment", "ma_bear_alignment",
                                   "ma5_slope", "ma20_slope", "price_ma5_deviation", "price_ma20_deviation"]})

    # MA交叉
    ma_cross = detect_ma_cross(ma5, ma10, ma20)
    f["ma_golden_cross"] = 1 if "金叉" in ma_cross else 0
    f["ma_death_cross"] = 1 if "死叉" in ma_cross else 0
    f["ma_bullish_arrangement"] = 1 if "多头" in ma_cross else 0
    f["ma_bearish_arrangement"] = 1 if "空头" in ma_cross else 0

    # === RSI特征 ===
    rsi_vals = calc_rsi(closes)
    if rsi_vals:
        f["rsi"] = rsi_vals[-1]
        f["rsi_above_50"] = 1 if rsi_vals[-1] > 50 else 0
        f["rsi_overbought"] = 1 if rsi_vals[-1] > 70 else 0
        f["rsi_oversold"] = 1 if rsi_vals[-1] < 30 else 0
        f["rsi_neutral"] = 1 if 40 <= rsi_vals[-1] <= 60 else 0
        f["rsi_rising"] = 1 if len(rsi_vals) >= 5 and rsi_vals[-1] > rsi_vals[-5] else 0
        # RSI区间
        f["rsi_zone_oversold"] = 1 if rsi_vals[-1] < 30 else 0
        f["rsi_zone_low"] = 1 if 30 <= rsi_vals[-1] < 40 else 0
        f["rsi_zone_mid"] = 1 if 40 <= rsi_vals[-1] <= 60 else 0
        f["rsi_zone_high"] = 1 if 60 < rsi_vals[-1] <= 70 else 0
        f["rsi_zone_overbought"] = 1 if rsi_vals[-1] > 70 else 0
        # RSI背离
        f["rsi_divergence_bottom"] = 1 if detect_rsi_divergence(rsi_vals, closes) == "底背离" else 0
        f["rsi_divergence_top"] = 1 if detect_rsi_divergence(rsi_vals, closes) == "顶背离" else 0
    else:
        f.update({k: 0 for k in ["rsi", "rsi_above_50", "rsi_overbought", "rsi_oversold",
                                   "rsi_neutral", "rsi_rising", "rsi_zone_oversold",
                                   "rsi_zone_low", "rsi_zone_mid", "rsi_zone_high",
                                   "rsi_zone_overbought", "rsi_divergence_bottom", "rsi_divergence_top"]})

    # === MACD特征 ===
    macd_line, signal_line, hist = calc_macd(closes)
    if macd_line and signal_line and hist:
        f["macd_positive"] = 1 if macd_line[-1] > 0 else 0
        f["macd_histogram_positive"] = 1 if hist[-1] > 0 else 0
        f["macd_histogram_increasing"] = 1 if len(hist) >= 2 and hist[-1] > hist[-2] else 0
        f["macd_golden_cross"] = 1 if len(macd_line) >= 2 and macd_line[-2] <= signal_line[-2] and macd_line[-1] > signal_line[-1] else 0
        f["macd_death_cross"] = 1 if len(macd_line) >= 2 and macd_line[-2] >= signal_line[-2] and macd_line[-1] < signal_line[-1] else 0
    else:
        f.update({k: 0 for k in ["macd_positive", "macd_histogram_positive", "macd_histogram_increasing",
                                   "macd_golden_cross", "macd_death_cross"]})

    # === 布林带特征 ===
    bb_upper, bb_mid, bb_lower = calc_bollinger(closes)
    if bb_upper:
        f["bb_position"] = (closes[-1] - bb_lower[-1]) / (bb_upper[-1] - bb_lower[-1]) if bb_upper[-1] != bb_lower[-1] else 0.5
        f["bb_upper_touch"] = 1 if closes[-1] >= bb_upper[-1] * 0.99 else 0
        f["bb_lower_touch"] = 1 if closes[-1] <= bb_lower[-1] * 1.01 else 0
        f["bb_squeeze"] = 1 if (bb_upper[-1] - bb_lower[-1]) / bb_mid[-1] < 0.05 else 0
    else:
        f.update({k: 0.0 for k in ["bb_position", "bb_upper_touch", "bb_lower_touch", "bb_squeeze"]})

    # === ATR特征 ===
    atr_vals = calc_atr(highs, lows, closes)
    if atr_vals and closes[-1]:
        f["atr_ratio"] = atr_vals[-1] / closes[-1] * 100
    else:
        f["atr_ratio"] = 0.0

    # === OBV特征 ===
    obv = calc_obv(closes, volumes)
    if len(obv) >= 2:
        f["obv_rising"] = 1 if obv[-1] > obv[-2] else 0
        f["obv_trend"] = 1 if len(obv) >= 10 and sum(obv[-5:]) > sum(obv[-10:-5]) else 0
    else:
        f.update({k: 0 for k in ["obv_rising", "obv_trend"]})

    # === 动量特征 ===
    momentum = calc_momentum(closes)
    if momentum:
        f["momentum_positive"] = 1 if momentum[-1] > 0 else 0
        f["momentum_accelerating"] = 1 if len(momentum) >= 2 and momentum[-1] > momentum[-2] else 0
        f["momentum_10d"] = momentum[-1]
    else:
        f.update({k: 0 for k in ["momentum_positive", "momentum_accelerating", "momentum_10d"]})

    # === 量能特征 ===
    vol_ratio = calc_volume_ratio(volumes)
    if vol_ratio:
        f["vol_ratio"] = vol_ratio[-1]
        f["vol_ratio_high"] = 1 if vol_ratio[-1] > 1.5 else 0
        f["vol_ratio_low"] = 1 if vol_ratio[-1] < 0.7 else 0
    else:
        f.update({k: 1.0 for k in ["vol_ratio"]})
        f.update({k: 0 for k in ["vol_ratio_high", "vol_ratio_low"]})

    f["volume_5d_avg"] = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else volumes[-1]
    f["volume_today_vs_5d"] = volumes[-1] / f["volume_5d_avg"] if f["volume_5d_avg"] > 0 else 1.0

    # 量价背离
    vol_price_div = detect_volume_price_divergence(volumes, closes)
    f["vp_divergence_up"] = 1 if "放量下跌" in vol_price_div or "缩量上涨" in vol_price_div else 0
    f["vp_divergence_down"] = 1 if "放量下跌" in vol_price_div or "量价齐升" in vol_price_div else 0

    # === 位置特征 ===
    near_high, near_low = calc_near_high_low(closes)
    f["near_period_high"] = near_high
    f["near_period_low"] = near_low
    f["price_amplitude"] = calc_amplitude(closes)

    # 连续涨跌
    up_days, down_days = calc_consecutive_days(closes)
    f["consecutive_up_days"] = up_days
    f["consecutive_down_days"] = down_days

    # 5日/10日/20日收益率
    if len(closes) >= 5:
        f["return_5d"] = (closes[-1] - closes[-5]) / closes[-5] * 100
    else:
        f["return_5d"] = 0.0
    if len(closes) >= 10:
        f["return_10d"] = (closes[-1] - closes[-10]) / closes[-10] * 100
    else:
        f["return_10d"] = 0.0
    if len(closes) >= 20:
        f["return_20d"] = (closes[-1] - closes[-20]) / closes[-20] * 100
    else:
        f["return_20d"] = 0.0

    # === 大盘相对强弱 ===
    market_closes = get_market_index()
    if market_closes and len(market_closes) >= 2:
        f["relative_strength"] = calc_relative_strength(closes, market_closes)
    else:
        f["relative_strength"] = 0.0

    # === 支撑/压力 ===
    support, resistance = calc_support_resistance(closes)
    f["support_distance"] = (closes[-1] - support) / closes[-1] * 100 if closes[-1] > 0 else 0
    f["resistance_distance"] = (resistance - closes[-1]) / closes[-1] * 100 if closes[-1] > 0 else 0

    # === 信号标签特征（兼容原有信号系统）===
    SIGNAL_FEATURES = [
        "趋势强势", "趋势弱势", "趋势反转",
        "RSI超买", "RSI偏强", "RSI中性", "RSI偏弱", "RSI超卖",
        "MACD金叉", "MACD死叉",
        "主力强势吸筹", "主力温和吸筹", "主力派发", "资金由卖转买",
        "横盘向上突破", "横盘向下突破",
        "尾盘偷袭", "放量异动", "缩量整理",
        "竞价试盘", "竞价护盘", "竞价派发",
    ]
    # 从history_store获取最新信号的标签
    try:
        conn = sqlite3.connect(str(Path.home() / ".forkx" / "history.db"))
        row = conn.execute(
            "SELECT signals FROM daily_records WHERE stock_code = ? ORDER BY record_date DESC LIMIT 1",
            (stock_code,)
        ).fetchone()
        conn.close()
        current_signals = json.loads(row[0]) if row and row[0] else []
    except Exception:
        current_signals = []

    for sig in SIGNAL_FEATURES:
        f[f"sig_{sig}"] = 1 if sig in current_signals else 0

    return f


import json  # for signal loading
