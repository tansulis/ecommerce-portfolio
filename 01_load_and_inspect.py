"""
步骤 2.5：数据加载与体检
作用：把下载好的 csv 读进来，看清楚行数、字段、缺失、行为分布、时间范围，
      并输出一份采样文件供后续清洗/EDA 使用。

用法：
  1. 把从 Kaggle 下载的 csv 放到本文件同级的 data/ 目录下
     （若放在本文件同级目录也可以，脚本会自动找）
  2. 把下面的 FILE_NAME 改成你的实际文件名
  3. 运行：python 01_load_and_inspect.py

运行后请把终端输出的「体检结果」复制给我，我据此写步骤 3 的清洗与 EDA 代码。
"""

import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

FILE_NAME = "tianchi_mobile_recommend_train_user.csv"  # ← 改成你下载的实际文件名
SAMPLE_ROWS = 1_000_000  # 只读前 N 行；文件不大想全量读就改成 None
OUT_NAME = "sample_user_behavior.csv"


def locate():
    for candidate in (os.path.join(DATA_DIR, FILE_NAME), os.path.join(HERE, FILE_NAME)):
        if os.path.exists(candidate):
            return candidate
    return None


def read_csv_safely(path, nrows):
    """依次尝试常见编码，避免 UnicodeDecodeError 卡住。"""
    for enc in ("utf-8", "utf-8-sig", "gbk"):
        try:
            return pd.read_csv(path, nrows=nrows, encoding=enc), enc
        except UnicodeDecodeError:
            continue
    raise RuntimeError("utf-8 / utf-8-sig / gbk 三种编码都读取失败，请检查文件是否损坏")


def main():
    path = locate()
    if path is None:
        print("没找到数据文件，请把 csv 放到这个目录：", DATA_DIR)
        raise SystemExit(1)

    print("=" * 60)
    print("读取文件:", path)
    df, enc = read_csv_safely(path, SAMPLE_ROWS)
    print("成功编码:", enc)

    print("\n--- 1. 行列数 shape ---")
    print(df.shape)

    print("\n--- 2. 前 5 行 head ---")
    print(df.head())

    print("\n--- 3. 字段类型 dtypes ---")
    print(df.dtypes)

    print("\n--- 4. 缺失值统计 ---")
    print(df.isnull().sum())

    print("\n--- 5. behavior_type 分布（1点击 2收藏 3加购 4支付）---")
    print(df["behavior_type"].value_counts().sort_index())

    print("\n--- 6. 时间范围 ---")
    print(df["time"].min(), "~", df["time"].max())

    print("\n--- 7. 去重前/后行数 ---")
    before = len(df)
    after = len(df.drop_duplicates())
    print("去重前:", before, "| 去重后:", after, "| 重复行:", before - after)

    out = os.path.join(DATA_DIR, OUT_NAME)
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print("\n采样文件已保存到:", out)


if __name__ == "__main__":
    main()
