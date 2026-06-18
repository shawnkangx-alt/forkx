"""每日分析结果存档。

analyze 跑完后自动落库，供后续回溯、信号学习、预测模型使用。
"""
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

_DB_PATH = Path.home() / ".forkx" / "history.db"


@dataclass
class DailyRecord:
    """单日分析存档。"""
    stock_code: str
    record_date: date
    close: float
    change_pct: float
    volume_ratio: float       # 量比
    rsi: float                # RSI(14)
    rsi_zone: str             # "偏强" / "超买" 等
    ma_status: str            # "多头排列" / "空头排列" 等
    macd_signal: str          # "金叉" / "死叉" 等
    fund_flow_net_wan: float  # 主力净流入（万元）
    fund_flow_trend: str      # 趋势描述
    auction_signal: str       # 竞价信号
    intraday_pattern: str     # 分时形态
    consolidation_days: int   # 横盘天数
    breakout_direction: str   # 突破方向
    composite_signal: str     # 综合信号
    signals: List[str]        # 信号标签列表
    note: str = ""


def _get_conn():
    p = _DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            record_date TEXT NOT NULL,
            close REAL,
            change_pct REAL,
            volume_ratio REAL,
            rsi REAL,
            rsi_zone TEXT,
            ma_status TEXT,
            macd_signal TEXT,
            fund_flow_net_wan REAL,
            fund_flow_trend TEXT,
            auction_signal TEXT,
            intraday_pattern TEXT,
            consolidation_days INTEGER,
            breakout_direction TEXT,
            composite_signal TEXT,
            signals TEXT,
            note TEXT,
            created_at TEXT,
            UNIQUE(stock_code, record_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_date ON daily_records(stock_code, record_date)")
    # 预测记录表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            record_date TEXT NOT NULL,  -- 这条记录是哪天的分析
            predicted_up_prob REAL,
            predicted_direction TEXT,   -- "up" / "down" / "neutral"
            actual_up REAL,             -- 次日实际涨跌（事后填入）
            actual_change_pct REAL,
            learned INTEGER DEFAULT 0,  -- 是否已用于权重更新
            created_at TEXT,
            UNIQUE(stock_code, record_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_predictions_learned ON predictions(stock_code, learned)")
    conn.commit()
    return conn


def save_daily_record(rec: DailyRecord) -> bool:
    """存档一笔日记录。存在则更新，不存在则插入。"""
    conn = _get_conn()
    signals_json = json.dumps(rec.signals) if rec.signals else "[]"
    now = datetime.now().isoformat()
    try:
        conn.execute("""
            INSERT INTO daily_records VALUES (
                NULL, :stock_code, :record_date, :close, :change_pct,
                :volume_ratio, :rsi, :rsi_zone, :ma_status, :macd_signal,
                :fund_flow_net_wan, :fund_flow_trend, :auction_signal, :intraday_pattern,
                :consolidation_days, :breakout_direction, :composite_signal,
                :signals, :note, :created_at
            )
        """, {
            "stock_code": rec.stock_code,
            "record_date": rec.record_date.isoformat(),
            "close": rec.close,
            "change_pct": rec.change_pct,
            "volume_ratio": rec.volume_ratio,
            "rsi": rec.rsi,
            "rsi_zone": rec.rsi_zone,
            "ma_status": rec.ma_status,
            "macd_signal": rec.macd_signal,
            "fund_flow_net_wan": rec.fund_flow_net_wan,
            "fund_flow_trend": rec.fund_flow_trend,
            "auction_signal": rec.auction_signal,
            "intraday_pattern": rec.intraday_pattern,
            "consolidation_days": rec.consolidation_days,
            "breakout_direction": rec.breakout_direction,
            "composite_signal": rec.composite_signal,
            "signals": signals_json,
            "note": rec.note,
            "created_at": now,
        })
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # 已存在，更新
        conn.execute("""
            UPDATE daily_records SET
                close=:close, change_pct=:change_pct, volume_ratio=:volume_ratio,
                rsi=:rsi, rsi_zone=:rsi_zone, ma_status=:ma_status,
                macd_signal=:macd_signal, fund_flow_net_wan=:fund_flow_net_wan,
                fund_flow_trend=:fund_flow_trend, auction_signal=:auction_signal,
                intraday_pattern=:intraday_pattern, consolidation_days=:consolidation_days,
                breakout_direction=:breakout_direction, composite_signal=:composite_signal,
                signals=:signals, note=:note
            WHERE stock_code=:stock_code AND record_date=:record_date
        """, {
            "stock_code": rec.stock_code,
            "record_date": rec.record_date.isoformat(),
            "close": rec.close,
            "change_pct": rec.change_pct,
            "volume_ratio": rec.volume_ratio,
            "rsi": rec.rsi,
            "rsi_zone": rec.rsi_zone,
            "ma_status": rec.ma_status,
            "macd_signal": rec.macd_signal,
            "fund_flow_net_wan": rec.fund_flow_net_wan,
            "fund_flow_trend": rec.fund_flow_trend,
            "auction_signal": rec.auction_signal,
            "intraday_pattern": rec.intraday_pattern,
            "consolidation_days": rec.consolidation_days,
            "breakout_direction": rec.breakout_direction,
            "composite_signal": rec.composite_signal,
            "signals": signals_json,
            "note": rec.note,
        })
        conn.commit()
        return True
    finally:
        conn.close()


def get_records(stock_code: str, days: int = 30) -> List[DailyRecord]:
    """获取最近N日的存档记录。"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT stock_code, record_date, close, change_pct, volume_ratio,
               rsi, rsi_zone, ma_status, macd_signal, fund_flow_net_wan,
               fund_flow_trend, auction_signal, intraday_pattern, consolidation_days,
               breakout_direction, composite_signal, signals, note
        FROM daily_records
        WHERE stock_code = ?
        ORDER BY record_date DESC
        LIMIT ?
    """, (stock_code, days)).fetchall()
    conn.close()
    records = []
    for r in rows:
        signals = json.loads(r[16]) if r[16] else []
        records.append(DailyRecord(
            stock_code=r[0], record_date=date.fromisoformat(r[1]),
            close=r[2], change_pct=r[3], volume_ratio=r[4], rsi=r[5],
            rsi_zone=r[6] or "", ma_status=r[7] or "", macd_signal=r[8] or "",
            fund_flow_net_wan=r[9] or 0.0, fund_flow_trend=r[10] or "",
            auction_signal=r[11] or "", intraday_pattern=r[12] or "",
            consolidation_days=r[13] or 0, breakout_direction=r[14] or "",
            composite_signal=r[15] or "", signals=signals, note=r[17] or "",
        ))
    return records


def save_prediction(stock_code: str, record_date: date, up_prob: float, direction: str):
    """保存预测记录（只在没有历史记录时插入）。"""
    conn = _get_conn()
    now = datetime.now().isoformat()
    # 只在不存在时插入（避免覆盖已学习的记录）
    conn.execute("""
        INSERT INTO predictions
        (stock_code, record_date, predicted_up_prob, predicted_direction, actual_up, actual_change_pct, learned, created_at)
        SELECT ?, ?, ?, ?, NULL, NULL, 0, ?
        WHERE NOT EXISTS (SELECT 1 FROM predictions WHERE stock_code = ? AND record_date = ?)
    """, (stock_code, record_date.isoformat(), up_prob, direction, now, stock_code, record_date.isoformat()))
    conn.commit()
    conn.close()


def learn_from_predictions(stock_code: str) -> dict:
    """对照未学习的预测记录与实际结果，更新信号权重。

    逻辑：
    - 找到 learned=0 的预测记录
    - 找该记录次日（即 record_date 的次日）的实际涨跌（从 daily_records）
    - 如果预测正确（方向一致）：各信号权重 +0.05
    - 如果预测错误（方向相反）：各信号权重 -0.10
    - 标记为 learned=1
    """
    from .signal_weights import load_signal_weights, save_signal_weights

    conn = _get_conn()
    # 找出该股票未学习的预测
    preds = conn.execute("""
        SELECT id, record_date, predicted_direction, predicted_up_prob
        FROM predictions
        WHERE stock_code = ? AND learned = 0
        ORDER BY record_date ASC
    """, (stock_code,)).fetchall()
    if not preds:
        conn.close()
        return {"updated": 0, "correct": 0, "wrong": 0}

    # 获取历史存档（用于找次日实际涨跌）
    hist_rows = conn.execute("""
        SELECT record_date, change_pct, signals
        FROM daily_records
        WHERE stock_code = ?
        ORDER BY record_date ASC
    """, (stock_code,)).fetchall()
    conn.close()

    if not hist_rows:
        return {"updated": 0, "correct": 0, "wrong": 0}

    # 构建 date → (change_pct, signals) 映射
    hist_map = {}
    signals_by_date = {}
    for h in hist_rows:
        d = date.fromisoformat(h[0])
        hist_map[d] = h[1]
        signals_by_date[d] = json.loads(h[2]) if h[2] else []

    updated = 0
    correct = 0
    wrong = 0
    changes = []

    weights = load_signal_weights()
    for pid, pred_date_str, pred_dir, up_prob in preds:
        pred_date = date.fromisoformat(pred_date_str)
        # 次日实际涨跌
        actual_change = hist_map.get(pred_date)
        if actual_change is None:
            continue  # 还没到次日，跳过
        actual_up = actual_change > 0
        pred_up = pred_dir == "up"
        is_correct = actual_up == pred_up

        # 获取当时的信号
        signals = signals_by_date.get(pred_date, [])

        # 修正量
        delta = 0.05 if is_correct else -0.10
        sigs_modified = []
        for sig in signals:
            old_w = weights.get(sig, SignalWeight(count=0, win=0, total_return=0.0, weight=0.0))
            # 调整 weight（基础分 ± delta）
            new_weight = max(0.0, old_w.weight + delta * 100)
            weights[sig] = SignalWeight(
                count=old_w.count,
                win=old_w.win,
                total_return=old_w.total_return,
                weight=new_weight
            )
            sigs_modified.append((sig, old_w.weight, new_weight))

        # 标记为已学习
        conn2 = _get_conn()
        conn2.execute("UPDATE predictions SET learned=1 WHERE id=?", (pid,))
        conn2.execute("UPDATE predictions SET actual_up=?, actual_change_pct=? WHERE id=?", (1 if actual_up else 0, actual_change, pid))
        conn2.commit()
        conn2.close()

        updated += 1
        if is_correct:
            correct += 1
        else:
            wrong += 1
        changes.append({
            "date": pred_date_str,
            "predicted": pred_dir,
            "actual": "up" if actual_up else "down",
            "correct": is_correct,
            "signals": sigs_modified,
        })

    save_signal_weights(weights)
    return {"updated": updated, "correct": correct, "wrong": wrong, "changes": changes}


def _direction_to_key(d: str) -> str:
    """统一方向字符串。"""
    if d in ("up", "上涨"):
        return "up"
    if d in ("down", "下跌"):
        return "down"
    return "neutral"


def get_prediction_records(stock_code: str, days: int = 60) -> List[dict]:
    """获取预测记录列表（供重训练用）。"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT record_date, predicted_up_prob, predicted_direction,
               actual_up, actual_change_pct, learned
        FROM predictions
        WHERE stock_code = ?
        ORDER BY record_date ASC
        LIMIT ?
    """, (stock_code, days)).fetchall()
    conn.close()
    return [
        {
            "record_date": r[0],
            "predicted_up_prob": r[1],
            "predicted_direction": r[2],
            "actual_up": r[3],
            "actual_change_pct": r[4],
            "learned": r[5],
        }
        for r in rows
    ]


def get_prediction_summary(stock_code: str) -> dict:
    """获取预测准确率统计。"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT predicted_direction, actual_up, learned
        FROM predictions
        WHERE stock_code = ?
        ORDER BY record_date DESC
    """, (stock_code,)).fetchall()
    conn.close()

    learned = [(p[0], p[1]) for p in rows if p[2] == 1]
    total = len(learned)
    if total == 0:
        return {"total": 0, "accuracy": None, "correct": 0, "wrong": 0}

    correct = sum(
        1 for pd, au in learned
        if _direction_to_key(pd) == "up" and au == 1
        or _direction_to_key(pd) != "up" and au == 0
    )
    return {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": correct / total if total > 0 else None,
    }


def get_next_day_return(stock_code: str, record_date: date) -> Optional[float]:
    """获取某日之后次日的收益率（用于预测模型标签）。"""
    conn = _get_conn()
    row = conn.execute("""
        SELECT change_pct FROM daily_records
        WHERE stock_code = ? AND record_date > ?
        ORDER BY record_date ASC
        LIMIT 1
    """, (stock_code, record_date.isoformat())).fetchone()
    conn.close()
    return row[0] if row else None
