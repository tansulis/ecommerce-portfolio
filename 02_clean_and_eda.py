# -*- coding: utf-8 -*-
"""
===========================================================
步骤 3：数据清洗 + 探索性数据分析（EDA）
项目：电商用户行为分析（淘宝移动端 2014-11-18 ~ 2014-12-18）
===========================================================

设计要点（写进作品集"工程说明"）：
1. 原始数据 1225 万行 / 508MB，机器 16GB 内存但可用仅约 3GB，
   因此**不全量读入内存**，改用两遍分块扫描：
   - 第 1 遍：算整行哈希，用 np.unique 定位"首次出现"的行号 → 精确定位全局重复行
   - 第 2 遍：按行号掩码过滤 + 边读边聚合，内存只留聚合表
2. 所有聚合都用 "块内 groupby → 汇总 concat" 的方式，峰值内存 < 1GB
3. 分析不落"结论"，只产出可信的统计表；解读留给报告阶段

输出：
  output/eda/*.csv          各分析维度的统计表（步骤 4 画图直接用）
  output/eda/EDA_SUMMARY.txt 控制台报告留档
  data/clean/behavior_clean.csv.gz  清洗后全量数据

用法：
  python 02_clean_and_eda.py              # 全量（约 2-4 分钟）
  python 02_clean_and_eda.py --limit 200000   # 快速试跑前 20 万行
===========================================================
"""

import os
import sys
import time
import argparse

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

# -----------------------------------------------------------
# 0. 路径与常量
# -----------------------------------------------------------
BASE = os.path.dirname(os.path.abspath(__file__))
RAW_PATH = os.path.join(BASE, "data", "tianchi_mobile_recommend_train_user.csv")
OUT_EDA = os.path.join(BASE, "output", "eda")
OUT_CLEAN = os.path.join(BASE, "data", "clean")
for d in (OUT_EDA, OUT_CLEAN):
    os.makedirs(d, exist_ok=True)

CHUNK_SIZE = 1_000_000
SAVE_CLEAN_CSV = True

# 用窄类型压内存：int64 的 id 需要保留（值接近 1e9），行为/品类可窄化
DTYPES = {
    "user_id": "int64",
    "item_id": "int64",
    "behavior_type": "int8",
    "user_geohash": "object",
    "item_category": "int64",
    "time": "object",
}
KEY_COLS = ["user_id", "item_id", "behavior_type", "user_geohash", "item_category", "time"]

BEHAVIOR_MAP = {1: "点击 pv", 2: "收藏 fav", 3: "加购 cart", 4: "支付 buy"}
BEHAVIOR_COLS = {1: "pv", 2: "fav", 3: "cart", 4: "buy"}
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# geohash 前缀只当匿名区域 ID 用（原始值已脱敏，不可反解为真实行政区域）

t_start = time.time()
LOG = []


def log(msg=""):
    """同时打印 + 记录到报告"""
    print(msg)
    LOG.append(str(msg))


def section(title):
    log()
    log("=" * 62)
    log(f"  {title}")
    log("=" * 62)


def save(df, name, index=True):
    """统一落盘：utf-8-sig 让 Excel 打开中文不乱码"""
    path = os.path.join(OUT_EDA, name)
    df.to_csv(path, encoding="utf-8-sig", index=index)
    log(f"  → 已保存 {name}  ({len(df):,} 行)")
    return path


# -----------------------------------------------------------
# 1. 第一遍扫描：精确定位全局重复行
# -----------------------------------------------------------
def pass1_dedup_index(limit=None):
    """
    为什么不用 df.drop_duplicates() 直接去重？
    > 1225 万行全量进内存约 1.5-2GB，本机可用内存不够，会触发
      页面交换、甚至 MemoryError。
    这里的做法：分块算每行的 64 位哈希，拼接后 np.unique 拿到
    "每个哈希首次出现的位置"，即为需要保留的全局行号。
    哈希碰撞概率 n^2/2^65 ≈ 4e-6，可忽略。

    注意：整行参与哈希（含 user_geohash / item_category），
    所以只有 6 个字段完全相同的行才算重复。
    """
    section("第 1 遍扫描：全局精确去重")
    hashes = []
    n_rows = 0
    reader = pd.read_csv(RAW_PATH, chunksize=CHUNK_SIZE, dtype=DTYPES, encoding="utf-8")
    for i, ch in enumerate(reader, 1):
        if limit is not None:
            remain = limit - n_rows
            if remain <= 0:
                break
            if len(ch) > remain:
                ch = ch.iloc[:remain]
        h = pd.util.hash_pandas_object(ch[KEY_COLS], index=False).to_numpy(dtype=np.uint64)
        hashes.append(h)
        n_rows += len(ch)
        log(f"  块 {i:>2}: 累计 {n_rows:>12,} 行")

    all_hash = np.concatenate(hashes)
    del hashes
    _, first_pos = np.unique(all_hash, return_index=True)
    del all_hash

    keep_mask = np.zeros(n_rows, dtype=bool)
    keep_mask[first_pos] = True
    n_dup = int((~keep_mask).sum())
    log()
    log(f"  原始行数      : {n_rows:,}")
    log(f"  全局唯一行数  : {int(keep_mask.sum()):,}")
    log(f"  完全重复行数  : {n_dup:,}  ({n_dup / n_rows * 100:.2f}%)")
    return keep_mask, n_rows


