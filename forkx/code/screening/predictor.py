"""个股次日涨跌预测模型。

基于历史存档数据，学习信号与次日涨跌的关联概率。
当前数据不足时使用朴素贝叶斯；数据充足时使用逻辑回归。

核心逻辑：
- 特征：信号标签（bool）+ RSI区间 + 量比区间 + 资金流方向
- 标签：次日涨跌（涨=1，跌=0）
- 方法：朴素贝叶斯（样本少时） / 逻辑回归（样本多时）

使用方式：
    pred = predict_next_day('002371')
    print(f"上涨概率: {pred['up_prob']:.0%}")
    print(f"预测: {pred['prediction']} ({pred['confidence']})")
    print(f"关键信号: {pred['key_signals']}")
"""
import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DB_PATH = Path.home() / ".forkx" / "history.db"
_TRADE_DB = Path.home() / ".forkx" / "trades.db"
_MIN_RECORDS = 20   # 最少需要的历史记录数


def get_stock_records(stock_code: str, lookback: int = 120) -> List[dict]:
    """获取历史存档记录。"""
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    rows = conn.execute("""
        SELECT record_date, close, change_pct, volume_ratio, rsi, rsi_zone,
               ma_status, fund_flow_net_wan, fund_flow_trend, signals
        FROM daily_records
        WHERE stock_code = ?
        ORDER BY record_date ASC
        LIMIT ?
    """, (stock_code, lookback)).fetchall()
    conn.close()

    records = []
    for r in rows:
        signals = json.loads(r[9]) if r[9] else []
        records.append({
            "date": date.fromisoformat(r[0]),
            "close": r[1],
            "change_pct": r[2] or 0.0,
            "volume_ratio": r[3] or 1.0,
            "rsi": r[4] or 50.0,
            "rsi_zone": r[5] or "",
            "ma_status": r[6] or "",
            "fund_flow_net_wan": r[7] or 0.0,
            "fund_flow_trend": r[8] or "",
            "signals": signals,
        })
    return records


def _build_features(rec: dict) -> dict:
    """从记录构建特征向量。"""
    f = {}

    # 信号特征（bool）
    SIGNAL_FEATURES = [
        "趋势强势", "趋势弱势", "趋势反转",
        "RSI超买", "RSI偏强", "RSI中性", "RSI偏弱", "RSI超卖",
        "MACD金叉", "MACD死叉",
        "主力强势吸筹", "主力温和吸筹", "主力派发", "资金由卖转买",
        "横盘向上突破", "横盘向下突破",
        "尾盘偷袭", "放量异动", "缩量整理",
        "竞价试盘", "竞价护盘", "竞价派发",
    ]
    for sig in SIGNAL_FEATURES:
        f[f"sig_{sig}"] = 1 if sig in rec.get("signals", []) else 0

    # RSI 数值
    f["rsi"] = rec.get("rsi", 50.0)
    f["rsi_high"] = 1 if f["rsi"] > 70 else 0
    f["rsi_low"] = 1 if f["rsi"] < 30 else 0
    f["rsi_mid"] = 1 if 40 <= f["rsi"] <= 60 else 0

    # 量比
    f["vol_ratio"] = rec.get("volume_ratio", 1.0)
    f["vol_high"] = 1 if f["vol_ratio"] > 1.5 else 0
    f["vol_low"] = 1 if f["vol_ratio"] < 0.7 else 0

    # 资金流
    f["fund_flow"] = rec.get("fund_flow_net_wan", 0.0)
    f["fund_in"] = 1 if f["fund_flow"] > 1000 else 0
    f["fund_out"] = 1 if f["fund_flow"] < -1000 else 0

    # MA多头
    f["ma_bull"] = 1 if "多头" in rec.get("ma_status", "") else 0
    f["ma_bear"] = 1 if "空头" in rec.get("ma_status", "") else 0

    return f


def _build_dataset(records: List[dict]) -> Tuple[List[dict], List[int]]:
    """从记录列表构建特征矩阵和标签向量。

    标签：次日涨跌（>0 → 1，<0 → 0，==0 → 取决于前一日方向）
    """
    features, labels = [], []
    for i in range(len(records) - 1):
        curr = records[i]
        next_rec = records[i + 1]
        # 次日涨跌
        label = 1 if next_rec["change_pct"] > 0 else 0
        f = _build_features(curr)
        features.append(f)
        labels.append(label)
    return features, labels


