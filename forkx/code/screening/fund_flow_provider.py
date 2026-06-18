"""资金流 Provider — 基于 efinance 的 Level2 数据源。

数据来源：efinance.stock.get_today_bill
- 每分钟一条记录（累计值）
- 字段：主力净流入、超大单净流入、大单净流入、中单净流入、小单净流入
- 特点：不需要token，不需要代理，直接调用东方财富接口

数据说明：
- 每行是从开盘到该分钟的累计值，需 diff 还原单笔流量
- 最后一行为当日收盘总合计

接入方式：
  from .fund_flow_provider import FundFlowProvider, format_fund_flow_summary
  ff = FundFlowProvider().get_fund_flow('002371', days=20)
  print(format_fund_flow_summary(ff))
"""
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional

import efinance as ef


@dataclass
class MinuteFundFlow:
    """单分钟资金流（还原后的单笔流量）。"""
    time: str          # HH:MM
    main_net: float    # 主力净流入（元），正=净买入
    super_large: float  # 超大单净流入
    large: float       # 大单净流入
    medium: float      # 中单净流入
    small: float       # 小单净流入

    # 衍生
    main_net_wan: float = 0.0

    def __post_init__(self):
        self.main_net_wan = round(self.main_net / 10000, 1)


@dataclass
class HourlyFundFlow:
    """每小时资金流汇总。"""
    hour: str          # HH:MM
    main_net_wan: float
    buy_minutes: int
    sell_minutes: int


@dataclass
class FundFlowRecord:
    """单日资金流向。"""
    date: date
    main_net_inflow: float   # 主力净流入（元）
    super_large_net: float
    large_net: float
    medium_net: float
    small_net: float
    main_net_wan: float
    signal: str

    # 仅今日有
    hourly: List[HourlyFundFlow] = field(default_factory=list)
    minute_records: List[MinuteFundFlow] = field(default_factory=list)


@dataclass
class FundFlowSummary:
    """资金流多日汇总。"""
    stock_code: str
    records: List[FundFlowRecord]
    quality: str
    trend: str
    total_net_wan: float
    buy_days: int
    sell_days: int


# ----------------------------------------------------------------------
# 今日 Level2 数据获取
# ----------------------------------------------------------------------

def _get_today_minute_flow(code: str) -> Optional[FundFlowRecord]:
    """获取今日逐分钟资金流（efinance Level2）。

    返回：FundFlowRecord（含小时级+分钟级明细分层）
    """
    warnings.filterwarnings('ignore')
    try:
        df = ef.stock.get_today_bill(code)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    # 判断是否为今日数据（efinance返回的是最近交易日）
    # 用最后一行的"时间"字段判断
    last_time = df['时间'].iloc[-1]
    try:
        dt = datetime.strptime(last_time, '%Y-%m-%d %H:%M')
        if dt.date() != date.today():
            return None  # 不是今日，跳过
    except ValueError:
        return None

    # 累计值 → 单笔流量（diff）
    for col in ['主力净流入', '超大单净流入', '大单净流入', '中单净流入', '小单净流入']:
        df[f'{col}_diff'] = df[col].diff().fillna(df[col])

    # 还原时间（取分钟部分）
    df['time'] = df['时间'].str[11:]  # 'YYYY-MM-DD HH:MM' → 'HH:MM'

    # 构建分钟级记录
    minute_records = []
    for _, row in df.iterrows():
        minute_records.append(MinuteFundFlow(
            time=row['time'],
            main_net=float(row['主力净流入_diff']),
            super_large=float(row['超大单净流入_diff']),
            large=float(row['大单净流入_diff']),
            medium=float(row['中单净流入_diff']),
            small=float(row['小单净流入_diff']),
        ))

    # 小时级汇总
    hourly = _aggregate_hourly(df)

    # 当日总计（取最后一行的累计值，即收盘总合计）
    last = df.iloc[-1]
    total_main = float(last['主力净流入'])
    total_super = float(last['超大单净流入'])
    total_large = float(last['大单净流入'])

    return FundFlowRecord(
        date=date.today(),
        main_net_inflow=total_main,
        super_large_net=total_super,
        large_net=total_large,
        medium_net=float(last['中单净流入']),
        small_net=float(last['小单净流入']),
        main_net_wan=round(total_main / 10000, 1),
        signal='净买入' if total_main > 0 else '净卖出',
        hourly=hourly,
        minute_records=minute_records,
    )


def _aggregate_hourly(df) -> List[HourlyFundFlow]:
    """按小时聚合资金流。"""
    hourly_list = []
    for h in range(9, 16):
        hour_str = f'{h:02d}'
        hour_df = df[df['time'].str.startswith(hour_str)]
        if hour_df.empty:
            continue
        diff_col = '主力净流入_diff'
        vals = hour_df[diff_col]
        hourly_list.append(HourlyFundFlow(
            hour=f'{h:02d}:00',
            main_net_wan=round(vals.sum() / 10000, 1),
            buy_minutes=int((vals > 0).sum()),
            sell_minutes=int((vals < 0).sum()),
        ))
    return hourly_list


# ----------------------------------------------------------------------
# 历史日级数据（腾讯日K成交额估算）
# ----------------------------------------------------------------------

