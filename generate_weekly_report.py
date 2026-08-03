"""
generate_weekly_report.py
產生過去 7 天（週一到週日）的投影機產業週報，讀取資料庫裡這段期間內、
已完成 Gemini 處理的文章彙整而成。

用法：
    python generate_weekly_report.py              # 預設抓「上一個完整的週一到週日」
    python generate_weekly_report.py 2026-07-20    # 抓指定週一所在那一週（週一到週日）

產出檔案：reports/{年}-W{週數}.md（例如 reports/2026-W30.md）
"""
import sys
from datetime import date, timedelta

import db
import gemini_client

REPORTS_DIR = "reports"


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main():
    if len(sys.argv) == 2:
        anchor = date.fromisoformat(sys.argv[1])
    else:
        # 預設抓「上一個完整的週一到週日」：今天所在週的週一，往前推 7 天
        anchor = _monday_of(date.today()) - timedelta(days=7)

    start = _monday_of(anchor)
    end = start + timedelta(days=6)
    year, week, _ = start.isocalendar()

    print(f"週報範圍：{start.isoformat()} ～ {end.isoformat()}（{year} 年第 {week} 週）")

    articles = db.get_articles_by_date_range(start.isoformat(), end.isoformat())
    print(f"讀到 {len(articles)} 篇文章")

    if not articles:
        print("這一週完全沒有文章資料，週報會產出但內容會標註「本週無資料」。")

    report_md = gemini_client.generate_weekly_report(start.isoformat(), end.isoformat(), articles)

    import os
    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"{year}-W{week:02d}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"週報已產出：{out_path}")
    return out_path


if __name__ == "__main__":
    main()
