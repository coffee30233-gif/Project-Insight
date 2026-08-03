"""
check_data_coverage.py
在跑 generate_annual_report.py 之前，先看一眼資料庫裡「現有」的文章實際
覆蓋了哪些月份、各多少篇，方便判斷值不值得直接拿現有資料去彙整年報，
還是應該先跑 backfill_last_year.py 補一些關鍵月份。

用法：
  python check_data_coverage.py          # 預設看「去年」
  python check_data_coverage.py 2025     # 指定年份
  python check_data_coverage.py 2025 2026  # 看多個年份
"""

import sys
from datetime import date

import db


def check_year(year: int):
    print(f"\n=== {year} 年資料覆蓋狀況 ===")
    total = 0
    covered_months = 0

    for month in range(1, 13):
        articles = db.get_articles_by_month(year, month)
        count = len(articles)
        total += count

        if count > 0:
            covered_months += 1
            by_source = {}
            for a in articles:
                by_source[a["source_name"]] = by_source.get(a["source_name"], 0) + 1
            source_breakdown = "、".join(f"{k}×{v}" for k, v in sorted(by_source.items()))
            print(f"  {month:2d} 月：{count:3d} 篇  ({source_breakdown})")
        else:
            print(f"  {month:2d} 月：  0 篇  ⚠️ 無資料")

    print(f"\n  小計：{covered_months}/12 個月有資料，共 {total} 篇文章")

    if covered_months == 12:
        print("  → 資料完整，可直接執行 generate_annual_report.py")
    elif covered_months >= 6:
        print("  → 資料涵蓋過半，年報會有部分月份標註「資料缺失」，")
        print("    如果想補齊，可考慮針對缺失月份執行 backfill_last_year.py")
    elif covered_months > 0:
        print("  → 資料覆蓋較零星，年報仍會產出，但多數月份會是「資料缺失」，")
        print("    整體參考價值有限，建議先跑 backfill_last_year.py 補資料，")
        print("    或至少確保未來爬蟲穩定執行以免持續缺口。")
    else:
        print("  → 完全沒有資料，無法產生年報。")


def main():
    db.init_db()

    if len(sys.argv) > 1:
        years = [int(y) for y in sys.argv[1:]]
    else:
        years = [date.today().year - 1]

    for year in years:
        check_year(year)


if __name__ == "__main__":
    main()