# -----------------------------------------------------------
# 2. 第二遍扫描：清洗 + 边读边聚合
# -----------------------------------------------------------
def pass2_clean_and_aggregate(keep_mask, limit=None):
    """
    清洗规则（逐条注明理由，面试可讲）：
    R1 整行精确去重           —— 采集/上游导出产生的完全重复记录
    R2 behavior_type 必须在 1-4 —— 超出范围的视为异常值丢弃
    R3 time 必须可解析为时间   —— 解析失败的行无法做时间维度分析
    R4 user_geohash 空值保留   —— 它不是错误值，只是"未采集到地域"，
                                  地域分析时单独过滤，不污染整体统计

    产出：把各维度的统计表汇总到 Series/DataFrame 里，最后统一收敛。
    """
    section("第 2 遍扫描：清洗 + 聚合")

    beh_parts, day_parts, hour_parts, wd_parts, cat_parts = [], [], [], [], []
    geo2_parts, geo3_parts = [], []
    pay_parts = []          # 支付明细，供复购分析
    user_parts = {1: [], 2: [], 3: [], 4: []}
    # 商品级漏斗明细：(user_id, item_id) 维度，用于"加购→支付"这类真正的转化率
    pair_parts = {"pv": [], "fav": [], "cart": [], "buy": []}
    raw_daily_parts = []    # 去重前的按日计数，用于披露重复率的时间分布

    clean_writer = None
    clean_path = os.path.join(OUT_CLEAN, "behavior_clean.csv.gz")
    if SAVE_CLEAN_CSV:
        clean_writer = open(clean_path, "w", encoding="utf-8", newline="")
        clean_writer.write("user_id,item_id,behavior_type,user_geohash,item_category,time,date,hour,weekday\n")

    n_read = n_kept = n_bad_behavior = n_bad_time = 0
    offset = 0
    reader = pd.read_csv(RAW_PATH, chunksize=CHUNK_SIZE, dtype=DTYPES, encoding="utf-8")

    for i, ch in enumerate(reader, 1):
        if limit is not None:
            remain = limit - n_read
            if remain <= 0:
                break
            if len(ch) > remain:
                ch = ch.iloc[:remain]
        n_read += len(ch)

        # 去重前按日计数（只取日期部分，异常时间不影响字符串切片）
        raw_daily_parts.append(ch["time"].str.slice(0, 10).value_counts())

        # R1 按全局行号掩码去掉重复行
        keep = keep_mask[offset: offset + len(ch)]
        offset += len(ch)
        ch = ch.loc[keep]

        # R2 行为类型合法性
        bad_b = ~ch["behavior_type"].isin([1, 2, 3, 4])
        n_bad_behavior += int(bad_b.sum())
        ch = ch.loc[~bad_b]

        # R3 时间解析（原始格式 "2014-12-06 02"，精确到小时）
        ts = pd.to_datetime(ch["time"], format="%Y-%m-%d %H", errors="coerce")
        bad_t = ts.isna()
        n_bad_time += int(bad_t.sum())
        ch = ch.loc[~bad_t]
        ts = ts.loc[~bad_t]

        if ch.empty:
            continue
        n_kept += len(ch)

        # ---- 派生时间字段 ----
        ch = ch.copy()
        ch["date"] = ts.dt.normalize()
        ch["hour"] = ts.dt.hour.astype("int8")
        ch["weekday"] = ts.dt.day_of_week.astype("int8")
        ch["ts_hour"] = ts.values.astype("datetime64[h]").astype("int64")

        # ---- 行为类型分布 ----
        beh_parts.append(ch["behavior_type"].value_counts())

        # ---- 日 × 行为 ----
        day_parts.append(ch.groupby(["date", "behavior_type"], observed=True).size())

        # ---- 小时 × 行为 ----
        hour_parts.append(ch.groupby(["hour", "behavior_type"], observed=True).size())

        # ---- 星期 × 行为 ----
        wd_parts.append(ch.groupby(["weekday", "behavior_type"], observed=True).size())

        # ---- 品类 × 行为 ----
        cat_parts.append(ch.groupby(["item_category", "behavior_type"], observed=True).size())

        # ---- 地域（geohash 前缀）× 行为 ----
        gh = ch["user_geohash"].fillna("")
        has_gh = gh.str.len() >= 3
        if has_gh.any():
            sub = ch.loc[has_gh]
            g = gh.loc[has_gh]
            geo2_parts.append(
                sub.assign(geo=g.str[:2]).groupby(["geo", "behavior_type"], observed=True).size()
            )
            geo3_parts.append(
                sub.assign(geo=g.str[:3]).groupby(["geo", "behavior_type"], observed=True).size()
            )

        # ---- 用户级行为集合（用于漏斗） ----
        for bt in (1, 2, 3, 4):
            ids = ch.loc[ch["behavior_type"] == bt, "user_id"].drop_duplicates()
            if len(ids):
                user_parts[bt].append(ids)

        # ---- 商品级漏斗明细：(user_id, item_id) 维度 ----
        # 这是本项目最"硬"的分析基础：真正的电商漏斗必须是同一用户对同一商品
        # 从点击/收藏/加购走到支付，而不是把全站点击和全站支付拿去除。
        for bt, nm in ((1, "pv"), (2, "fav"), (3, "cart"), (4, "buy")):
            sel = ch.loc[ch["behavior_type"] == bt, ["user_id", "item_id", "ts_hour"]]
            if nm == "pv":
                # 点击只需判断"是否点过"，去掉时间后按用户×商品去重，省大量内存
                sel = sel[["user_id", "item_id"]].drop_duplicates()
            if len(sel):
                pair_parts[nm].append(sel)

        # ---- 支付明细 ----
        pay = ch.loc[ch["behavior_type"] == 4, ["user_id", "item_id", "item_category", "date", "hour", "weekday"]]
        if len(pay):
            pay_parts.append(pay)

        # ---- 落清洗后数据 ----
        if clean_writer is not None:
            out = ch[["user_id", "item_id", "behavior_type", "user_geohash",
                      "item_category", "time", "date", "hour", "weekday"]].copy()
            out["user_geohash"] = out["user_geohash"].fillna("")
            out.to_csv(clean_writer, header=False, index=False)

        log(f"  块 {i:>2}: 累计读取 {n_read:>12,} | 清洗后保留 {n_kept:>12,}")

    if clean_writer is not None:
        clean_writer.close()
        size_mb = os.path.getsize(clean_path) / 1024 ** 2
        log(f"\n  清洗后数据已落盘: {clean_path}  ({size_mb:.1f} MB)")

    log()
    log(f"  读取总行数            : {n_read:,}")
    log(f"  清洗后保留            : {n_kept:,}")
    log(f"  丢弃-行为类型异常     : {n_bad_behavior:,}")
    log(f"  丢弃-时间解析失败     : {n_bad_time:,}")

    def merge(parts, names):
        if not parts:
            return pd.Series(dtype="int64")
        s = pd.concat(parts).groupby(level=list(range(len(names))), observed=True).sum()
        s.index = s.index.set_names(names)
        return s

    return {
        "behavior": merge(beh_parts, ["behavior_type"]),
        "daily": merge(day_parts, ["date", "behavior_type"]),
        "hour": merge(hour_parts, ["hour", "behavior_type"]),
        "weekday": merge(wd_parts, ["weekday", "behavior_type"]),
        "category": merge(cat_parts, ["item_category", "behavior_type"]),
        "geo2": merge(geo2_parts, ["geo", "behavior_type"]),
        "geo3": merge(geo3_parts, ["geo", "behavior_type"]),
        "pay": pd.concat(pay_parts, ignore_index=True) if pay_parts else pd.DataFrame(),
        "pairs": {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame(columns=["user_id", "item_id"]))
                  for k, v in pair_parts.items()},
        "raw_daily": (pd.concat(raw_daily_parts).groupby(level=0).sum().sort_index()
                      if raw_daily_parts else pd.Series(dtype="int64")),
        "users": {bt: (pd.concat(v).drop_duplicates() if v else pd.Series(dtype="int64"))
                  for bt, v in user_parts.items()},
        "rows": {"read": n_read, "kept": n_kept,
                 "bad_behavior": n_bad_behavior, "bad_time": n_bad_time},
    }


