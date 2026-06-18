"""K线图渲染模块。"""
import datetime
from pathlib import Path
from typing import List

from ..data.models import DailyQuote


def render_kline(
    quotes: List[DailyQuote],
    code: str,
    name: str = "",
    period: str = "日K",
    out_path: str = None,
) -> str:
    """渲染K线图，保存为PNG并返回路径。

    包含：
    - K线（红涨绿跌）
    - MA5/MA20/MA60 均线
    - 成交量柱状图
    - 副图：MACD + KDJ
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # 无头渲染
        import matplotlib.pyplot as plt
        import matplotlib.gridspec as gridspec
        from matplotlib import rcParams
        rcParams["font.sans-serif"] = ["Arial Unicode MS", "DejaVu Sans"]
        rcParams["axes.unicode_minus"] = False
    except ImportError:
        return "（matplotlib 未安装）"

    if len(quotes) < 5:
        return "（数据不足）"

    # —— 数据准备 ——
    dates = [q.date for q in quotes]
    opens = [q.open for q in quotes]
    highs = [q.high for q in quotes]
    lows = [q.low for q in quotes]
    closes = [q.close for q in quotes]
    volumes = [q.volume for q in quotes]

    # 颜色
    up_color = "#e74c3c"
    down_color = "#27ae60"

    # 判断涨跌
    colors = [up_color if closes[i] >= opens[i] else down_color for i in range(len(quotes))]

    # MA计算
    def ma(values, n):
        if len(values) < n:
            return [None] * len(values)
        result = [None] * (n - 1)
        for i in range(n - 1, len(values)):
            result.append(round(sum(values[i - n + 1:i + 1]) / n, 2))
        return result

    ma5 = ma(closes, 5)
    ma20 = ma(closes, 20)
    ma60 = ma(closes, 60) if len(closes) >= 60 else [None] * len(closes)

    # —— 图床布局 ——
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(3, 1, height_ratios=[3, 1, 1], hspace=0.1)

    ax1 = fig.add_subplot(gs[0])   # K线+均线
    ax2 = fig.add_subplot(gs[1], sharex=ax1)  # 成交量
    ax3 = fig.add_subplot(gs[2], sharex=ax1)  # MACD

    # 去掉日期标签重叠
    for ax in [ax1, ax2, ax3]:
        ax.tick_params(labelbottom=False)
    ax3.tick_params(labelbottom=True)

    # —— K线蜡烛图（手绘）——
    for i in range(len(quotes)):
        date = dates[i]
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        color = colors[i]
        # 实体
        ax1.add_patch(plt.Rectangle(
            (i - 0.4, min(o, c)),
            0.8, abs(c - o),
            facecolor=color, edgecolor=color, linewidth=0.5
        ))
        # 上影线
        ax1.plot([i, i], [h, max(o, c)], color=color, linewidth=0.8)
        # 下影线
        ax1.plot([i, i], [l, min(o, c)], color=color, linewidth=0.8)

    # MA线
    x = range(len(quotes))
    ax1.plot(x, ma5, color="#1f77b4", linewidth=1, label="MA5")
    ax1.plot(x, ma20, color="#ff7f0e", linewidth=1, label="MA20")
    ax1.plot(x, ma60, color="#2ca02c", linewidth=1, label="MA60")
    ax1.set_ylabel("价格")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.set_title(f"{name}（{code}）{period}  {dates[0]} ~ {dates[-1]}")
    ax1.grid(True, alpha=0.3)

    # 紧固Y轴范围
    price_min = min(lows)
    price_max = max(highs)
    ax1.set_ylim(price_min * 0.97, price_max * 1.03)

    # —— 成交量图 ——
    ax2.bar(x, volumes, color=colors, width=0.8, alpha=0.7)
    ax2.set_ylabel("成交量")
    ax2.set_ylim(0, max(volumes) * 1.1)
    ax2.grid(True, alpha=0.3)

    # —— MACD图（简化）——
    # 使用前复权价格计算MACD
    def ema(vals, n):
        if len(vals) < n:
            return [0.0] * len(vals)
        k = 2.0 / (n + 1)
        result = [0.0] * (n - 1)
        result.append(sum(vals[:n]) / n)
        for i in range(n, len(vals)):
            result.append(result[-1] + k * (vals[i] - result[-1]))
        return result

    def calc_macd_fast(c, f=12, s=26, sig=9):
        ef = ema(c, f)
        es = ema(c, s)
        dif = [ef[i] - es[i] if ef[i] and es[i] else 0 for i in range(len(c))]
        dea = ema(dif, sig)
        macd = [(dif[i] - dea[i]) * 2 if dea[i] else 0 for i in range(len(dif))]
        return dif, dea, macd

    dif, dea, macd_hist = calc_macd_fast(closes)

    # MACD柱状图
    macd_colors = [up_color if macd_hist[i] >= 0 else down_color for i in range(len(macd_hist))]
    ax3.bar(x, macd_hist, color=macd_colors, width=0.8, alpha=0.8)
    ax3.plot(x, dif, color="#1f77b4", linewidth=1, label="DIF")
    ax3.plot(x, dea, color="#ff7f0e", linewidth=1, label="DEA")
    ax3.axhline(0, color="gray", linewidth=0.5)
    ax3.set_ylabel("MACD")
    ax3.legend(loc="upper left", fontsize=8)
    ax3.grid(True, alpha=0.3)

    # X轴：显示部分日期
    tick_step = max(1, len(dates) // 10)
    ax3.set_xticks(range(0, len(dates), tick_step))
    ax3.set_xticklabels([dates[i].strftime("%Y-%m-%d") for i in range(0, len(dates), tick_step)], rotation=45, fontsize=7)

    # —— 保存 ——
    if out_path is None:
        out_dir = Path.home() / ".forkx" / "charts"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{code}_{dates[0].strftime('%Y%m%d')}_{dates[-1].strftime('%Y%m%d')}.png"

    fig.savefig(str(out_path), dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return str(out_path)
