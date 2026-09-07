"""gemini_client 的免費額度節流 / backoff 輔助函式。"""
import time

import gemini_client as g


def test_retry_delay_parsed_from_error():
    assert g._retry_delay_from_error('blah "retryDelay": "37s" blah', default=99) == 38  # +1 緩衝
    assert g._retry_delay_from_error("retry_delay: 5s", default=99) == 6
    assert g._retry_delay_from_error("完全沒有這個欄位", default=30) == 30
    # 上限 120 秒
    assert g._retry_delay_from_error('retryDelay: "999s"', default=30) == 120


def test_pace_enforces_min_interval(monkeypatch):
    monkeypatch.setattr(g, "MIN_CALL_INTERVAL", 0.2)
    monkeypatch.setattr(g, "_last_call_ts", 0.0)
    t0 = time.monotonic()
    g.pace()   # 第一次幾乎不等（距離上次很久）
    g.pace()   # 第二次要等 ~0.2s
    assert time.monotonic() - t0 >= 0.18


def test_pace_disabled_when_interval_zero(monkeypatch):
    monkeypatch.setattr(g, "MIN_CALL_INTERVAL", 0)
    t0 = time.monotonic()
    g.pace(); g.pace(); g.pace()
    assert time.monotonic() - t0 < 0.05


def test_raw_content_truncation_constant():
    assert g.MAX_RAW_CONTENT_CHARS == 4000