# -----------------------------------------------------------
# 3. 各维度分析
# -----------------------------------------------------------
def analyze_behavior(agg):
    """A. 行为结构：四类行为各占多少"""
    section("A. 行为结构（behavior_type 分布）")
    s = agg["behavior"]
    total = int(s.sum())
    out = pd.DataFrame({
        "behavior_code": s.index.astype(int),
        "behavior_name": [BEHAVIOR_MAP[int(i)] for i in s.index],
        "count": s.values,
    })
    out["share"] = out["count"] / total
    log(out.to_string(index=False, formatters={"count": "{:,}".format, "share": "{:.2%}".format}))
    log(f"\n  记录总数: {total:,}")

    # 用户规模
    log("\n  各行为涉及的去重用户数：")
    urows = []
    for bt in (1, 2, 3, 4):
        urows.append({
            "behavior": BEHAVIOR_MAP[bt],
            "users": int(len(agg["users"][bt])),
        })
    udf = pd.DataFrame(urows)
    log(udf.to_string(index=False, formatters={"users": "{:,}".format}))

    save(out, "01_behavior_structure.csv", index=False)
    save(udf, "01b_users_by_behavior.csv", index=False)
    return out, udf


def analyze_funnel(agg):
    """
    B. 用户级转化漏斗
    严谨性说明：该数据集没有 session_id，且同一用户点击 A 商品、支付 B 商品
    都会各记一行，所以**不能**做"同商品严格漏斗"。
    这里采用电商行业常用的近似口径：
      用户级转化率 = 有支付行为的用户数 / 有任意行为的用户数
    """
    section("B. 用户行为覆盖率（各行为触达多少用户）")
    u = {bt: set(agg["users"][bt].tolist()) for bt in (1, 2, 3, 4)}
    all_users = u[1] | u[2] | u[3] | u[4]
    n_all = len(all_users)

    rows = []
    for bt in (1, 2, 3, 4):
        n = len(u[bt])
        rows.append({
            "stage": BEHAVIOR_MAP[bt],
            "users": n,
            "rate_of_all": n / n_all,
        })
    fdf = pd.DataFrame(rows)
    log(f"  全样本去重用户数: {n_all:,}")
    log(fdf.to_string(index=False, formatters={"users": "{:,}".format,
                                              "rate_of_all": "{:.2%}".format}))
    log(f"\n  说明：以上是「行为覆盖率」——有多少用户曾经做过某类行为，")
    log(f"        不是转化率。真正的点击→支付转化率见 E-1 商品级漏斗。")

    # 潜在流失池：有过"意图行为"但从未支付，是唤醒营销最该捞的人
    log("\n  潜在流失池（有意图信号但窗口内未支付）：")
    waste_rows = []
    for bt in (2, 3):
        pool = u[bt] - u[4]
        waste_rows.append({
            "signal": BEHAVIOR_MAP[bt],
            "signal_users": len(u[bt]),
            "not_paid_users": len(pool),
            "not_paid_rate": len(pool) / len(u[bt]) if u[bt] else np.nan,
        })
    wdf = pd.DataFrame(waste_rows)
    log(wdf.to_string(index=False, formatters={"signal_users": "{:,}".format,
                                               "not_paid_users": "{:,}".format,
                                               "not_paid_rate": "{:.2%}".format}))

    only_click = u[1] - u[4]
    log(f"  仅点击未支付用户  : {len(only_click):,}（占点击用户 {len(only_click) / len(u[1]):.2%}）")

    save(fdf, "02_user_funnel.csv", index=False)
    save(wdf, "02b_intent_pool.csv", index=False)
    return fdf, n_all, len(u[4]), len(only_click)


