"""rag._build_context：丟給模型的文章要依發布日期新到舊排序。"""
import rag


def _a(title, date):
    return {"title_zh": title, "source_name": "s", "publish_date": date,
            "category": "新品發布", "summary_zh": "x"}


def test_context_sorted_newest_first():
    retrieved = [  # 故意用「相似度順序 ≠ 日期順序」
        _a("IFA 2024 舊機", "2024-09-01"),
        _a("IFA 2026 新機", "2026-09-05"),
        _a("CES 2025 中間", "2025-01-06"),
    ]
    ctx = rag._build_context(retrieved)
    # 文章1 應該是最新那篇
    assert ctx.index("IFA 2026 新機") < ctx.index("CES 2025 中間") < ctx.index("IFA 2024 舊機")
    assert ctx.startswith("[文章1] 標題：IFA 2026 新機")


def test_context_missing_date_sorts_last():
    retrieved = [_a("有日期", "2026-01-01"), _a("沒日期", None)]
    ctx = rag._build_context(retrieved)
    assert ctx.index("有日期") < ctx.index("沒日期")
