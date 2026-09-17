@echo off
setlocal enabledelayedexpansion
REM 每日更新的「安全網」（daily_update.sh / catch_up.sh 的 Windows 對應版）。
REM 用工作排程器另外排一個比主排程晚一小時的觸發，跑這支：
REM   今天已經成功跑過 daily_update.bat 就什麼都不做，
REM   沒有（或根本沒觸發到）就補跑一次。
cd /d "D:\Projector Insight"

for /f %%d in ('python -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set STAMP=%%d
set LOGFILE=logs\daily_%STAMP%.log

REM 用 [FAILED=0] 這個純 ASCII 標記判斷「今天成功了沒」——findstr 對 UTF-8
REM 中文字串（例如原本用的「每日更新完成」）常常比對不到，會誤判成「沒成功」
REM 導致每天都白白補跑一次。
if exist "%LOGFILE%" (
    findstr /c:"[FAILED=0]" "%LOGFILE%" >nul
    if not errorlevel 1 (
        echo %date% %time% [catch_up] 今天已成功跑過，不補跑
        echo 今天已成功跑過每日更新，不需要補跑 | python notify_n8n.py catchup skipped
        exit /b 0
    )
)

echo %date% %time% [catch_up] 今天沒有成功的每日更新，補跑 daily_update.bat
call "daily_update.bat"
set DAILY_RC=%errorlevel%
if "%DAILY_RC%"=="0" (
    echo 補跑 daily_update.bat 成功 | python notify_n8n.py catchup success
) else (
    echo 補跑 daily_update.bat 失敗 rc=%DAILY_RC% | python notify_n8n.py catchup failed
)
exit /b %DAILY_RC%
