"""
ingest.py
串接 db.py 與 gemini_client.py：接收一篇「原始文章」dict，去重後呼叫 Gemini 處理，
再把結構化結果寫回資料庫。所有爬蟲（RSS 或 HTML）最後都呼叫這裡的 ingest_article()。
"""

import logging
import db
import gemini_client
import embeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def ingest_article(source_name: str, original_title: str, url: str,
                    publish_date: str, raw_content: str):
    """
    raw_content 建議至少放「文章前 1000-2000 字」或完整內文，太短會讓 Gemini
    摘要品質下降。publish_date 請正規化成 'YYYY-MM-DD' 格式，方便月報依月份查詢。
    """
    if db.article_exists(url):
        logger.info("略過已存在文章：%s", url)
        return

    article_id = db.insert_raw_article(source_name, original_title, url,
                                        publish_date, raw_content)

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
        return

    db.update_processed_fields(article_id, analysis, gemini_client.now_iso())
    logger.info("已處理：[%s] %s", analysis["category"], analysis["title_zh"])

    try:
        vector = embeddings.embed_article(analysis["title_zh"], analysis["summary_zh"])
        db.set_embedding(article_id, vector)
    except Exception:
        logger.exception("embedding 產生失敗，文章仍會保留（可事後用 "
                          "embeddings.backfill_embeddings() 補齊）：%s", url)


if __name__ == "__main__":
    db.init_db()
    # 手動測試單篇範例
    ingest_article(
        source_name="ProjectorCentral",
        original_title="Epson Announces New Laser Projector Line",
        url="https://example.com/test-article-1",
        publish_date="2026-07-15",
        raw_content="Epson today announced a new line of laser projectors "
                    "featuring improved brightness and contrast ratios...",
    )
