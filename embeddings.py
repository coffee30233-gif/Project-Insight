"""
embeddings.py
負責把文章摘要轉成向量（embedding），並提供向量相似度搜尋，是 RAG 問答功能
的檢索基礎。

規模考量：這個範例用「把所有 embedding 讀進記憶體、用 numpy 算 cosine
similarity」的簡單做法，不需要額外的向量資料庫，幾千篇文章的規模完全夠用、
延遲也很低。文章數量成長到數萬篇以上時，才需要考慮換成專門的向量資料庫
（如 sqlite-vec、Chroma、pgvector）。
"""

import os

from dotenv import load_dotenv

load_dotenv()

import json
import time

import numpy as np
from google import genai
from google.genai import types

import db

EMBED_MODEL = "gemini-embedding-2"
EMBED_DIMENSIONS = 768  # 用 MRL 截斷到 768 維，兼顧品質與儲存/計算成本

_client = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("請先設定環境變數 GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client


def embed_text(text: str, task_type: str, max_retry: int = 4) -> list[float]:
    """
    task_type 依用途區分：
      - "RETRIEVAL_DOCUMENT"：文章存入資料庫時使用
      - "RETRIEVAL_QUERY"：使用者提問時使用
    這兩種 task_type 會讓模型針對「被搜尋」與「發起搜尋」分別優化向量，
    檢索品質會比兩邊都用同一種 task_type 好。

    遇到 429（超速）/ 503（Google 端過載）會退避重試——批次重算幾百篇時，
    中間撞一次暫時性錯誤不該讓整批中斷。
    """
    client = get_client()
    for attempt in range(max_retry):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=EMBED_DIMENSIONS,
                ),
            )
            return list(result.embeddings[0].values)
        except Exception as e:
            msg = str(e).lower()
            transient = any(k in msg for k in
                            ("429", "503", "unavailable", "resource_exhausted",
                             "deadline", "500", "internal"))
            if not transient or attempt == max_retry - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"embed_text 暫時性錯誤（{type(e).__name__}），{wait}s 後重試 "
                  f"({attempt + 1}/{max_retry})")
            time.sleep(wait)


def _article_embed_text(title_zh, summary_zh, category=None,
                         brands=None, keywords=None) -> str:
    """組出要 embed 的文字：標題 + 摘要 + 分類 + 品牌 + 關鍵字。
    加進分類/品牌/關鍵字後，像「當貝有什麼新品」「雷射光源」這類查詢的命中率會更好。"""
    parts = [title_zh or "", summary_zh or ""]
    if category:
        parts.append(f"分類：{category}")
    if brands:
        parts.append("品牌：" + "、".join(str(b) for b in brands if b))
    if keywords:
        parts.append("關鍵字：" + "、".join(str(k) for k in keywords if k))
    return "\n".join(p for p in parts if p)


def embed_article(title_zh, summary_zh, category=None,
                   brands=None, keywords=None) -> list[float]:
    """文章 embed。Embedding 免費額度是 100 RPM，遠不到瓶頸，所以這裡不套節流閥。"""
    text = _article_embed_text(title_zh, summary_zh, category, brands, keywords)
    return embed_text(text, task_type="RETRIEVAL_DOCUMENT")


def reembed_all(sleep_between: float = 0.7) -> int:
    """
    把「應該要有 embedding」的文章全部重新 embed（換模型 / 改 embed 文字後用）。
    不會改變向量『數量』——只是用新的輸入文字重算既有這些文章的向量，維度一樣 768。
    回傳重算的篇數。
    """
    rows = db.get_articles_for_reembed()
    total = len(rows)
    print(f"要重新 embed 的文章：{total} 篇")
    done = failed = 0
    for r in rows:
        try:
            vec = embed_article(
                r["title_zh"], r["summary_zh"],
                category=r.get("category"),
                brands=r.get("mentioned_brands"),
                keywords=r.get("keywords"),
            )
            db.set_embedding(r["id"], vec)
            done += 1
        except Exception as e:
            failed += 1
            print(f"  ! id={r['id']} 重算失敗，跳過：{type(e).__name__}: {str(e)[:80]}")
        if (done + failed) % 50 == 0 or (done + failed) == total:
            print(f"  {done + failed}/{total}（成功 {done}、失敗 {failed}）")
        if sleep_between:
            time.sleep(sleep_between)
    print(f"完成，共重算 {done} 篇（失敗 {failed} 篇，可再跑一次補）。")
    return done


