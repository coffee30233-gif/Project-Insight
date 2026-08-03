@echo off
cd /d "D:\Projector Insight"

if not exist "logs" mkdir "logs"
set LOGFILE=logs\daily_%date:~0,4%%date:~5,2%%date:~8,2%.log

echo ===== %date% %time% 開始每日更新 ===== >> "%LOGFILE%" 2>&1

python scraper_example.py >> "%LOGFILE%" 2>&1
echo [scraper exit code: %errorlevel%] >> "%LOGFILE%" 2>&1

python export_static_data.py >> "%LOGFILE%" 2>&1
echo [export exit code: %errorlevel%] >> "%LOGFILE%" 2>&1

git add data projector_intel.db >> "%LOGFILE%" 2>&1
git commit -m "Daily update %date%" >> "%LOGFILE%" 2>&1
git push origin main >> "%LOGFILE%" 2>&1
echo [git push exit code: %errorlevel%] >> "%LOGFILE%" 2>&1

echo ===== %date% %time% 更新完成 ===== >> "%LOGFILE%" 2>&1
