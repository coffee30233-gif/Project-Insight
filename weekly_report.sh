#!/bin/bash
set -uo pipefail
PROJECT_DIR="/opt/projector-insight"
cd "$PROJECT_DIR" || exit 1
source venv/bin/activate
mkdir -p logs
LOGFILE="logs/weekly_$(date +%Y%m%d).log"
FAILED=0
# GEMINI_API_KEY 從 .env 讀取（Python 端 load_dotenv()），不要寫死在腳本裡。

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
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') weekly report started ====="
    git pull origin main || echo "[git pull 非零，先繼續]"

    python generate_weekly_report.py
    gwr_rc=$?
    echo "[generate_weekly_report exit code: $gwr_rc]"
    [ "$gwr_rc" -ne 0 ] && { echo "[!! generate_weekly_report 失敗 rc=$gwr_rc]"; FAILED=1; }

    REPORT_FILE=$(python -c "
from datetime import date, timedelta
d = date.today()
monday = d - timedelta(days=d.weekday() + 7)
y, w, _ = monday.isocalendar()
print(f'{y}-W{w:02d}.md')
")
    echo "Report file: $REPORT_FILE"
    if [ -f "reports/$REPORT_FILE" ]; then
        python generate_weekly_pdf.py "reports/$REPORT_FILE" || { echo "[!! generate_weekly_pdf 失敗]"; FAILED=1; }
        python generate_slides.py "reports/$REPORT_FILE" || { echo "[!! generate_slides 失敗]"; FAILED=1; }
    else
        echo "[!! 找不到 reports/$REPORT_FILE，PDF/簡報略過]"
        FAILED=1
    fi

    python export_static_data.py
    exp_rc=$?
    echo "[export exit code: $exp_rc]"
    [ "$exp_rc" -ne 0 ] && { echo "[!! export_static_data 失敗 rc=$exp_rc]"; FAILED=1; }

    git add data reports
    if git diff --cached --quiet; then
        echo "[沒有新變更，略過 commit / push]"
    else
        git commit -m "Weekly report $REPORT_FILE" || { echo "[!! git commit 失敗]"; FAILED=1; }
        push_with_retry || FAILED=1
    fi

    echo "Sending weekly email..."
    python send_weekly_email.py "reports/$REPORT_FILE"
    mail_rc=$?
    echo "[send_weekly_email exit code: $mail_rc]"
    [ "$mail_rc" -ne 0 ] && { echo "[!! 週報寄信失敗 rc=$mail_rc]"; FAILED=1; }

    echo "[FAILED=$FAILED]"
    echo "===== $(date '+%Y-%m-%d %H:%M:%S') weekly report finished ====="
} >> "$LOGFILE" 2>&1

if [ "$FAILED" -ne 0 ]; then
    tail -c 4000 "$LOGFILE" | python notify.py "週報流程有步驟失敗 $(date +%F)" || true
fi

exit "$FAILED"
