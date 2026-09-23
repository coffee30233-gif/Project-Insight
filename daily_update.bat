@echo off
setlocal enabledelayedexpansion
cd /d "D:\Projector Insight"

if not exist "logs" mkdir "logs"
for /f %%d in ('python -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set STAMP=%%d
set LOGFILE=logs\daily_%STAMP%.log
set FAILED=0

REM 同一時間只允許一個每日更新在跑（用資料夾當鎖，mkdir 是原子操作）。
REM Windows 工作排程器本身也有「如果工作已在執行中就不要再啟動」的設定，
REM 這裡多一層是為了防手動雙擊時撞到排程正在跑的那次。
set LOCKDIR=%TEMP%\projector-insight-daily.lock
mkdir "%LOCKDIR%" 2>nul
if errorlevel 1 (
    echo %date% %time% 另一個每日更新正在執行，本次略過 >> "%LOGFILE%" 2>&1
    exit /b 0
)

echo ===== %date% %time% 開始每日更新 ===== >> "%LOGFILE%" 2>&1

git pull origin main >> "%LOGFILE%" 2>&1
echo [git pull exit code: %errorlevel%] >> "%LOGFILE%" 2>&1

REM 注意：沒有像 Linux 版用 timeout 包住爬蟲逾時保底（Windows 原生批次檔做
REM 不到乾淨的「N 分鐘後強制中止」）。scraper_example.py 內建的
REM socket.setdefaulttimeout(30) 仍會擋掉多數「接了不回應」的情況，
REM 但如果真的整支卡死不動，還是需要手動到工作管理員結束 python.exe。
python scraper_example.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! 爬蟲失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)
echo [scraper exit code: %errorlevel%] >> "%LOGFILE%" 2>&1

REM 每季（1/4/7/10 月 1 號）跑一次原文連結健檢。Windows 的 %date% 格式因地區
REM 設定而異，交給 Python 判斷比較保險（跟 monthly_report.bat 算日期的做法一致）。
for /f %%q in ('python -c "from datetime import date; d=date.today(); print(1 if (d.day==1 and d.month in (1,4,7,10)) else 0)"') do set IS_QUARTER_START=%%q
if "%IS_QUARTER_START%"=="1" (
    echo [quarterly link check start %time%] >> "%LOGFILE%" 2>&1
    python check_links.py >> "%LOGFILE%" 2>&1
    if errorlevel 1 (
        echo [!! check_links 失敗] >> "%LOGFILE%" 2>&1
        set FAILED=1
    )
)

python export_static_data.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! export_static_data 失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)
echo [export exit code: %errorlevel%] >> "%LOGFILE%" 2>&1

REM 注意：只 add data，不 add projector_intel.db —— DB 已經不進 git了，
REM AI 問答改讀 data/rag.jsonl（跟 Linux 版一致，見 MIGRATION.md）。
git add data >> "%LOGFILE%" 2>&1
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Daily update %date%" >> "%LOGFILE%" 2>&1
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
    echo [今天沒有任何新變更，略過 commit / push] >> "%LOGFILE%" 2>&1
)

echo [FAILED=!FAILED!] >> "%LOGFILE%" 2>&1
echo ===== %date% %time% 每日更新完成 ===== >> "%LOGFILE%" 2>&1

rmdir "%LOCKDIR%" 2>nul

REM 失敗告警信改由 n8n 處理（見下方 notify_n8n.py 呼叫），這台電腦連不進
REM 公司信箱（smtp.minaik.com 535 認證錯誤），本機不再寄信。
if "!FAILED!"=="1" (
    set N8N_STATUS=failed
) else (
    set N8N_STATUS=success
)

REM 不管成功失敗都通知一次 n8n（沒設 N8N_WEBHOOK_DAILY 就靜靜略過，見 notify_n8n.py）
python -c "d=open(r'%LOGFILE%',encoding='utf-8',errors='replace').read(); print(d[-4000:])" | python notify_n8n.py daily !N8N_STATUS!

exit /b %FAILED%
