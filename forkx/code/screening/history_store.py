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
