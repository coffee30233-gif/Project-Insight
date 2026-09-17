@echo off
setlocal enabledelayedexpansion
cd /d "D:\Projector Insight"

if not exist "logs" mkdir "logs"
for /f %%d in ('python -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set STAMP=%%d
set LOGFILE=logs\weekly_%STAMP%.log
set FAILED=0

echo ===== %date% %time% 開始每週報告 ===== >> "%LOGFILE%" 2>&1

REM 先拉一次最新的訂閱名單（網站的訂閱表單會直接 commit 到 GitHub）
git pull origin main >> "%LOGFILE%" 2>&1

python generate_weekly_report.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! generate_weekly_report 失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)

REM 找出剛產生的週報檔名（用 Python 算，比較保險）
for /f %%f in ('python -c "from datetime import date, timedelta; d=date.today(); monday=d-timedelta(days=d.weekday()+7); y,w,_=monday.isocalendar(); print(f'{y}-W{w:02d}.md')"') do set REPORT_FILE=%%f
echo 本週報告檔名：%REPORT_FILE% >> "%LOGFILE%" 2>&1

if exist "reports\%REPORT_FILE%" (
    python generate_weekly_pdf.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo [!! generate_weekly_pdf 失敗] >> "%LOGFILE%" 2>&1
        set FAILED=1
    )
    python generate_slides.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo [!! generate_slides 失敗] >> "%LOGFILE%" 2>&1
        set FAILED=1
    )
) else (
    echo [!! 找不到 reports\%REPORT_FILE%，PDF/簡報略過] >> "%LOGFILE%" 2>&1
    set FAILED=1
)

python export_static_data.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! export_static_data 失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)

git add data reports >> "%LOGFILE%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Weekly report %REPORT_FILE%" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo [!! git commit 失敗] >> "%LOGFILE%" 2>&1
        set FAILED=1
    )

    set PUSH_OK=0
    for /l %%i in (1,1,3) do (
        if "!PUSH_OK!"=="0" (
            git push origin main >> "%LOGFILE%" 2>&1
            if not errorlevel 1 (
                set PUSH_OK=1
                echo [git push succeeded on attempt %%i] >> "%LOGFILE%" 2>&1
            ) else (
                echo [git push failed on attempt %%i, pulling and retrying] >> "%LOGFILE%" 2>&1
                git pull origin main --no-edit >> "%LOGFILE%" 2>&1
            )
        )
    )
    if "!PUSH_OK!"=="0" (
        echo [!! git push 三次都失敗] >> "%LOGFILE%" 2>&1
        set FAILED=1
    )
) else (
    echo [沒有新變更，略過 commit / push] >> "%LOGFILE%" 2>&1
)

echo 寄送週報 email... >> "%LOGFILE%" 2>&1
python send_weekly_email.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! 週報寄信失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)

echo [FAILED=!FAILED!] >> "%LOGFILE%" 2>&1
echo ===== %date% %time% 每週報告完成 ===== >> "%LOGFILE%" 2>&1

if "!FAILED!"=="1" (
    python -c "d=open(r'%LOGFILE%',encoding='utf-8',errors='replace').read(); print(d[-4000:])" | python notify.py "週報流程有步驟失敗 %date%"
)

exit /b %FAILED%
