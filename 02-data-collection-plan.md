# 电商用户行为数据分析 · 数据采集方案（步骤 2）

> 求职作品集 · 第二步（数据采集方案）
> 项目主题：电商用户行为数据分析（淘宝公开脱敏数据集）
> 说明：本文档只讲"采集思路 + 字段 + 代码框架"，不直接交付成品脚本，需自行调试运行。

---

## 0. 结论先行

本项目**主数据源采用公开脱敏数据集，不爬淘宝**。原因：

1. 淘宝反爬强（登录校验、滑块验证、动态渲染），个人硬爬成功率低、易封 IP；
2. robots 协议与平台服务条款限制，存在法律与合规风险；
3. 作品集若写"淘宝爬取"，面试官会质疑数据合法性与真实性，是**减分项**。

因此主线走公开数据集；爬虫能力另用**合法练习站**做一份可跑通的范式（附录 A），作为"会写爬虫"的能力证明，不混入主数据。

---

## 1. 数据集选型（关键：两个版本别搞混）

网上有两个都被叫作"淘宝用户行为"的数据集，字段和用途完全不同：

| 版本 | 来源 | 时间范围 | 行数 | 字段 | 地域字段 |
|------|------|----------|------|------|----------|
| **A. 2014 移动端版** | 天池 dataset 46「阿里移动推荐算法数据集」/ Kaggle 同名 | 2014-11-18 ~ 12-18 | 12,256,906 | `user_id, item_id, behavior_type(1/2/3/4), user_geohash, item_category, time` | ✅ 有（缺失 68.3%） |
| **B. 2017 推荐版** | 阿里云天池 dataset 649 `UserBehavior` | 2017-11-25 ~ 12-03 | 100,150,807 | `userid, itemid, categoryid, type(pv/buy/cart/fav), timestamp` | ❌ 无 |

### 推荐：A（2014 移动端版）

- 字段与《电商项目.txt》**完全一致**（`behavior_type` 为 1/2/3/4，含 `user_geohash`）；
- 支持第 4 个业务问题「地域消费力分析」；
- 约 1200 万行，本地可跑，读取 100~200 万行子集即可；
- 代价：数据较旧（2014），`user_geohash` 约 70% 缺失 → 必须写进局限性。

### 何时选 B

只有当你更想强调"1 亿级大数据量"的体量感时选 B；但 B **没有 geohash 字段**，必须删掉"地域分析"这一业务问题，改成"用户行为转化漏斗"或"商品类目热度"。

> 本文档以 **A** 为主线。若你确认改用 B，字段与清洗逻辑需相应调整。

---

## 2. 数据源与下载

| 项目 | 内容 |
|------|------|
| 数据集全名 | 淘宝用户行为数据集（`tianchi_mobile_recommend_train_user`） |
| **主下载地址（推荐）** | 阿里云天池 dataset 46：`https://tianchi.aliyun.com/dataset/dataDetail?dataId=46`（国内可直连，支付宝/淘宝扫码登录，**无 Google 验证码**） |
| 文件名 / 大小 | `tianchi_mobile_recommend_train_user.zip`，约 **109 MB**；解压后 `tianchi_mobile_recommend_train_user.csv`，约 1225 万行 |
| 备用地址 | Kaggle：`https://www.kaggle.com/datasets/yijiajia/taobao-userbehavior`（需 Google reCAPTCHA，国内常加载失败，**不推荐**） |
| ⚠ 别下错 | 天池 **dataset 649 是 2017 版（B）**，没有 `user_geohash`，不是 A |
| 下载前提 | 天池需登录（支付宝/淘宝扫码即可，无需翻墙） |
| 文件形态 | `.csv`，逗号分隔，带表头 |
| 合规声明 | 公开脱敏数据集，**非爬虫采集**，仅用于学习与求职作品集 |

---

## 3. 字段清单（数据字典）

以 A 版为准：

| 字段 | 类型 | 含义 | 取值 / 说明 | 用途 |
|------|------|------|-------------|------|
| `user_id` | int | 用户 ID | 脱敏后的整数 | 用户维度分析 |
| `item_id` | int | 商品 ID | 脱敏后的整数 | 商品维度分析 |
| `behavior_type` | int | 行为类型 | 1=点击 2=收藏 3=加购 4=支付 | 转化漏斗 |
| `user_geohash` | str | 用户地理位置哈希 | 大量为空，需解码/聚合 | 地域分析（有限） |
| `item_category` | int | 商品类目 ID | 脱敏后的整数 | 品类分析 |
| `time` | str | 行为时间 | 格式 `YYYY-MM-DD HH`（只到小时） | 时间规律分析 |

> 注意：A 版 `time` 只精确到小时，不是完整时间戳；B 版 `timestamp` 才是 Unix 秒级时间戳，两者清洗方式不同。

---

## 4. 读取与采样代码框架（pandas）

