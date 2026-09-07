#!/bin/bash
set -uo pipefail
PROJECT_DIR="/opt/projector-insight"
cd "$PROJECT_DIR" || exit 1
source venv/bin/activate
mkdir -p logs
LOGFILE="logs/daily_$(date +%Y%m%d).log"
FAILED=0

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

    git pull origin main || echo "[git pull 非零，先繼續（push 前會再 pull 一次）]"

    # 用 timeout 包住爬蟲：即使某個來源「接受連線但不回應」，最多也只拖 15 分鐘就被
    # 中止（--kill-after 再多給 60 秒收尾），不會像 2026-08 那次卡死好幾天擋住整條流程。
    # exit code 124 = 逾時被中止。
    timeout --kill-after=60 900 python scraper_example.py
    src_rc=$?
    echo "[scraper exit code: $src_rc]"
    [ "$src_rc" -ne 0 ] && { echo "[!! 爬蟲失敗/逾時 rc=$src_rc]"; FAILED=1; }

    # 每季（1/4/7/10 月的 1 號）跑一次原文連結健檢，把失效的「查看原文」連結標記到
    # 資料庫，讓網站在使用者點到之前就先顯示提示。
    case "$(date +%m-%d)" in
        01-01|04-01|07-01|10-01)
            echo "[quarterly link check start $(date '+%H:%M:%S')]"
            python check_links.py || { echo "[!! check_links 失敗]"; FAILED=1; }
            echo "[link check done]"
            ;;
    esac

    python export_static_data.py
    exp_rc=$?
    echo "[export exit code: $exp_rc]"
    [ "$exp_rc" -ne 0 ] && { echo "[!! export_static_data 失敗 rc=$exp_rc]"; FAILED=1; }

    git add data projector_intel.db
    if git diff --cached --quiet; then
        echo "[今天沒有任何新變更，略過 commit / push]"
    else
        git commit -m "Daily update $(date +%Y-%m-%d)" || { echo "[!! git commit 失敗]"; FAILED=1; }
        push_with_retry || FAILED=1
    fi

    echo "[FAILED=$FAILED]"
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') daily update finished ====="
} >> "$LOGFILE" 2>&1

# 有任何關鍵步驟失敗就寄告警信（把 log 尾巴帶上），寄信本身失敗也不影響結束碼。
if [ "$FAILED" -ne 0 ]; then
    tail -c 4000 "$LOGFILE" | python notify.py "每日更新有步驟失敗 $(date +%F)" || true
fi

exit "$FAILED"
