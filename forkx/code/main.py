"""FORKX CLI 入口。"""
import argparse
import sys
from datetime import date, datetime, timedelta

from .data.models import AlertRecord, TradeRecord
from .data.tencent_provider import TencentProvider
from .data.sina_provider import SinaProvider
from .data.baostock_provider import BaoStockProvider
from .screening.analyzer import Analyzer, format_analysis
from .screening.indicators import calc_ma, calc_rsi, rsi_zone, ma_status
from .trading.log_store import add_trade, get_positions, list_trades
from .trading.backtest import backtest_ma_cross, format_backtest
from .notification.alert_store import add_alert, list_alerts, remove_alert, toggle_alert
from .notification.checker import check_alerts, format_alert_check
from .utils.watchlist import load_watchlist, add_to_watchlist, remove_from_watchlist


def _provider():
    return {
        "realtime": TencentProvider(),
        "kline": SinaProvider(),
        "financial": BaoStockProvider(),
    }


def cmd_watch(args):
    watchlist = load_watchlist()
    if not watchlist:
        print("自选股为空，请先用 forlsx add <股票代码> 添加")
        return
    prov = _provider()
    realtime = prov["realtime"].get_realtime(watchlist)
    if not realtime:
        print("无法获取行情数据，请检查网络")
        return
    end = datetime.today().date()
    start = end - timedelta(days=90)
    kline = prov["kline"]
    print()
    print(f"{'代码':<8} {'名称':<10} {'价格':>8} {'涨跌%':>8} {'RSI':>8} {'均线状态':<8} {'趋势'}")
    print("-" * 70)
    for code in watchlist:
        rt = realtime.get(code)
        if not rt:
            print(f"{code:<8} {'（无数据）'}")
            continue
        quotes = kline.get_daily_quotes(code, start, end)
        rsi_str = "—"
        ma_str = "—"
        trend_str = "—"
        if len(quotes) >= 20:
            closes = [q.close for q in quotes]
            rsi_vals = calc_rsi(closes)
            rsi = rsi_vals[-1] if rsi_vals else 0
            zone = rsi_zone(rsi)
            rsi_str = f"{rsi:.0f}({zone[:2]})"
            ma = ma_status(quotes)
            ma_str = ma["alignment"][:8]
            trend_str = ma["cross"] if ma["cross"] != "无信号" else ""
        print(f"{code:<8} {rt.name:<10} {rt.price:>8.2f} {rt.pct_chg:>+8.2f}% {rsi_str:>8} {ma_str:<8} {trend_str}")


def cmd_analyze(args):
    code = args.stock
    prov = _provider()
    rt_data = prov["realtime"].get_realtime([code])
    rt = rt_data.get(code)
    if not rt:
        print(f"无法获取 {code} 的行情数据")
        return
    start = date.fromisoformat(args.start) if args.start else date(2024, 1, 1)
    end = date.fromisoformat(args.end) if args.end else date.today()
    quotes = prov["kline"].get_daily_quotes(code, start, end)
    fin = prov["financial"].get_financials(code)
    analyzer = Analyzer(quotes, fin, rt)
    report = analyzer.analyze()
    print(format_analysis(report))

    # 博弈分析（底层分析）
    try:
        minute_quotes = SinaProvider().get_minute_quotes(code, freq=5, days=5)
        bid_data = prov["realtime"].get_order_book(code)
        from .screening.game_analyzer import build_game_report, format_game_report
        game = build_game_report(code, rt.name, quotes, minute_quotes, bid_data)
        print()
        print(format_game_report(game, rt.name))

        # 资金流（庄家行为直接信号）
        try:
            from .screening.fund_flow_provider import FundFlowProvider, format_fund_flow_summary
            ff = FundFlowProvider().get_fund_flow(code, days=20)
            ff_text = format_fund_flow_summary(ff)
            if ff_text:
                print()
                print("  【资金流】（庄家行为）")
                print(ff_text)
        except Exception:
            pass
    except Exception as e:
        print(f"\n[博弈分析暂时不可用: {e}]")


def cmd_chart(args):
    code = args.stock
    prov = _provider()
    rt_data = prov["realtime"].get_realtime([code])
    rt = rt_data.get(code)
    name = rt.name if rt else code
    start = date.fromisoformat(args.start) if args.start else date(2024, 1, 1)
    end = date.fromisoformat(args.end) if args.end else date.today()
    quotes = prov["kline"].get_daily_quotes(code, start, end)
    if len(quotes) < 20:
        print(f"数据不足（{len(quotes)}天），至少需要20天")
        return
    from .charts.kline import render_kline
    path = render_kline(quotes, code, name)
    print(f"K线图已保存：{path}")


