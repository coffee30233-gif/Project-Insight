"""
backfill_last_year.py
用「分頁回溯」的方式，把去年份的歷史文章補進資料庫（解決 RSS/最新列表頁
抓不到舊資料的問題）。

適用前提：來源網站的列表頁本身有分頁機制（例如 ?page=2、_2.shtml 這類
網址規則），而不是只依賴 RSS。這類頁面理論上可以一直往回翻，直到翻到
去年份的文章為止。

【重要：這裡的分頁網址規則多數還沒有逐一驗證過】
只有 ZOL 投影機頻道的分頁規則有初步跡象（從網站上觀察到的連結格式），
其餘來源（投影時代網頁本體、ZNDS、RUNTO、ProjectorCentral）的實際分頁
網址格式都還需要你或我再花時間逐一開瀏覽器確認，不能直接照抄下面的
PAGINATED_SOURCES 設定就上線——這只是一個可運作的框架，需要照著
README「回溯爬蟲的驗證步驟」把每個來源的分頁規則補確認過一次。

運作邏輯：
  1. 從第 1 頁開始抓列表頁，用跟 scraper_example.py 一樣的正則抓文章連結
  2. 對每篇文章抓 meta 標籤拿到 publish_date
  3. 若該頁文章日期已經早於「目標年份 1/1」，代表翻過頭了，停止翻頁
  4. 若文章日期落在目標年份區間內，才送進 ingest_article()
  5. 為了避免抓到不會停止的網站（例如日期解析失敗），設定 MAX_PAGES 上限

用法：
  python backfill_last_year.py           # 預設抓「去年」
  python backfill_last_year.py 2025      # 指定年份
"""

import re
import sys
import time
import logging
from datetime import date

import requests
from bs4 import BeautifulSoup

import db
from ingest import ingest_article
from scraper_example import (
    HEADERS, _fetch_article_meta, _is_projector_related, PROJECTOR_KEYWORDS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_PAGES = 200  # 安全上限，避免網站分頁規則跟預期不同導致無限爬取


# page_url_template 用 {page} 佔位，page 從 1 開始。
#
# ⚠️ 2026-07 實測結果：ZOL 投影機頻道的「更多」列表頁（more/2_958.shtml）
# 沒有第二頁——網址不會因為翻頁而改變，代表這個頁面很可能是用 JavaScript
# 「載入更多」或滾動載入（AJAX）實作的，背景資料是透過額外的 API 請求拿到，
# 不是單純的網址分頁。這種情況下，用 requests 抓固定網址無法取得更多資料，
# 除非能抓到背後實際呼叫的 API 網址（需要瀏覽器開發者工具的「網路」面板
# 才能看到，這不是本專案目前工具鏈能做到的事）。
#
# 目前為止，我們已確認的所有來源都還沒有找到真正可用的網址分頁機制，
# 所以這個清單暫時是空的。如果你之後發現某個來源確實有「上一頁/下一頁」
# 連結、且網址真的會變，把規則加進這裡即可套用同一套回溯邏輯。
PAGINATED_SOURCES = [
    # 目前沒有已確認可用的來源。
]


def _page_url(source: dict, page: int) -> str:
    page_suffix = "" if page == 1 else f"_{page}"
    return source["page_url_template"].format(page_suffix=page_suffix)


def backfill_source(source: dict, target_year: int):
    logger.info("開始回溯來源：%s，目標年份：%d", source["name"], target_year)
    need_filter = source.get("filter", False)
    encoding = source.get("encoding", "utf-8")

    total_ingested = 0

    for page in range(1, MAX_PAGES + 1):
        url = _page_url(source, page)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
        except Exception:
            logger.warning("第 %d 頁請求失敗，停止翻頁：%s", page, url)
            break
        resp.encoding = encoding

        article_urls = sorted(set(re.findall(source["link_pattern"], resp.text)))
        if not article_urls:
            logger.info("第 %d 頁沒有找到任何文章連結，停止翻頁", page)
            break

        page_has_target_year = False
        page_all_too_old = True

        for article_url in article_urls:
            detail = _fetch_article_meta(article_url, encoding)
            if not detail:
                continue

            try:
                article_year = int(detail["publish_date"][:4])
            except (ValueError, TypeError):
                continue

            if article_year > target_year:
                # 比目標年份新，跳過（可能列表頁混雜了近期文章）
                page_all_too_old = False
                continue
            if article_year < target_year:
                # 比目標年份舊，代表這頁已經翻過頭了
                continue

            page_all_too_old = False
            page_has_target_year = True

            if need_filter and not _is_projector_related(detail["title"]):
                continue

            ingest_article(
                source_name=source["name"],
                original_title=detail["title"],
                url=article_url,
                publish_date=detail["publish_date"],
                raw_content=detail["summary"],
            )
            total_ingested += 1
            time.sleep(2)

        logger.info("第 %d 頁處理完成，本頁是否含目標年份文章：%s", page, page_has_target_year)

        if page_all_too_old:
            logger.info("整頁文章都早於目標年份，停止翻頁")
            break

    logger.info("來源 %s 回溯完成，共補入 %d 篇 %d 年文章", source["name"], total_ingested, target_year)


def main():
    target_year = int(sys.argv[1]) if len(sys.argv) == 2 else date.today().year - 1

    if not PAGINATED_SOURCES:
        print("目前 PAGINATED_SOURCES 是空的——已確認的來源都沒有找到真正可用的")
        print("網址分頁機制（例如 ZOL 實測後發現列表頁沒有第二頁，很可能是 AJAX")
        print("載入，不是傳統網址分頁）。")
        print()
        print("這代表目前沒有可靠的方式能自動回溯歷史資料。建議做法：")
        print(f"  1. 直接用資料庫裡「現有」的資料跑：python generate_annual_report.py {target_year}")
        print("     缺的月份會誠實標「資料缺失」，不會硬湊內容。")
        print("  2. 讓 scraper_example.py 之後穩定每天執行（照 README 的 cron 建議），")
        print("     這樣明年就不會再遇到今年這種歷史缺口問題。")
        return

    db.init_db()
    for source in PAGINATED_SOURCES:
        backfill_source(source, target_year)

    print(f"\n回溯完成。接下來可以執行：")
    print(f"  python generate_annual_report.py {target_year}")
    print("年報產生時會自動偵測資料庫裡已補齊的月份，不需要再手動跑月報。")


if __name__ == "__main__":
    main()
