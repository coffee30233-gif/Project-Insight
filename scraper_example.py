"""
scraper_example.py
兩種爬蟲類型，涵蓋 12 個來源的兩種型態：

  A. RSS 來源 -> fetch_rss_source()
     已實測確認可用：投影時代、DigiTimes、TrendForce（Display / Consumer
     Electronics）、IT之家。其中投影時代的 RSS 直接提供完整全文，其餘幾個
     是「綜合性」feed，需搭配 PROJECTOR_KEYWORDS 過濾。
     Reddit r/projectors 的 .rss 是 Reddit 平台標準功能（對任何 subreddit
     加上 /.rss 都適用），機制上是可信的，但因為我的搜尋工具目前抓不到
     reddit.com 的網址本身、沒辦法直接 fetch 測試，尚未做到「有測過」的
     確認等級，正式使用前建議自己手動跑一次確認沒問題。

  B. 純 HTML 列表頁、無 RSS -> fetch_html_list_source()
     已實測確認可用：ZOL投影機頻道、ZNDS投影頻道、洛圖科技(RUNTO)、
     ProjectorCentral、ProjectorReviews。文章詳情頁一律改用穩定的 SEO
     meta 標籤（description / og:title / article:published_time）取資料，
     比針對每個網站硬寫正文 CSS class 更耐用。

  尚未整合：
    - AVS Forum：對自動化請求直接回 402（疑似機器人偵測/反爬），
      需要換一套抓取策略（例如瀏覽器自動化），這裡先不列入。
    - SID：官網雖有新聞區塊，但內容多半非投影機專屬、核心出版品又大多
      需要 Wiley 會員權限，更新頻率也低，不值得自動化，建議人工定期查看。

兩者最後都呼叫 ingest.ingest_article() 完成寫入。
"""

import re
import time
import logging
import feedparser
import requests
from bs4 import BeautifulSoup

from ingest import ingest_article
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ProjectorIntelBot/1.0; "
                  "+mailto:you@example.com)"
}

# 綜合性來源（非投影機專屬）用這組關鍵字過濾標題，符合其一才送進 ingest，
# 避免把大量不相關新聞餵給 Gemini 浪費成本。這份清單建議定期檢視、視情況擴充——
# 太窄會漏掉相關文章，太寬則會混入太多不相關內容，兩者都需要靠觀察
# fetch_rss_source() / fetch_html_list_source() 印出的統計數字來調整。
PROJECTOR_KEYWORDS = [
    "投影", "projector", "projection", "激光电视", "Laser TV",
    "LCoS", "DLP", "3LCD", "1LCD", "ALPD",
    # 中國品牌
    "极米", "XGIMI", "坚果", "当贝", "Dangbei", "Vidda", "峰米", "Fengmi",
    "小明", "小米投影", "海信激光", "长虹", "TCL投影",
    # 國際品牌
    "BenQ", "明基", "Optoma", "奥图码", "Epson", "爱普生", "Sony", "索尼",
    "Panasonic", "松下", "ViewSonic", "优派", "NEC", "Barco", "科视",
    "Christie", "科视", "JVC",
]


def _is_projector_related(title: str) -> bool:
    text = title.lower()
    return any(kw.lower() in text for kw in PROJECTOR_KEYWORDS)


def _normalize_date(raw: str) -> str:
    """
    日期正規化，統一轉成 YYYY-MM-DD（以台灣時間 UTC+8 為準），方便月報依月份查詢。

    重要：原本的寫法是直接 parse 完就 strftime，但像 DigiTimes、TrendForce 這類
    美國/其他時區的網站，RSS 的 pubDate 常常帶有原始時區（例如美東時間），如果不轉換
    成台灣時間就直接取日期，深夜發布的文章換算成台灣時間後就會早一天顯示，
    跟文章實際頁面上顯示的日期對不起來。
    """
    from dateutil import parser as date_parser
    from datetime import timezone, timedelta

    TW_TZ = timezone(timedelta(hours=8))
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone(TW_TZ)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return time.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# A. RSS 來源
# ---------------------------------------------------------------------------

