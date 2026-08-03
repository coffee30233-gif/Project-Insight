@echo off
cd /d "D:\Projector Insight"

if not exist "logs" mkdir "logs"
set LOGFILE=logs\weekly_%date:~0,4%%date:~5,2%%date:~8,2%.log

echo ===== %date% %time% 開始每週報告 ===== >> "%LOGFILE%" 2>&1

REM 先拉一次最新的訂閱名單（網站的訂閱表單會直接 commit 到 GitHub）
git pull origin main >> "%LOGFILE%" 2>&1

python generate_weekly_report.py >> "%LOGFILE%" 2>&1

REM 找出剛產生的週報檔名（用 Python 算，比較保險）
for /f %%f in ('python -c "from datetime import date, timedelta; d=date.today(); monday=d-timedelta(days=d.weekday()+7); y,w,_=monday.isocalendar(); print(f'{y}-W{w:02d}.md')"') do set REPORT_FILE=%%f

echo 本週報告檔名：%REPORT_FILE% >> "%LOGFILE%" 2>&1

if exist "reports\%REPORT_FILE%" (
    python generate_weekly_pdf.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1
    python generate_slides.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1
) else (
    echo 找不到 reports\%REPORT_FILE%，略過產生 PDF/簡報 >> "%LOGFILE%" 2>&1
)

python export_static_data.py >> "%LOGFILE%" 2>&1

git add data reports >> "%LOGFILE%" 2>&1
git commit -m "Weekly report %REPORT_FILE%" >> "%LOGFILE%" 2>&1
git push origin main >> "%LOGFILE%" 2>&1

echo 寄送週報 email... >> "%LOGFILE%" 2>&1
python send_weekly_email.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1

echo ===== %date% %time% 每週報告完成 ===== >> "%LOGFILE%" 2>&1
