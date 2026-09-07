"""scraper_example.py 裡幾個純函式的單元測試（不碰網路 / DB）。"""
import datetime as dt

import pytest

from scraper_example import normalize_url, _is_projector_related, _normalize_date


# ---------------------------------------------------------------------------
# normalize_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    # scheme / host 轉小寫
    ("HTTPS://Example.COM/a", "https://example.com/a"),
    # 去掉 fragment
    ("https://example.com/a#section-2", "https://example.com/a"),
    # 移除追蹤參數、保留其他、其他參數排序
    ("https://example.com/a?utm_source=x&b=2&a=1", "https://example.com/a?a=1&b=2"),
    ("https://example.com/a?fbclid=abc", "https://example.com/a"),
    ("https://example.com/a?gclid=abc&id=7", "https://example.com/a?id=7"),
    # 路徑本身不動：尾斜線、大小寫都保留
    ("https://www.projectorreviews.com/Foo-Bar/", "https://www.projectorreviews.com/Foo-Bar/"),
    ("http://www.199it.com/archives/1.html", "http://www.199it.com/archives/1.html"),
    # 沒有 query 就原樣（host 小寫）
    ("https://projector.zol.com.cn/1219/12421835.html",
     "https://projector.zol.com.cn/1219/12421835.html"),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_normalize_url_empty(bad):
    # None / 空字串不應該爆掉
    assert normalize_url(bad) in (None, "", "   ".strip() or None) or normalize_url(bad) == bad


def test_normalize_url_idempotent():
    once = normalize_url("https://Example.com/x?utm_medium=a&z=1#f")
    assert normalize_url(once) == once


# ---------------------------------------------------------------------------
# _is_projector_related
# ---------------------------------------------------------------------------

def test_keyword_match_english_case_insensitive():
    assert _is_projector_related("New DLP Projector from BenQ")
    assert _is_projector_related("epson announces laser tv")  # 全小寫也要中


def test_keyword_match_chinese():
    assert _is_projector_related("極米發表新款投影機")
    assert _is_projector_related("當貝 Dangbei N3 Max 開箱")


def test_keyword_no_match():
    assert not _is_projector_related("Apple releases new MacBook Pro")
    assert not _is_projector_related("")


# ---------------------------------------------------------------------------
# _normalize_date
# ---------------------------------------------------------------------------

def test_normalize_date_naive():
    assert _normalize_date("2026-09-07") == "2026-09-07"


def test_normalize_date_tz_converted_to_taipei():
    # 美東時間深夜 -> 換算台灣時間會跨到隔天
    # 2026-09-06 23:00 -04:00  ==  2026-09-07 11:00 +08:00
    assert _normalize_date("2026-09-06T23:00:00-04:00") == "2026-09-07"


def test_normalize_date_garbage_falls_back_to_today():
    today = dt.date.today().strftime("%Y-%m-%d")
    assert _normalize_date("not a date") == today
    assert _normalize_date("") == today
