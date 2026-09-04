"""
db.py
負責 SQLite 資料庫的建立與讀寫。單機/小規模使用足夠；資料量變大後可平移到 PostgreSQL
（欄位設計相同，改用 psycopg2 / SQLAlchemy 即可）。
"""

import os
import sqlite3
import json
from contextlib import contextmanager

# 用絕對路徑（相對於這個檔案的位置），避免在 Vercel Serverless Function 裡
# 因為執行時的工作目錄（cwd）不是專案根目錄，導致找不到資料庫檔案。
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "projector_intel.db")

# Vercel Serverless Function 的檔案系統是唯讀的（只有 /tmp 可寫，而且不會保留），
# 所以部署在 Vercel 上時，一律用「唯讀」模式打開資料庫，就算程式邏輯不小心呼叫到
# 寫入操作，也會直接丟出明確的錯誤，而不是讓 sqlite 嘗試建立 -journal 檔案而失敗。
# 本機開發（跑 ingest.py、api.py 等）不受影響，一樣是正常可寫入模式。
IS_VERCEL = bool(os.environ.get("VERCEL"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    original_title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    publish_date TEXT,
    raw_content TEXT,

    -- 以下欄位由 Gemini 處理後填入（見 gemini_client.process_article）
    title_zh TEXT,
    summary_zh TEXT,
    category TEXT,
    importance INTEGER,
    original_language TEXT,
    keywords TEXT,           -- 存成 JSON 字串陣列
    mentioned_brands TEXT,   -- 存成 JSON 字串陣列

    processed_at TEXT,
    embedding TEXT,          -- 存成 JSON 浮點數陣列，供 RAG 向量搜尋使用
    image_url TEXT,          -- 文章代表圖片網址（例如 og:image），抓不到就是 NULL
    relevance TEXT,          -- Direct / Indirect / Maybe / Unrelated
    relevance_reason TEXT,   -- Gemini 判斷相關性等級的理由

    -- 以下欄位由 check_links.py 定期（每季）填入，用來標記「查看原文」連結是否還活著
    link_status TEXT,        -- ok / dead / blocked / error / NULL(還沒檢查過)
    link_checked_at TEXT,    -- 最後一次檢查的時間（ISO 字串）
    link_final_url TEXT      -- 跟隨轉址後的最終網址（和 url 不同時代表來源網站換了連結）
);
"""

# SQLite 早期版本的資料庫檔案可能是在加入 embedding 欄位之前就建立的，
# 用 ALTER TABLE 補欄位；欄位已存在時會拋錯，直接忽略即可。
MIGRATIONS = [
    "ALTER TABLE articles ADD COLUMN embedding TEXT",
    "ALTER TABLE articles ADD COLUMN image_url TEXT",
    "ALTER TABLE articles ADD COLUMN relevance TEXT",
    "ALTER TABLE articles ADD COLUMN relevance_reason TEXT",
    "ALTER TABLE articles ADD COLUMN link_status TEXT",
    "ALTER TABLE articles ADD COLUMN link_checked_at TEXT",
    "ALTER TABLE articles ADD COLUMN link_final_url TEXT",
]

# 查詢文章時預設排除的相關性等級（「無關」文章不進報告、不進 AI 問答，
# 但仍保留在資料庫裡當作已處理過的記錄，避免爬蟲每次重複處理同一篇浪費額度）。
# 舊資料（還沒有 relevance 欄位、值是 NULL）視為沒問題，不會被這個過濾條件擋掉。
EXCLUDED_RELEVANCE = ("Unrelated",)


@contextmanager
def get_conn():
    if IS_VERCEL:
        # uri=True + mode=ro：純唯讀連線，不會嘗試建立 journal/wal 檔案
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if not IS_VERCEL:
            conn.commit()
    finally:
        conn.close()


def init_db():
    if IS_VERCEL:
        return  # 唯讀環境：資料庫結構在本機產生時就已經建立好，不需要（也不能）在這裡嘗試建表
    with get_conn() as conn:
        conn.execute(SCHEMA)
        for migration in MIGRATIONS:
            try:
                conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # 欄位已存在，忽略


def _relevance_filter_sql() -> str:
    """回傳排除「無關」文章的 SQL 條件片段。NULL（舊資料、還沒判斷過）視為沒問題，不會被排除。"""
    placeholders = ", ".join("?" for _ in EXCLUDED_RELEVANCE)
    return f"(relevance IS NULL OR relevance NOT IN ({placeholders}))"


def article_exists(url: str) -> bool:
    """
    判斷這篇文章「是否已經處理成功過」（不是單純「有沒有這筆原始資料」）。

    這點很重要：insert_raw_article() 會在呼叫 Gemini 之前就先把原始文章寫進資料庫，
    如果 Gemini 處理當下失敗（例如額度不足、503 服務中斷），這筆原始資料還是會留著、
    但 processed_at 是 NULL。如果這裡只檢查「網址存不存在」，這篇文章就會被永遠當成
    「已存在」而跳過，變成再也不會被重試的殭屍資料。改成同時檢查 processed_at，
    失敗的文章下次爬蟲跑到同一個網址時就會被當成「還沒處理過」，重新嘗試。
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM articles WHERE url = ? AND processed_at IS NOT NULL",
            (url,),
        ).fetchone()
        return row is not None