def analyze_time(agg):
    """C. 时间规律：日趋势 / 小时 / 星期"""
    section("C. 时间规律")

    # --- 日趋势 ---
    daily = agg["daily"].unstack(fill_value=0)
    daily.columns = [BEHAVIOR_COLS.get(int(c), c) for c in daily.columns]
    for c in ("pv", "fav", "cart", "buy"):
        if c not in daily.columns:
            daily[c] = 0
    daily = daily[["pv", "fav", "cart", "buy"]]
    daily.index.name = "date"
    daily["total"] = daily.sum(axis=1)
    daily = daily.reset_index()
    daily["date_str"] = daily["date"].dt.strftime("%Y-%m-%d")
    daily["weekday"] = daily["date"].dt.day_of_week

    log(f"  时间跨度: {daily['date_str'].min()} ~ {daily['date_str'].max()}  ({len(daily)} 天)")
    log("\n  日支付量 TOP 5：")
    top5 = daily.nlargest(5, "buy")[["date_str", "weekday", "pv", "cart", "buy"]].copy()
    top5["weekday"] = top5["weekday"].map(lambda x: WEEKDAY_CN[int(x)])
    log(top5.to_string(index=False, formatters={"pv": "{:,}".format,
                                               "cart": "{:,}".format,
                                               "buy": "{:,}".format}))
    save(daily[["date", "date_str", "weekday", "pv", "fav", "cart", "buy", "total"]],
         "03_daily_trend.csv", index=False)

    # --- 数据质量披露：重复率按日分布 ---
    # 全量重复率 33%，远高于"随机脏数据"的常见水平，必须查清重复是不是集中在某几天，
    # 否则日趋势会被重复记录放大，结论直接失真。
    raw = agg.get("raw_daily")
    if raw is not None and len(raw) >= 1:
        rd_idx = pd.to_datetime(raw.index)
        kept = daily.set_index("date")["total"]
        cmp = pd.DataFrame({
            "raw": raw.values.astype("int64"),
            "kept": kept.reindex(rd_idx).to_numpy(),
        }, index=rd_idx)
        cmp.index.name = "date"
        cmp["dup_rate"] = 1 - cmp["kept"] / cmp["raw"]
        log("\n  重复率按日分布（去重前 vs 去重后）：")
        log(f"    最低 {cmp['dup_rate'].min():.1%} | 最高 {cmp['dup_rate'].max():.1%} | 均值 {cmp['dup_rate'].mean():.1%}")
        for d, r in cmp.nlargest(3, "dup_rate").iterrows():
            log(f"    重复最重 {d.date()}: 原始 {int(r['raw']):,} → 保留 {int(r['kept']):,}（重复 {r['dup_rate']:.1%}）")
        cmp.reset_index().assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")).to_csv(
            os.path.join(OUT_EDA, "03b_dup_rate_by_day.csv"), encoding="utf-8-sig", index=False)

    # --- 小时分布 ---
    hd = agg["hour"].unstack(fill_value=0)
    hd.columns = [BEHAVIOR_COLS.get(int(c), c) for c in hd.columns]
    for c in ("pv", "fav", "cart", "buy"):
        if c not in hd.columns:
            hd[c] = 0
    hd = hd[["pv", "fav", "cart", "buy"]].reset_index()
    hd.columns = ["hour", "pv", "fav", "cart", "buy"]
    peak_buy = hd.loc[hd["buy"].idxmax()]
    log(f"\n  支付量最高时段: {int(peak_buy['hour']):02d}:00  ({int(peak_buy['buy']):,} 次)")
    log(f"  点击量最高时段: {int(hd.loc[hd['pv'].idxmax(), 'hour']):02d}:00")
    save(hd, "04_hour_distribution.csv", index=False)

    # --- 星期分布 ---
    wd = agg["weekday"].unstack(fill_value=0)
    wd.columns = [BEHAVIOR_COLS.get(int(c), c) for c in wd.columns]
    for c in ("pv", "fav", "cart", "buy"):
        if c not in wd.columns:
            wd[c] = 0
    wd = wd[["pv", "fav", "cart", "buy"]].reset_index()
    wd.columns = ["weekday", "pv", "fav", "cart", "buy"]
    wd["weekday_cn"] = wd["weekday"].map(lambda x: WEEKDAY_CN[int(x)])
    wd["buy_rate"] = wd["buy"] / wd["pv"]
    save(wd, "05_weekday_distribution.csv", index=False)

    # 周末 vs 工作日
    wk = wd.copy()
    wk["is_weekend"] = wk["weekday"] >= 5
    g = wk.groupby("is_weekend")[["pv", "fav", "cart", "buy"]].sum()
    g["buy_rate"] = g["buy"] / g["pv"]
    g.index = ["工作日", "周末"]
    log("\n  工作日 vs 周末（点击-支付转化率）：")
    log(g.to_string(formatters={"pv": "{:,}".format, "fav": "{:,}".format,
                                "cart": "{:,}".format, "buy": "{:,}".format,
                                "buy_rate": "{:.3%}".format}))
    g.reset_index().rename(columns={"index": "day_type"}).to_csv(
        os.path.join(OUT_EDA, "05b_weekend_vs_workday.csv"), encoding="utf-8-sig", index=False)

    return daily, hd, wd


