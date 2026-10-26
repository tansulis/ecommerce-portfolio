# -*- coding: utf-8 -*-
"""
步骤 4：数据分析 + 可视化设计
读取 output/eda/ 下的聚合结果，绘制 4 张业务图表 + 1 张备选地域图（PNG），供作品集使用。

主图 4 张（对应模板要求）：
  图1  用户消费时间规律      —— 日趋势(双轴, 标注双十二) + 24小时分布(黄金时段)
  图2  品类曝光-转化效率      —— 散点(识别流量黑洞)
  图3  用户购买量集中度      —— Lorenz/Pareto 曲线(检验 80/20 是否成立)
  图4  行为意向→支付转化     —— 加购是最强购买信号(替代脱敏的地域图)

备选 1 张（补回原定第4个业务问题，地域已脱敏，只能做匿名分区）：
  图5  匿名地域分区行为量

作者：谭惠（求职作品集）  运行：python 03_visualize.py
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # 无界面环境必须
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager

# ---------- 中文字体设置（Windows 用微软雅黑）----------
CAND = ["Microsoft YaHei", "SimHei", "PingFang SC", "Arial Unicode MS"]
AVAIL = {f.name for f in font_manager.fontManager.ttflist}
CN = next((c for c in CAND if c in AVAIL), None)
if CN:
    plt.rcParams["font.family"] = CN
plt.rcParams["axes.unicode_minus"] = False  # 正常显示负号
plt.rcParams["figure.dpi"] = 130
plt.rcParams["savefig.bbox"] = "tight"

EDA = os.path.join(os.path.dirname(__file__), "output", "eda")
OUT = os.path.join(os.path.dirname(__file__), "charts")
os.makedirs(OUT, exist_ok=True)

# 统一配色（中国习惯：红=重点/支付）
C_PV = "#4C78A8"      # 点击/浏览 蓝
C_BUY = "#E45756"     # 支付 红
C_CART = "#F58518"    # 加购 橙
GREY = "#999999"


def _style(ax, grid_axis="both"):
    ax.grid(alpha=0.28, axis=grid_axis)
    ax.spines["top"].set_visible(False)


# ============================================================
# 图1：用户消费时间规律（日趋势双轴 + 24小时）
# ============================================================
def chart_time():
    daily = pd.read_csv(os.path.join(EDA, "03_daily_trend.csv"), parse_dates=["date"])
    hour = pd.read_csv(os.path.join(EDA, "04_hour_distribution.csv"))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9))

    # ---- 上：31 天日趋势（双轴，避免支付被点击压平）----
    ax1.plot(daily["date"], daily["pv"], color=C_PV, lw=1.8, label="点击/浏览（左轴）")
    ax1.set_ylabel("点击/浏览次数", color=C_PV)
    ax1.tick_params(axis="y", labelcolor=C_PV)

    ax1r = ax1.twinx()
    ax1r.plot(daily["date"], daily["buy"], color=C_BUY, lw=2.2, label="支付（右轴）")
    ax1r.set_ylabel("支付次数", color=C_BUY)
    ax1r.tick_params(axis="y", labelcolor=C_BUY)

    d1212 = pd.Timestamp("2014-12-12")
    buy_1212 = daily.loc[daily["date"] == d1212, "buy"].iloc[0]
    pv_1212 = daily.loc[daily["date"] == d1212, "pv"].iloc[0]
    # 用「不含双十二的日常均值」做基准，倍数动态计算，避免手写错数
    base = daily[daily["date"] != d1212]
    pv_ratio = pv_1212 / base["pv"].mean()
    buy_ratio = buy_1212 / base["buy"].mean()
    ax1r.axvline(d1212, color=C_CART, ls="--", lw=1.6)
    ax1r.annotate(f"双十二\n支付 {buy_1212:,}（约日常 {buy_ratio:.1f} 倍）\n点击 {pv_1212:,}（约 {pv_ratio:.1f} 倍）",
                  xy=(d1212, buy_1212),
                  xytext=(d1212 - pd.Timedelta(days=13), buy_1212 * 0.62),
                  color=C_CART, fontsize=10, fontweight="bold",
                  arrowprops=dict(arrowstyle="->", color=C_CART, lw=1.6))

    ax1.set_title("图1-A  31天每日行为量趋势（2014-11-18 ~ 12-18）", fontsize=13, fontweight="bold")
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax1r.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False)
    _style(ax1)

    # ---- 下：24 小时分布（双轴）----
    ax2.bar(hour["hour"], hour["pv"], color=C_PV, alpha=0.85, label="点击/浏览（左轴）")
    ax2.set_ylabel("点击/浏览次数", color=C_PV)
    ax2.tick_params(axis="y", labelcolor=C_PV)

    ax2r = ax2.twinx()
    ax2r.plot(hour["hour"], hour["buy"], color=C_BUY, marker="o", ms=4, lw=1.9, label="支付（右轴）")
    ax2r.set_ylabel("支付次数", color=C_BUY)
    ax2r.tick_params(axis="y", labelcolor=C_BUY)

    ax2.axvspan(19.5, 23.5, color=C_CART, alpha=0.12)
    ax2.text(21.5, hour["pv"].max() * 0.9, "黄金四小时\n20:00–23:00", ha="center",
             color=C_CART, fontsize=10, fontweight="bold",
             bbox=dict(facecolor="white", alpha=0.8, edgecolor="none", pad=1.5))
    ax2.set_title("图1-B  24小时行为分布（夜间是消费高峰）", fontsize=13, fontweight="bold")
    ax2.set_xlabel("小时（0–23）")
    ax2.set_xticks(range(0, 24, 2))
    h1, l1 = ax2.get_legend_handles_labels()
    h2, l2 = ax2r.get_legend_handles_labels()
    ax2.legend(h1 + h2, l1 + l2, loc="upper left", frameon=False)
    _style(ax2, "y")

    fig.tight_layout()
    p = os.path.join(OUT, "01_daily_hourly_trend.png")
    fig.savefig(p)
    plt.close(fig)
    return p, pv_1212, buy_1212, pv_ratio, buy_ratio


# ============================================================
# 图2：品类曝光-转化效率散点（流量黑洞）
# ============================================================
def chart_category():
    cat = pd.read_csv(os.path.join(EDA, "06_category_stats.csv"))
    # 过滤极小曝光品类，避免散点被长尾淹没（保留曝光量前 50%）
    cat2 = cat[cat["pv"] >= cat["pv"].quantile(0.5)].copy()

    fig, ax = plt.subplots(figsize=(11, 7))
    ax.scatter(cat2["pv"], cat2["buy_rate"] * 100,
               s=cat2["buy"].clip(upper=3000) / 8 + 10,
               color=C_PV, alpha=0.4, edgecolor="none")

    # 流量黑洞：曝光最高但转化极低
    hole = cat2.sort_values("pv", ascending=False).iloc[0]
    # 高效品类：曝光中上、转化最高
    eff = cat2[cat2["pv"] >= cat2["pv"].quantile(0.6)].sort_values("buy_rate", ascending=False).iloc[0]

    ax.annotate(f"流量黑洞：品类{int(hole['item_category'])}\n曝光 {hole['pv']:,.0f}，转化仅 {hole['buy_rate']*100:.2f}%",
                xy=(hole["pv"], hole["buy_rate"] * 100),
                xytext=(hole["pv"] * 0.10, hole["buy_rate"] * 100 + 1.8),
                fontsize=10, color="#B01818", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#B01818", lw=1.5))
    ax.annotate(f"高效品类：{int(eff['item_category'])}\n转化 {eff['buy_rate']*100:.2f}%",
                xy=(eff["pv"], eff["buy_rate"] * 100),
                xytext=(eff["pv"] * 1.15, eff["buy_rate"] * 100 * 0.82),
                fontsize=10, color="#1A7A1A", fontweight="bold",
                arrowprops=dict(arrowstyle="->", color="#1A7A1A", lw=1.5))

    ax.set_xscale("log")
    ax.set_title("图2  品类曝光量 vs 支付转化率（气泡大小=支付量）", fontsize=13, fontweight="bold")
    ax.set_xlabel("品类点击/曝光量（对数轴）")
    ax.set_ylabel("支付转化率(%)")
    ax.text(0.98, 0.96, "整体呈「曝光越多、转化越低」的长尾特征",
            transform=ax.transAxes, ha="right", va="top", fontsize=9.5,
            color=GREY, style="italic")
    _style(ax)

    fig.tight_layout()
    p = os.path.join(OUT, "02_category_efficiency.png")
    fig.savefig(p)
    plt.close(fig)
    return p, hole, eff


# ============================================================
# 图3：用户购买量集中度（Lorenz / Pareto 曲线）
# ============================================================
def chart_pareto():
    u = pd.read_csv(os.path.join(EDA, "08b_user_profile.csv"))
    s = np.sort(u["records"].values)[::-1]          # 按购买件次降序
    n = len(s)
    cum_u = np.arange(1, n + 1) / n * 100            # 累计用户占比
    cum_p = np.cumsum(s) / s.sum() * 100             # 累计购买量占比

    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.plot([0, 100], [0, 100], ls="--", color=GREY, lw=1, label="绝对平均线（人人等量购买）")
    ax.plot(cum_u, cum_p, color=C_BUY, lw=2.4, label="实际累计购买量占比")
    ax.fill_between(cum_u, cum_p, cum_u, color=C_BUY, alpha=0.08)

    # 标注关键分位
    for pct, txt, dy in [(10, "前10%用户\n贡献36.9%", 0), (20, "前20%用户\n仅54.8%", 0),
                         (50, "前50%用户\n贡献84.1%", 0)]:
        idx = int(np.ceil(pct / 100 * n)) - 1
        ax.scatter(pct, cum_p[idx], color=C_BUY, zorder=5, s=45)
        ax.annotate(txt, xy=(pct, cum_p[idx]),
                    xytext=(pct + 4, cum_p[idx] - 12 + dy),
                    fontsize=9.5, color=C_BUY, fontweight="bold",
                    arrowprops=dict(arrowstyle="->", color=C_BUY, lw=1.2))

    ax.axhline(80, color=GREY, ls=":", lw=1)
    ax.text(2, 81.5, "80% 购买量", fontsize=9, color=GREY)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 101)
    ax.set_title("图3  用户购买量集中度曲线（检验 80/20 法则：结论是不成立）",
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("累计用户占比(%)  —— 按购买件次从高到低排序")
    ax.set_ylabel("累计购买量占比(%)")
    ax.legend(loc="lower right", frameon=False)
    _style(ax)

    fig.tight_layout()
    p = os.path.join(OUT, "03_user_purchase_pareto.png")
    fig.savefig(p)
    plt.close(fig)
    return p, cum_p


# ============================================================
# 图4：行为意向→支付转化（加购是最强信号）
# ============================================================
def chart_funnel():
    f = pd.read_csv(os.path.join(EDA, "10_pair_funnel.csv"))
    stages = ["点击", "收藏", "加购"]
    rates = f.set_index("stage").loc[stages, "conv_rate"] * 100
    pairs = f.set_index("stage").loc[stages, "user_item_pairs"]

    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(stages, rates, color=[C_PV, "#72B7B2", C_CART], width=0.55)
    for b, r, nn in zip(bars, rates, pairs):
        ax.text(b.get_x() + b.get_width() / 2, r + 0.35,
                f"{r:.2f}%\n(n={int(nn):,})", ha="center", fontsize=10, fontweight="bold")

    lift = rates["加购"] / rates["点击"]
    ax.annotate(f"加购后转化率 = 纯点击的 {lift:.1f} 倍",
                xy=(2, rates["加购"] * 0.55), xytext=(0.15, rates["加购"] * 0.72),
                fontsize=11, color=C_CART, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=C_CART, lw=1.6))
    ax.set_ylim(0, rates.max() * 1.25)
    ax.set_title("图4  行为意向 → 支付转化率（同一用户×同一商品锁对计算）",
                 fontsize=13, fontweight="bold")
    ax.set_ylabel("该行为后发生支付的比例(%)")
    _style(ax, "y")

    fig.tight_layout()
    p = os.path.join(OUT, "04_behavior_intent_funnel.png")
    fig.savefig(p)
    plt.close(fig)
    return p, lift


# ============================================================
# 图5（备选）：匿名地域分区行为量（geohash 已脱敏，只能做相对比较）
# ============================================================
def chart_geo_bonus():
    geo = pd.read_csv(os.path.join(EDA, "09_geo_stats.csv"))
    top = geo.sort_values("pv", ascending=False).head(12).iloc[::-1]

    fig, ax = plt.subplots(figsize=(11, 6.5))
    y = np.arange(len(top))
    ax.barh(y, top["pv"], color=C_PV, alpha=0.8, label="点击/浏览次数")
    ax.set_yticks(y)
    ax.set_yticklabels([f"区域 {g}" for g in top["geo_prefix"]])
    for i, (pv, br) in enumerate(zip(top["pv"], top["buy_rate"])):
        ax.text(pv * 1.01, i, f"{int(pv):,}  转化{br*100:.2f}%", va="center", fontsize=9)

    ax.set_title("图5（备选）匿名地域分区行为量 Top12  —— geohash 已脱敏，仅作相对比较",
                 fontsize=12.5, fontweight="bold")
    ax.set_xlabel("点击/浏览次数")
    ax.set_xlim(0, top["pv"].max() * 1.22)
    _style(ax, "x")

    fig.tight_layout()
    p = os.path.join(OUT, "05_geo_region_bonus.png")
    fig.savefig(p)
    plt.close(fig)
    return p


if __name__ == "__main__":
    paths = []
    p1, pv12, buy12, pv_r, buy_r = chart_time(); paths.append(p1)
    p2, hole, eff = chart_category(); paths.append(p2)
    p3, cum_p = chart_pareto(); paths.append(p3)
    p4, lift = chart_funnel(); paths.append(p4)
    p5 = chart_geo_bonus(); paths.append(p5)

    print("已生成图表：")
    for p in paths:
        print("  ", p)
    print(f"\n双十二：点击 {pv12:,}({pv_r:.2f}x) / 支付 {buy12:,}({buy_r:.2f}x)")
    print(f"流量黑洞品类: {int(hole['item_category'])} (曝光{hole['pv']:,.0f}, 转化{hole['buy_rate']*100:.2f}%)")
    print(f"高效品类    : {int(eff['item_category'])} (转化{eff['buy_rate']*100:.2f}%)")
    print(f"加购/点击转化倍数: {lift:.2f}x")
    print(f"前10%/20%/50% 用户购买量占比: {cum_p[int(0.1*len(cum_p))-1]:.1f}% / "
          f"{cum_p[int(0.2*len(cum_p))-1]:.1f}% / {cum_p[int(0.5*len(cum_p))-1]:.1f}%")
