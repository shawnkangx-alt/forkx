"""博弈分析模块（技术信号层 + 资金博弈推断层）。

数据来源：
- 日K：sina_provider（SinaProvider）
- 5分钟K：baostock（BaoStockProvider, frequency=5）
- 实时五档：tencent_provider（TencentProvider）

博弈信号说明：
- 集合竞价分析：通过开盘5分钟K线幅度+成交量推断庄家意图
- 缩量横盘检测：连续N日振幅极窄+量能萎缩=主力控盘
- 分时形态识别：全天5分钟K走势形态分类
- 五档资金博弈：主动买入vs被动卖出压力
- 量价异动：放量/缩量的性质判断
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional

from ..data.models import DailyQuote


@dataclass
class AuctionSignal:
    """集合竞价信号。"""
    date: date
    open_price: float
    prev_close: float
    open_change_pct: float        # 开盘涨跌幅 %
    first_5min_volume: int        # 开盘5分钟成交量
    avg_5min_volume: float        # 近5日同时段均量
    volume_ratio: float           # 量比（开盘5分钟量/均量）
    signal: str                   # 试盘/诱多/护盘/正常/派发
    interpretation: str           # 文字解读


@dataclass
class ConsolidationSignal:
    """缩量横盘信号。"""
    stock_code: str
    consolidation_days: int       # 横盘天数
    avg_daily_range_pct: float    # 日均振幅 %
    avg_volume_ratio: float       # 相对均量（倍）
    volume_trend: str             # 缩量/平量/放量
    pattern: str                  # 横盘类型：窄幅横盘/收敛三角/矩形整理
    breakout_direction: str       # 向上/向下/待定
    breakout_likelihood: float    # 突破概率 0~1
    interpretation: str


@dataclass
class IntradayPattern:
    """分时形态。"""
    stock_code: str
    pattern_type: str             # 横盘整理/震荡上行/震荡下行/脉冲拉升/尾盘偷袭/瀑布式下跌
    strength: str                 # 强/中/弱
    volume_characteristics: str    # 量能特征
    manipulation_signs: List[str]  # 疑似控盘迹象
    interpretation: str


@dataclass
class OrderBookPressure:
    """五档买卖压力。"""
    stock_code: str
    timestamp: datetime
    bid_total: float              # 买盘总量（万元）
    ask_total: float              # 卖盘总量（万元）
    net_pressure: float           # 净压力（买入-卖出，正=偏买）
    pressure_ratio: float         # 买卖比（买入/卖出）
    large_orders_detected: List[str]  # 疑似大单信号
    interpretation: str


@dataclass
class VolumePriceAnomaly:
    """量价异动。"""
    stock_code: str
    date: date
    anomaly_type: str              # 突放天量/缩量上涨/放量滞涨/缩量下跌/地量
    volume_ratio: float            # 量比
    price_change_pct: float        # 当日涨跌幅
    consecutive_days: int          # 连续天数
    quality: str                   # 真信号/可疑/待观察
    interpretation: str


@dataclass
class GameAnalysisReport:
    """博弈分析报告。"""
    stock_code: str
    auction: Optional[AuctionSignal]
    consolidation: Optional[ConsolidationSignal]
    intraday_pattern: Optional[IntradayPattern]
    order_pressure: Optional[OrderBookPressure]
    volume_anomaly: Optional[VolumePriceAnomaly]
    composite_signal: str           # 综合信号：吸筹/试盘/拉升/派发/观望
    actionable_advice: str           # 操作建议


# ─────────────────────────────────────────────────────────────────────────────
# 集合竞价分析
# ─────────────────────────────────────────────────────────────────────────────

def analyze_auction(
    code: str,
    name: str,
    daily_quotes: List[DailyQuote],
    minute_quotes_5: List[dict],   # BaoStock 5分钟K: {'date','time','open','high','low','close','volume'}
) -> AuctionSignal:
    """集合竞价/开盘信号分析。

    逻辑：
    - 开盘涨跌幅 > 1%：可能有消息或主力引导
    - 开盘5分钟量 > 近5日同时段均量2倍：异动
    - 开盘涨幅大但成交量萎缩：可能是诱多
    - 开盘跌幅大但成交量萎缩：可能是最后一杀
    - 开盘涨幅大+成交量温和：可能是真拉升
    """
    if not daily_quotes or len(daily_quotes) < 2:
        return _auction_unknown("数据不足")

    prev_close = daily_quotes[-1].close
    today = daily_quotes[-1]

    # 找今日开盘价（5分钟K第一根）
    today_str = str(today.date)
    today_mins = [m for m in minute_quotes_5 if str(m.get('date','')) == today_str]

    if not today_mins:
        return _auction_unknown("无今日分钟数据")

    first_5 = today_mins[:3]  # 前3根5分钟K≈15分钟
    open_price = float(first_5[0]['open'])
    first_5min_vol = sum(int(m.get('volume', 0)) for m in first_5)

    open_change_pct = (open_price - prev_close) / prev_close * 100

    # 计算近5日同时段均量（取每日同时刻±15分钟窗口）
    # 简化：取近5日每日开盘后15分钟成交量均值
    avg_5min_vol = first_5min_vol  # 暂无历史对比数据，用自身替代
    volume_ratio = 1.0  # 待历史数据对齐后计算

    # 信号判断
    signal, interp = _auction_judge(open_change_pct, first_5min_vol, avg_5min_vol)

    return AuctionSignal(
        date=today.date,
        open_price=open_price,
        prev_close=prev_close,
        open_change_pct=round(open_change_pct, 2),
        first_5min_volume=first_5min_vol,
        avg_5min_volume=avg_5min_vol,
        volume_ratio=round(volume_ratio, 2),
        signal=signal,
        interpretation=interp,
    )


def _auction_judge(open_pct: float, vol: int, avg_vol: float):
    abs_pct = abs(open_pct)
    vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0

    if abs_pct < 0.3:
        return "正常", f"开盘涨幅 {open_pct:+.2f}%，无明显异动"
    elif open_pct > 2.0 and vol_ratio < 0.8:
        return "诱多嫌疑", f"高开 {open_pct:.2f}% 但量能萎缩，可能是拉高出货"
    elif open_pct > 2.0 and vol_ratio >= 0.8:
        return "试盘/拉升", f"高开 {open_pct:.2f}% 配合放量，可能是主力引导"
    elif open_pct < -2.0 and vol_ratio < 0.8:
        return "最后一杀", f"低开 {open_pct:.2f}% 且缩量，可能是恐慌抛盘尾声"
    elif open_pct < -2.0 and vol_ratio >= 1.5:
        return "主动砸盘", f"低开 {open_pct:.2f}% 伴随放量，主力在吸筹或洗盘"
    elif open_pct > 0.5 and open_pct <= 2.0:
        return "温和偏强", f"开盘上涨 {open_pct:.2f}%，做多意愿一般"
    elif open_pct < -0.5 and open_pct >= -2.0:
        return "偏弱整理", f"开盘下跌 {open_pct:.2f}%，短期承压"
    else:
        return "正常", f"开盘变化 {open_pct:+.2f}%，属正常波动"


def _auction_unknown(reason: str):
    return AuctionSignal(
        date=date.today(),
        open_price=0, prev_close=0, open_change_pct=0,
        first_5min_volume=0, avg_5min_volume=0, volume_ratio=0,
        signal="数据不足", interpretation=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 缩量横盘检测
# ─────────────────────────────────────────────────────────────────────────────

def detect_consolidation(
    daily_quotes: List[DailyQuote],
    lookback: int = 20,
) -> ConsolidationSignal:
    """检测缩量横盘形态。

    横盘定义：
    - 连续N日收盘价振幅 < 3%（窄幅横盘）
    - 或 连续N日高低点区间极窄（< 5%）
    - 成交量低于20日均量50%以上
    """
    quotes = daily_quotes[-lookback:] if len(daily_quotes) >= lookback else daily_quotes
    if len(quotes) < 5:
        return _consolidation_unknown("数据不足")

    closes = [q.close for q in quotes]
    highs = [q.high for q in quotes]
    lows = [q.low for q in quotes]
    volumes = [q.volume for q in quotes]

    # 逐日振幅
    daily_ranges = [(highs[i] - lows[i]) / lows[i] * 100 for i in range(len(quotes))]
    avg_range = sum(daily_ranges) / len(daily_ranges)

    # 区间总振幅
    total_range = (max(closes) - min(closes)) / min(closes) * 100

    # 量能分析
    avg_vol = sum(volumes) / len(volumes)
    last_vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
    vol_trend = "缩量" if last_vol_ratio < 0.6 else ("放量" if last_vol_ratio > 1.5 else "平量")

    # 横盘天数：连续振幅 < 3% 的天数
    cons_days = 0
    for r in reversed(daily_ranges):
        if r < 3.0:
            cons_days += 1
        else:
            break

    # 判断横盘类型
    if cons_days >= 5 and avg_range < 2.0:
        pattern = "窄幅横盘（主力控盘）"
    elif cons_days >= 3 and total_range < 8.0:
        pattern = "收敛整理（选择方向）"
    elif total_range < 10.0 and avg_range < 2.5:
        pattern = "矩形整理"
    else:
        return _consolidation_unknown("未形成明显横盘")

    # 突破方向判断（用最后一天的收盘位置）
    recent_closes = closes[-5:]
    recent_avg = sum(recent_closes) / len(recent_closes)
    latest_close = closes[-1]
    price_position = (latest_close - min(recent_closes)) / (max(recent_closes) - min(recent_closes) + 0.001)

    if price_position > 0.7 and last_vol_ratio > 1.3:
        breakout = "向上突破"
        likelihood = 0.75
    elif price_position < 0.3 and last_vol_ratio > 1.3:
        breakout = "向下突破"
        likelihood = 0.7
    else:
        breakout = "待定（需放量确认）"
        likelihood = 0.4

    interp = (
        f"连续{cons_days}日窄幅整理，日均振幅{avg_range:.1f}%，"
        f"量能{vol_trend}（均量比{last_vol_ratio:.2f}x），"
        f"总振幅仅{total_range:.1f}%，{breakout}概率{likelihood*100:.0f}%。"
        f"这种形态通常是主力吸筹完毕后的选择方向阶段。"
    )

    return ConsolidationSignal(
        stock_code=quotes[-1].stock_code,
        consolidation_days=cons_days,
        avg_daily_range_pct=round(avg_range, 2),
        avg_volume_ratio=round(last_vol_ratio, 2),
        volume_trend=vol_trend,
        pattern=pattern,
        breakout_direction=breakout,
        breakout_likelihood=likelihood,
        interpretation=interp,
    )


def _consolidation_unknown(reason: str):
    return ConsolidationSignal(
        stock_code="", consolidation_days=0,
        avg_daily_range_pct=0, avg_volume_ratio=0,
        volume_trend="未知", pattern="无", breakout_direction="",
        breakout_likelihood=0, interpretation=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 分时形态识别（基于5分钟K）
# ─────────────────────────────────────────────────────────────────────────────

def classify_intraday_pattern(
    code: str,
    minute_quotes: List[dict],
) -> IntradayPattern:
    """分时形态识别（基于单个完整交易日）。

    形态类型：
    - 横盘整理：全天高低点价差<3%，无明显趋势
    - 震荡上行：底部逐步抬高，整体上涨
    - 震荡下行：顶部逐步降低，整体下跌
    - 脉冲拉升：短时间快速上涨，其余时间横盘
    - 尾盘偷袭：全天平稳，尾盘最后30分钟急拉/急跌
    - 瀑布式下跌：开盘即跌，全天无明显反弹
    """
    if len(minute_quotes) < 20:
        return _intraday_unknown("分钟数据不足")

    # 按日期分组，取最近一个完整交易日
    from collections import defaultdict
    by_date = defaultdict(list)
    for m in minute_quotes:
        by_date[m.get('date', '')].append(m)

    if not by_date:
        return _intraday_unknown("分钟数据日期异常")

    # 排序取最近一天（跳过今天的不完整数据）
    sorted_dates = sorted(by_date.keys(), reverse=True)
    target_date = None
    for d in sorted_dates:
        bars = by_date[d]
        # 完整交易日至少有40根5分钟K（A股一天4小时=48根）
        if len(bars) >= 40:
            target_date = d
            break

    if not target_date:
        # 取数据量最大的那一天
        target_date = max(by_date.keys(), key=lambda d: len(by_date[d]))
        bars_today = by_date.get(str(date.today()), [])
        if len(bars_today) >= len(by_date[target_date]):
            target_date = str(date.today())

    bars = by_date[target_date]
    # 按time排序
    bars = sorted(bars, key=lambda x: x.get('time', ''))

    closes = [float(m['close']) for m in bars]
    volumes = [int(m.get('volume', 0)) for m in bars]
    highs = [float(m['high']) for m in bars]
    lows = [float(m['low']) for m in bars]

    first_price = closes[0]
    last_price = closes[-1]
    max_price = max(highs)
    min_price = min(lows)
    price_range_pct = (max_price - min_price) / min_price * 100

    overall_change_pct = (last_price - first_price) / first_price * 100

    # 找最大单段涨幅/跌幅（用于识别脉冲）
    max_up_pct = 0
    max_down_pct = 0
    for i in range(1, len(closes)):
        chg = (closes[i] - closes[i-1]) / closes[i-1] * 100
        if chg > max_up_pct:
            max_up_pct = chg
        if chg < max_down_pct:
            max_down_pct = chg

    # 尾盘判断（最后15根5分钟K ≈ 75分钟）
    tail_size = min(15, len(closes) // 4)
    tail_change = (closes[-1] - closes[-tail_size-1]) / closes[-tail_size-1] * 100 if tail_size > 0 else 0

    # 形态判断
    signs = []  # 疑似控盘迹象

    if abs(overall_change_pct) < 1.0 and price_range_pct < 2.5:
        pattern_type = "横盘整理"
        strength = "弱"
        interp = f"全天振幅仅{price_range_pct:.1f}%，价格几乎不动。横盘期间若缩量，往往是主力锁仓。"

    elif overall_change_pct > 1.5 and max_up_pct > overall_change_pct * 1.5:
        pattern_type = "脉冲拉升"
        strength = "中"
        interp = f"全天上涨{overall_change_pct:.2f}%，但单段最大涨幅{max_up_pct:.2f}%，显示为间歇性脉冲。可能是试探上攻或拉高试盘。"
        signs.append("脉冲式拉升（非流畅上涨）")

    elif tail_change > 0.8 and abs(overall_change_pct - tail_change) > 0.5:
        pattern_type = "尾盘偷袭"
        strength = "中"
        interp = f"尾盘最后{tail_size*5}分钟上涨{tail_change:.2f}%，全天其余时间变化{overall_change_pct - tail_change:.2f}%。尾盘拉升通常是做图或次日出货预留空间。"
        signs.append("尾盘异动")

    elif overall_change_pct < -1.5 and abs(max_down_pct) > abs(overall_change_pct) * 1.5:
        pattern_type = "瀑布式下跌"
        strength = "弱"
        interp = f"全天下跌{overall_change_pct:.2f}%，单段最大跌幅{max_down_pct:.2f}%，无明显反弹。可能是主力出货或恐慌抛盘。"
        signs.append("持续卖出压力")

    elif overall_change_pct > 1.0:
        pattern_type = "震荡上行"
        strength = "中"
        interp = f"全天上涨{overall_change_pct:.2f}%，形态偏强，但非流畅拉升，说明上方有抛压。"

    elif overall_change_pct < -1.0:
        pattern_type = "震荡下行"
        strength = "弱"
        interp = f"全天下跌{overall_change_pct:.2f}%，短期偏弱，可能有继续调整的压力。"

    else:
        pattern_type = "中性震荡"
        strength = "弱"
        interp = f"全天变化{overall_change_pct:.2f}%，无明显方向。"

    # 大单迹象检测：某根5分钟K成交量异常大
    avg_vol = sum(volumes) / len(volumes)
    large_order_candidates = []
    for i, v in enumerate(volumes):
        if v > avg_vol * 5:
            large_order_candidates.append(
                f"第{i+1}根K线量能为均量{v/avg_vol:.1f}倍"
            )

    vol_char = (
        f"均量基准约{avg_vol/10000:.0f}万股，"
        f"{'存在异常放量K线（' + str(len(large_order_candidates)) + '根）' if large_order_candidates else '无明显异常量K线'}"
    )

    return IntradayPattern(
        stock_code=code,
        pattern_type=pattern_type,
        strength=strength,
        volume_characteristics=vol_char,
        manipulation_signs=signs,
        interpretation=f"[{target_date}] " + interp,
    )


def _intraday_unknown(reason: str):
    return IntradayPattern(
        stock_code="", pattern_type="数据不足", strength="",
        volume_characteristics="", manipulation_signs=[],
        interpretation=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 五档买卖压力分析
# ─────────────────────────────────────────────────────────────────────────────

def analyze_order_pressure(
    code: str,
    bid_data: dict,   # 腾讯五档：{'bid1': [price, vol], 'ask1': [price, vol], ...}
) -> OrderBookPressure:
    """分析五档买卖盘压力。

    bid_data格式（腾讯）：
    - bid1, bid2...bid5: [价格, 挂单量]
    - ask1, ask2...ask5: [价格, 挂单量]
    """
    if not bid_data:
        return _pressure_unknown("五档数据获取失败")

    # 提取买卖盘总量（万元）
    bid_total = 0.0
    ask_total = 0.0
    large_bids = []
    large_asks = []

    for i in range(1, 6):
        bid_key = f'bid{i}'
        ask_key = f'ask{i}'
        if bid_key in bid_data and ask_key in bid_data:
            bid_price, bid_vol = bid_data.get(bid_key, [0, 0])
            ask_price, ask_vol = bid_data.get(ask_key, [0, 0])

            bid_vol = float(bid_vol) if bid_vol else 0
            ask_vol = float(ask_vol) if ask_vol else 0

            # 转为万元（成交量*价格/10000）
            bid_amount = bid_vol * float(bid_price) / 10000 if bid_price else 0
            ask_amount = ask_vol * float(ask_price) / 10000 if ask_price else 0

            bid_total += bid_amount
            ask_total += ask_amount

            # 大单阈值：单档挂单量>10万元
            if bid_amount > 10:
                large_bids.append(f"买{i}档:{bid_amount:.0f}万@{bid_price}")
            if ask_amount > 10:
                large_asks.append(f"卖{i}档:{ask_amount:.0f}万@{ask_price}")

    net_pressure = bid_total - ask_total
    pressure_ratio = bid_total / ask_total if ask_total > 0 else 0

    large_orders = large_bids + large_asks

    # 解读
    if pressure_ratio > 1.5:
        interp = f"买盘主导，买入压力是卖出压力的{pressure_ratio:.1f}倍。大单挂买{large_bids}，偏多。"
    elif pressure_ratio < 0.67:
        interp = f"卖盘主导，卖出压力是买入压力的{1/pressure_ratio:.1f}倍。大单挂卖{large_asks}，偏空。"
    else:
        interp = f"买卖均衡，买卖比{pressure_ratio:.2f}，多空博弈中。"

    if large_orders:
        interp += f" 检测到大单：{large_orders}"

    return OrderBookPressure(
        stock_code=code,
        timestamp=datetime.now(),
        bid_total=round(bid_total, 1),
        ask_total=round(ask_total, 1),
        net_pressure=round(net_pressure, 1),
        pressure_ratio=round(pressure_ratio, 2),
        large_orders_detected=large_orders,
        interpretation=interp,
    )


def _pressure_unknown(reason: str):
    return OrderBookPressure(
        stock_code="", timestamp=datetime.now(),
        bid_total=0, ask_total=0, net_pressure=0,
        pressure_ratio=0, large_orders_detected=[],
        interpretation=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 量价异动检测
# ─────────────────────────────────────────────────────────────────────────────

def detect_volume_anomaly(
    daily_quotes: List[DailyQuote],
    lookback: int = 20,
) -> VolumePriceAnomaly:
    """量价异动检测。

    异动类型：
    - 突放天量：量比>3倍 + 价格变化不大 → 可能出货或换庄
    - 缩量上涨：量比<0.5 + 价格涨 → 主力控盘，上涨健康
    - 放量滞涨：量比>2倍 + 涨幅<0.5% → 上涨乏力
    - 缩量下跌：量比<0.5 + 价格跌 → 可能最后一跌
    - 地量：量比<0.3 → 极度缩量，选择方向前兆
    """
    quotes = daily_quotes[-lookback:] if len(daily_quotes) >= lookback else daily_quotes
    if len(quotes) < 5:
        return _vol_anomaly_unknown("数据不足")

    volumes = [q.volume for q in quotes]
    closes = [q.close for q in quotes]

    avg_vol = sum(volumes[:-1]) / (len(volumes) - 1)  # 不含今日
    today_vol = volumes[-1]
    today_close = closes[-1]
    yesterday_close = closes[-2]
    today_change_pct = (today_close - yesterday_close) / yesterday_close * 100

    vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0

    # 找连续异动天数
    consecutive = 1
    for i in range(len(volumes)-2, max(0, len(volumes)-6), -1):
        v_ratio = volumes[i] / (sum(volumes[max(0,i-5):i])/min(5,i) + 0.001)
        if abs(v_ratio - vol_ratio) < 0.5:  # 相近水平
            consecutive += 1
        else:
            break

    # 判断异动类型和质量
    if vol_ratio > 3.0 and abs(today_change_pct) < 1.5:
        anomaly_type = "突放天量（异常）"
        quality = "可疑"
        interp = f"量能放大至均量{vol_ratio:.1f}倍，但价格变化仅{today_change_pct:.2f}%。这种放量不涨是典型的主力出货或换庄信号，需高度警惕。"
    elif vol_ratio > 2.0 and today_change_pct > 2.0:
        anomaly_type = "放量上涨"
        quality = "待观察"
        interp = f"放量{vol_ratio:.1f}倍上涨{today_change_pct:.2f}%。放量上涨若能持续是好信号，但需观察次日是否接力。"
    elif vol_ratio < 0.5 and today_change_pct > 0.5:
        anomaly_type = "缩量上涨"
        quality = "真信号"
        interp = f"缩量至均量{vol_ratio:.1f}倍，价格却上涨{today_change_pct:.2f}%。缩量上涨是主力高度控盘的特征，上涨质量较高。"
    elif vol_ratio < 0.5 and today_change_pct < -0.5:
        anomaly_type = "缩量下跌"
        quality = "可疑"
        interp = f"缩量至均量{vol_ratio:.1f}倍，价格下跌{today_change_pct:.2f}%。缩量下跌可能是最后一跌（主力不认输），也可能是无人接盘。"
    elif vol_ratio < 0.3:
        anomaly_type = "地量"
        quality = "观察"
        interp = f"量比仅{vol_ratio:.1f}倍，为近期极致缩量。地量通常意味着选择方向，可能是主力吸筹完毕，也可能是无人问津。需结合位置判断。"
    elif vol_ratio > 2.0 and abs(today_change_pct) < 0.5:
        anomaly_type = "放量滞涨"
        quality = "可疑"
        interp = f"放量{vol_ratio:.1f}倍但价格几乎不动（{today_change_pct:.2f}%）。放量滞涨是主力派发的常见特征，短期偏空。"
    else:
        return _vol_anomaly_unknown("无明显异动")

    return VolumePriceAnomaly(
        stock_code=quotes[-1].stock_code,
        date=quotes[-1].date,
        anomaly_type=anomaly_type,
        volume_ratio=round(vol_ratio, 2),
        price_change_pct=round(today_change_pct, 2),
        consecutive_days=consecutive,
        quality=quality,
        interpretation=interp,
    )


def _vol_anomaly_unknown(reason: str):
    return VolumePriceAnomaly(
        stock_code="", date=date.today(), anomaly_type="无异动",
        volume_ratio=0, price_change_pct=0, consecutive_days=0,
        quality="正常", interpretation=reason,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 综合报告生成
# ─────────────────────────────────────────────────────────────────────────────

def build_game_report(
    code: str,
    name: str,
    daily_quotes: List[DailyQuote],
    minute_quotes: List[dict],
    bid_data: dict = None,
) -> GameAnalysisReport:
    """综合博弈分析报告。"""
    # 各模块分析
    auction = analyze_auction(code, name, daily_quotes, minute_quotes)
    consolidation = detect_consolidation(daily_quotes)
    intraday = classify_intraday_pattern(code, minute_quotes)
    pressure = analyze_order_pressure(code, bid_data) if bid_data else None
    vol_anomaly = detect_volume_anomaly(daily_quotes)

    # 综合信号判断
    signals = []

    # 竞价信号
    if auction.signal in ("试盘/拉升", "诱多嫌疑", "最后一杀", "主动砸盘"):
        signals.append(auction.signal)

    # 横盘信号
    if consolidation.consolidation_days >= 5:
        signals.append(f"横盘{consolidation.consolidation_days}日")
        if consolidation.breakout_direction:
            signals.append(consolidation.breakout_direction)

    # 分时信号
    if intraday.pattern_type in ("脉冲拉升", "尾盘偷袭"):
        signals.append(intraday.pattern_type)
        if intraday.manipulation_signs:
            signals.extend(intraday.manipulation_signs)

    # 五档信号
    if pressure and pressure.pressure_ratio != 0:
        if pressure.pressure_ratio > 1.3:
            signals.append("买盘主导")
        elif pressure.pressure_ratio < 0.75:
            signals.append("卖盘主导")

    # 量价信号
    if vol_anomaly.anomaly_type != "无异动":
        signals.append(vol_anomaly.anomaly_type)

    # 综合判断
    if not signals:
        composite = "观望"
        advice = "各维度无明显异动，建议继续观察。"
    else:
        # 简化规则
        if any(s in signals for s in ("诱多嫌疑", "放量滞涨", "瀑布式下跌", "尾盘偷袭")):
            composite = "谨慎/观望"
            advice = "检测到疑似主力派发或做图信号，短期宜观望，不宜追高。"
        elif any(s in signals for s in ("试盘/拉升", "缩量上涨", "买盘主导")) and "横盘" in str(signals):
            composite = "关注偏多"
            advice = "量价配合+横盘整理，可能在蓄势。如放量突破可考虑跟进。"
        elif any(s in signals for s in ("主动砸盘", "最后一杀", "缩量下跌")):
            composite = "关注偏空"
            advice = "检测到疑似最后一跌或吸筹信号，可等待止跌后介入。"
        elif "横盘" in str(signals):
            composite = "横盘整理"
            advice = f"横盘{signals.count('横盘N日')}日，等待方向确认。"
        else:
            composite = "中性"
            advice = f"当前信号：{', '.join(signals)}，无明确方向。"

    return GameAnalysisReport(
        stock_code=code,
        auction=auction,
        consolidation=consolidation,
        intraday_pattern=intraday,
        order_pressure=pressure,
        volume_anomaly=vol_anomaly,
        composite_signal=composite,
        actionable_advice=advice,
    )


def format_game_report(report: GameAnalysisReport, name: str = "") -> str:
    """格式化博弈分析报告。"""
    code = report.stock_code
    name_str = name or code
    lines = []
    lines.append(f"{'='*52}")
    lines.append(f"  博弈分析  {name_str}（{code}）")
    lines.append(f"{'='*52}")
    lines.append("")

    # 竞价分析
    if report.auction:
        a = report.auction
        lines.append(f"【集合竞价】")
        lines.append(f"  开盘：{a.open_price:.2f}（{a.open_change_pct:+.2f}% vs 前收{a.prev_close:.2f}）")
        lines.append(f"  信号：{a.signal}  — {a.interpretation}")
        lines.append("")

    # 横盘检测
    if report.consolidation and report.consolidation.consolidation_days > 0:
        c = report.consolidation
        lines.append(f"【缩量横盘】")
        lines.append(f"  横盘：{c.consolidation_days}天，日均振幅{c.avg_daily_range_pct:.1f}%，量能{c.volume_trend}（{c.avg_volume_ratio:.2f}x）")
        lines.append(f"  类型：{c.pattern}")
        lines.append(f"  突破：{c.breakout_direction}（概率{c.breakout_likelihood*100:.0f}%）")
        lines.append(f"  {c.interpretation}")
        lines.append("")

    # 分时形态
    if report.intraday_pattern:
        ip = report.intraday_pattern
        lines.append(f"【分时形态】")
        lines.append(f"  类型：{ip.pattern_type}（强度：{ip.strength}）")
        lines.append(f"  量能：{ip.volume_characteristics}")
        if ip.manipulation_signs:
            lines.append(f"  控盘迹象：{'；'.join(ip.manipulation_signs)}")
        lines.append(f"  解读：{ip.interpretation}")
        lines.append("")

    # 五档压力
    if report.order_pressure:
        op = report.order_pressure
        lines.append(f"【五档博弈】")
        lines.append(f"  买盘：{op.bid_total:.0f}万  卖盘：{op.ask_total:.0f}万  买卖比={op.pressure_ratio:.2f}")
        lines.append(f"  解读：{op.interpretation}")
        lines.append("")

    # 量价异动
    if report.volume_anomaly and report.volume_anomaly.anomaly_type != "无异动":
        va = report.volume_anomaly
        lines.append(f"【量价异动】")
        lines.append(f"  类型：{va.anomaly_type}（质量：{va.quality}）")
        lines.append(f"  量比：{va.volume_ratio}x  涨跌：{va.price_change_pct:+.2f}%")
        lines.append(f"  解读：{va.interpretation}")
        lines.append("")

    # 综合结论
    lines.append(f"─── 综合信号：{report.composite_signal} ───")
    lines.append(f"  操作建议：{report.actionable_advice}")
    lines.append(f"{'='*52}")

    return "\n".join(lines)
