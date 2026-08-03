"""
generate_monthly_report.py
每月排程執行（建議用 cron 排在每月 1 號凌晨）：
  1. 從資料庫撈出上個月所有已處理文章
  2. 呼叫 Gemini 彙整成月報 Markdown
  3. 存檔到 reports/{year}-{month:02d}.md

用法：
  python generate_monthly_report.py            # 預設抓「上個月」
  python generate_monthly_report.py 2026 6      # 指定年月
"""

import sys
import os
from datetime import date

import db
import gemini_client


def _last_month() -> tuple[int, int]:
    today = date.today()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def main():
    if len(sys.argv) == 3:
        year, month = int(sys.argv[1]), int(sys.argv[2])
    else:
        year, month = _last_month()

    db.init_db()
    articles = db.get_articles_by_month(year, month)

    if not articles:
        print(f"{year}-{month:02d} 沒有已處理的文章，先確認爬蟲/ingest 是否有正常執行。")
        return

    print(f"共 {len(articles)} 篇文章，開始呼叫 Gemini 彙整月報...")
    report_md = gemini_client.generate_monthly_report(year, month, articles)

    os.makedirs("reports", exist_ok=True)
    out_path = os.path.join("reports", f"{year}-{month:02d}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"月報已產出：{out_path}")


if __name__ == "__main__":
    main()
