@echo off
cd /d "D:\Projector Insight"

echo ===== 開始每月報告產生 =====

REM generate_monthly_report.py 不帶參數時，預設處理「上個月」
python generate_monthly_report.py

REM 用 Python 算出「上個月」對應的檔名（YYYY-MM.md），避免批次檔自己解析日期
REM （%date% 的格式在不同 Windows 地區設定下不一樣，容易出錯，交給 Python 比較保險）
for /f %%f in ('python -c "from datetime import date; d=date.today(); y=d.year-(1 if d.month==1 else 0); m=12 if d.month==1 else d.month-1; print(f'{y}-{m:02d}.md')"') do set REPORT_FILE=%%f

echo 上個月報告檔名：%REPORT_FILE%

if exist "reports\%REPORT_FILE%" (
    python generate_slides.py "reports\%REPORT_FILE%"
) else (
    echo 找不到 reports\%REPORT_FILE%，可能上個月沒有任何已處理的文章，略過產生簡報
)

python export_static_data.py

git add data reports
git commit -m "Monthly report update"
git push origin main

echo ===== 本月報告產生完成 =====
