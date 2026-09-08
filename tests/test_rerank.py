"""embeddings.cosine_similarity_search 的 importance tie-breaker。"""
import numpy as np
import pytest

import embeddings


def _fake_articles(rows):
    """rows: list of (id, vec, importance)"""
    return [
        {"id": i, "embedding": list(v), "importance": imp,
         "source_name": "s", "title_zh": f"t{i}", "summary_zh": "x",
         "category": "技術動態", "url": f"u{i}", "publish_date": "2026-09-01"}
        for (i, v, imp) in rows
    ]


def test_importance_breaks_near_ties(monkeypatch):
    # 兩篇跟 query 幾乎一樣近（相似度差 < bonus），importance 高的要排前面
    q = [1.0, 0.0]
    arts = _fake_articles([
        (1, [1.00, 0.02], 2),   # 稍微更近一點點，但 importance 低
        (2, [1.00, 0.05], 5),   # 稍微遠一點點，但 importance 高
        (3, [0.0, 1.0], 3),     # 完全不相關
    ])
    monkeypatch.setattr(embeddings.db, "get_all_embedded_articles", lambda: arts)
    out = embeddings.cosine_similarity_search(q, top_k=2)
    assert [a["id"] for a in out] == [2, 1]         # importance 5 的被拉到前面
    assert out[0]["similarity"] < out[1]["similarity"]  # 但回傳的 similarity 仍是真實 cosine


def test_importance_does_not_beat_real_relevance(monkeypatch):
    # 相似度差很多時，importance 不該翻盤
    q = [1.0, 0.0]
    arts = _fake_articles([
        (1, [1.0, 0.0], 1),     # 完全命中，importance 最低
        (2, [0.3, 0.95], 5),    # 明顯較不相關，importance 最高
    ])
    monkeypatch.setattr(embeddings.db, "get_all_embedded_articles", lambda: arts)
    out = embeddings.cosine_similarity_search(q, top_k=2)
    assert out[0]["id"] == 1                        # 真正相關的還是第一


def test_min_similarity_still_applies(monkeypatch):
    q = [1.0, 0.0]
    arts = _fake_articles([(1, [0.0, 1.0], 5)])     # 垂直 → 相似度 ~0
    monkeypatch.setattr(embeddings.db, "get_all_embedded_articles", lambda: arts)
    assert embeddings.cosine_similarity_search(q, top_k=5, min_similarity=0.3) == []
