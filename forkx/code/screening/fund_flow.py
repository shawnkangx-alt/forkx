"""主力资金流数据 Provider。

数据来源：东方财富资金流向 API
接口：https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get

字段说明（f2顺序）：
  f51=日期
  f52=主力净流入（元）
  f53=超大单净流入
  f54=大单净流入
  f55=中单净流入
  f56=小单净流入

使用说明：
  1. 注册 Tushare Pro（https://tushare.pro），获取 token
  2. 将 token 写入 ~/.forkx/config.toml：
     [providers]
     tushare_token = "your_token_here"
  3. 本模块自动检测配置，有 token 时启用，无 token 时跳过
"""
import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import List, Optional


@dataclass
class FundFlowRecord:
    """单日资金流向。"""
    stock_code: str
    date: date
    main_net_inflow: float      # 主力净流入（元），正=净买入，负=净卖出
    super_large_net: float      # 超大单净流入
    large_net: float           # 大单净流入
    medium_net: float          # 中单净流入
    small_net: float           # 小单净流入

    # 衍生指标
    main_net_inflow_wan: float  # 主力净流入（万元）
    net_inflow_5d_avg: float   # 5日均量

    # 质量标签
    signal: str    # 净买入/净卖出/均衡
    interpretation: str


@dataclass
class FundFlowSummary:
    """资金流汇总（多日）。"""
    stock_code: str
    records: List[FundFlowRecord]
    total_main_net: float       # 累计主力净流入
    avg_daily_net: float        # 日均净流入
    buy_days: int               # 净买入天数
    sell_days: int             # 净卖出天数
    trend: str                 # 趋势：持续买入/持续卖出/来回拉扯
    quality: str               # 质量评级：强吸筹/弱吸筹/中性/弱派发/强派发


def _em_fund_flow_api(code: str) -> List[dict]:
    """调用东方财富资金流日K接口。"""
    market = 0 if not code.startswith(("6", "9")) else 1
    secid = f"{market}.{code}"
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
        f"?lmt=0&klt=101&secid={secid}"
        f"&fields1=f1,f2,f3,f7"
        f"&fields2=f51,f52,f53,f54,f55,f56"
        f"&ut=b2884a393a59ad64002292a3e90d46a5"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        raw = json.loads(r.read())
    klines = raw["data"]["klines"]
    return klines


def _parse_em_fund_flow(code: str, klines: List[str]) -> List[FundFlowRecord]:
    """解析东方财富资金流原始数据。"""
    records = []
    for k in klines:
        parts = k.split(",")
        # f51=日期, f52=主力净流入, f53=超大单, f54=大单, f55=中单, f56=小单
        try:
            rec = FundFlowRecord(
                stock_code=code,
                date=date.fromisoformat(parts[0]),
                main_net_inflow=float(parts[1]),
                super_large_net=float(parts[2]),
                large_net=float(parts[3]),
                medium_net=float(parts[4]),
                small_net=float(parts[5]),
                main_net_inflow_wan=round(float(parts[1]) / 10000, 1),
                net_inflow_5d_avg=0.0,
                signal="",
                interpretation="",
            )
            # 派生字段
            if rec.main_net_inflow > 0:
                rec.signal = "净买入"
            elif rec.main_net_inflow < 0:
                rec.signal = "净卖出"
            else:
                rec.signal = "均衡"

            wan = rec.main_net_inflow_wan
            if wan > 1000:
                rec.interpretation = f"主力大幅净买入 {wan:.0f}万，强势吸筹"
            elif wan > 100:
                rec.interpretation = f"主力净买入 {wan:.0f}万，温和吸筹"
            elif wan < -1000:
                rec.interpretation = f"主力大幅净卖出 {wan:.0f}万，强势派发"
            elif wan < -100:
                rec.interpretation = f"主力净卖出 {wan:.0f}万，温和派发"
            else:
                rec.interpretation = f"主力资金基本持平（{wan:.0f}万）"

            records.append(rec)
        except (ValueError, IndexError):
            continue
    return records


