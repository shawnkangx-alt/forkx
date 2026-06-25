"""板块联动分析模块（2026-06-25 新增）。

功能：
- 基于 efinance 板块成分股数据，计算板块整体 RSI 区间
- 统计板块内个股主力资金流向分布（判断板块整体在吸筹还是派发）
- 当板块 RSI<35 且多数个股主力净流入 → 板块级别底背离信号
- 支持自选股所属板块的联动分析

数据来源：efinance.stock.get_members()
"""
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import date

from ..data.sina_provider import SinaProvider
from ..data.models import DailyQuote
from .indicators import calc_rsi, rsi_zone


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StockRSI:
    code: str
    name: str
    rsi: float
    main_net_wan: float       # 主力净流入（万元）
    pct_chg: float            # 涨跌幅 %


@dataclass
class SectorReport:
    sector_name: str
    stock_count: int
    avg_rsi: float
    rsi_zone: str             # 超买/超卖/中性等
    inflow_stock_count: int    # 主力净流入个股数
    outflow_stock_count: int   # 主力净流出个股数
    inflow_ratio: float        # 流入个股占比
    stocks: List[StockRSI]     # 成分股RSI列表
    composite_signal: str      # 板块综合信号
    interpretation: str
    watch_codes: List[str]     # 值得关注的自选股代码


# ─────────────────────────────────────────────────────────────────────────────
# 板块 RSI 计算
# ─────────────────────────────────────────────────────────────────────────────

def _calc_stock_rsi(code: str, name: str, sina: SinaProvider, fund_flow_provider=None,
                    days: int = 20) -> Optional[StockRSI]:
    """计算单只股票的 RSI 和主力净流入（精确值）。"""
    try:
        quotes = sina.get_daily_quotes(code, date(2026, 1, 1), date.today())
        if len(quotes) < 15:
            return None
        closes = [q.close for q in quotes]
        rsi_vals = calc_rsi(closes)
        rsi = rsi_vals[-1] if rsi_vals else 50.0
        pct_chg = quotes[-1].pct_chg if hasattr(quotes[-1], 'pct_chg') else 0.0

        # 用 FundFlowProvider 获取精确主力净流入
        main_net_wan = 0.0
        if fund_flow_provider:
            try:
                ff = fund_flow_provider.get_fund_flow(code, days=5)
                if ff and ff.records:
                    # 取最近5日合计
                    main_net_wan = sum(r.main_net_wan for r in ff.records[-5:])
            except Exception:
                pass

        return StockRSI(code=code, name=name, rsi=round(rsi, 1),
                        main_net_wan=round(main_net_wan, 0), pct_chg=round(pct_chg, 2))
    except Exception:
        return None


def get_sector_members(sector_name: str = "半导体") -> List[Dict]:
    """获取板块成分股列表。"""
    import efinance as ef
    try:
        df = ef.stock.get_members(sector_name)
        if df is None or df.empty:
            return []
        return df.to_dict('records')
    except Exception:
        return []


