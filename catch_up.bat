@echo off
setlocal enabledelayedexpansion
REM 每日更新的「安全網」（daily_update.sh / catch_up.sh 的 Windows 對應版）。
REM 用工作排程器另外排一個比主排程晚一小時的觸發，跑這支：
REM   今天已經成功跑過 daily_update.bat 就什麼都不做，
REM   沒有（或根本沒觸發到）就補跑一次。
cd /d "D:\Projector Insight"

for /f %%d in ('python -c "from datetime import date; print(date.today().strftime('%%Y%%m%%d'))"') do set STAMP=%%d
set LOGFILE=logs\daily_%STAMP%.log

if exist "%LOGFILE%" (
    findstr /c:"每日更新完成" "%LOGFILE%" >nul
    if not errorlevel 1 (
        findstr /c:"[FAILED=1]" "%LOGFILE%" >nul
        if errorlevel 1 (
            echo %date% %time% [catch_up] 今天已成功跑過，不補跑
            exit /b 0
        )
    )
)

echo %date% %time% [catch_up] 今天沒有成功的每日更新，補跑 daily_update.bat
call "daily_update.bat"