```python
import pandas as pd

FILE = "tianchi_mobile_recommend_train_user.csv"

# 1) 只读前 200 万行做子集，避免一次性读 1200 万行撑爆内存
df = pd.read_csv(FILE, nrows=2_000_000, encoding="utf-8")

# 2) 基础体检
print(df.shape)              # 行数、列数
print(df.head())             # 前 5 行
print(df.dtypes)             # 字段类型
print(df.isnull().sum())     # 各列缺失量（重点看 user_geohash）

# 3) 时间字段解析（A 版只到小时）
df["time"] = pd.to_datetime(df["time"], format="%Y-%m-%d %H", errors="coerce")

# 4) 落盘为采样文件，供后续步骤使用
df.to_csv("sample_user_behavior_2m.csv", index=False, encoding="utf-8-sig")
```

**调试要点：**

- 若报编码错误，把 `encoding` 换成 `"gbk"` 再试；
- 若内存仍吃紧，用 `chunksize` 分批读：

```python
chunks = pd.read_csv(FILE, chunksize=500_000, encoding="utf-8")
sample = pd.concat([c for _, c in zip(range(4), chunks)], ignore_index=True)
```

- 采样后**固定一份** `sample_user_behavior_2m.csv`，后续所有分析都基于它，保证可复现。

---

## 5. 采集规范（若涉及任何网页请求）

1. **遵守 robots.txt**：先访问 `域名/robots.txt`，确认允许抓取路径；
2. **控制频率**：每次请求间隔 1~2 秒（`time.sleep(1)`），避免给对方服务器压力；
3. **设置 UA**：注明用途（如 `PortfolioBot/1.0; +learning`），不伪装成普通用户做恶意请求；
4. **只采公开数据**：不碰登录后内容、个人隐私、支付信息；
5. **不绕过风控**：不破解验证码、不伪造 Cookie、不使用代理池对抗封禁；
6. **遵守平台条款**：若 ToS 明确禁止抓取，则改用公开 API 或数据集。

> 一句话：**能被公开 API / 数据集解决的，就不要硬爬。**

---

## 6. 存储方案

| 文件 | 内容 | 说明 |
|------|------|------|
| `tianchi_mobile_recommend_train_user.csv` | 原始全量 | 只读不写，保留原始 |
| `sample_user_behavior_2m.csv` | 200 万行采样 | 分析主文件 |
| `clean_user_behavior.csv` | 清洗后 | 步骤 3 产出 |
| `books_demo.csv` | 爬虫练习产出 | 附录 A 演示用 |

- 编码统一 `utf-8-sig`（Excel 打开不乱码）；
- 文件名带语义前缀（raw / sample / clean），便于版本管理。

---

## 附录 A：可跑通的 requests + bs4 爬虫范式（合法练习站）

> 用途：证明"会写爬虫"，目标换成专为爬虫练习设计的 `books.toscrape.com`（允许抓取、结构稳定），**不用于淘宝**。

### A.1 目标与字段

- 目标站：`https://books.toscrape.com/`（电商书籍列表，含分页）
- 采集字段：`title`（书名）、`price`（价格）、`rating`（星级）

### A.2 核心代码（已实测跑通）

```python
import csv
import time
import requests
from bs4 import BeautifulSoup

BASE = "https://books.toscrape.com/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioBot/1.0; +learning)"}


def parse_page(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    r.encoding = "utf-8"          # 关键：显式指定，否则价格会乱码成 Â£
    soup = BeautifulSoup(r.text, "html.parser")

    rows = []
    for card in soup.select("article.product_pod"):
        rows.append({
            "title": card.h3.a["title"],
            "price": card.select_one("p.price_color").get_text(strip=True),
            "rating": card.select_one("p.star-rating")["class"][1],
        })

    nxt = soup.select_one("li.next a")
    return rows, (BASE + nxt["href"] if nxt else None)


def crawl_all():
    all_rows, url = [], BASE
    while url:
        rows, url = parse_page(url)
        all_rows.extend(rows)
        time.sleep(1)             # 限速，尊重对方服务器
    return all_rows


if __name__ == "__main__":
    data = crawl_all()
    with open("books_demo.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "price", "rating"])
        writer.writeheader()
        writer.writerows(data)
    print("done:", len(data))
```

### A.3 实测结果（本机验证）

- 单页解析：20 本书，`has next page: True`；
- 修正编码后价格正确显示为 `£51.77`、`£53.74`、`£50.10`；
- 脚本：`ecommerce-portfolio/crawler_demo.py`。

### A.4 踩坑记录（面试可讲）

- **乱码坑**：`requests` 在响应头无 charset 时默认按 ISO-8859-1 解码，导致 `£` 变 `Â£`；显式 `r.encoding = "utf-8"` 解决。
- **分页坑**：下一页链接是相对路径 `catalogue/page-2.html`，需拼接 `BASE`。
- **限速坑**：不加 `sleep` 连续请求易被限流，加 1 秒间隔即可稳定跑完。

---

## 7. 下一步

1. 按第 2 节下载 A 版数据集（`.csv`）；
2. 跑第 4 节代码，生成 `sample_user_behavior_2m.csv`；
3. 若下载不便，可先用**同结构模拟数据**跑通全流程，真实数据到位后再替换（不影响代码与报告结构）；
4. 进入**步骤 3：数据清洗 + EDA**。
