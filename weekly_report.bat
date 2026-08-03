@echo off
cd /d "D:\Projector Insight"

echo ===== %date% %time% 開始每週報告 =====

REM 先拉一次最新的訂閱名單（網站的訂閱表單會直接 commit 到 GitHub）
git pull origin main

python generate_weekly_report.py

REM 找出剛產生的週報檔名（用 Python 算，比較保險）
for /f %%f in ('python -c "from datetime import date, timedelta; d=date.today(); monday=d-timedelta(days=d.weekday()+7); y,w,_=monday.isocalendar(); print(f'{y}-W{w:02d}.md')"') do set REPORT_FILE=%%f

echo 本週報告檔名：%REPORT_FILE%

if exist "reports\%REPORT_FILE%" (
    python generate_slides.py "reports\%REPORT_FILE%"
) else (
    echo 找不到 reports\%REPORT_FILE%，略過產生簡報
)

python export_static_data.py

git add data reports
git commit -m "Weekly report %REPORT_FILE%"
git push origin main

echo 寄送週報 email...
python send_weekly_email.py "reports\%REPORT_FILE%"

echo ===== 每週報告完成 =====