def _get_historical_fund_flow(code: str, days: int) -> List[FundFlowRecord]:
    """基于新浪日K成交额估算历史每日资金流（降级方案）。"""
    from ..data.sina_provider import SinaProvider

    end = date.today()
    start = date(end.year, 1, 1) if end.month <= 2 else date(end.year, end.month - 2, 1)

    quotes = SinaProvider().get_daily_quotes(code, start, end)
    if not quotes:
        return []

    quotes = quotes[-days:] if len(quotes) >= days else quotes
    # 估算成交额（万元）
    avg_amount = sum(
        q.amount if q.amount > 0 else (q.high + q.low + q.close) / 3 * q.volume
        for q in quotes if q.volume > 0
    ) / len(quotes)

    records = []
    for q in quotes:
        if q.volume <= 0:
            continue
        amount = q.amount if q.amount > 0 else (q.high + q.low + q.close) / 3 * q.volume
        ratio = amount / avg_amount if avg_amount > 0 else 1.0

        if ratio > 1.5 and q.close >= q.open:
            net_wan = round(amount * 0.3 * (q.close - q.open) / q.open, 1)
            signal = "净买入"
        elif ratio > 1.5 and q.close < q.open:
            net_wan = round(-amount * 0.3 * (q.open - q.close) / q.open, 1)
            signal = "净卖出"
        elif ratio < 0.5:
            net_wan, signal = 0.0, "均衡"
        else:
            net_wan = round(amount * 0.1 * (q.close - q.open) / q.open, 1)
            signal = "均衡" if abs(net_wan) < 10 else ("净买入" if net_wan > 0 else "净卖出")

        records.append(FundFlowRecord(
            date=q.date,
            main_net_inflow=net_wan * 10000,
            super_large_net=0, large_net=0, medium_net=0, small_net=0,
            main_net_wan=net_wan,
            signal=signal,
        ))
    return records


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------

class FundFlowProvider:
    """资金流 Provider。

    数据源优先级：
    1. efinance（今日Level2，逐分钟主力资金流，无需token/代理）
    2. 新浪日K估算（历史数据，降级方案）
    """

    def get_fund_flow(self, stock_code: str, days: int = 20) -> FundFlowSummary:
        """获取近N日资金流。

        - 今日：efinance Level2 精确数据
        - 历史：新浪日K成交额估算
        """
        # 今日
        today_record = _get_today_minute_flow(stock_code)

        # 历史
        hist_records = _get_historical_fund_flow(stock_code, days)

        # 合并：efinance今日数据优先级最高（Level2精确值）
        # 如果历史里已有今日，先删掉（估算值不可靠）
        if today_record:
            hist_records = [r for r in hist_records if r.date != today_record.date]
            hist_records.append(today_record)

        # 只取最近days条
        records = sorted(hist_records, key=lambda r: r.date)[-days:]

        return self._summarize(stock_code, records)

    def _summarize(self, code: str, records: List[FundFlowRecord]) -> FundFlowSummary:
        if not records:
            return FundFlowSummary(code, [], "无数据", "暂无数据", 0, 0, 0)

        total_net = sum(r.main_net_wan for r in records)
        buy_days = sum(1 for r in records if r.main_net_wan > 50)
        sell_days = sum(1 for r in records if r.main_net_wan < -50)

        recent = records[-5:]
        prev = records[-10:-5] if len(records) >= 10 else records[:-5]
        recent_net = sum(r.main_net_wan for r in recent)
        prev_net = sum(r.main_net_wan for r in prev) if prev else 0

        ratio = buy_days / len(records)
        if ratio >= 0.7 and recent_net > 5000:
            quality = "强吸筹"
        elif ratio >= 0.55:
            quality = "弱吸筹"
        elif ratio <= 0.3 and recent_net < -5000:
            quality = "强派发"
        elif ratio <= 0.45:
            quality = "弱派发"
        else:
            quality = "中性"

        if recent_net > 5000:
            trend = f"持续买入（近5日{recent_net:+.0f}万 vs 前5日{prev_net:+.0f}万）" if prev_net else f"持续买入（近5日{recent_net:+.0f}万）"
        elif recent_net < -5000:
            trend = f"持续卖出（近5日{recent_net:+.0f}万 vs 前5日{prev_net:+.0f}万）" if prev_net else f"持续卖出（近5日{recent_net:+.0f}万）"
        else:
            trend = f"来回拉扯（近5日{recent_net:+.0f}万 vs 前5日{prev_net:+.0f}万）" if prev_net else f"中性（近5日{recent_net:+.0f}万）"

        return FundFlowSummary(
            stock_code=code,
            records=records,
            quality=quality,
            trend=trend,
            total_net_wan=round(total_net, 1),
            buy_days=buy_days,
            sell_days=sell_days,
        )


def format_fund_flow_summary(summary: FundFlowSummary) -> str:
    """格式化资金流汇总。"""
    if not summary.records:
        return ""

    today_record = summary.records[-1] if summary.records else None

    lines = []
    lines.append(f"  【主力资金·近{len(summary.records)}日】")
    lines.append(f"  {summary.quality}  {summary.trend}")
    lines.append(f"  累计净流入：{summary.total_net_wan:+.0f}万  买入{summary.buy_days}天/卖出{summary.sell_days}天")

    # 近5日明细
    recent = summary.records[-5:]
    parts = []
    for r in recent:
        arrow = "▲" if r.main_net_wan > 0 else "▼" if r.main_net_wan < 0 else "―"
        parts.append(f"{r.date}[{arrow}{abs(r.main_net_wan):.0f}万]")
    lines.append(f"  近5日：{'  '.join(parts)}")

    # 今日分层（efinance Level2才有）
    if today_record and today_record.hourly:
        lines.append("  今日逐时：")
        for h in today_record.hourly:
            arrow = "▲" if h.main_net_wan > 0 else "▼" if h.main_net_wan < 0 else "―"
            lines.append(
                f"    {h.hour}  {arrow}{abs(h.main_net_wan):>8.0f}万"
                f"  买{h.buy_minutes}分钟/卖{h.sell_minutes}分钟"
            )

    return "\n".join(lines)
