@echo off
setlocal enabledelayedexpansion
cd /d "D:\Projector Insight"

if not exist "logs" mkdir "logs"
for /f %%d in ('python -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set STAMP=%%d
set LOGFILE=logs\dbbackup_%STAMP%.log
set FAILED=0

echo ===== %date% %time% 開始資料庫備份 ===== >> "%LOGFILE%" 2>&1

python backup_db.py >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo [!! backup_db 失敗 rc=%errorlevel%] >> "%LOGFILE%" 2>&1
    set FAILED=1
)

echo [FAILED=!FAILED!] >> "%LOGFILE%" 2>&1
echo ===== %date% %time% 資料庫備份完成 ===== >> "%LOGFILE%" 2>&1

if "!FAILED!"=="1" (
    set N8N_STATUS=failed
) else (
    set N8N_STATUS=success
)

REM 不管成功失敗都通知一次 n8n（沒設 N8N_WEBHOOK_DBBACKUP 就靜靜略過，見 notify_n8n.py）
python -c "d=open(r'%LOGFILE%',encoding='utf-8',errors='replace').read(); print(d[-4000:])" | python notify_n8n.py dbbackup !N8N_STATUS!

exit /b %FAILED%