def cmd_alert(args):
    if args.action == "add":
        alert = AlertRecord(
            stock_code=args.stock,
            alert_type=args.alert_type,
            threshold=float(args.threshold),
            note=args.note or "",
        )
        aid = add_alert(alert)
        print(f"已添加提醒 [{aid}]：{args.stock} {args.alert_type} {args.threshold}")
    elif args.action == "list":
        alerts = list_alerts(enabled_only=args.enabled_only) if args.enabled_only else list_alerts()
        if not alerts:
            print("暂无提醒")
            return
        for a in alerts:
            status = "启用" if a.enabled else "禁用"
            print(f"[{a.id}] {a.stock_code} {a.alert_type} {a.threshold}  {status}  {a.note}")
    elif args.action == "remove":
        ok = remove_alert(args.id)
        print(f"已删除" if ok else f"未找到 {args.id}")
    elif args.action == "check":
        result = check_alerts()
        print(format_alert_check(result))
    elif args.action == "toggle":
        if not args.id:
            print("--id required for toggle")
            return
        # 先查当前状态
        all_alerts = list_alerts()
        target = next((a for a in all_alerts if a.id == args.id), None)
        if not target:
            print(f"未找到 {args.id}")
            return
        new_state = not target.enabled
        toggle_alert(args.id, new_state)
        print(f"[{args.id}] {'启用' if new_state else '禁用'}")


def cmd_compare(args):
    from .screening.compare import compare_game_trend, format_compare_report
    days = int(args.days) if args.days else 5
    r = compare_game_trend(args.stock, days=days)
    print(format_compare_report(r))


def cmd_log(args):
    if args.action == "add":
        # 自动提取信号（除非手动指定）
        auto_signals = []
        if not getattr(args, 'signals', None):
            try:
                from .screening.signal_extractor import extract_current_signals
                auto_signals = extract_current_signals(args.stock)
            except Exception:
                pass

        trade = TradeRecord(
            stock_code=args.stock,
            action=args.action_type,
            price=float(args.price),
            volume=float(args.volume),
            date=date.fromisoformat(args.date),
            note=args.note or "",
            signals=auto_signals,
        )
        tid = add_trade(trade)
        sig_text = " | ".join(auto_signals) if auto_signals else "（无信号）"
        print(f"已记录 [{tid}]：{args.action_type.upper()} {args.stock} {args.volume}股 @{args.price}")
        print(f"  信号：{sig_text}")
    elif args.action == "list":
        trades = list_trades(stock_code=args.stock)
        if not trades:
            print("暂无交易记录")
            return
        for t in trades:
            sig_str = f"  [{', '.join(t.signals)}]" if t.signals else ""
            print(f"{t.date}  {t.action.upper():>4}  {t.stock_code}  {t.volume}股 @{t.price:.2f}{sig_str}")
            if t.note:
                print(f"    备注：{t.note}")
    elif args.action == "positions":
        positions = get_positions()
        if not positions:
            print("暂无持仓")
            return
        print()
        print(f"{'代码':<8} {'持仓量':>10} {'平均成本':>10} {'交易次数':>8}")
        print("-" * 40)
        for p in positions:
            print(f"{p['stock_code']:<8} {p['volume']:>10.0f} {p['avg_cost']:>10.2f} {p['trade_count']:>8}")
    elif args.action == "stats":
        _print_log_stats()
    elif args.action == "signals":
        _print_signal_stats()


def _print_signal_stats():
    """按信号标签统计胜率。"""
    from collections import defaultdict
    trades = list_trades()
    if not trades:
        print("暂无交易记录")
        return

    # 按股票分组，匹配同股票的买→卖交易对
    stock_trades = defaultdict(list)
    for t in trades:
        stock_trades[t.stock_code].append(t)

    # 每只股票：匹配买-卖对，计算每笔卖出的收益率
    # 买入记录需要价格，卖出时计算相对于最近一次买入的收益率
    signal_stats = defaultdict(lambda: {"count": 0, "win": 0, "total_return": 0.0})

    for code, recs in stock_trades.items():
        # 按日期排序
        recs_sorted = sorted(recs, key=lambda r: r.date)
        buy_stack = []  # 未平仓的买入
        for rec in recs_sorted:
            if rec.action == "buy":
                buy_stack.append(rec)
            elif rec.action == "sell" and buy_stack:
                buy = buy_stack.pop(0)
                ret_pct = (rec.price - buy.price) / buy.price * 100
                # 分配信号
                for sig in buy.signals:
                    signal_stats[sig]["count"] += 1
                    signal_stats[sig]["total_return"] += ret_pct
                    if ret_pct > 0:
                        signal_stats[sig]["win"] += 1

    if not signal_stats:
        print("暂无有效交易对（需先有买入→卖出记录）")
        return

    print(f"{'═' * 50}")
    print(f"  信号胜率统计")
    print(f"{'═' * 50}")
    print(f"{'信号':<20} {'次数':>6} {'胜率':>8} {'平均收益':>10}")
    print(f"{'-' * 50}")
    for sig, s in sorted(signal_stats.items(), key=lambda x: -x[1]["count"]):
        win_rate = s["win"] / s["count"] * 100 if s["count"] > 0 else 0
        avg_ret = s["total_return"] / s["count"] if s["count"] > 0 else 0
        bar = "█" * int(win_rate / 10) + "░" * (10 - int(win_rate / 10))
        print(f"{sig:<18} {s['count']:>6}  {bar} {win_rate:>5.0f}%  {avg_ret:>+7.1f}%")
    print(f"{'═' * 50}")


