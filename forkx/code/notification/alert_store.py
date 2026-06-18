"""提醒存储。"""
import sqlite3
from pathlib import Path
from typing import List

from ..data.models import AlertRecord

_CONFIG_DIR = Path.home() / ".forkx"
_CONFIG_DIR.mkdir(exist_ok=True)
_DB_PATH = _CONFIG_DIR / "alerts.db"


def _get_conn():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id TEXT PRIMARY KEY,
            stock_code TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            threshold REAL NOT NULL,
            note TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def add_alert(alert: AlertRecord) -> str:
    conn = _get_conn()
    conn.execute(
        "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?)",
        (alert.id, alert.stock_code, alert.alert_type, alert.threshold,
         alert.note, 1 if alert.enabled else 0, alert.created_at.isoformat())
    )
    conn.commit()
    conn.close()
    return alert.id


def list_alerts(stock_code: str = None, enabled_only: bool = False) -> List[AlertRecord]:
    conn = _get_conn()
    query = "SELECT * FROM alerts WHERE 1=1"
    params = []
    if stock_code:
        query += " AND stock_code = ?"
        params.append(stock_code)
    if enabled_only:
        query += " AND enabled = 1"
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_row_to_alert(r) for r in rows]


def remove_alert(alert_id: str) -> bool:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def toggle_alert(alert_id: str, enabled: bool) -> bool:
    conn = _get_conn()
    cur = conn.execute("UPDATE alerts SET enabled = ? WHERE id = ?", (1 if enabled else 0, alert_id))
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def _row_to_alert(row) -> AlertRecord:
    from datetime import datetime
    return AlertRecord(
        id=row[0], stock_code=row[1], alert_type=row[2],
        threshold=row[3], note=row[4],
        enabled=bool(row[5]),
        created_at=datetime.fromisoformat(row[6]),
    )
