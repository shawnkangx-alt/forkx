"""交易日志 — 记录每一笔实际交易，建立「信号→结果」反馈闭环。

每次建仓/止损/止盈后手动记录（或 cronjob 自动记录触发信号的交易），
定期 review 时对照当时的信号标签，找出真正有效的信号组合。

表结构：
  trades — 交易记录
    id, stock_code, entry_date, entry_price, stop_loss, position_size,
    exit_date, exit_price, outcome, pnl_pct,
    trigger_signal, note, created_at
"""
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Optional

DB_PATH = Path.home() / ".forkx" / "history.db"


class Outcome(str, Enum):
    HOLDING = "holding"     # 未平仓
    STOP_LOSS = "stop_loss" # 止损
    TAKE_PROFIT = "take_profit"  # 止盈
    SOLD = "sold"           # 主动卖出（不算止盈也不算止损）


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    stock_code: str = ""
    entry_date: Optional[date] = None
    entry_price: float = 0.0
    stop_loss: float = 0.0
    position_size: int = 0
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    outcome: Outcome = Outcome.HOLDING
    pnl_pct: float = 0.0
    trigger_signal: str = ""
    note: str = ""
    id: Optional[int] = None
    created_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 数据库
# ─────────────────────────────────────────────────────────────────────────────

