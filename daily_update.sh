#!/bin/bash
set -uo pipefail
PROJECT_DIR="/opt/projector-insight"
cd "$PROJECT_DIR"
source venv/bin/activate
mkdir -p logs
LOGFILE="logs/daily_$(date +%Y%m%d).log"

push_with_retry() {
    local max_attempts=3
    local attempt=1
    while [ "$attempt" -le "$max_attempts" ]; do
        if git push origin main; then
            echo "[git push succeeded on attempt $attempt]"
            return 0
        fi
        echo "[git push failed on attempt $attempt, pulling latest and retrying]"
        git pull origin main --no-edit
        attempt=$((attempt + 1))
    done
    echo "[git push failed after $max_attempts attempts, giving up]"
    return 1
}

{
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily update started ====="
    git pull origin main
    echo "[git pull exit code: $?]"
    python scraper_example.py
    echo "[scraper exit code: $?]"

    # 每季（1/4/7/10 月的 1 號）跑一次原文連結健檢，把失效的「查看原文」連結標記到
    # 資料庫，讓網站在使用者點到之前就先顯示提示。整輪約需 (文章數 x 1 秒)，
    # 目前規模十幾分鐘內跑得完。
    case "$(date +%m-%d)" in
        01-01|04-01|07-01|10-01)
            echo "[quarterly link check start $(date '+%H:%M:%S')]"
            python check_links.py
            echo "[link check exit code: $?]"
            ;;
    esac

    python export_static_data.py
    echo "[export exit code: $?]"
    git add data projector_intel.db
    git commit -m "Daily update $(date +%Y-%m-%d)"
    push_with_retry
    echo "[git push exit code: $?]"
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily update finished ====="
} >> "$LOGFILE" 2>&1
