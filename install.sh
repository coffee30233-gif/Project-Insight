#!/usr/bin/env bash
#
# install.sh — 一鍵安裝 projector_intel 的 systemd timer 排程
#
# 用法：
#   cd projector_intel
#   sudo bash deploy/install.sh
#
# 這個腳本會：
#   1. 自動抓取專案實際路徑，取代 .service 檔案裡的 __PROJECT_DIR__ 佔位符
#   2. 用「執行這個腳本的原始使用者」（sudo 前的 $SUDO_USER）取代
#      __RUN_USER__，避免排程用 root 身份執行
#   3. 複製 .service / .timer 到 /etc/systemd/system/
#   4. 如果 /etc/projector-intel.env 還不存在，複製範例檔案過去
#      （複製後你還是要自己編輯填入實際的 API key）
#   5. systemctl daemon-reload，並啟用三個 timer

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "請用 sudo 執行：sudo bash deploy/install.sh"
    exit 1
fi

RUN_USER="${SUDO_USER:-$USER}"
if [[ "$RUN_USER" == "root" ]]; then
    echo "⚠️  偵測到執行使用者是 root。建議改用一般使用者帳號執行 sudo，"
    echo "    避免爬蟲/API 呼叫以 root 權限跑（風險較高）。"
    read -p "仍要繼續、以 root 身份設定排程嗎？[y/N] " confirm
    [[ "$confirm" == "y" || "$confirm" == "Y" ]] || exit 1
fi

# 專案目錄 = 這個腳本所在目錄的上一層（deploy/ 的上一層）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "專案路徑：$PROJECT_DIR"
echo "執行使用者：$RUN_USER"
echo

# 1. 複製並替換 .service 檔案裡的佔位符
for svc in projector-intel-daily projector-intel-monthly projector-intel-annual; do
    sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__RUN_USER__|$RUN_USER|g" \
        "$SCRIPT_DIR/${svc}.service" > "/etc/systemd/system/${svc}.service"
    cp "$SCRIPT_DIR/${svc}.timer" "/etc/systemd/system/${svc}.timer"
    echo "已安裝：${svc}.service / ${svc}.timer"
done

# 2. 環境變數檔案（API key 等敏感資訊），已存在就不覆蓋
if [[ ! -f /etc/projector-intel.env ]]; then
    cp "$SCRIPT_DIR/projector-intel.env.example" /etc/projector-intel.env
    chmod 600 /etc/projector-intel.env
    chown "$RUN_USER" /etc/projector-intel.env
    echo
    echo "⚠️  已建立 /etc/projector-intel.env，但裡面還是範例值。"
    echo "    請執行以下指令編輯，填入實際的 GEMINI_API_KEY（SLACK_WEBHOOK_URL 可選）："
    echo "      sudo nano /etc/projector-intel.env"
else
    echo "偵測到 /etc/projector-intel.env 已存在，不覆蓋既有設定。"
fi

# 3. 建立 logs 目錄並確保執行使用者可寫入
mkdir -p "$PROJECT_DIR/logs"
chown "$RUN_USER" "$PROJECT_DIR/logs"

# 4. 重新載入並啟用 timer
systemctl daemon-reload
for svc in projector-intel-daily projector-intel-monthly projector-intel-annual; do
    systemctl enable --now "${svc}.timer"
done

echo
echo "===== 安裝完成 ====="
echo "確認排程狀態：systemctl list-timers | grep projector-intel"
echo "查看每日爬蟲的即時 log：journalctl -u projector-intel-daily.service -f"
echo
echo "別忘了先確認 /etc/projector-intel.env 裡的 GEMINI_API_KEY 是實際值，"
echo "不然排程執行時會直接失敗。"
