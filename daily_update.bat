@echo off
cd /d "D:\Projector Insight"

echo ===== %date% %time% 開始每日更新 =====

python scraper_example.py
python export_static_data.py

git add data projector_intel.db
git commit -m "Daily update %date%"
git push origin main

echo ===== 更新完成 =====