def insert_raw_article(source_name: str, original_title: str, url: str,
                        publish_date: str, raw_content: str,
                        image_url: str | None = None) -> int:
    """
    先寫入未處理的原始文章，回傳 row id。若 url 已存在（不論之前有沒有處理成功），
    一律回傳既有的那筆 row id，不會產生重複資料——這樣上次處理失敗的文章，
    這次會拿到同一個 id 繼續補跑 Gemini 處理，不會變成兩筆重複記錄。
    """
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO articles
               (source_name, original_title, url, publish_date, raw_content, image_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source_name, original_title, url, publish_date, raw_content, image_url),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute("SELECT id FROM articles WHERE url = ?", (url,)).fetchone()
        return row["id"]


def update_processed_fields(article_id: int, analysis: dict, processed_at: str):
    with get_conn() as conn:
        conn.execute(
            """UPDATE articles SET
                 title_zh = ?, summary_zh = ?, category = ?, importance = ?,
                 original_language = ?, keywords = ?, mentioned_brands = ?,
                 processed_at = ?, relevance = ?, relevance_reason = ?
               WHERE id = ?""",
            (
                analysis["title_zh"],
                analysis["summary_zh"],
                analysis["category"],
                analysis["importance"],
                analysis["original_language"],
                json.dumps(analysis["keywords"], ensure_ascii=False),
                json.dumps(analysis["mentioned_brands"], ensure_ascii=False),
                processed_at,
                analysis.get("relevance"),
                analysis.get("relevance_reason"),
                article_id,
            ),
        )


def get_articles_by_month(year: int, month: int) -> list[dict]:
    """取出指定年月、且已完成 Gemini 處理（processed_at 非空）的文章。"""
    prefix = f"{year:04d}-{month:02d}"
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT source_name, title_zh, summary_zh, category, importance,
                      url, publish_date, keywords, mentioned_brands, image_url
               FROM articles
               WHERE publish_date LIKE ? AND processed_at IS NOT NULL
                     AND {_relevance_filter_sql()}""",
            (f"{prefix}%", *EXCLUDED_RELEVANCE),
        ).fetchall()

    articles = []
    for r in rows:
        articles.append({
            "source_name": r["source_name"],
            "title_zh": r["title_zh"],
            "summary_zh": r["summary_zh"],
            "category": r["category"],
            "importance": r["importance"],
            "url": r["url"],
            "publish_date": r["publish_date"],
            "keywords": json.loads(r["keywords"] or "[]"),
            "mentioned_brands": json.loads(r["mentioned_brands"] or "[]"),
            "image_url": r["image_url"],
        })
    return articles


def get_articles_by_date_range(start_date: str, end_date: str) -> list[dict]:
    """
    取出發布日期落在 [start_date, end_date] 區間（含頭尾）、且已完成 Gemini
    處理的文章，依發布日期排序。日期格式是 "YYYY-MM-DD"。供週報使用。
    """
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT source_name, title_zh, summary_zh, category, importance,
                      url, publish_date, keywords, mentioned_brands, image_url
               FROM articles
               WHERE publish_date >= ? AND publish_date <= ? AND processed_at IS NOT NULL
                     AND {_relevance_filter_sql()}
               ORDER BY publish_date ASC""",
            (start_date, end_date, *EXCLUDED_RELEVANCE),
        ).fetchall()

    articles = []
    for r in rows:
        articles.append({
            "source_name": r["source_name"],
            "title_zh": r["title_zh"],
            "summary_zh": r["summary_zh"],
            "category": r["category"],
            "importance": r["importance"],
            "url": r["url"],
            "publish_date": r["publish_date"],
            "keywords": json.loads(r["keywords"] or "[]"),
            "mentioned_brands": json.loads(r["mentioned_brands"] or "[]"),
            "image_url": r["image_url"],
        })
    return articles