def analyze_category(agg, min_pv=1000):
    """
    D. 品类差异
    注意：转化率 = buy/pv 是"行为量口径"，不是"用户口径"。
    低曝光品类转化率波动极大，所以必须设最小点击量阈值（默认 1000），
    否则 TOP 榜会被只有几次点击的小品类占满 —— 这是新手最常犯的错。
    """
    section("D. 品类差异")
    cat = agg["category"].unstack(fill_value=0)
    cat.columns = [BEHAVIOR_COLS.get(int(c), c) for c in cat.columns]
    for c in ("pv", "fav", "cart", "buy"):
        if c not in cat.columns:
            cat[c] = 0
    cat = cat[["pv", "fav", "cart", "buy"]]
    cat.index.name = "item_category"
    cat = cat.reset_index()
    cat["interact"] = cat["fav"] + cat["cart"]
    cat["buy_rate"] = cat["buy"] / cat["pv"].replace(0, np.nan)

    valid = cat[cat["pv"] >= min_pv]
    log(f"  品类总数: {len(cat):,}，其中点击量 ≥{min_pv:,} 的有效品类: {len(valid):,}")
    log(f"  头部 10 个品类贡献了全部点击的 "
        f"{cat.nlargest(10, 'pv')['pv'].sum() / cat['pv'].sum():.1%}")

    log(f"\n  点击量 TOP 10 品类：")
    t = cat.nlargest(10, "pv")[["item_category", "pv", "cart", "buy", "buy_rate"]]
    log(t.to_string(index=False, formatters={"pv": "{:,}".format, "cart": "{:,}".format,
                                             "buy": "{:,}".format, "buy_rate": "{:.2%}".format}))

    log(f"\n  转化率 TOP 10 品类（点击 ≥{min_pv:,}）：")
    t2 = valid.nlargest(10, "buy_rate")[["item_category", "pv", "buy", "buy_rate"]]
    log(t2.to_string(index=False, formatters={"pv": "{:,}".format, "buy": "{:,}".format,
                                              "buy_rate": "{:.2%}".format}))

    log(f"\n  支付量 TOP 10 品类：")
    t3 = cat.nlargest(10, "buy")[["item_category", "pv", "buy", "buy_rate"]]
    log(t3.to_string(index=False, formatters={"pv": "{:,}".format, "buy": "{:,}".format,
                                              "buy_rate": "{:.2%}".format}))

    save(cat.sort_values("pv", ascending=False), "06_category_stats.csv", index=False)
    return cat


