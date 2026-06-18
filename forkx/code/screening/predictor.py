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
    calc_all_features,
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

    优先从 history_store 读取已存档的数据（质量有保证），
    辅以实时计算（用于最新数据）。

    labels：次日涨跌（>0 → 1，<0 → 0）
    """
    from .history_store import get_records

    features_list = []
    labels = []

    # 优先从 history_store 读取存档（161天，质量好）
    try:
        stored = get_records(stock_code, days=365)
        if len(stored) >= 20:
            print(f"  [特征] 使用 history_store 存档 {len(stored)} 天")
            # 用存档数据构建特征
            for i in range(len(stored) - 1):
                rec = stored[i]
                rec_next = stored[i + 1]
                f = _record_to_features(rec)
                if not f:
                    continue
                features_list.append(f)
                # label: 次日是否上涨
                actual_change = rec_next.change_pct if rec_next.change_pct else 0.0
                labels.append(1 if actual_change > 0 else 0)
            print(f"  [特征] 存档构建 {len(features_list)} 样本")
            return features_list, labels
    except Exception:
        pass

    # 降级：用实时计算
    if len(quotes) < 25:
        return [], []

    lookback = 20  # 用过去20天数据计算特征（缩短窗口增加样本）
    for i in range(lookback, len(quotes) - 1):
        hist_quotes = quotes[i - lookback:i + 1]
        curr = quotes[i]
        next_q = quotes[i + 1]

        f = calc_all_features(stock_code, hist_quotes)
        if not f:
            continue

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

    # 如有学习到的系数，叠加到预测概率上
    coef = _load_coefficients()
    if coef and coef.get("coefficients"):
        pred = _apply_coefficients(pred, current_f, coef["coefficients"])

    # 近5日涨跌
    recent = [(quotes[i+1].close - quotes[i].close) / quotes[i].close * 100
              for i in range(len(quotes) - 6, len(quotes) - 1)]
    pred["recent_5d"] = recent
    pred["recent_trend"] = "上涨为主" if sum(recent) > 0 else "下跌为主"

    # 附加信息
    pred["learn_result"] = learn_result
    if retrain_result:
        pred["retrain"] = retrain_result

    # 保存预测（只在没有历史记录时）
    save_prediction(stock_code, today, pred["up_prob"], pred["prediction"])

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

    # 重训练信息
    if pred.get("retrain"):
        r = pred["retrain"]
        lines.append(f"{'─' * 54}")
        lines.append(f"  【🔄 模型已重训练】样本{r['sample_count']}条")
        if r.get("top_features"):
            top = r["top_features"][:5]
            lines.append(f"  高权重特征：{', '.join([f[0] for f in top])}")

    # 历史准确率
    if pred.get("learn_result"):
        lr = pred["learn_result"]
        total = lr.get("correct", 0) + lr.get("wrong", 0)
        if total > 0:
            acc = lr["correct"] / total
            lines.append(f"  [历史准确率] {acc:.0%}（{lr['correct']} 正确 / {total} 总）")

    lines.append(f"{'═' * 54}")
    return "\n".join(lines)


# =============================================================================
# 自动重训练机制
# =============================================================================

_COEF_PATH = Path.home() / ".forkx" / "feature_coefficients.json"
_RETRAIN_MIN_RECORDS = 60  # 触发重训练的最低预测记录数
_RETRAIN_WINDOW = 60       # 用最近60条已学习的预测来重训


def _load_coefficients() -> Optional[dict]:
    """加载已学习的特征系数。"""
    if not _COEF_PATH.exists():
        return None
    try:
        return json.loads(_COEF_PATH.read_text())
    except Exception:
        return None


def _save_coefficients(coef: dict):
    """保存特征系数到磁盘。"""
    _COEF_PATH.parent.mkdir(parents=True, exist_ok=True)
    _COEF_PATH.write_text(json.dumps(coef, ensure_ascii=False, indent=2))


def auto_retrain_if_needed(stock_code: str) -> dict:
    """检查是否需要重训练，必要时执行重训练。

    触发条件：predictions 表中已学习的记录 >= _RETRAIN_MIN_RECORDS
    重训练：用最近 _RETRAIN_WINDOW 条已学习预测，重新计算每维特征的系数。
    返回重训练结果（无更新时返回空dict）。
    """
    conn = sqlite3.connect(str(Path.home() / ".forkx" / "history.db"))
    rows = conn.execute("""
        SELECT predicted_direction, actual_up, learned
        FROM predictions
        WHERE stock_code = ? AND actual_up IS NOT NULL
        ORDER BY record_date DESC
        LIMIT ?
    """, (stock_code, _RETRAIN_WINDOW)).fetchall()
    learned_count = conn.execute("""
        SELECT COUNT(*) FROM predictions
        WHERE stock_code = ? AND actual_up IS NOT NULL
    """, (stock_code,)).fetchone()[0]
    conn.close()

    if learned_count < _RETRAIN_MIN_RECORDS:
        return {}  # 数据不够，不重训

    # 至少达到触发阈值时才重训（避免重复重训）
    prev = _load_coefficients()
    if prev and prev.get("trained_count", 0) >= learned_count:
        return {}  # 上次训练的样本数 >= 当前样本数，无需重训

    coef = _retrain_from_predictions(rows, learned_count)
    _save_coefficients(coef)
    return {
        "trained": True,
        "sample_count": learned_count,
        "coefficients": coef,
    }


def _retrain_from_predictions(rows: List, total_count: int) -> dict:
    """从预测历史重新计算特征系数。

    逻辑：每条预测 = (predicted_direction, actual_up)
    对每维特征，比较"有这个特征时预测正确的概率"vs"无这个特征时预测正确的概率"，
    得出该特征对预测准确性的贡献系数，存入 coefficients 字典。
    """
    from .feature_engineering import calc_all_features
    from .history_store import get_records, get_prediction_records

    if not rows:
        return {}

    # 获取对应的特征数据（需要从历史存档重建每条预测当日的特征）
    pred_records = get_prediction_records("002371", days=min(total_count + 10, 100))
    daily_records = get_records("002371", days=min(total_count + 30, 150))

    # 构建 date → daily_record 映射
    daily_by_date = {r.record_date: r for r in daily_records}

    # 构建 (predicted_dir, actual_up) 列表对应到日期
    # predictions表按日期正序，最近的在前
    pred_by_date = {}
    for p in pred_records:
        if p["actual_up"] is not None:
            pred_by_date[date.fromisoformat(p["record_date"])] = (
                p["predicted_direction"],
                p["actual_up"],
            )

    # 对每条有实际结果的预测，重建其当日特征
    feature_list = []
    label_list = []  # 1 = 预测正确，0 = 预测错误

    dates_with_features = []
    for d, (pred_dir, actual_up) in sorted(pred_by_date.items()):
        if d not in daily_by_date:
            continue
        rec = daily_by_date[d]
        # 用历史存档重建特征（简化版，直接用存档里的字段）
        feats = _record_to_features(rec)
        feature_list.append(feats)
        pred_correct = (pred_dir == "up" and actual_up == 1) or (pred_dir == "down" and actual_up == 0)
        label_list.append(1 if pred_correct else 0)
        dates_with_features.append(d)

    if len(feature_list) < 10:
        return {}

    # 计算每维特征的系数
    # 系数 = (有这个特征时正确率 - 无这个特征时正确率) * 加权因子
    coefficients = {}
    all_feature_names = set()
    for f in feature_list:
        all_feature_names.update(f.keys())

    n = len(label_list)
    for fname in all_feature_names:
        f1_correct = sum(1 for i, f in enumerate(feature_list) if f.get(fname, 0) == 1 and label_list[i] == 1)
        f1_total = sum(1 for f in feature_list if f.get(fname, 0) == 1)
        f0_correct = sum(1 for i, f in enumerate(feature_list) if f.get(fname, 0) == 0 and label_list[i] == 1)
        f0_total = sum(1 for f in feature_list if f.get(fname, 0) == 0)

        if f1_total < 3 or f0_total < 3:
            continue

        p_correct_1 = f1_correct / f1_total
        p_correct_0 = f0_correct / f0_total
        # 系数：正值=该特征提升正确率，负值=降低正确率
        coefficients[fname] = round(p_correct_1 - p_correct_0, 4)

    # 统计最重要的特征（按系数绝对值）
    top_coef = sorted(coefficients.items(), key=lambda x: abs(x[1]), reverse=True)[:15]

    return {
        "coefficients": coefficients,
        "top_features": top_coef,
        "trained_count": total_count,
        "sample_count": len(feature_list),
    }


def _record_to_features(rec) -> dict:
    """把 DailyRecord 转换成特征字典（供重训练用）。"""
    feats = {}

    # 布尔特征
    if rec.signals:
        for s in rec.signals:
            feats[f"sig_{s}"] = 1

    # RSI
    if rec.rsi is not None:
        rsi = rec.rsi
        feats["rsi_above_50"] = 1 if rsi > 50 else 0
        feats["rsi_overbought"] = 1 if rsi > 70 else 0
        feats["rsi_oversold"] = 1 if rsi < 30 else 0
        feats["rsi_neutral"] = 1 if 40 <= rsi <= 60 else 0
        feats["rsi"] = rsi / 100.0

    # 涨跌幅
    if rec.change_pct is not None:
        feats["change_pct"] = rec.change_pct / 100.0
        feats["up_day"] = 1 if rec.change_pct > 0 else 0

    # 量比
    if rec.volume_ratio is not None:
        feats["vol_ratio"] = rec.volume_ratio
        feats["vol_ratio_high"] = 1 if rec.volume_ratio > 1.5 else 0
        feats["vol_ratio_low"] = 1 if rec.volume_ratio < 0.7 else 0

    # 均线状态
    if rec.ma_status:
        feats["ma_bullish_arrangement"] = 1 if "多头" in rec.ma_status else 0
        feats["ma_bearish_arrangement"] = 1 if "空头" in rec.ma_status else 0

    # MACD信号
    if rec.macd_signal:
        feats["macd_positive"] = 1 if "金叉" in rec.macd_signal or "零轴上方" in rec.macd_signal else 0
        feats["macd_negative"] = 1 if "死叉" in rec.macd_signal or "零轴下方" in rec.macd_signal else 0

    # 资金流
    if rec.fund_flow_net_wan is not None:
        feats["fund_inflow"] = 1 if rec.fund_flow_net_wan > 0 else 0

    # 横盘天数
    if rec.consolidation_days:
        feats["consolidating"] = 1 if rec.consolidation_days >= 5 else 0
        feats["consolidation_days"] = rec.consolidation_days

    # 竞价信号
    if rec.auction_signal:
        feats["auction_positive"] = 1 if "试盘" in rec.auction_signal or "护盘" in rec.auction_signal else 0
        feats["auction_negative"] = 1 if "派发" in rec.auction_signal or "诱多" in rec.auction_signal else 0

    # 分时形态
    if rec.intraday_pattern:
        feats["pattern_pulse"] = 1 if "脉冲" in rec.intraday_pattern else 0
        feats["pattern_tail"] = 1 if "尾盘" in rec.intraday_pattern else 0
        feats["pattern_waterfall"] = 1 if "瀑布" in rec.intraday_pattern else 0

    return feats


# =============================================================================
# 预测入口（已整合重训练）
# =============================================================================

def predict_next_day(stock_code: str) -> Dict:
    """预测次日涨跌（含自动重训练）。"""
    from .history_store import learn_from_predictions, save_prediction

    today = date.today()
    start = today - timedelta(days=180)

    # 先触发学习反馈
    learn_result = learn_from_predictions(stock_code)

    # 自动重训练（检查是否需要）
    retrain_result = auto_retrain_if_needed(stock_code)

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

    # 如有学习到的系数，叠加到预测概率上
    coef = _load_coefficients()
    if coef and coef.get("coefficients"):
        pred = _apply_coefficients(pred, current_f, coef["coefficients"])

    # 近5日涨跌
    recent = [(quotes[i+1].close - quotes[i].close) / quotes[i].close * 100
              for i in range(len(quotes) - 6, len(quotes) - 1)]
    pred["recent_5d"] = recent
    pred["recent_trend"] = "上涨为主" if sum(recent) > 0 else "下跌为主"

    # 附加信息
    pred["learn_result"] = learn_result
    if retrain_result:
        pred["retrain"] = retrain_result

    # 保存预测（只在没有历史记录时）
    save_prediction(stock_code, today, pred["up_prob"], pred["prediction"])

    return pred


def _apply_coefficients(pred: Dict, current_f: dict, coefs: dict) -> Dict:
    """将学习到的特征系数叠加到预测概率上。"""
    score = 0.0
    for fname, coef in coefs.items():
        if current_f.get(fname, 0) == 1:
            score += coef * 2  # 有该特征时应用系数
        else:
            score -= coef * 0.5  # 无该特征时轻微反向

    import math
    base_prob = pred["up_prob"]
    adjusted = base_prob + score * 0.1
    adjusted = max(0.05, min(0.95, adjusted))

    # 更新预测方向（如果调整幅度大）
    new_direction = "上涨" if adjusted > 0.5 else "下跌"

    return {
        **pred,
        "up_prob": round(adjusted, 3),
        "down_prob": round(1 - adjusted, 3),
        "prediction": new_direction,
        "coefficients_applied": True,
        "coefficient_score": round(score, 4),
    }