def analyze_sector(
    sector_name: str = "半导体",
    watch_codes: Optional[List[str]] = None,
    sample_size: int = 20,  # 最多分析成分股数量（避免API超时）
) -> SectorReport:
    """分析指定板块的整体状态。

    参数：
        sector_name: 板块名称，默认"半导体"
        watch_codes: 自选股代码列表（用于标注哪些值得重点关注）
        sample_size: 最大分析成分股数量

    返回：
        SectorReport：板块综合分析报告
    """
    import efinance as ef

    watch_codes = watch_codes or []
    sina = SinaProvider()

    # 获取成分股
    members = get_sector_members(sector_name)
    if not members:
        return SectorReport(
            sector_name=sector_name, stock_count=0,
            avg_rsi=0, rsi_zone="数据不足",
            inflow_stock_count=0, outflow_stock_count=0, inflow_ratio=0,
            stocks=[], composite_signal="无法分析",
            interpretation=f"板块【{sector_name}】成分股数据获取失败",
            watch_codes=[],
        )

    # 取前 sample_size 只（按权重排序，取最重要的）
    # members 已按权重降序
    sample = members[:sample_size]

    # 初始化 FundFlowProvider（精确资金流数据）
    from .fund_flow_provider import FundFlowProvider
    ff_provider = FundFlowProvider()

    # 计算每只股票的 RSI
    stock_rsis: List[StockRSI] = []
    for m in sample:
        code = str(m.get('股票代码', ''))
        name = str(m.get('股票名称', ''))
        if not code:
            continue
        sr = _calc_stock_rsi(code, name, sina, fund_flow_provider=ff_provider)
        if sr:
            stock_rsis.append(sr)

    if not stock_rsis:
        return SectorReport(
            sector_name=sector_name, stock_count=len(members),
            avg_rsi=0, rsi_zone="数据不足",
            inflow_stock_count=0, outflow_stock_count=0, inflow_ratio=0,
            stocks=[], composite_signal="无法分析",
            interpretation="RSI计算失败",
            watch_codes=[],
        )

    # 板块整体 RSI（成分股平均）
    avg_rsi = sum(s.rsi for s in stock_rsis) / len(stock_rsis)
    rsi_z = rsi_zone(avg_rsi)

    # 主力资金方向统计（用 pct_chg * vol_ratio 近似判断）
    # 涨+放量为净流入，跌+放量为净流出
    inflow_stocks = [s for s in stock_rsis if s.main_net_wan > 0]
    outflow_stocks = [s for s in stock_rsis if s.main_net_wan < 0]
    inflow_ratio = len(inflow_stocks) / len(stock_rsis) if stock_rsis else 0

    # 综合信号判断
    if avg_rsi < 35 and inflow_ratio >= 0.6:
        signal = "板块底背离+吸筹"
        interp = (
            f"板块RSI={avg_rsi:.0f}<35（超卖区域），且{inflow_ratio:.0%}个股主力净流入，"
            f"板块与资金共振反弹概率高。建议关注自选股中RSI<40且主力净流入的标的。"
        )
    elif avg_rsi < 35:
        signal = "板块超卖"
        interp = f"板块RSI={avg_rsi:.0f}<35（超卖区域），但资金尚未明显配合，持续观望。"
    elif avg_rsi > 70 and inflow_ratio >= 0.7:
        signal = "板块强势拉升"
        interp = f"板块RSI={avg_rsi:.0f}>70（超买），且{inflow_ratio:.0%}个股资金流入，短线上方仍有空间，注意利润锁定。"
    elif avg_rsi > 70:
        signal = "板块超买"
        interp = f"板块RSI={avg_rsi:.0f}>70（超买区域），注意短期调整风险。"
    elif avg_rsi > 60:
        signal = "板块偏强"
        interp = f"板块RSI={avg_rsi:.0f}，多头延续，趋势未坏。"
    else:
        signal = "板块中性"
        interp = f"板块RSI={avg_rsi:.0f}，无明显方向，等待信号。"

    # 标注自选股中值得关注的目标
    watch_targets = []
    if watch_codes:
        for s in stock_rsis:
            if s.code in watch_codes:
                watch_targets.append(s.code)
        # 同时找出自选股中RSI偏低且有资金流入的
        for s in stock_rsis:
            if s.code in watch_codes and s.rsi < 50 and s.main_net_wan > 0:
                watch_targets.append(s.code)
        watch_targets = list(dict.fromkeys(watch_targets))  # 去重保留顺序

    return SectorReport(
        sector_name=sector_name,
        stock_count=len(members),
        avg_rsi=round(avg_rsi, 1),
        rsi_zone=rsi_z,
        inflow_stock_count=len(inflow_stocks),
        outflow_stock_count=len(outflow_stocks),
        inflow_ratio=round(inflow_ratio, 2),
        stocks=stock_rsis,
        composite_signal=signal,
        interpretation=interp,
        watch_codes=watch_targets,
    )


def format_sector_report(report: SectorReport) -> str:
    """格式化板块分析报告为可读字符串。"""
    lines = [
        "=" * 56,
        f"  板块分析  【{report.sector_name}】",
        "=" * 56,
        f"  成分股总数：{report.stock_count}（本次采样{len(report.stocks)}只）",
        "",
        f"  板块整体RSI：{report.avg_rsi}  —  {report.rsi_zone}",
        f"  资金流向：{report.inflow_stock_count}只净流入 / {report.outflow_stock_count}只净流出",
        f"  流入个股占比：{report.inflow_ratio:.0%}",
        "",
        f"  综合信号：{report.composite_signal}",
        f"  {report.interpretation}",
    ]

    if report.watch_codes:
        watch_in_report = [s for s in report.stocks if s.code in report.watch_codes]
        if watch_in_report:
            lines.append("")
            lines.append(f"  自选股机会（板块内）：")
            for s in sorted(watch_in_report, key=lambda x: x.rsi):
                flow = "▲净流入" if s.main_net_wan > 0 else "▼净流出"
                rsi_tag = "🔴超卖" if s.rsi < 35 else ("⚠️偏弱" if s.rsi < 50 else "✅偏强")
                lines.append(f"    {s.name}({s.code}) RSI={s.rsi} {rsi_tag} {flow} {s.pct_chg:+.2f}%")

    lines.append("=" * 56)
    return "\n".join(lines)