def _pair_key(df):
    """
    把 (user_id, item_id) 压成一个 int64 主键。
    user_id 约 1e8、item_id 约 1e9，乘 1e10 后约 1e18，未超 int64 上限 9.2e18。
    用 int64 主键 + np.isin 做匹配，比 DataFrame.merge 省一个数量级的内存。
    """
    return df["user_id"].to_numpy(np.int64) * 10 ** 10 + df["item_id"].to_numpy(np.int64)


def analyze_pair_funnel(agg):
    """
    E-1. 商品级转化漏斗（本项目最核心、也最容易被面试官认可的分析）

    为什么必须做这一层？
    「全站点击 748 万次、全站支付 11 万次，所以转化率 1.5%」这种算法是错的：
    点击 A 商品、支付 B 商品的用户会把转化率算高，而且分子分母根本不是同一批对象。
    正确做法是**锁定同一个 (用户, 商品) 对**，看它在点击/收藏/加购之后有没有走向支付。

    口径：
      - 分母：发生过该行为的唯一 (user_id, item_id) 对数
      - 分子：其中该商品最终发生过支付的（收藏/加购还要求"行为时间 ≤ 首次支付时间"）
      - 时间窗口限制：数据只有 30 天，最后几天的加购可能还没来得及转化，
        所以这个转化率是**观测窗口内的下限**，不是绝对转化率。
    """
    section("E-1. 商品级转化漏斗（同一用户 × 同一商品）")
    pairs = agg["pairs"]
    buy = pairs.get("buy")
    if buy is None or buy.empty:
        log("  无支付记录")
        return None

    buy_first = buy.groupby(["user_id", "item_id"], as_index=False)["ts_hour"].min()
    buy_first.columns = ["user_id", "item_id", "buy_ts"]
    buy_keys = np.sort(_pair_key(buy_first))
    log(f"  发生过支付的「用户×商品」对数: {len(buy_first):,}")

    rows = []
    for nm, label in (("pv", "点击"), ("fav", "收藏"), ("cart", "加购")):
        src = pairs.get(nm)
        if src is None or src.empty:
            continue
        if nm == "pv":
            s = src.drop_duplicates(["user_id", "item_id"])
            conv = np.isin(_pair_key(s), buy_keys)
            n_src = len(s)
            n_conv = int(conv.sum())
            rate = n_conv / n_src
            note = "该用户对该商品是否曾支付"
        else:
            s = src.groupby(["user_id", "item_id"], as_index=False)["ts_hour"].min()
            s.columns = ["user_id", "item_id", "src_ts"]
            m = s.merge(buy_first, on=["user_id", "item_id"], how="left")
            has = m["buy_ts"].notna().to_numpy()
            # NaN 参与比较恒为 False，不会误判
            after = np.where(has, m["buy_ts"].to_numpy() >= m["src_ts"].to_numpy(), False)
            n_src = len(m)
            n_conv = int(after.sum())
            rate = n_conv / n_src
            note = "先有该行为、其后发生支付"
        rows.append({"stage": label, "user_item_pairs": n_src,
                     "converted": n_conv, "conv_rate": rate, "note": note})
        log(f"  {label:<2} → 支付 : {n_conv:>8,} / {n_src:>9,} = {rate:6.2%}   ({note})")

    fdf = pd.DataFrame(rows)
    if len(fdf) >= 3:
        log(f"\n  逐级衰减倍数：")
        for i in range(1, len(fdf)):
            prev, cur = fdf.iloc[i - 1], fdf.iloc[i]
            log(f"    {prev['stage']} → {cur['stage']}: "
                f"{prev['conv_rate']:.2%} → {cur['conv_rate']:.2%}"
                f"（意图强度放大 {cur['conv_rate'] / prev['conv_rate']:.1f}×）")
    save(fdf, "10_pair_funnel.csv", index=False)
    return fdf


