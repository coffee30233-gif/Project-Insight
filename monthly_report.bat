@echo off
setlocal enabledelayedexpansion
cd /d "D:\Projector Insight"

if not exist "logs" mkdir "logs"
for /f %%d in ('python -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set STAMP=%%d
set LOGFILE=logs\monthly_%STAMP%.log
set FAILED=0

echo ===== %date% %time% 開始每月報告產生 ===== >> "%LOGFILE%" 2>&1

git pull origin main >> "%LOGFILE%" 2>&1

REM generate_monthly_report.py 不帶參數時，預設處理「上個月」
python generate_monthly_report.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! generate_monthly_report 失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)

REM 用 Python 算出「上個月」對應的檔名（YYYY-MM.md），避免批次檔自己解析日期
REM （%date% 的格式在不同 Windows 地區設定下不一樣，容易出錯，交給 Python 比較保險）
for /f %%f in ('python -c "from datetime import date; d=date.today(); y=d.year-(1 if d.month==1 else 0); m=12 if d.month==1 else d.month-1; print(f'{y}-{m:02d}.md')"') do set REPORT_FILE=%%f
echo 上個月報告檔名：%REPORT_FILE% >> "%LOGFILE%" 2>&1

if exist "reports\%REPORT_FILE%" (
    python generate_slides.py "reports\%REPORT_FILE%" >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo [!! generate_slides 失敗] >> "%LOGFILE%" 2>&1
        set FAILED=1
    )
) else (
    echo [!! 找不到 reports\%REPORT_FILE%，可能上個月沒有任何已處理的文章，略過產生簡報] >> "%LOGFILE%" 2>&1
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
    git commit -m "Monthly report %REPORT_FILE%" >> "%LOGFILE%" 2>&1
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

echo [FAILED=!FAILED!] >> "%LOGFILE%" 2>&1
echo ===== %date% %time% 每月報告產生完成 ===== >> "%LOGFILE%" 2>&1

if "!FAILED!"=="1" (
    python -c "d=open(r'%LOGFILE%',encoding='utf-8',errors='replace').read(); print(d[-4000:])" | python notify.py "月報流程有步驟失敗 %date%"
)

exit /b %FAILED%
