# -*- coding: utf-8 -*-
"""
步骤4 延伸：动态可视化（GIF 动画）
主题：淘宝用户行为 31 天趋势「逐日生长」+ 双十二爆发标注
说明：用 matplotlib FuncAnimation 逐帧揭示日趋势，最后一帧定格并标出双十二，
      比静态图更能讲清「时间规律」这一业务问题。
依赖：pandas / matplotlib / pillow
"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "output", "charts")
os.makedirs(OUT, exist_ok=True)
EDA = os.path.join(ROOT, "output", "eda")

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

C_PV = "#4C72B0"
C_BUY = "#C44E52"

daily = pd.read_csv(os.path.join(EDA, "03_daily_trend.csv"), parse_dates=["date"])
daily = daily.sort_values("date").reset_index(drop=True)
dates = daily["date"]
pv = daily["pv"].values
buy = daily["buy"].values
n = len(daily)
d1212 = pd.Timestamp("2014-12-12")
base_pv = daily.loc[daily["date"] != d1212, "pv"].mean()
base_buy = daily.loc[daily["date"] != d1212, "buy"].mean()

fig, ax1 = plt.subplots(figsize=(11, 5.2), dpi=110)
ax2 = ax1.twinx()

ln_pv, = ax1.plot([], [], color=C_PV, lw=2.2, label="点击/浏览")
ln_buy, = ax2.plot([], [], color=C_BUY, lw=2.2, marker="o", ms=3, label="支付")
title = ax1.set_title("", fontsize=14, fontweight="bold")
txt = ax1.text(0.01, 0.95, "", transform=ax1.transAxes, fontsize=11,
               va="top", bbox=dict(boxstyle="round", fc="white", ec="#ccc"))

ax1.set_xlabel("日期（2014-11-18 ~ 2014-12-18）")
ax1.set_ylabel("点击量", color=C_PV)
ax2.set_ylabel("支付量", color=C_BUY)
ax1.set_xlim(dates.iloc[0], dates.iloc[-1])
# 固定少量刻度，避免日期标签互相重叠
tick_pos = list(pd.date_range(dates.iloc[0], dates.iloc[-1], freq="5D"))
ax1.set_xticks(tick_pos)
ax1.set_xticklabels([d.strftime("%m-%d") for d in tick_pos], rotation=0, fontsize=9)
ax1.set_ylim(0, pv.max() * 1.12)
ax2.set_ylim(0, buy.max() * 1.25)
ax1.grid(alpha=0.25)

# 预先画好背景中的双十二虚线位置（最后展示）
vline = ax1.axvline(d1212, color=C_BUY, ls="--", lw=1.4, alpha=0)

def init():
    ln_pv.set_data([], [])
    ln_buy.set_data([], [])
    return ln_pv, ln_buy, title, txt, vline

def update(frame):
    # frame: 当前展示到第几天（含）
    k = frame + 1
    x = dates.iloc[:k]
    ln_pv.set_data(x, pv[:k])
    ln_buy.set_data(x, buy[:k])
    cur = dates.iloc[frame]
    if cur == d1212:
        vline.set_alpha(1)
        title.set_text("双十二爆发：支付 %d（日常 %.1f 倍），点击仅 %.1f 倍"
                       % (buy[frame], buy[frame] / base_buy, pv[frame] / base_pv))
    else:
        title.set_text("淘宝用户行为日趋势 · 第 %d / %d 天（%s）"
                       % (k, n, cur.strftime("%Y-%m-%d")))
    # 实时累计信息
    txt.set_text("累计点击 %s\n累计支付 %s"
                 % (f"{pv[:k].sum():,}", f"{buy[:k].sum():,}"))
    return ln_pv, ln_buy, title, txt, vline

# 31 天逐帧 + 末尾停顿 15 帧定格
frames = list(range(n)) + [n - 1] * 15
ani = FuncAnimation(fig, update, frames=frames, init_func=init,
                    interval=180, blit=True, repeat_delay=800)

gif_path = os.path.join(OUT, "chart1_time_pattern_anim.gif")
ani.save(gif_path, writer="pillow", fps=6)
plt.close(fig)
print("已生成动图:", gif_path)
print("文件大小: %.1f KB" % (os.path.getsize(gif_path) / 1024))