def analyze_repurchase(agg):
    """
    E-2. 购买强度与复购

    【一个必须避开的坑 —— 我第一版就踩了】
    这个数据集**没有订单号**，一条支付记录 = "支付了 1 件某商品"。
    如果把"支付记录数"当成"购买次数"，会算出"人均支付 12 次、复购率 91%"
    这种在电商里根本不可能的数——因为用户买 12 件不同商品，被误当成了重复购买。

    所以复购必须定义在**同一个商品**上：
      - 复购（严格）：同一用户对同一 item_id 支付 ≥ 2 次
      - 跨天复购  ：同一用户对同一 item_id 在有支付的天数 ≥ 2 天
      - 同品类复购：同一用户对同一 item_category 支付 ≥ 2 次（放宽口径，衡量品类忠诚）
    另外单独给出"购买件次"分布和"购买广度"（买了多少个不同商品/品类），
    这两个指标才对应"人均购买件数"，不要叫复购。
    """
    section("E-2. 购买强度与复购")
    pay = agg["pay"]
    if pay.empty:
        log("  无支付记录")
        return None

    n_records = len(pay)
    n_buyers = pay["user_id"].nunique()

    # 同一用户、同一商品、同一小时的多条支付记录，无法区分"买 2 件"和"重复记录"，
    # 保守起见折叠为 1 次（宁可低估，也不虚报复购率）
    pay_fold = pay.drop_duplicates(subset=["user_id", "item_id", "date", "hour"])
    log(f"  支付用户数                : {n_buyers:,}")
    log(f"  支付记录数（原始）        : {n_records:,}")
    log(f"  折合同用户同商品同小时    : {len(pay_fold):,}"
        f"（折叠掉 {n_records - len(pay_fold):,} 条，占 {(n_records - len(pay_fold)) / n_records:.1%}）")

    by_item = pay_fold.groupby(["user_id", "item_id"]).agg(
        cnt=("date", "size"), days=("date", "nunique"))
    per_user = by_item.groupby(level=0).agg(
        item_pairs=("cnt", "size"),   # 购买过的不同商品数
        records=("cnt", "sum"),       # 购买件次
    )
    per_user["cats"] = pay_fold.groupby("user_id")["item_category"].nunique()

    rep_item = (by_item["cnt"] >= 2).groupby(level=0).any().reindex(per_user.index).fillna(False)
    rep_day = (by_item["days"] >= 2).groupby(level=0).any().reindex(per_user.index).fillna(False)
    by_cat = pay_fold.groupby(["user_id", "item_category"]).size()
    rep_cat = (by_cat >= 2).groupby(level=0).any().reindex(per_user.index).fillna(False)

    log()
    log(f"  人均购买件次              : {per_user['records'].sum() / n_buyers:.2f} 件")
    log(f"  人均购买商品数            : {per_user['item_pairs'].mean():.2f} 个")
    log(f"  人均购买品类数            : {per_user['cats'].mean():.2f} 个")
    log()
    log(f"  复购率（同商品支付≥2次）  : {rep_item.mean():.2%}  ({int(rep_item.sum()):,} / {n_buyers:,} 人)")
    log(f"  跨天复购率（同商品≥2天）  : {rep_day.mean():.2%}  ({int(rep_day.sum()):,} 人)")
    log(f"  同品类复购率（同品类≥2次）: {rep_cat.mean():.2%}  ({int(rep_cat.sum()):,} 人)")

    # ---- 购买件次分布 + 帕累托 ----
    bins = [0, 1, 2, 5, 10, 20, np.inf]
    labels = ["1 件", "2 件", "3-5 件", "6-10 件", "11-20 件", "20 件以上"]
    band = pd.cut(per_user["records"], bins=bins, labels=labels)
    dist = band.value_counts().reindex(labels)
    total_rec = per_user["records"].sum()
    ddf = pd.DataFrame({
        "purchase_band": labels,
        "users": dist.values,
        "user_share": dist.values / n_buyers,
        "records": [int(per_user.loc[band == l, "records"].sum()) for l in labels],
    })
    ddf["record_share"] = ddf["records"] / total_rec
    ddf["cum_record_share"] = ddf["record_share"].cumsum()
    log("\n  购买件次分布（帕累托：少数人贡献多数购买量）：")
    log(ddf.to_string(index=False, formatters={
        "users": "{:,}".format, "user_share": "{:.2%}".format,
        "records": "{:,}".format, "record_share": "{:.2%}".format,
        "cum_record_share": "{:.2%}".format}))
    save(ddf, "07_purchase_band.csv", index=False)

    summary = pd.DataFrame([
        {"metric": "支付用户数", "value": n_buyers},
        {"metric": "支付记录数", "value": n_records},
        {"metric": "折叠后支付件次", "value": len(pay_fold)},
        {"metric": "人均购买件次", "value": round(len(pay_fold) / n_buyers, 2)},
        {"metric": "人均购买商品数", "value": round(float(per_user["item_pairs"].mean()), 2)},
        {"metric": "人均购买品类数", "value": round(float(per_user["cats"].mean()), 2)},
        {"metric": "复购率_同商品", "value": round(float(rep_item.mean()), 4)},
        {"metric": "跨天复购率_同商品", "value": round(float(rep_day.mean()), 4)},
        {"metric": "同品类复购率", "value": round(float(rep_cat.mean()), 4)},
    ])
    save(summary, "08_repurchase_summary.csv", index=False)

    # 用户画像表，步骤 4 的"高价值用户"分析直接用
    prof = per_user.reset_index()
    prof["is_repurchase_item"] = rep_item.values
    prof["is_repurchase_cross_day"] = rep_day.values
    prof["is_repurchase_cat"] = rep_cat.values
    prof.to_csv(os.path.join(OUT_EDA, "08b_user_profile.csv"), encoding="utf-8-sig", index=False)
    log(f"\n  → 已保存 08b_user_profile.csv ({len(prof):,} 行，用户级画像)")
    return prof