# ---------------------------------------------------------------------------
# 以下為 RAG（embedding）與網站 API 用的查詢函式
# ---------------------------------------------------------------------------

def set_embedding(article_id: int, vector: list[float]):
    with get_conn() as conn:
        conn.execute(
            "UPDATE articles SET embedding = ? WHERE id = ?",
            (json.dumps(vector), article_id),
        )


def get_articles_pending_relevance() -> list[dict]:
    """取出已完成摘要處理、但還沒有相關性分類（舊資料）的文章，供回溯分類使用。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, title_zh, summary_zh FROM articles
               WHERE processed_at IS NOT NULL AND relevance IS NULL"""
        ).fetchall()
    return [{"id": r["id"], "title_zh": r["title_zh"], "summary_zh": r["summary_zh"]}
            for r in rows]


def update_relevance(article_id: int, relevance: str, reason: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE articles SET relevance = ?, relevance_reason = ? WHERE id = ?",
            (relevance, reason, article_id),
        )
        if relevance == "Unrelated":
            # 無關文章不需要留著 embedding（反正查詢時也會被過濾掉），順便清掉省空間
            conn.execute("UPDATE articles SET embedding = NULL WHERE id = ?", (article_id,))


def get_unembedded_articles(limit: int = 200) -> list[dict]:
    """取出已完成 Gemini 摘要處理、但尚未產生 embedding 的文章。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, title_zh, summary_zh FROM articles
               WHERE processed_at IS NOT NULL AND embedding IS NULL
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_embedded_articles() -> list[dict]:
    """取出所有已產生 embedding 的文章，供 RAG 檢索時載入記憶體做相似度計算。"""
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, source_name, title_zh, summary_zh, category,
                      importance, url, publish_date, embedding, link_status
               FROM articles
               WHERE embedding IS NOT NULL AND {_relevance_filter_sql()}""",
            EXCLUDED_RELEVANCE,
        ).fetchall()

    articles = []
    for r in rows:
        articles.append({
            "id": r["id"],
            "source_name": r["source_name"],
            "title_zh": r["title_zh"],
            "summary_zh": r["summary_zh"],
            "category": r["category"],
            "importance": r["importance"],
            "url": r["url"],
            "publish_date": r["publish_date"],
            "embedding": json.loads(r["embedding"]),
            "link_status": r["link_status"],
        })
    return articles


