"""
generate_semiannual_report.py
產生半年度投影機市場總結報告，讀取 reports/{year}-{month:02d}.md（6 個月份）
彙整而成，做法跟 generate_annual_report.py 一樣是讀月報而不是重新處理原始文章。

用法：
    python generate_semiannual_report.py 2026 1   # 2026 年上半年（1-6月）
    python generate_semiannual_report.py 2026 2   # 2026 年下半年（7-12月）

執行前提：該半年 6 個月的月報最好都已經用 generate_monthly_report.py 產生過。
缺少的月份仍會產出報告，但會在對應段落註明「該月資料缺失」。

產出檔案：reports/{year}-h1.md 或 reports/{year}-h2.md
"""
import sys
import os

import gemini_client

REPORTS_DIR = "reports"


def _load_monthly_reports(year: int, months: range) -> list[dict]:
    """依序讀取指定月份範圍的月報檔案，缺檔的月份 content 設為 None。"""
    monthly_reports = []
    missing_months = []

    for month in months:
        path = os.path.join(REPORTS_DIR, f"{year}-{month:02d}.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            monthly_reports.append({"month": month, "content": content})
        else:
            monthly_reports.append({"month": month, "content": None})
            missing_months.append(month)

    if missing_months:
        print(f"提醒：缺少以下月份的月報：{', '.join(str(m) + '月' for m in missing_months)}")
        print("      半年報仍會產出，但缺失月份會在報告中標註「該月資料缺失」。")
        print("      若要補齊，請先對該月執行：python generate_monthly_report.py "
              f"{year} <月份>")

    return monthly_reports


def main():
    if len(sys.argv) != 3:
        print("用法：python generate_semiannual_report.py <年份> <1或2>")
        print("      1 = 上半年（1-6月）　2 = 下半年（7-12月）")
        sys.exit(1)

    year = int(sys.argv[1])
    half = int(sys.argv[2])
    if half not in (1, 2):
        print("第二個參數只能是 1（上半年）或 2（下半年）")
        sys.exit(1)

    months = range(1, 7) if half == 1 else range(7, 13)
    monthly_reports = _load_monthly_reports(year, months)
    available = [m for m in monthly_reports if m["content"]]

    if not available:
        half_label = "上半年" if half == 1 else "下半年"
        print(f"{year} 年{half_label}完全沒有月報資料，請先跑過至少幾個月的 "
              f"generate_monthly_report.py 再產生半年報。")
        return

    print(f"讀到 {len(available)}/6 個月的月報，開始呼叫 Gemini 彙整半年報...")
    report_md = gemini_client.generate_semiannual_report(year, half, monthly_reports)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    suffix = "h1" if half == 1 else "h2"
    out_path = os.path.join(REPORTS_DIR, f"{year}-{suffix}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    print(f"半年報已產出：{out_path}")


if __name__ == "__main__":
    main()
