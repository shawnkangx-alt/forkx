"""个股次日涨跌预测模型 v2 — 富特征集版。

基于 60+ 维技术特征（趋势/动量/量能/位置/形态/相对强弱），
学习历史模式，预测次日涨跌概率。

特征维度（60+）：
  MA类（9）：ma5_above_ma10/ma20、ma_bull/bear排列、ma5/20斜率、乖离率、金叉死叉
  RSI类（13）：数值、50之上/超买/超卖/中性/上升、5区间、底背离/顶背离
  MACD类（5）：快线正负、histogram方向/递增、金叉/死叉
  布林带类（4）：position、上轨碰触、下轨碰触、收缩
  ATR类（1）：ATR/价格比
  OBV类（2）：上升、趋势
  动量类（3）：方向、加速、10日动量值
  量能类（5）：量比、量比高/低、5日均量对比、量价背离
  位置类（6）：距高低点、振幅、连续涨跌、5/10/20日收益率
  大盘类（1）：相对强弱
  信号类（26）：原始26种信号标签

使用方式：
    pred = predict_next_day('002371')
    print(f"上涨概率: {pred['up_prob']:.0%}")
"""
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .feature_engineering import (
    calc_all_features, calc_rsi, calc_ema, calc_macd, calc_bollinger,
    calc_atr, calc_obv, calc_momentum, calc_volume_ratio,
    detect_rsi_divergence, detect_ma_cross, detect_volume_price_divergence,
    calc_support_resistance, calc_consecutive_days, calc_near_high_low,
    calc_amplitude, calc_relative_strength, get_market_index,
)
from ..data.sina_provider import SinaProvider
from ..data.models import DailyQuote

_DB_PATH = Path.home() / ".forkx" / "history.db"
_TRADE_DB = Path.home() / ".forkx" / "trades.db"
_MIN_RECORDS = 20


# =============================================================================
# 特征构建
# =============================================================================

def _quote_to_dict(q: DailyQuote) -> dict:
    return {
        "date": q.date,
        "open": q.open,
        "high": q.high,
        "low": q.low,
        "close": q.close,
        "volume": q.volume,
        "change_pct": getattr(q, "change_pct", 0.0),
    }


def _build_rich_features(quotes: List[DailyQuote], stock_code: str) -> Tuple[List[dict], List[int]]:
    """为每条历史记录构建富特征集，返回 (features_list, labels)。

    labels：次日涨跌（>0 → 1，<0 → 0）
    """
    if len(quotes) < 25:
        return [], []

    features_list = []
    labels = []

    # 对每条记录，取其之前N天数据计算特征
    lookback = 60  # 用过去60天数据计算特征
    for i in range(lookback, len(quotes) - 1):
        hist_quotes = quotes[i - lookback:i + 1]  # 含当天
        curr = quotes[i]
        next_q = quotes[i + 1]

        # 计算特征
        f = calc_all_features(stock_code, hist_quotes)
        if not f:
            continue

        # 追加基础字段
        f["change_pct_today"] = curr.change_pct if hasattr(curr, "change_pct") else 0.0
        f["volume_today"] = curr.volume

        features_list.append(f)
        labels.append(1 if next_q.close > curr.close else 0)

    return features_list, labels


def _build_current_features(stock_code: str, quotes: List[DailyQuote]) -> dict:
    """为最新一天构建特征。"""
    if len(quotes) < 25:
        return {}
    lookback = 60
    return calc_all_features(stock_code, quotes[-lookback:])


# =============================================================================
# 朴素贝叶斯预测（打分制）
# =============================================================================

