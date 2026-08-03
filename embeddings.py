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


def embed_text(text: str, task_type: str) -> list[float]:
    """
    task_type 依用途區分：
      - "RETRIEVAL_DOCUMENT"：文章存入資料庫時使用
      - "RETRIEVAL_QUERY"：使用者提問時使用
    這兩種 task_type 會讓模型針對「被搜尋」與「發起搜尋」分別優化向量，
    檢索品質會比兩邊都用同一種 task_type 好。
    """
    client = get_client()
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=EMBED_DIMENSIONS,
        ),
    )
    return list(result.embeddings[0].values)


def embed_article(title_zh: str, summary_zh: str) -> list[float]:
    """文章用標題+摘要一起 embed，比只用摘要更能捕捉關鍵詞（品牌、型號等）。"""
    text = f"{title_zh}\n{summary_zh}"
    return embed_text(text, task_type="RETRIEVAL_DOCUMENT")


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
            vector = embed_article(article["title_zh"], article["summary_zh"])
            db.set_embedding(article["id"], vector)
            total += 1
        print(f"已補產生 {total} 篇文章的 embedding...")
    print(f"完成，共補產生 {total} 篇文章的 embedding。")


def cosine_similarity_search(query_vector: list[float], top_k: int = 8) -> list[dict]:
    """在所有已 embed 的文章中，找出跟 query_vector 最相似的 top_k 篇。"""
    articles = db.get_all_embedded_articles()
    if not articles:
        return []

    query_vec = np.array(query_vector, dtype=np.float32)
    query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-10)

    matrix = np.array([a["embedding"] for a in articles], dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    matrix_normalized = matrix / norms

    scores = matrix_normalized @ query_vec  # cosine similarity（向量已正規化）
    top_indices = np.argsort(-scores)[:top_k]

    results = []
    for idx in top_indices:
        article = dict(articles[int(idx)])
        article["similarity"] = float(scores[idx])
        del article["embedding"]  # 不需要回傳給呼叫端
        results.append(article)
    return results


if __name__ == "__main__":
    db.init_db()
    backfill_embeddings()