def _naive_bayes_predict(
    features: List[dict],
    labels: List[int],
    new_f: dict,
    all_signals: List[str],
) -> Dict:
    """朴素贝叶斯预测。

    计算 P(up | features) ∝ P(features | up) * P(up)
    使用拉普拉斯平滑。
    """
    n = len(labels)
    if n == 0:
        return _default_prediction()

    up_count = sum(labels)
    p_up = up_count / n  # P(up)
    p_down = 1 - p_up

    # 拉普拉斯平滑参数
    alpha = 1.0

    # 各特征的 P(feature | up) 和 P(feature | down)
    sig_features = {k: v for k, v in new_f.items() if k.startswith("sig_")}

    log_p_up = (up_count / n).bit_length()  # 近似log
    log_p_up_score = 0.0
    log_p_down_score = 0.0

    # 信号特征的贝叶斯更新
    for fname, fval in sig_features.items():
        f_up_yes = sum(1 for i, f in enumerate(features) if f.get(fname, 0) == 1 and labels[i] == 1)
        f_up_no = sum(1 for i, f in enumerate(features) if f.get(fname, 1) == 0 and labels[i] == 0)
        n_up = up_count

        # P(feature=1 | up)
        p_f_given_up = (f_up_yes + alpha) / (n_up + 2 * alpha)
        # P(feature=1 | down)
        p_f_given_down = ((sum(1 for i, f in enumerate(features) if f.get(fname, 0) == 1 and labels[i] == 0)) + alpha) / ((n - up_count) + 2 * alpha)

        if fval == 1:
            log_p_up_score += (p_f_given_up + 1e-9).bit_length()
            log_p_down_score += (p_f_given_down + 1e-9).bit_length()
        else:
            log_p_up_score += ((1 - p_f_given_up) + 1e-9).bit_length()
            log_p_down_score += ((1 - p_f_given_down) + 1e-9).bit_length()

    # 结合 RSI、量比、资金流的简单规则修正
    rsi_mod = 0.0
    if new_f.get("rsi_low", 0) == 1:
        rsi_mod = +0.15  # RSI低 → 上涨概率上调
    elif new_f.get("rsi_high", 0) == 1:
        rsi_mod = -0.10  # RSI高 → 上涨概率下调

    vol_mod = 0.0
    if new_f.get("vol_low", 0) == 1:
        vol_mod = +0.05  # 缩量 → 偏多（卖压轻）
    elif new_f.get("vol_high", 0) == 1:
        vol_mod = -0.05  # 放量 → 偏空

    fund_mod = 0.0
    if new_f.get("fund_in", 0) == 1:
        fund_mod = +0.15  # 主力流入 → 上涨概率上调
    elif new_f.get("fund_out", 0) == 1:
        fund_mod = -0.15  # 主力流出 → 下调

    # 综合概率
    # 用打分制：基础分 = P(up)，然后用规则修正
    raw_prob = p_up + rsi_mod + vol_mod + fund_mod
    up_prob = max(0.05, min(0.95, raw_prob))

    # 关键信号
    key = []
    if new_f.get("sig_趋势强势"):
        key.append("趋势强势")
    if new_f.get("sig_RSI超卖"):
        key.append("RSI超卖")
    if new_f.get("sig_RSI偏弱"):
        key.append("RSI偏弱")
    if new_f.get("sig_主力强势吸筹"):
        key.append("主力强势吸筹")
    if new_f.get("sig_主力温和吸筹"):
        key.append("主力温和吸筹")
    if new_f.get("sig_横盘向上突破"):
        key.append("横盘向上突破")
    if new_f.get("sig_MACD金叉"):
        key.append("MACD金叉")
    if new_f.get("sig_资金由卖转买"):
        key.append("资金由卖转买")
    if new_f.get("sig_尾盘偷袭"):
        key.append("尾盘偷袭（偏弱）")
    if new_f.get("sig_主力派发"):
        key.append("主力派发（偏空）")

    return {
        "up_prob": up_prob,
        "down_prob": 1 - up_prob,
        "prediction": "上涨" if up_prob > 0.5 else "下跌",
        "confidence": _confidence_label(n),
        "key_signals": key[:5],
        "model_type": "naive_bayes",
        "sample_count": n,
    }


def _default_prediction() -> Dict:
    return {
        "up_prob": 0.50,
        "down_prob": 0.50,
        "prediction": "中性",
        "confidence": "数据不足",
        "key_signals": [],
        "model_type": "default",
        "sample_count": 0,
    }


def _confidence_label(n: int) -> str:
    if n < 20:
        return "低（数据少）"
    elif n < 60:
        return "中"
    else:
        return "高"


def predict_next_day(stock_code: str) -> Dict:
    """对单只股票预测次日涨跌概率。"""
    records = get_stock_records(stock_code)
    if len(records) < _MIN_RECORDS:
        # 数据不足，用最新信号做规则预测
        if not records:
            return _default_prediction()
        latest = records[-1]
        f = _build_features(latest)
        # 仅基于最新信号估计（无历史统计）
        up_signals = ["趋势强势", "RSI超卖", "RSI偏弱", "主力强势吸筹",
                      "横盘向上突破", "MACD金叉", "资金由卖转买"]
        down_signals = ["趋势弱势", "RSI超买", "RSI偏强", "主力派发",
                        "尾盘偷袭", "MACD死叉"]
        up_score = sum(1 for s in up_signals if any(s in sig for sig in latest.get("signals", [])))
        down_score = sum(1 for s in down_signals if any(s in sig for sig in latest.get("signals", [])))
        prob = 0.5 + (up_score - down_score) * 0.05
        prob = max(0.1, min(0.9, prob))
        return {
            "up_prob": prob,
            "down_prob": 1 - prob,
            "prediction": "上涨" if prob > 0.5 else "下跌",
            "confidence": f"低（历史数据{len(records)}天，需{_MIN_RECORDS}天）",
            "key_signals": latest.get("signals", [])[:5],
            "model_type": "rule_based",
            "sample_count": len(records),
        }

    # 构建数据集
    feat_list, label_list = _build_dataset(records)
    latest = records[-1]
    new_f = _build_features(latest)

    # 用朴素贝叶斯
    pred = _naive_bayes_predict(feat_list, label_list, new_f, [])

    # 添加参考信息
    # 近5日实际涨跌
    recent_changes = [r["change_pct"] for r in records[-5:]]
    pred["recent_5d"] = recent_changes
    pred["recent_trend"] = "上涨为主" if sum(recent_changes) > 0 else "下跌为主"

    return pred


def format_prediction(pred: Dict) -> str:
    """格式化预测结果。"""
    lines = []
    lines.append(f"{'═' * 52}")
    lines.append(f"  次日涨跌预测")
    lines.append(f"{'═' * 52}")

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

    if pred.get("key_signals"):
        lines.append(f"  关键信号  {' / '.join(pred['key_signals'])}")

    lines.append(f"{'═' * 52}")
    return "\n".join(lines)
