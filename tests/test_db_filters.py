"""db.py 的查詢過濾：SQL 片段的 placeholder 數量，以及「Reddit 不進報告、
Unrelated 不進報告」的實際行為（用臨時的 sqlite 檔跑整條查詢）。"""
import json

import pytest

import db


def test_filter_sql_placeholder_counts_match_constants():
    assert db._relevance_filter_sql().count("?") == len(db.EXCLUDED_RELEVANCE)
    assert db._report_source_filter_sql().count("?") == len(db.EXCLUDED_FROM_REPORTS)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """建一個臨時資料庫，塞幾筆測試文章，讓 db.get_conn() 指過去。"""
    p = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", str(p))
    monkeypatch.setattr(db, "IS_VERCEL", False)
    db.init_db()
    rows = [
        # (source_name, title, url, publish_date, relevance)
        ("ProjectorCentral", "正常文章 A", "u1", "2026-09-02", "Direct"),
        ("投影時代",          "正常文章 B", "u2", "2026-09-03", None),      # 舊資料，relevance NULL 也算數
        ("Reddit r/projectors", "論壇求助帖", "u3", "2026-09-04", "Direct"),  # 來源被排除
        ("DigiTimes",        "無關新聞",   "u4", "2026-09-05", "Unrelated"),  # relevance 被排除
    ]
    with db.get_conn() as conn:
        for src, title, url, pdate, rel in rows:
            conn.execute(
                """INSERT INTO articles
                   (source_name, original_title, url, publish_date, raw_content,
                    title_zh, summary_zh, category, importance,
                    processed_at, relevance)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (src, title, url, pdate, "raw", title, "摘要", "技術動態", 3,
                 "2026-09-06T00:00:00Z", rel),
            )
    return p


def test_date_range_excludes_reddit_and_unrelated(temp_db):
    got = db.get_articles_by_date_range("2026-09-01", "2026-09-30")
    titles = {a["title_zh"] for a in got}
    assert titles == {"正常文章 A", "正常文章 B"}


def test_month_query_excludes_reddit_and_unrelated(temp_db):
    got = db.get_articles_by_month(2026, 9)
    titles = {a["title_zh"] for a in got}
    assert "論壇求助帖" not in titles
    assert "無關新聞" not in titles
    assert "正常文章 A" in titles


def test_list_articles_still_includes_reddit(temp_db):
    # 「最新情報」列表要照常顯示 Reddit（只是不進報告）
    res = db.list_articles(source="Reddit r/projectors")
    assert res["total"] == 1


# ---------------------------------------------------------------------------
# _load_rag_jsonl
# ---------------------------------------------------------------------------

def test_load_rag_jsonl(tmp_path, monkeypatch):
    p = tmp_path / "rag.jsonl"
    p.write_text(
        json.dumps({"id": 1, "embedding": [0.1, 0.2]}, ensure_ascii=False) + "\n"
        + "\n"  # 空行要被略過
        + json.dumps({"id": 2, "embedding": [0.3]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "RAG_JSONL_PATH", str(p))
    rows = db._load_rag_jsonl()
    assert [r["id"] for r in rows] == [1, 2]


def test_load_rag_jsonl_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "RAG_JSONL_PATH", str(tmp_path / "nope.jsonl"))
    assert db._load_rag_jsonl() == []
