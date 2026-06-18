"""信号权重调优器。

基于交易记录（买→卖配对）的历史胜率，自动计算每个信号标签的权重。
权重越高 → 该信号历史上盈利概率越大。

使用方式：
    weights = load_signal_weights()          # 读取当前权重
    update_signal_weights()                   # 从交易记录重新计算权重
    score = score_signals(signals, weights)   # 对当前信号打分
    advice = get_weighted_advice(signals)     # 返回操作建议
"""
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_WEIGHTS_PATH = Path.home() / ".forkx" / "signal_weights.json"
_DB_PATH = Path.home() / ".forkx" / "trades.db"
_MIN_SAMPLES = 2   # 最少样本数才启用该信号


@dataclass
class SignalWeight:
    count: int       # 出现次数
    win: int         # 盈利次数
    total_return: float  # 累计收益率（%）
    weight: float    # 权重分（0-100）

    @property
    def win_rate(self) -> float:
        return self.win / self.count if self.count > 0 else 0.0

    @property
    def avg_return(self) -> float:
        return self.total_return / self.count if self.count > 0 else 0.0

    @property
    def confidence(self) -> float:
        """样本数置信度，0-1。"""
        if self.count < _MIN_SAMPLES:
            return 0.0
        return min(1.0, (self.count - _MIN_SAMPLES) / 10)


def load_signal_weights() -> Dict[str, SignalWeight]:
    """读取已保存的信号权重。"""
    if not _WEIGHTS_PATH.exists():
        return {}
    with open(_WEIGHTS_PATH) as f:
        raw = json.load(f)
    return {k: SignalWeight(**v) for k, v in raw.items()}


def save_signal_weights(weights: Dict[str, SignalWeight]):
    """保存信号权重到文件。"""
    _WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_WEIGHTS_PATH, "w") as f:
        json.dump({k: {
            "count": v.count, "win": v.win,
            "total_return": v.total_return, "weight": v.weight
        } for k, v in weights.items()}, f, ensure_ascii=False, indent=2)


def update_signal_weights() -> Dict[str, SignalWeight]:
    """从交易记录重新计算所有信号权重。"""
    conn = sqlite3.connect(str(_DB_PATH))
    rows = conn.execute(
        "SELECT id, stock_code, action, price, volume, trade_date, signals FROM trades ORDER BY stock_code, trade_date"
    ).fetchall()
    conn.close()

    if not rows:
        return {}

    # 按股票分组，按日期排序
    from collections import defaultdict
    stock_trades = defaultdict(list)
    for r in rows:
        import json as _json
        signals_raw = r[6] if len(r) > 6 else ""
        signals = _json.loads(signals_raw) if signals_raw else []
        stock_trades[r[1]].append({
            "action": r[2], "price": r[3],
            "date": r[5], "signals": signals
        })

    # 匹配买→卖，计算每个信号的收益率贡献
    signal_stats = defaultdict(lambda: {"count": 0, "win": 0, "total_return": 0.0})
    for code, recs in stock_trades.items():
        recs_sorted = sorted(recs, key=lambda x: x["date"])
        buy_stack = []
        for rec in recs_sorted:
            if rec["action"] == "buy":
                buy_stack.append(rec)
            elif rec["action"] == "sell" and buy_stack:
                buy = buy_stack.pop(0)
                ret_pct = (rec["price"] - buy["price"]) / buy["price"] * 100
                for sig in buy.get("signals", []):
                    s = signal_stats[sig]
                    s["count"] += 1
                    s["total_return"] += ret_pct
                    if ret_pct > 0:
                        s["win"] += 1

    # 计算权重：win_rate × confidence
    weights = {}
    for sig, s in signal_stats.items():
        sw = SignalWeight(
            count=s["count"], win=s["win"],
            total_return=s["total_return"], weight=0.0
        )
        # 权重 = 胜率 × 置信度（置信度随样本数增加而提升）
        sw.weight = sw.win_rate * sw.confidence * 100
        weights[sig] = sw

    save_signal_weights(weights)
    return weights


