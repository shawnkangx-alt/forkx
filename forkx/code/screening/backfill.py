"""历史数据回填脚本。

将股票的历史数据回填到 history_store，
供预测模型和信号权重学习使用。

数据源：baostock（352+天，无需代理）> 新浪日K（备用）

用法：
    python -m forkx.code.screening.backfill --stock 002371 --days 180
"""
import argparse
import sys
from datetime import date, timedelta

# 确保项目路径在 sys.path 中
sys.path.insert(0, '/Users/shawnkangx/projects/forkx')

import baostock as bs
from forkx.code.data.sina_provider import SinaProvider
from forkx.code.data.models import DailyQuote
from forkx.code.screening.indicators import calc_rsi, ma_status, rsi_zone
from forkx.code.screening.signal_extractor import extract_signals_from_analysis
from forkx.code.screening.history_store import save_daily_record, DailyRecord
from forkx.code.screening.game_analyzer import (
    detect_consolidation, classify_intraday_pattern,
    analyze_order_pressure, detect_volume_anomaly
)
from forkx.code.data.tencent_provider import TencentProvider


def _baostock_quotes(stock_code: str, start: date, end: date) -> list:
    """用 baostock 获取历史日K（352+天，无代理限制）。"""
    # baostock 的 code 格式：sz.002371 → 去掉前缀
    bs_code = stock_code.lower()
    if not bs_code.startswith("sz.") and not bs_code.startswith("sh."):
        bs_code = "sz." + stock_code if stock_code.startswith("0") else "sh." + stock_code

    bs.login()
    rs = bs.query_history_k_data_plus(
        bs_code,
        'date,open,high,low,close,volume,amount',
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        frequency='d'
    )
    rows = rs.get_data()
    bs.logout()

    if rows.empty:
        return []

    quotes = []
    for _, row in rows.iterrows():
        try:
            q = DailyQuote(
                stock_code=stock_code,
                date=date.fromisoformat(row['date']),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=float(row['volume']),
                amount=float(row['amount']) if row['amount'] else 0.0,
            )
            quotes.append(q)
        except (ValueError, KeyError):
            continue
    return quotes


def backfill_stock(stock_code: str, days: int = 180) -> dict:
    """回填单只股票的历史数据（优先用 baostock）。"""
    end = date.today()
    start = end - timedelta(days=days + 60)  # 多拿60天作为指标计算缓冲

    print(f"获取历史K线 {stock_code} ({start} → {end}) ...")

    # 优先用 baostock（352+天，无需代理）
    quotes = _baostock_quotes(stock_code, start, end)
    print(f"  baostock: {len(quotes)} 条")

    # 如果 baostock 数据太少，用新浪补充（最新部分）
    if len(quotes) < days * 0.5:
        sina_quotes = SinaProvider().get_daily_quotes(stock_code, start, end)
        print(f"  新浪: {len(sina_quotes)} 条（补充）")
        if sina_quotes:
            # 合并，去重（以日期为主，baostock 优先）
            sina_by_date = {q.date: q for q in sina_quotes}
            for q in quotes:
                sina_by_date.pop(q.date, None)
            quotes.extend(sina_by_date.values())
            quotes.sort(key=lambda q: q.date)
            print(f"  合并后: {len(quotes)} 条")

    if not quotes:
        print("获取K线失败")
        return {"saved": 0, "skipped": 0}

    print(f"获取到 {len(quotes)} 条K线，开始计算指标和信号...")

    saved = 0
    skipped = 0
    today = date.today()

    # 预加载五档数据（用于博弈分析，但历史数据没有，用None）
    tencent = None
    try:
        tencent = TencentProvider()
    except Exception:
        pass

    for i, q in enumerate(quotes):
        q_date = q.date

        # 只回填今天及以前的数据
        if q_date > today:
            continue

        # 计算RSI
        close_prices = [x.close for x in quotes[:i+1]]
        rsi_vals = calc_rsi(close_prices)
        rsi = rsi_vals[-1] if rsi_vals else 50.0
        rsi_z = rsi_zone(rsi)

        # 计算MA状态
        ma_s = ma_status(quotes[:i+1])
        ma_str = ma_s.get("alignment", "") if ma_s else ""

        # 横盘检测（需要至少5天数据）
        cons_result = None
        if i >= 5:
            try:
                cons_result = detect_consolidation(quotes[:i+1])
            except Exception:
                pass

        cons_days = cons_result.consolidation_days if cons_result else 0
        cons_dir = cons_result.breakout_direction if cons_result else ""
        cons_signal = getattr(cons_result, 'signal', '') or ''

        # 量价异动检测
        vol_anomaly = None
        if i >= 20:
            try:
                vol_anomaly = detect_volume_anomaly(quotes[:i+1])
            except Exception:
                pass

        vol_ratio = q.volume  # 成交量（万手）
        # 量比：当天成交量/过去5日平均成交量
        if i >= 5:
            avg_vol = sum(x.volume for x in quotes[i-4:i+1]) / 5
            vol_ratio_calc = vol_ratio / avg_vol if avg_vol > 0 else 1.0
        else:
            vol_ratio_calc = 1.0

        # 竞价分析（历史数据没有竞价数据）
        auction_signal = ""
        intraday_pattern = ""
        buy_pressure = None
        vol_anomaly_sig = ""

        if vol_anomaly:
            vol_anomaly_sig = vol_anomaly.signal if hasattr(vol_anomaly, 'signal') else ""

        # 提取信号
        try:
            signals = extract_signals_from_analysis(
                rsi=rsi,
                ma_status=ma_s,
                macd_signal="",
                rsi_zone_label=rsi_z,
                auction=None,
                intraday=None,
                order_pressure=None,
                consolidation=cons_result,
                volume_anomaly=vol_anomaly,
                fund_flow_net_wan=0.0,  # 历史资金流不可用
                fund_flow_trend="",
            )
        except Exception:
            signals = []

        # 计算涨跌幅（从环比）
        if i >= 1:
            prev_close = quotes[i-1].close
            change_pct = (q.close - prev_close) / prev_close * 100
        else:
            change_pct = 0.0

        # 构建存档记录
        rec = DailyRecord(
            stock_code=stock_code,
            record_date=q_date,
            close=q.close,
            change_pct=change_pct,
            volume_ratio=vol_ratio_calc,
            rsi=rsi,
            rsi_zone=rsi_z,
            ma_status=ma_str,
            macd_signal="",
            fund_flow_net_wan=0.0,
            fund_flow_trend="",
            auction_signal=auction_signal,
            intraday_pattern=intraday_pattern,
            consolidation_days=cons_days,
            breakout_direction=cons_dir,
            composite_signal=cons_signal,
            signals=signals,
        )

        try:
            save_daily_record(rec)
            saved += 1
            if saved % 20 == 0:
                print(f"  已回填 {saved} 天... {q_date}")
        except Exception as e:
            skipped += 1
            print(f"  跳过 {q_date}: {e}")

    return {"saved": saved, "skipped": skipped}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="历史数据回填")
    parser.add_argument("--stock", default="002371", help="股票代码")
    parser.add_argument("--days", type=int, default=90, help="回填天数")
    args = parser.parse_args()

    result = backfill_stock(args.stock, args.days)
    print(f"\n完成：已回填 {result['saved']} 天，跳过 {result['skipped']} 天")