def _print_log_stats():
    """交易统计。"""
    trades = list_trades()
    if not trades:
        print("暂无交易记录")
        return
    buys = [t for t in trades if t.action == "buy"]
    sells = [t for t in trades if t.action == "sell"]
    print(f"总交易次数：{len(trades)}（买{len(buys)}/卖{len(sells)}）")


def cmd_backtest(args):
    code = args.stock
    fast = int(args.fast)
    slow = int(args.slow)
    start = date.fromisoformat(args.start) if args.start else date(2023, 1, 1)
    end = date.fromisoformat(args.end) if args.end else date.today()
    prov = _provider()
    quotes = prov["kline"].get_daily_quotes(code, start, end)
    if len(quotes) < 60:
        print(f"数据不足（需要60天以上，当前{len(quotes)}天）")
        return
    result = backtest_ma_cross(quotes, fast, slow)
    print(format_backtest(result))


def cmd_add(args):
    code = args.stock
    ok = add_to_watchlist(code)
    print(f"已添加 {code} 到自选股" if ok else f"{code} 已在自选股中")


def cmd_remove(args):
    code = args.stock
    ok = remove_from_watchlist(code)
    print(f"已移除 {code}" if ok else f"{code} 不在自选股中")


def main():
    parser = argparse.ArgumentParser(prog="forlsx", description="FORKX — 个人炒股助理")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("watch", help="查看自选股池状态")
    an = sub.add_parser("analyze", help="分析单只股票")
    an.add_argument("stock", help="股票代码")
    an.add_argument("--start", help="起始日期 YYYY-MM-DD")
    an.add_argument("--end", help="结束日期 YYYY-MM-DD")
    ch = sub.add_parser("chart", help="K线图")
    ch.add_argument("stock", help="股票代码")
    ch.add_argument("--start", help="起始日期 YYYY-MM-DD")
    ch.add_argument("--end", help="结束日期 YYYY-MM-DD")
    al = sub.add_parser("alert", help="提醒管理")
    al.add_argument("action", choices=["add", "list", "remove", "check", "toggle"])
    al.add_argument("--stock", help="股票代码")
    al.add_argument("--type", dest="alert_type",
                    choices=[
                        # 传统
                        "price_below", "price_above",
                        "rsi_overbought", "rsi_oversold", "volume_surge",
                        # 博弈信号
                        "consolidation_break",  # 横盘突破（threshold=涨幅%）
                        "tail_swing",           # 尾盘偷袭（threshold=1，固定）
                        "main_inflow_surge",    # 主力大幅买入（threshold=万元）
                        "main_inflow_reversal", # 资金由卖转买（threshold=1，固定）
                        "buy_pressure_surge",   # 买卖比飙升（threshold=比值）
                        "volume_anomaly",       # 量价异动（threshold=量比）
                    ])
    al.add_argument("--threshold", help="阈值")
    al.add_argument("--note", help="备注")
    al.add_argument("--id", help="提醒ID")
    al.add_argument("--enabled-only", dest="enabled_only", action="store_true")
    lg = sub.add_parser("log", help="交易记录")
    lg.add_argument("action", choices=["add", "list", "positions", "stats", "signals"])
    lg.add_argument("--stock", help="股票代码")
    lg.add_argument("--action-type", dest="action_type", choices=["buy", "sell"])
    lg.add_argument("--price", help="成交价格")
    lg.add_argument("--volume", help="成交数量")
    lg.add_argument("--date", help="成交日期 YYYY-MM-DD")
    lg.add_argument("--note", help="备注")
    bt = sub.add_parser("backtest", help="均线回测")
    bt.add_argument("stock", help="股票代码")
    bt.add_argument("--fast", default="5", help="快线周期")
    bt.add_argument("--slow", default="20", help="慢线周期")
    bt.add_argument("--start", help="起始日期 YYYY-MM-DD")
    bt.add_argument("--end", help="结束日期 YYYY-MM-DD")
    co = sub.add_parser("compare", help="多日博弈对比")
    co.add_argument("stock", help="股票代码")
    co.add_argument("--days", default="5", help="对比天数（默认5天）")
    sub.add_parser("add", help="添加自选股").add_argument("stock", help="股票代码")
    sub.add_parser("remove", help="移除自选股").add_argument("stock", help="股票代码")

    args = parser.parse_args()
    if args.command == "watch":
        cmd_watch(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "chart":
        cmd_chart(args)
    elif args.command == "alert":
        cmd_alert(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "compare":
        cmd_compare(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "remove":
        cmd_remove(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
