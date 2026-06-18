"""交易记录存储。"""
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import List, Optional

from ..data.models import TradeRecord

_CONFIG_DIR = Path.home() / ".forkx"
_CONFIG_DIR.mkdir(exist_ok=True)
_DB_PATH = _CONFIG_DIR / "trades.db"


def _get_conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            stock_code TEXT NOT NULL,
            action TEXT NOT NULL,
            price REAL NOT NULL,
            volume REAL NOT NULL,
            trade_date TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def add_trade(trade: TradeRecord) -> str:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (trade.id, trade.stock_code, trade.action, trade.price,
         trade.volume, trade.date.isoformat(), trade.note, trade.created_at.isoformat())
    )
    conn.commit()
    conn.close()
    return trade.id


def list_trades(stock_code: Optional[str] = None) -> List[TradeRecord]:
    conn = _get_conn()
    if stock_code:
        rows = conn.execute(
            "SELECT * FROM trades WHERE stock_code = ? ORDER BY trade_date DESC",
            (stock_code,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trades ORDER BY trade_date DESC").fetchall()
    conn.close()
    return [_row_to_trade(r) for r in rows]


def _row_to_trade(row) -> TradeRecord:
    return TradeRecord(
        id=row[0], stock_code=row[1], action=row[2],
        price=row[3], volume=row[4],
        date=date.fromisoformat(row[5]), note=row[6],
    )


def get_positions() -> List[dict]:
    """计算当前持仓。"""
    trades = list_trades()
    positions: dict = {}
    for t in trades:
        if t.stock_code not in positions:
            positions[t.stock_code] = {"buy_volume": 0, "sell_volume": 0, "buy_cost": 0, "trades": []}
        pos = positions[t.stock_code]
        pos["trades"].append(t)
        if t.action == "buy":
            pos["buy_volume"] += t.volume
            pos["buy_cost"] += t.price * t.volume
        else:
            pos["sell_volume"] += t.volume

    result = []
    for code, pos in positions.items():
        net = pos["buy_volume"] - pos["sell_volume"]
        if net <= 0:
            continue
        avg_cost = pos["buy_cost"] / pos["buy_volume"]
        result.append({
            "stock_code": code,
            "volume": net,
            "avg_cost": round(avg_cost, 2),
            "trade_count": len(pos["trades"]),
        })
    return result