def embed_query(question: str) -> list[float]:
    return embed_text(question, task_type="RETRIEVAL_QUERY")


def backfill_embeddings(batch_size: int = 200):
    """把資料庫裡「已處理但還沒有 embedding」的文章補產生 embedding。
    ingest.py 在正常流程中會自動呼叫這個功能的單篇版本，這個函式主要用在：
      - 第一次導入 RAG 功能時，補齊過去已經存在的文章
      - embedding 模型更換時，重新 backfill
    """
    total = 0
    while True:
        pending = db.get_unembedded_articles(limit=batch_size)
        if not pending:
            break
        for article in pending:
            vector = embed_article(
                article["title_zh"], article["summary_zh"],
                category=article.get("category"),
                brands=article.get("mentioned_brands"),
                keywords=article.get("keywords"),
            )
            db.set_embedding(article["id"], vector)
            total += 1
        print(f"已補產生 {total} 篇文章的 embedding...")
    print(f"完成，共補產生 {total} 篇文章的 embedding。")


# importance（1-5，3 為基準）在「相似度相近」時當加分：每偏離基準 1 分，
# 對排序分數加/減這麼多。抓 0.02 是因為真正相關的文章之間相似度差距通常 > 0.05，
# 所以這個加分只會翻動「本來就咬得很近」的名次，不會把不相關的文章拉上來。
IMPORTANCE_RERANK_BONUS = 0.02


def cosine_similarity_search(query_vector: list[float], top_k: int = 8,
                              min_similarity: float = 0.0) -> list[dict]:
    """
    在所有已 embed 的文章中，找出跟 query_vector 最相似的 top_k 篇。

    排序：主要看 cosine 相似度，importance 只在相似度相近時當 tie-breaker
    （見 IMPORTANCE_RERANK_BONUS）。回傳的 similarity 欄位仍是「真實的 cosine 值」。

    min_similarity：真實 cosine 相似度低於這個值的結果直接丟掉。用來讓「資料庫裡
    其實沒有相關內容」的問題回傳空清單，而不是硬塞幾篇不相關的給模型當根據。
    """
    articles = db.get_all_embedded_articles()
    if not articles:
        return []

    query_vec = np.array(query_vector, dtype=np.float32)
    query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-10)

    matrix = np.array([a["embedding"] for a in articles], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    matrix_normalized = matrix / norms

    scores = matrix_normalized @ query_vec  # cosine similarity（向量已正規化）

    # 先取比 top_k 寬一點的候選（純相似度），再用「相似度 + importance 加分」重排。
    pool = min(len(articles), max(top_k * 3, top_k + 5))
    pool_idx = np.argsort(-scores)[:pool]

    def rerank_key(i):
        imp = articles[int(i)].get("importance") or 3
        return float(scores[i]) + IMPORTANCE_RERANK_BONUS * (imp - 3)

    ordered = sorted(pool_idx, key=rerank_key, reverse=True)

    results = []
    for idx in ordered:
        score = float(scores[idx])           # 真實 cosine，不含加分
        if score < min_similarity:
            continue
        article = dict(articles[int(idx)])
        article["similarity"] = score
        del article["embedding"]             # 不需要回傳給呼叫端
        results.append(article)
        if len(results) >= top_k:
            break
    return results


if __name__ == "__main__":
    db.init_db()
    backfill_embeddings()