def _bayesian_predict(
    features_list: List[dict],
    labels: List[int],
    current_f: dict,
) -> Dict:
    """贝叶斯打分预测 v2。

    对每个特征（布尔），计算 P(up|feature=1) 和 P(up|feature=0)。
    用 odds ratio 累加：
      当前有这个特征 → 加上 (p_up_given_1 - 0.5)
      当前没有这个特征 → 加上 (p_up_given_0 - 0.5)
    最终用 sigmoid 压缩到 [0.05, 0.95]。
    """
    n = len(labels)
    if n == 0:
        return _default_pred()

    up_count = sum(labels)
    p_up_base = up_count / n  # 先验 P(up)
    alpha = 1.0

    # 所有布尔特征（从 current_f 推断）
    bool_feature_names = set()
    for fd in features_list:
        bool_feature_names.update(fd.keys())
    bool_feature_names = {k for k in bool_feature_names
                         if k.startswith("sig_") or k in (
                             "ma5_above_ma10", "ma5_above_ma20", "ma10_above_ma20",
                             "ma_bull_alignment", "ma_bear_alignment",
                             "ma_golden_cross", "ma_death_cross",
                             "ma_bullish_arrangement", "ma_bearish_arrangement",
                             "rsi_above_50", "rsi_overbought", "rsi_oversold",
                             "rsi_neutral", "rsi_rising",
                             "rsi_zone_oversold", "rsi_zone_low", "rsi_zone_mid",
                             "rsi_zone_high", "rsi_zone_overbought",
                             "rsi_divergence_bottom", "rsi_divergence_top",
                             "macd_positive", "macd_histogram_positive",
                             "macd_histogram_increasing",
                             "macd_golden_cross", "macd_death_cross",
                             "bb_upper_touch", "bb_lower_touch", "bb_squeeze",
                             "obv_rising", "obv_trend",
                             "momentum_positive", "momentum_accelerating",
                             "vol_ratio_high", "vol_ratio_low",
                             "vp_divergence_up", "vp_divergence_down",
                         )}

    score = 0.0
    feature_impacts = []  # [(fname, impact, direction_str), ...]

    for fname in bool_feature_names:
        # 统计
        f1_up = sum(1 for i, fd in enumerate(features_list) if fd.get(fname, 0) == 1 and labels[i] == 1)
        f1_total = sum(1 for fd in features_list if fd.get(fname, 0) == 1)
        f0_up = sum(1 for i, fd in enumerate(features_list) if fd.get(fname, 0) == 0 and labels[i] == 1)
        f0_total = sum(1 for fd in features_list if fd.get(fname, 0) == 0)

        if f1_total < 3 and f0_total < 3:
            continue  # 样本太少

        # P(up|feature=1) 和 P(up|feature=0)，拉普拉斯平滑
        p_up_1 = (f1_up + alpha) / (f1_total + 2 * alpha)
        p_up_0 = (f0_up + alpha) / (f0_total + 2 * alpha)

        # 当前值对打分的影响
        curr_val = current_f.get(fname, 0)
        if curr_val == 1:
            impact = p_up_1 - 0.5
            score += impact
        else:
            impact = p_up_0 - 0.5
            score += impact

        # 记录（用于展示）
        if f1_total >= 3:
            freq = f1_total / n
            feature_impacts.append((fname, impact, "↑" if impact > 0 else "↓", freq))

    # sigmoid 压缩到概率
    import math
    prob = 1 / (1 + math.exp(-score * 4))
    up_prob = max(0.05, min(0.95, prob))

    # 排序最重要的特征（按影响幅度 * 频率）
    feature_impacts.sort(key=lambda x: abs(x[1]) * x[3], reverse=True)
    top_features = feature_impacts[:10]

    # 关键信号
    sig_features = [(k.replace("sig_", ""), v) for k, v in current_f.items()
                    if k.startswith("sig_") and v == 1]
    sig_features.sort(key=lambda x: abs(
        sum(1 for i, fd in enumerate(features_list)
            if fd.get(f"sig_{x[0]}", 0) == 1 and labels[i] == 1) /
        max(1, sum(1 for fd in features_list if fd.get(f"sig_{x[0]}", 0) == 1)) - 0.5
    ), reverse=True)
    key_signals = [s[0] for s in sig_features[:5]]

    return {
        "up_prob": up_prob,
        "down_prob": 1 - up_prob,
        "prediction": "上涨" if up_prob > 0.5 else "下跌",
        "confidence": _conf_label(n),
        "key_signals": key_signals,
        "top_features": [(f[0], f[2], f"{f[1]:+.3f}") for f in top_features],
        "model_type": "bayesian_rich",
        "sample_count": n,
    }


def _conf_label(n: int) -> str:
    if n < 20:
        return f"低（数据{n}天，需20天）"
    elif n < 60:
        return f"中（数据{n}天）"
    else:
        return f"高（数据{n}天）"


def _default_pred() -> Dict:
    return {
        "up_prob": 0.50,
        "down_prob": 0.50,
        "prediction": "中性",
        "confidence": "数据不足",
        "key_signals": [],
        "top_features": [],
        "model_type": "default",
        "sample_count": 0,
    }


# =============================================================================
# 主预测入口
# =============================================================================

def predict_next_day(stock_code: str) -> Dict:
    """预测次日涨跌。"""
    today = date.today()
    start = today - timedelta(days=180)

    # 获取历史K线
    try:
        quotes = SinaProvider().get_daily_quotes(stock_code, start, today)
        quotes = [q for q in quotes if q.date <= today]
    except Exception:
        return _default_pred()

    if len(quotes) < _MIN_RECORDS + 5:
        return _default_pred()

    # 构建特征
    feat_list, label_list = _build_rich_features(quotes, stock_code)
    current_f = _build_current_features(stock_code, quotes)

    if len(feat_list) < 5:
        return _default_pred()

    # 预测
    pred = _bayesian_predict(feat_list, label_list, current_f)

    # 近5日涨跌
    recent = [(quotes[i+1].close - quotes[i].close) / quotes[i].close * 100
              for i in range(len(quotes) - 6, len(quotes) - 1)]
    pred["recent_5d"] = recent
    pred["recent_trend"] = "上涨为主" if sum(recent) > 0 else "下跌为主"

    return pred


def format_prediction(pred: Dict) -> str:
    """格式化预测结果（富展示版）。"""
    lines = []
    lines.append(f"{'═' * 54}")
    lines.append(f"  次日涨跌预测")
    lines.append(f"{'═' * 54}")

    up_prob = pred["up_prob"]
    n = int(up_prob * 20)
    bar = "█" * n + "░" * (20 - n)
    lines.append(f"  上涨概率  {bar}  {up_prob:.0%}")
    lines.append(f"  下跌概率           {pred['down_prob']:.0%}")
    lines.append(f"  预测结果  {pred['prediction']}  （置信度：{pred['confidence']}）")
    lines.append(f"  数据样本  {pred.get('sample_count', 0)} 天历史记录")

    if pred.get("recent_5d"):
        changes_str = " / ".join([f"{c:+.1f}%" for c in pred["recent_5d"]])
        lines.append(f"  近5日涨跌  [{changes_str}]  {pred.get('recent_trend', '')}")

    # 关键信号
    if pred.get("key_signals"):
        lines.append(f"  关键信号  {' / '.join(pred['key_signals'])}")

    # 重要特征拆解
    if pred.get("top_features"):
        lines.append(f"{'─' * 54}")
        lines.append(f"  【特征拆解】（↑=看涨 ↓=看跌）")
        emoji_map = {"↑": "🔼", "↓": "🔽"}
        for fname, direction, impact in pred["top_features"][:8]:
            display_name = fname.replace("_", " ")
            lines.append(f"  {emoji_map.get(direction, direction)} {display_name:<28} {impact}")

    lines.append(f"{'═' * 54}")
    return "\n".join(lines)