RSS_SOURCES = [
    {"name": "Reddit r/projectors", "url": "https://www.reddit.com/r/projectors/.rss"},
    # 投影時代（PJTime）：description 欄位直接是完整文章全文，最省力的來源。
    {"name": "投影時代", "url": "http://rss.pjtime.com/Projector.xml"},
    # 以下四個是「綜合性」RSS，已實測確認 feed 本身可正常訂閱，
    # 但務必搭配 filter=True 過濾標題，否則會混入大量不相關新聞。
    {"name": "DigiTimes", "url": "https://www.digitimes.com/rss/daily.xml", "filter": True},
    {"name": "TrendForce-Display", "url": "https://www.trendforce.com/feed/Display.html", "filter": True},
    {"name": "TrendForce-ConsumerElec",
     "url": "https://www.trendforce.com/feed/Consumer_electronics.html", "filter": True},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "filter": True},
]


def fetch_rss_source(source: dict):
    logger.info("抓取 RSS 來源：%s", source["name"])
    for retry in range(3):
        try:
            feed = feedparser.parse(source["url"])
        except Exception:
            if retry == 2:
                logging.exception(f"{source['name']} RSS 下載失敗")
                return

            logger.warning("Retry...")
            time.sleep(5)

    need_filter = source.get("filter", False)

    total_entries = len(feed.entries)
    filtered_out = 0
    processed = 0

    for entry in feed.entries:
        title = entry.get("title", "")
        if need_filter and not _is_projector_related(title):
            filtered_out += 1
            continue

        url = entry.get("link")
        # RSS 摘要通常不完整，若需要完整內文，建議另外對 entry.link 發請求
        # 抓詳細頁再解析；投影時代這類提供全文的來源則不需要。
        raw_content = entry.get("summary", title)
        publish_date = _normalize_date(entry.get("published", ""))

        # 嘗試抓縮圖網址（不是每個 RSS 來源都有，抓不到就是 None，不強求）
        image_url = None
        media_thumbnail = entry.get("media_thumbnail")
        media_content = entry.get("media_content")
        if media_thumbnail:
            image_url = media_thumbnail[0].get("url")
        elif media_content:
            image_url = media_content[0].get("url")
        else:
            for link in entry.get("links", []):
                if link.get("type", "").startswith("image/"):
                    image_url = link.get("href")
                    break

        already_exists = db.article_exists(url)
        ingest_article(
            source_name=source["name"],
            original_title=title,
            url=url,
            publish_date=publish_date,
            raw_content=raw_content,
            image_url=image_url,
        )
        if not already_exists:
            processed += 1
        time.sleep(1)  # 避免對來源網站造成負擔

    logger.info(
        "【%s】RSS 共 %d 篇 → 關鍵字濾掉 %d 篇 → 新寫入 %d 篇（其餘為已存在，已跳過）",
        source["name"], total_entries, filtered_out, processed,
    )


# ---------------------------------------------------------------------------
# B. 純 HTML 列表頁（無 RSS）
# ---------------------------------------------------------------------------

HTML_LIST_SOURCES = [
    # ZOL 投影機頻道：列表頁 GBK 編碼，文章網址格式
    # https://projector.zol.com.cn/{目錄}/{文章ID}.html
    {
        "name": "ZOL投影機頻道",
        "list_url": "https://projector.zol.com.cn/list.html",
        "encoding": "gbk",
        "link_pattern": r"https://projector\.zol\.com\.cn/\d{3,4}/\d+\.html",
    },
    # ZNDS資訊：確認有獨立「投影」頻道（news.znds.com，同站也鏡射在
    # n.znds.com），首頁是綜合內容需要過濾。
    {
        "name": "ZNDS投影頻道",
        "list_url": "https://news.znds.com/",
        "encoding": "utf-8",
        "link_pattern": r"https://news\.znds\.com/article(?:/news)?/\d+\.html",
        "filter": True,
    },
    # 洛圖科技 (RUNTO)：官網是涵蓋電視、智能鎖、電子紙等多品類的「市場洞察」
    # 綜合入口，不只投影機，需要過濾。文章連結格式：
    # http://runtotech.com/MarketInsights/info_itemid_{id}_lcid_12.html
    # 由於同一份報告常被 IT之家、ZNDS 等媒體轉載，也可以考慮改成監控搜尋結果
    # 而不一定要直接爬官網。
    {
        "name": "洛圖科技RUNTO",
        "list_url": "http://runtotech.com/",
        "encoding": "utf-8",
        "link_pattern": r"http://runtotech\.com/MarketInsights/info_itemid_\d+_lcid_\d+\.html",
        "filter": True,
    },
    # ProjectorCentral：首頁沒找到公開 RSS 連結，改用新聞列表頁。
    {
        "name": "ProjectorCentral",
        "list_url": "https://www.projectorcentral.com/news-and-articles.cfm",
        "encoding": "utf-8",
        "link_pattern": r"https://www\.projectorcentral\.com/[a-z0-9\-]+\.htm",
    },
    # ProjectorReviews：確認有維護良好的「Industry News」列表頁，內容更新
    # 到 2026-07。文章網址是根目錄下的長 slug（如
    # /epson-enters-the-dvled-market-with-new-le-c1-series-all-in-one-displays/），
    # 跟導覽列的分類連結（如 /best-4k-projectors/）很像，用「slug 至少 25 字元」
    # 這個粗略規則過濾掉大部分導覽連結，仍可能偶爾漏進一兩個分類頁，
    # 但不影響資料正確性，最多就是多一筆內容普通的項目。
    {
        "name": "ProjectorReviews",
        "list_url": "https://www.projectorreviews.com/industry-news/",
        "encoding": "utf-8",
        "link_pattern": r"https://www\.projectorreviews\.com/[a-z0-9\-]{25,}/",
    },
]