def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code    TEXT    NOT NULL,
            entry_date    TEXT    NOT NULL,
            entry_price   REAL    NOT NULL,
            stop_loss     REAL,
            position_size INTEGER,
            exit_date     TEXT,
            exit_price    REAL,
            outcome       TEXT,
            pnl_pct       REAL    DEFAULT 0,
            trigger_signal TEXT,
            note          TEXT,
            created_at    TEXT,
            UNIQUE(stock_code, entry_date)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_stock ON trades(stock_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_entry ON trades(entry_date)")
    return conn


def save_trade(trade: TradeRecord) -> int:
    """保存/更新交易记录。返回 trade_id。"""
    conn = _get_conn()
    now = datetime.now().isoformat()

    if trade.id is None:
        conn.execute("""
            INSERT OR REPLACE INTO trades
            (stock_code, entry_date, entry_price, stop_loss, position_size,
             exit_date, exit_price, outcome, pnl_pct, trigger_signal, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.stock_code,
            trade.entry_date.isoformat() if trade.entry_date else None,
            trade.entry_price,
            trade.stop_loss,
            trade.position_size,
            trade.exit_date.isoformat() if trade.exit_date else None,
            trade.exit_price,
            trade.outcome.value if isinstance(trade.outcome, Outcome) else trade.outcome,
            trade.pnl_pct,
            trade.trigger_signal,
            trade.note,
            trade.created_at or now,
        ))
    else:
        conn.execute("""
            UPDATE trades SET
                exit_date     = ?,
                exit_price    = ?,
                outcome       = ?,
                pnl_pct       = ?,
                note          = ?
            WHERE id = ?
        """, (
            trade.exit_date.isoformat() if trade.exit_date else None,
            trade.exit_price,
            trade.outcome.value if isinstance(trade.outcome, Outcome) else trade.outcome,
            trade.pnl_pct,
            trade.note,
            trade.id,
        ))
    conn.commit()
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return rid


def get_trades(stock_code: Optional[str] = None,
               outcome: Optional[Outcome] = None,
               days: int = 0) -> List[TradeRecord]:
    """查询交易记录。"""
    conn = _get_conn()
    q = "SELECT id, stock_code, entry_date, entry_price, stop_loss, position_size, exit_date, exit_price, outcome, pnl_pct, trigger_signal, note, created_at FROM trades WHERE 1=1"
    args = []
    if stock_code:
        q += " AND stock_code = ?"
        args.append(stock_code)
    if outcome:
        q += " AND outcome = ?"
        args.append(outcome.value)
    if days > 0:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        q += " AND entry_date >= ?"
        args.append(cutoff)
    q += " ORDER BY entry_date DESC"

    rows = conn.execute(q, args).fetchall()
    conn.close()

    return [
        TradeRecord(
            id=r[0], stock_code=r[1],
            entry_date=date.fromisoformat(r[2]),
            entry_price=r[3], stop_loss=r[4] or 0,
            position_size=r[5] or 0,
            exit_date=date.fromisoformat(r[6]) if r[6] else None,
            exit_price=r[7],
            outcome=Outcome(r[8]) if r[8] else Outcome.HOLDING,
            pnl_pct=r[9] or 0,
            trigger_signal=r[10] or "",
            note=r[11] or "",
            created_at=r[12],
        )
        for r in rows
    ]


def close_trade(trade_id: int, exit_date: date, exit_price: float,
                outcome: Outcome, note: str = "") -> bool:
    """平仓：更新 exit_date / exit_price / outcome，自动算 pnl_pct。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT entry_price, stop_loss FROM trades WHERE id=?", (trade_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    entry_price = row[0]
    pnl_pct = (exit_price - entry_price) / entry_price * 100
    conn.execute("""
        UPDATE trades SET exit_date=?, exit_price=?, outcome=?, pnl_pct=?, note=?
        WHERE id=?
    """, (exit_date.isoformat(), exit_price, outcome.value, pnl_pct, note, trade_id))
    conn.commit()
    conn.close()
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 反馈分析
# ─────────────────────────────────────────────────────────────────────────────

def review_trades(days: int = 90) -> dict:
    """复盘近 N 日交易，计算各触发信号的胜率/盈亏比。

    返回结构：
    {
        "total": N,
        "win_rate": 0.x,
        "avg_pnl": x.x,
        "by_signal": {
            "RSI底背离+主力流入": {"count": N, "wins": N, "win_rate": 0.x, "avg_pnl": x.x},
            ...
        }
    }
    """
    trades = get_trades(days=days)
    # 排除未平仓
    closed = [t for t in trades if t.outcome != Outcome.HOLDING]
    if not closed:
        return {"total": 0, "win_rate": 0, "avg_pnl": 0, "by_signal": {}}

    wins = [t for t in closed if t.pnl_pct > 0]
    win_rate = len(wins) / len(closed)
    avg_pnl = sum(t.pnl_pct for t in closed) / len(closed)

    # 按触发信号分组
    by_signal: dict = {}
    for t in closed:
        sigs = [s.strip() for s in t.trigger_signal.split(",") if s.strip()]
        for sig in sigs:
            if sig not in by_signal:
                by_signal[sig] = {"count": 0, "wins": 0, "total_pnl": 0.0}
            by_signal[sig]["count"] += 1
            if t.pnl_pct > 0:
                by_signal[sig]["wins"] += 1
            by_signal[sig]["total_pnl"] += t.pnl_pct

    for sig, s in by_signal.items():
        s["win_rate"] = round(s["wins"] / s["count"], 3) if s["count"] else 0
        s["avg_pnl"] = round(s["total_pnl"] / s["count"], 2) if s["count"] else 0

    return {
        "total": len(closed),
        "win_rate": round(win_rate, 3),
        "avg_pnl": round(avg_pnl, 2),
        "by_signal": by_signal,
    }


def format_review(review: dict) -> str:
    """格式化复盘结果。"""
    if review["total"] == 0:
        return "暂无已平仓交易记录，无法复盘。"

    lines = [
        "=" * 52,
        "  交易复盘报告",
        "=" * 52,
        f"  总交易数：{review['total']}  胜率：{review['win_rate']:.1%}  平均盈亏：{review['avg_pnl']:+.2f}%",
        "",
    ]

    by_sig = review["by_signal"]
    if by_sig:
        lines.append("  各信号胜率/盈亏比：")
        # 按样本数排序
        sorted_sigs = sorted(by_sig.items(), key=lambda x: x[1]["count"], reverse=True)
        for sig, s in sorted_sigs:
            tag = "✅" if s["win_rate"] >= 0.6 else ("⚠️" if s["count"] >= 3 else "  ")
            lines.append(
                f"  {tag} {sig}: {s['count']}笔  胜率{s['win_rate']:.1%}  均盈{s['avg_pnl']:+.2f}%"
            )
    else:
        lines.append("  （无带触发信号的记录）")

    lines.append("=" * 52)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# CLI 子命令
# ─────────────────────────────────────────────────────────────────────────────

def cmd_trade(args) -> None:
    """forkx trade <action> ..."""
    action = args.action

    if action == "log":
        # forkx trade log 688521 --entry 1500 --sl 1400 --size 100 --signal RSI底背离
        t = TradeRecord(
            stock_code=args.stock,
            entry_date=date.fromisoformat(args.entry_date) if args.entry_date else date.today(),
            entry_price=float(args.entry),
            stop_loss=float(args.sl) if args.sl else 0,
            position_size=int(args.size) if args.size else 0,
            trigger_signal=args.signal or "",
            note=args.note or "",
        )
        rid = save_trade(t)
        print(f"✅ 已记录入场：{args.stock} @{args.entry}  (id={rid})")

    elif action == "close":
        # forkx trade close <trade_id> --exit <price> --outcome stop_loss|take_profit|sold
        t = TradeRecord(
            id=int(args.trade_id),
            exit_price=float(args.exit),
            exit_date=date.fromisoformat(args.exit_date) if args.exit_date else date.today(),
            outcome=Outcome(args.outcome),
            note=args.note or "",
        )
        # 先拿 entry 信息
        conn = _get_conn()
        row = conn.execute(
            "SELECT entry_price FROM trades WHERE id=?", (t.id,)
        ).fetchone()
        conn.close()
        if not row:
            print(f"❌ 找不到 trade_id={t.id}")
            return
        t.entry_price = row[0]
        t.pnl_pct = (t.exit_price - t.entry_price) / t.entry_price * 100
        save_trade(t)
        print(f"✅ 已平仓：id={t.id}  结局={t.outcome.value}  盈亏={t.pnl_pct:+.2f}%")

    elif action == "list":
        trades = get_trades(stock_code=args.stock, days=int(args.days) if args.days else 0)
        if not trades:
            print("暂无交易记录。")
            return
        for t in trades:
            status = "🔴止损" if t.outcome == Outcome.STOP_LOSS else ("🟢止盈" if t.outcome == Outcome.TAKE_PROFIT else ("🟡持仓" if t.outcome == Outcome.HOLDING else "⚪卖"))
            print(f"  [{t.id}] {t.stock_code} {t.entry_date} @{t.entry_price:.2f}  {status}  信号:{t.trigger_signal}")

    elif action == "review":
        r = review_trades(days=int(args.days) if args.days else 90)
        print(format_review(r))

    else:
        print(f"未知操作：{action}")


def register_trade_parser(sub):
    """注册 trade 子命令到 argparse。"""
    tr = sub.add_parser("trade", help="交易日志管理")
    tr.add_argument("action", choices=["log", "close", "list", "review"],
                    help="log=记录入场, close=平仓, list=查询, review=复盘")
    tr.add_argument("--stock", help="股票代码（log时）")
    tr.add_argument("--entry", help="入场价格（log时）")
    tr.add_argument("--entry-date", dest="entry_date", help="入场日期 YYYY-MM-DD（log时）")
    tr.add_argument("--sl", dest="sl", help="止损价（log时）")
    tr.add_argument("--size", help="股数（log时）")
    tr.add_argument("--signal", help="触发信号标签（log时，多个用逗号）")
    tr.add_argument("--note", help="备注")
    tr.add_argument("--trade-id", dest="trade_id", help="交易ID（close时）")
    tr.add_argument("--exit", help="出场价格（close时）")
    tr.add_argument("--exit-date", dest="exit_date", help="出场日期 YYYY-MM-DD（close时）")
    tr.add_argument("--outcome", choices=["stop_loss", "take_profit", "sold"],
                    help="结局（close时）")
    tr.add_argument("--days", help="查询近N天（list/review时）")
    tr.set_defaults(func=cmd_trade)