def list_articles(source: str | None = None, category: str | None = None,
                   year: int | None = None, month: int | None = None,
                   search: str | None = None, page: int = 1,
                   page_size: int = 20) -> dict:
    """給網站前端「最新文章」列表使用，支援來源/分類/年月/關鍵字過濾與分頁。"""
    conditions = ["processed_at IS NOT NULL", _relevance_filter_sql()]
    params: list = list(EXCLUDED_RELEVANCE)

    if source:
        conditions.append("source_name = ?")
        params.append(source)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if year and month:
        conditions.append("publish_date LIKE ?")
        params.append(f"{year:04d}-{month:02d}%")
    elif year:
        conditions.append("publish_date LIKE ?")
        params.append(f"{year:04d}%")
    if search:
        conditions.append("(title_zh LIKE ? OR summary_zh LIKE ? OR keywords LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where_clause = " AND ".join(conditions)
    offset = (page - 1) * page_size

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM articles WHERE {where_clause}", params
        ).fetchone()["c"]

        rows = conn.execute(
            f"""SELECT id, source_name, title_zh, summary_zh, category,
                       importance, url, publish_date, keywords, mentioned_brands,
                       link_status
                FROM articles
                WHERE {where_clause}
                ORDER BY publish_date DESC, id DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset],
        ).fetchall()

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "source_name": r["source_name"],
            "title_zh": r["title_zh"],
            "summary_zh": r["summary_zh"],
            "category": r["category"],
            "importance": r["importance"],
            "url": r["url"],
            "publish_date": r["publish_date"],
            "keywords": json.loads(r["keywords"] or "[]"),
            "mentioned_brands": json.loads(r["mentioned_brands"] or "[]"),
            # 只有被檢查判定為 dead 時前端才會顯示「連結可能已失效」提示；
            # ok / blocked / error / None 一律當成正常連結（不干擾使用者）。
            "link_status": r["link_status"],
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def get_dashboard_stats() -> dict:
    """給網站首頁 Hero 區塊用的統計數字。"""
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM articles "
            f"WHERE processed_at IS NOT NULL AND {_relevance_filter_sql()}",
            EXCLUDED_RELEVANCE,
        ).fetchone()["c"]

        source_rows = conn.execute(
            f"""SELECT source_name, COUNT(*) AS c FROM articles
               WHERE processed_at IS NOT NULL AND {_relevance_filter_sql()}
               GROUP BY source_name ORDER BY c DESC""",
            EXCLUDED_RELEVANCE,
        ).fetchall()

        category_rows = conn.execute(
            f"""SELECT category, COUNT(*) AS c FROM articles
               WHERE processed_at IS NOT NULL AND {_relevance_filter_sql()}
               GROUP BY category""",
            EXCLUDED_RELEVANCE,
        ).fetchall()

        latest = conn.execute(
            f"""SELECT publish_date FROM articles
               WHERE processed_at IS NOT NULL AND {_relevance_filter_sql()}
               ORDER BY publish_date DESC LIMIT 1""",
            EXCLUDED_RELEVANCE,
        ).fetchone()

    return {
        "total_articles": total,
        "total_sources": len(source_rows),
        "by_source": {r["source_name"]: r["c"] for r in source_rows},
        "by_category": {r["category"]: r["c"] for r in category_rows},
        "latest_publish_date": latest["publish_date"] if latest else None,
    }


# ---------------------------------------------------------------------------
# 原文連結健檢（見 check_links.py）
# ---------------------------------------------------------------------------

def get_articles_for_link_check(stale_days: int | None = None,
                                 limit: int | None = None) -> list[dict]:
    """
    取出需要做「原文連結還活著嗎」檢查的文章（只挑已完成 Gemini 處理的）。

    stale_days：只回傳「從沒檢查過」或「上次檢查超過 N 天前」的文章。傳 None 代表
    全部重檢（每季那次就是這樣跑）。上次結果是 dead / error 的一律重檢，因為來源
    網站可能又把文章補回去、或只是當時暫時性錯誤。
    limit：最多回傳幾筆，方便分批跑。
    """
    conditions = ["processed_at IS NOT NULL"]
    params: list = []
    if stale_days is not None:
        conditions.append(
            "(link_checked_at IS NULL "
            " OR link_status IN ('dead', 'error') "
            " OR julianday('now') - julianday(link_checked_at) >= ?)"
        )
        params.append(stale_days)

    sql = (f"SELECT id, url, link_status, link_checked_at FROM articles "
           f"WHERE {' AND '.join(conditions)} ORDER BY id ASC")
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def update_link_status(article_id: int, status: str, checked_at: str,
                        final_url: str | None = None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE articles
               SET link_status = ?, link_checked_at = ?, link_final_url = ?
               WHERE id = ?""",
            (status, checked_at, final_url, article_id),
        )


def get_link_check_summary() -> dict:
    """回傳各連結狀態的文章數，供 check_links.py 印摘要、export 寫進 stats.json。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT COALESCE(link_status, 'unchecked') AS s, COUNT(*) AS c
               FROM articles WHERE processed_at IS NOT NULL
               GROUP BY COALESCE(link_status, 'unchecked')"""
        ).fetchall()
        last = conn.execute(
            "SELECT MAX(link_checked_at) AS m FROM articles"
        ).fetchone()
    return {
        "by_status": {r["s"]: r["c"] for r in rows},
        "last_checked_at": last["m"] if last else None,
    }


def get_dead_articles_for_archive() -> list[dict]:
    """
    取出「原文連結已失效（dead）」且有存到原文內容（raw_content）的文章，
    供 export_static_data.py 在 ENABLE_ORIGINAL_CACHE 開啟時匯出成本站存檔。
    """
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT id, source_name, original_title, title_zh, url, publish_date,
                       link_final_url, raw_content
               FROM articles
               WHERE processed_at IS NOT NULL
                     AND link_status = 'dead'
                     AND raw_content IS NOT NULL AND TRIM(raw_content) <> ''
                     AND {_relevance_filter_sql()}""",
            EXCLUDED_RELEVANCE,
        ).fetchall()
    return [dict(r) for r in rows]
