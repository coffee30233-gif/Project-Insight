#!/bin/bash
# 每日更新的「安全網」。
#
# 背景：n8n 的節點層級 Retry 間隔上限只有 5 秒（輸入大數字會被縮回 5000），
# 擋不住早上那種 SSH ECONNREFUSED 瞬斷持續數十分鐘的情況。作法改成：
#   主排程   n8n 每天 08:30（台北）跑 daily_update.sh
#   安全網   n8n 每天 09:30（台北）跑這支 —— 今天已成功就什麼都不做，
#            沒成功（或根本沒跑到）就補跑一次 daily_update.sh。
#
# n8n 只要一個 Schedule Trigger + 一個 SSH 節點執行：
#   bash /opt/projector-insight/catch_up.sh
set -uo pipefail
PROJECT_DIR="/opt/projector-insight"
cd "$PROJECT_DIR" || exit 1
LOGFILE="logs/daily_$(date +%Y%m%d).log"

# 和 daily_update.sh 搶同一把鎖：如果主排程還在跑，就不要插隊。
exec 9>/tmp/projector-insight-daily.lock
if ! flock -n 9; then
    echo "$(date '+%F %T') [catch_up] 每日更新正在執行中，不動作"
    exit 0
fi
flock -u 9  # 放掉鎖，讓底下 exec 的 daily_update.sh 自己去搶

# 今天的 log 有 "daily update finished" 且沒有 "[FAILED=1]" -> 視為已成功
if [ -f "$LOGFILE" ] \
   && grep -q "daily update finished" "$LOGFILE" \
   && ! grep -q "\[FAILED=1\]" "$LOGFILE"; then
    echo "$(date '+%F %T') [catch_up] 今天已成功跑過，不補跑"
    exit 0
fi

echo "$(date '+%F %T') [catch_up] 今天沒有成功的每日更新，補跑 daily_update.sh"
exec bash daily_update.sh
