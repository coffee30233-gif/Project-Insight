"""
ingest.py
串接 db.py 與 gemini_client.py：接收一篇「原始文章」dict，去重後呼叫 Gemini 處理，
再把結構化結果寫回資料庫。所有爬蟲（RSS 或 HTML）最後都呼叫這裡的 ingest_article()。

retry_unprocessed()：補處理「原始記錄已寫入、但 Gemini 那步失敗過」的文章
（processed_at 仍為 NULL）。這類文章通常是遇到 Gemini 塞車失敗、之後又從來源
feed / 列表頁捲掉，爬蟲再也遇不到、也就不會自動重試。爬蟲跑完會呼叫一次。
"""

import logging
import db
import gemini_client
import embeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _process_and_store(article_id: int, source_name: str, original_title: str,
                        url: str, publish_date: str, raw_content: str) -> bool:
    """對「資料庫裡已有原始記錄」的一篇文章跑 Gemini 處理 + 寫回 + 產生 embedding。
    成功回 True，Gemini 那步失敗回 False（原始記錄保留，之後可再補）。"""
    try:
        analysis = gemini_client.process_article(
            source_name=source_name,
            original_title=original_title,
            url=url,
            publish_date=publish_date,
            raw_content=raw_content,
        )
    except Exception:
        logger.exception("Gemini 處理失敗，文章仍保留原始資料待重試：%s", url)
        return False

    db.update_processed_fields(article_id, analysis, gemini_client.now_iso())
    relevance = analysis.get("relevance", "?")
    logger.info("已處理：[%s][%s] %s（%s）", relevance, analysis["category"],
                analysis["title_zh"], analysis.get("relevance_reason", ""))

    if relevance == "Unrelated":
        logger.info("判定為無關文章，不產生 embedding、不會出現在報告或 AI 問答：%s", url)
        return True

    if source_name in db.EXCLUDED_FROM_REPORTS:
        # 這類來源（例如 Reddit）只在「最新情報」列表顯示，不進報告也不進 AI 問答，
        # 因此不需要花 Gemini 額度產生 embedding。
        logger.info("來源 %s 不進報告/問答，略過 embedding：%s", source_name, url)
        return True

    try:
        vector = embeddings.embed_article(analysis["title_zh"], analysis["summary_zh"])
        db.set_embedding(article_id, vector)
    except Exception:
        logger.exception("embedding 產生失敗，文章仍會保留（可事後用 "
                          "embeddings.backfill_embeddings() 補齊）：%s", url)
    return True


def ingest_article(source_name: str, original_title: str, url: str,
                    publish_date: str, raw_content: str, image_url: str | None = None):
    """
    raw_content 建議至少放「文章前 1000-2000 字」或完整內文，太短會讓 Gemini
    摘要品質下降。publish_date 請正規化成 'YYYY-MM-DD' 格式，方便月報依月份查詢。
    image_url 是文章的代表圖片網址（例如 og:image），抓不到就傳 None，之後週報
    PDF 沒有數據可畫圖表時，會拿這個圖片當作視覺點綴用。
    """
    if db.article_exists(url):
        logger.info("略過已存在文章：%s", url)
        return

    article_id = db.insert_raw_article(source_name, original_title, url,
                                        publish_date, raw_content, image_url)
    _process_and_store(article_id, source_name, original_title, url,
                       publish_date, raw_content)


def retry_unprocessed(limit: int = 20, max_consecutive_failures: int = 3) -> dict:
    """
    補處理積壓的未完成文章（processed_at 為 NULL、但有 raw_content 的）。
    limit：這一輪最多補幾篇（守住 Gemini 免費額度）。
    max_consecutive_failures：連續失敗這麼多次就提早收手（大概是 Gemini 又掛了，
    不用把這輪額度全浪費掉）。
    回傳 {"tried": n, "ok": n, "failed": n}。
    """
    rows = db.get_unprocessed_articles(limit=limit)
    if not rows:
        logger.info("沒有待補處理的文章。")
        return {"tried": 0, "ok": 0, "failed": 0}

    logger.info("補處理未完成文章：這輪最多 %d 篇（資料庫目前積壓 %d 篇）",
                limit, db.count_unprocessed())
    ok = failed = consecutive = 0
    for r in rows:
        success = _process_and_store(
            r["id"], r["source_name"], r["original_title"],
            r["url"], r["publish_date"], r["raw_content"],
        )
        if success:
            ok += 1
            consecutive = 0
        else:
            failed += 1
            consecutive += 1
            if consecutive >= max_consecutive_failures:
                logger.warning("連續 %d 次失敗，Gemini 可能又塞車了，這輪補處理提早收手。",
                               consecutive)
                break

    logger.info("補處理完成：嘗試 %d 篇 → 成功 %d、失敗 %d（剩餘積壓 %d）",
                ok + failed, ok, failed, db.count_unprocessed())
    return {"tried": ok + failed, "ok": ok, "failed": failed}


if __name__ == "__main__":
    db.init_db()
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    retry_unprocessed(limit=n)