def score_signals(signals: List[str], weights: Optional[Dict[str, SignalWeight]] = None) -> Tuple[float, float, int]:
    """对一组信号打分。

    Returns: (weighted_score, avg_win_rate, signal_count)
    """
    if not signals:
        return 0.0, 0.0, 0
    if weights is None:
        weights = load_signal_weights()

    total_score = 0.0
    total_win_rate = 0.0
    count_with_weights = 0

    for sig in signals:
        if sig in weights:
            w = weights[sig]
            total_score += w.weight
            total_win_rate += w.win_rate
            count_with_weights += 1

    n = len(signals)
    avg_score = total_score / n if n > 0 else 0.0
    avg_wr = total_win_rate / count_with_weights if count_with_weights > 0 else 0.0
    return avg_score, avg_wr, count_with_weights


def get_weighted_advice(signals: List[str]) -> Tuple[str, str]:
    """基于信号权重返回操作建议。

    Returns: (level, advice_text)
    level: "强势买入" / "买入" / "观望" / "卖出" / "强势卖出"
    """
    if not signals:
        return "观望", "无有效信号，建议观望"

    weights = load_signal_weights()
    avg_score, avg_wr, n = score_signals(signals, weights)

    # 基准分（无权重信号）
    if n == 0:
        # 没有历史权重，用信号计数判断
        buy_score = sum(1 for s in signals if s in {
            "趋势强势", "RSI超卖", "主力强势吸筹", "横盘向上突破",
            "MACD金叉", "竞价试盘", "资金由卖转买"
        })
        sell_score = sum(1 for s in signals if s in {
            "趋势弱势", "RSI超买", "主力派发", "MACD死叉",
            "尾盘偷袭", "高开回落", "瀑布式下跌"
        })
        if buy_score >= 3:
            return "买入", f"买入信号{buy_score}个，但无历史权重参考"
        elif sell_score >= 3:
            return "卖出", f"卖出信号{sell_score}个，但无历史权重参考"
        return "观望", "多空信号均衡，建议观望"

    # 有权重的路径
    if avg_score >= 60 and avg_wr >= 0.6:
        return "强势买入", f"综合得分{avg_score:.0f}，历史胜率{avg_wr:.0%}，信号强"
    elif avg_score >= 35 and avg_wr >= 0.5:
        return "买入", f"综合得分{avg_score:.0f}，历史胜率{avg_wr:.0%}"
    elif avg_score <= 15 and avg_wr <= 0.4:
        return "卖出", f"综合得分{avg_score:.0f}，历史胜率{avg_wr:.0%}"
    elif avg_score <= 5:
        return "强势卖出", f"综合得分{avg_score:.0f}，历史胜率{avg_wr:.0%}，信号极弱"
    else:
        return "观望", f"综合得分{avg_score:.0f}，多空信号均衡"


def format_weights_table(weights: Dict[str, SignalWeight]) -> str:
    """格式化权重表。"""
    if not weights:
        return "暂无历史权重（需要至少一笔卖出平仓记录）"

    lines = []
    lines.append(f"{'═' * 56}")
    lines.append(f"  信号权重表")
    lines.append(f"{'═' * 56}")
    lines.append(f"{'信号':<18} {'次数':>5} {'胜率':>7} {'均收益':>8} {'权重':>7}")
    lines.append(f"{'-' * 56}")

    for sig, w in sorted(weights.items(), key=lambda x: -x[1].weight):
        conf_mark = "●" if w.confidence >= 0.7 else "○" if w.confidence >= 0.3 else "·"
        lines.append(
            f"{sig:<16}{conf_mark} {w.count:>4}   {w.win_rate:>6.0%}   "
            f"{w.avg_return:>+7.1f}%   {w.weight:>5.1f}"
        )
    lines.append(f"{'═' * 56}")
    return "\n".join(lines)
