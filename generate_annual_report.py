"""
generate_annual_report.py
產生年度投影機市場總結報告。設計上直接讀取 reports/{year}-{month:02d}.md
（也就是 generate_monthly_report.py 逐月產出的檔案）作為輸入，而不是重新
處理全年的原始文章：
  - 更省成本：不用把整年上千篇文章的原始資料再丟一次給 Gemini
  - 品質更好：月報本身已經是「跨篇比對」過的產物，年報只需要在此基礎上
    再做一次「跨月比對」，資訊層次更清楚

用法：
  python generate_annual_report.py        # 預設抓「去年」
  python generate_annual_report.py 2025   # 指定年份

執行前提：該年度 1-12 月的月報最好都已經用 generate_monthly_report.py
產生過。缺少的月份仍會產出報告，但會在對應段落註明「該月資料缺失」。
"""

import sys
import os
from datetime import date

import gemini_client

REPORTS_DIR = "reports"


def _last_year() -> int:
    return date.today().year - 1


def _load_monthly_reports(year: int) -> list[dict]:
    """依序讀取 1-12 月的月報檔案，缺檔的月份 content 設為 None。"""
    monthly_reports = []
    missing_months = []

    for month in range(1, 13):
        path = os.path.join(REPORTS_DIR, f"{year}-{month:02d}.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            monthly_reports.append({"month": month, "content": content})
        else:
            monthly_reports.append({"month": month, "content": None})
            missing_months.append(month)

    if missing_months:
        print(f"提醒：{year} 年缺少以下月份的月報："
              f"{', '.join(str(m) + '月' for m in missing_months)}")
        print("      年報仍會產出，但缺失月份會在報告中標註「該月資料缺失」。")
        print("      若要補齊，請先對該月執行：python generate_monthly_report.py "
              f"{year} <月份>")

    return monthly_reports


def main():
    if len(sys.argv) == 2:
        year = int(sys.argv[1])
    else:
        year = _last_year()

    monthly_reports = _load_monthly_reports(year)
    available = [m for m in monthly_reports if m["content"]]

    if not available:
        print(f"{year} 年完全沒有月報資料，請先跑過至少幾個月的 "
              f"generate_monthly_report.py 再產生年報。")
        return

    print(f"讀到 {len(available)}/12 個月的月報，開始呼叫 Gemini 彙整年度報告...")
    report_md = gemini_client.generate_annual_report(year, monthly_reports)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    out_path = os.path.join(REPORTS_DIR, f"{year}-annual.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"年度報告已產出：{out_path}")


if __name__ == "__main__":
    main()