def fetch_html_list_source(source: dict):
    logger.info("抓取 HTML 列表來源：%s", source["name"])
    resp = requests.get(source["list_url"], headers=HEADERS, timeout=15)
    resp.raise_for_status()
    resp.encoding = source.get("encoding", resp.apparent_encoding)

    # 大部分新聞站的列表頁沒有統一好抓的 class，直接用正則從全頁 HTML 撈
    # 符合網址格式的連結，再去重，比硬寫 CSS selector 更不容易因版面調整而失效。
    urls = sorted(set(re.findall(source["link_pattern"], resp.text)))
    logger.info("列表頁找到 %d 篇文章連結", len(urls))

    need_filter = source.get("filter", False)
    meta_failed = 0
    filtered_out = 0
    processed = 0

    for url in urls:
        detail = _fetch_article_meta(url, source.get("encoding", "utf-8"))
        if not detail:
            meta_failed += 1
            continue
        if need_filter and not _is_projector_related(detail["title"]):
            filtered_out += 1
            continue

        already_exists = db.article_exists(url)
        ingest_article(
            source_name=source["name"],
            original_title=detail["title"],
            url=url,
            publish_date=detail["publish_date"],
            raw_content=detail["summary"],
            image_url=detail.get("image_url"),
        )
        if not already_exists:
            processed += 1
        time.sleep(2)  # 中文站點對爬蟲頻率較敏感，間隔可拉長

    logger.info(
        "【%s】列表頁連結 %d 篇 → meta 抓取失敗 %d 篇 → 關鍵字濾掉 %d 篇 → "
        "新寫入 %d 篇（其餘為已存在，已跳過）",
        source["name"], len(urls), meta_failed, filtered_out, processed,
    )


def _fetch_article_meta(url: str, encoding: str) -> dict | None:
    """從文章詳情頁的 meta 標籤取出標題、摘要、發布時間。"""

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        logger.warning("抓取文章 meta 失敗：%s", url)
        return None

    resp.encoding = encoding
    soup = BeautifulSoup(resp.text, "html.parser")

    def get_meta(name: str) -> str:
        tag = (
            soup.find("meta", attrs={"name": name})
            or soup.find("meta", attrs={"property": name})
        )
        return tag.get("content", "").strip() if tag else ""

    title = get_meta("og:title") or (
        soup.title.get_text(strip=True) if soup.title else ""
    )
    summary = get_meta("description")
    image_url = get_meta("og:image")

    published_raw = (
        get_meta("article:published_time")
        or get_meta("og:updated_time")
    )
    publish_date = (
        _normalize_date(published_raw) if published_raw else time.strftime("%Y-%m-%d")
    )

    if not title or not summary:
        logger.warning("meta 標籤不完整，略過：%s", url)
        return None

    return {
        "title": title,
        "summary": summary,
        "publish_date": publish_date,
        "image_url": image_url or None,
    }


if __name__ == "__main__":

    db.init_db()

    for src in RSS_SOURCES:
        try:
            fetch_rss_source(src)
        except Exception:
            logging.exception(f"抓取失敗：{src['name']}")

    for src in HTML_LIST_SOURCES:
        try:
            fetch_html_list_source(src)
        except Exception:
            logging.exception(f"抓取失敗：{src['name']}")