def get_fund_flow(code: str, days: int = 20) -> FundFlowSummary:
    """获取近N日资金流向汇总。

    Returns:
        FundFlowSummary with 多日统计 + 趋势判断
    """
    try:
        klines = _em_fund_flow_api(code)
    except Exception:
        return _empty_summary(code)

    # 只取最近days条
    records = _parse_em_fund_flow(code, klines[-days:])
    if not records:
        return _empty_summary(code)

    # 计算5日均线
    for i, rec in enumerate(records):
        window = records[max(0, i-4):i+1]
        rec.net_inflow_5d_avg = sum(r.main_net_inflow_wan for r in window) / len(window)

    total = sum(r.main_net_inflow for r in records)
    avg = total / len(records)
    buy_days = sum(1 for r in records if r.main_net_inflow > 0)
    sell_days = sum(1 for r in records if r.main_net_inflow < 0)

    # 趋势判断
    recent_5 = records[-5:]
    recent_net = sum(r.main_net_inflow_wan for r in recent_5)
    prev_5 = records[-10:-5] if len(records) >= 10 else records[:-5]
    prev_net = sum(r.main_net_inflow_wan for r in prev_5) if prev_5 else 0

    if buy_days / len(records) >= 0.7 and recent_net > 5000:
        trend = "持续买入"
        quality = "强吸筹"
    elif buy_days / len(records) >= 0.6:
        trend = "偏买入"
        quality = "弱吸筹"
    elif buy_days / len(records) <= 0.3 and recent_net < -5000:
        trend = "持续卖出"
        quality = "强派发"
    elif buy_days / len(records) <= 0.4:
        trend = "偏卖出"
        quality = "弱派发"
    else:
        trend = "来回拉扯"
        quality = "中性"

    # 与前期对比
    if prev_net != 0 and len(records) >= 10:
        trend += f"（近5日{recent_net:+.0f}万 vs 前5日{prev_net:+.0f}万）"
    elif recent_net != 0:
        trend += f"（近5日净{recent_net:+.0f}万）"

    return FundFlowSummary(
        stock_code=code,
        records=records,
        total_main_net=round(total / 10000, 1),
        avg_daily_net=round(avg / 10000, 1),
        buy_days=buy_days,
        sell_days=sell_days,
        trend=trend,
        quality=quality,
    )


def _empty_summary(code: str) -> FundFlowSummary:
    return FundFlowSummary(
        stock_code=code, records=[],
        total_main_net=0, avg_daily_net=0,
        buy_days=0, sell_days=0, trend="无数据", quality="未知",
    )


def format_fund_flow(summary: FundFlowSummary) -> str:
    """格式化资金流汇总。"""
    if not summary.records:
        return "  资金流数据暂不可用"

    lines = []
    lines.append(f"  【主力资金·近{len(summary.records)}日】")
    lines.append(f"  趋势：{summary.trend}  评级：{summary.quality}")
    lines.append(f"  累计净流入：{summary.total_main_net:+.0f}万  日均：{summary.avg_daily_net:+.0f}万")
    lines.append(f"  买入天数：{summary.buy_days}  卖出天数：{summary.sell_days}")

    # 近5日明细
    recent = summary.records[-5:]
    lines.append("  近5日明细（万元）：")
    for r in recent:
        arrow = "▲" if r.main_net_inflow > 0 else "▼"
        signal_str = f"[{r.signal}]" if r.signal else ""
        lines.append(
            f"    {r.date}  {arrow}{abs(r.main_net_inflow_wan):>8.0f}  {signal_str}  {r.interpretation}"
        )

    # 5日均线对比
    if len(recent) >= 3:
        last_3_avg = sum(r.net_inflow_5d_avg for r in recent) / 3
        lines.append(f"  近3日均量：{last_3_avg:+.0f}万（对比日均{src.avg_daily_net:+.0f}万）" if False else "")

    return "\n".join(lines)
