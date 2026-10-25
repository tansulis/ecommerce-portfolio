import requests
from bs4 import BeautifulSoup

BASE = "https://books.toscrape.com/"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PortfolioBot/1.0; +learning)"}


def parse_page(url):
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    r.encoding = "utf-8"
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


if __name__ == "__main__":
    rows, next_url = parse_page(BASE)
    print("page1 parsed books:", len(rows))
    for row in rows[:3]:
        print(row)
    print("has next page:", bool(next_url))