def analyze_geo(agg, topn=20):
    """
    F. 地域分布

    三个必须在报告里写清的口径限制（否则结论站不住）：
    1) user_geohash 缺失严重：原始数据约 68% 缺失、清洗后仍约 53% 缺失
       （仅约 47% 的清洗后记录带位置；按用户计约 82% 的用户至少有一条带位置）。
       地域结论只代表"有地理标记的记录"子集，不能外推到全量用户；
    2) 该字段已脱敏：用标准 geohash 算法解码，得到的坐标落在北美
       （实测 lon≈-123），证明原始值被偏移/替换过，**无法还原真实城市**。
       所以这里只把 geohash 前缀当作"匿名区域 ID"，做**区域之间的相对比较**，
       不做中国地图落点，也不把前缀解释成具体城市名 —— 这是避免作品集
       出现"看起来专业、实际错误"内容的关键；
    3) 一个 geohash 前缀可能横跨多个城市，只能理解为"同一片区域"。
    """
    section("F. 地域分布（geohash 前缀，匿名区域）")
    gh = agg["geo2"]
    if gh.empty:
        log("  无地域数据")
        return None

    def build(series, name="geo_prefix"):
        df = series.unstack(fill_value=0)
        df.columns = [BEHAVIOR_COLS.get(int(c), c) for c in df.columns]
        for c in ("pv", "fav", "cart", "buy"):
            if c not in df.columns:
                df[c] = 0
        df = df[["pv", "fav", "cart", "buy"]].reset_index()
        df.columns = [name, "pv", "fav", "cart", "buy"]
        df["total"] = df[["pv", "fav", "cart", "buy"]].sum(axis=1)
        df["buy_rate"] = df["buy"] / df["pv"].replace(0, np.nan)
        return df.sort_values("total", ascending=False)

    geo = build(gh)
    cov = geo["total"].sum() / agg["behavior"].sum()
    log(f"  有 geohash 的记录占比 : {cov:.2%}（其余为缺失，地域结论仅代表此子集）")
    log(f"  前 2 位分区数         : {len(geo):,}（粗粒度，约千公里级）")

    log(f"\n  行为量 TOP {topn} 区域（仅作匿名区域 A/B/C 比较，非真实地名）：")
    top = geo.head(topn).copy()
    top["rank"] = range(1, len(top) + 1)
    log(top[["rank", "geo_prefix", "pv", "cart", "buy", "buy_rate"]].to_string(
        index=False, formatters={"pv": "{:,}".format, "cart": "{:,}".format,
                                 "buy": "{:,}".format, "buy_rate": "{:.2%}".format}))
    log(f"\n  区域集中度：TOP5 区域占该子集行为量 "
        f"{top['total'].head(5).sum() / geo['total'].sum():.1%}")
    log(f"  区域内转化率极差：最高 {geo['buy_rate'].max():.2%} / 最低 {geo['buy_rate'].min():.2%}")

    save(geo, "09_geo_stats.csv", index=False)
    save(top, "09b_geo_top.csv", index=False)
    return geo


# -----------------------------------------------------------
# 4. 主流程
# -----------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="只读前 N 行，用于快速试跑")
    ap.add_argument("--no-save-clean", action="store_true", help="不落清洗后明细（省时间与磁盘）")
    args = ap.parse_args()
    limit = args.limit
    global SAVE_CLEAN_CSV
    if args.no_save_clean:
        SAVE_CLEAN_CSV = False

    log("=" * 62)
    log("  电商用户行为分析 · 步骤 3：数据清洗 + EDA")
    log("=" * 62)
    log(f"  数据源: {RAW_PATH}")
    log(f"  模式  : {'全量' if limit is None else f'前 {limit:,} 行（试跑）'}")

    if not os.path.exists(RAW_PATH):
        log(f"\n  [错误] 找不到数据文件: {RAW_PATH}")
        sys.exit(1)

    keep_mask, n_rows = pass1_dedup_index(limit)
    agg = pass2_clean_and_aggregate(keep_mask, limit)

    analyze_behavior(agg)
    analyze_funnel(agg)
    analyze_time(agg)
    analyze_category(agg)
    analyze_pair_funnel(agg)
    analyze_repurchase(agg)
    analyze_geo(agg)

    section("完成")
    log(f"  总耗时: {time.time() - t_start:.1f} 秒")
    log(f"  统计表目录: {OUT_EDA}")

    with open(os.path.join(OUT_EDA, "EDA_SUMMARY.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(LOG))
    print(f"\n  报告已保存: {os.path.join(OUT_EDA, 'EDA_SUMMARY.txt')}")


if __name__ == "__main__":
    main()
