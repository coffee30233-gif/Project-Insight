"""
notify_n8n.py
每次排程跑完（不管成功失敗）都通知一次公司 n8n 的 Webhook，讓整條流程可以在 n8n
裡看到執行紀錄、串接後續通知。每個 workflow（daily/catch_up/weekly/monthly）用
自己的 Webhook 網址，設定在 .env 的 N8N_WEBHOOK_<WORKFLOW> 裡，沒設定就略過
（不影響原本的爬蟲/報告流程）。

公司 n8n 伺服器對外網路整個被防火牆擋住（連 raw.githubusercontent.com 都連不到，
不是只有 GitHub），所以沒辦法讓 n8n 自己回頭去 GitHub 抓訂閱名單和週報 PDF。
改成反過來：週報跑成功時，這支程式直接把 data/subscribers.json 的訂閱名單
和對應的 PDF 檔案一起用檔案上傳（multipart/form-data）的方式送給 n8n 的 Webhook，
n8n 收到後就有全部需要的資料，不用再對外連線。

用法：
    # 從程式呼叫
    import notify_n8n; notify_n8n.send_webhook("daily", "success", "……log 尾巴……")

    # 從 shell：把 log 尾巴用 stdin 餵進來
    tail -c 4000 logs/daily_20260918.log | python notify_n8n.py daily success

    # 週報成功時多帶報告檔名，會自動一併上傳訂閱名單 + PDF
    tail -c 4000 logs/weekly_20260918.log | python notify_n8n.py weekly success 2026-W38.md
"""
import json
import os
import re
import sys
import socket
from datetime import date, datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

SUBSCRIBERS_PATH = os.path.join("data", "subscribers.json")


def _load_subscriber_emails() -> list[str]:
    # 測試用：設了 N8N_TEST_SUBSCRIBERS 就用這組（逗號分隔），不去動真正的
    # data/subscribers.json，避免測試時寄信給真實訂閱戶。
    override = os.environ.get("N8N_TEST_SUBSCRIBERS")
    if override:
        return [e.strip() for e in override.split(",") if e.strip()]

    if not os.path.exists(SUBSCRIBERS_PATH):
        return []
    with open(SUBSCRIBERS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [s["email"] for s in data]


def _extract_summary(report_md: str) -> str:
    """抓「本週重點」段落的文字，當作週報信件本文的摘要（跟 send_weekly_email.py 同邏輯）。"""
    lines = report_md.splitlines()
    in_summary = False
    collected = []
    for line in lines:
        if line.strip().startswith("## "):
            if in_summary:
                break
            if "本週重點" in line or "半年摘要" in line or "年度摘要" in line:
                in_summary = True
            continue
        if in_summary and line.strip():
            collected.append(line.strip())
    return " ".join(collected) if collected else "本週投影機產業動態，詳見附件 PDF。"


def _week_range_label(report_file: str) -> str:
    """把 "2026-W38.md" 這種檔名換算成 "2026-09-14 ～ 2026-09-20" 這種日期區間文字。"""
    m = re.match(r"(\d{4})-W(\d{2})", report_file)
    if not m:
        return ""
    year, week = int(m.group(1)), int(m.group(2))
    monday = date.fromisocalendar(year, week, 1)
    sunday = date.fromisocalendar(year, week, 7)
    return f"{monday.isoformat()} ～ {sunday.isoformat()}"


def _build_email_html(summary_text: str, website_url: str) -> str:
    """跟 send_weekly_email.py 的 build_email_html() 同一套樣式，讓 n8n 寄出的信
    維持一樣的視覺風格。"""
    return f"""\
<html>
<body style="font-family: -apple-system, Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #1B1D22;">
  <div style="padding: 24px;">
    <h2 style="margin-bottom: 4px;">投影機情報站 · 週報</h2>
    <p style="color: #6B7280; font-size: 13px; margin-top: 0;">完整內容請見附件 PDF（含本週文章分類統計圖）</p>
    <p style="line-height: 1.7;">{summary_text}</p>
    <p style="margin-top: 24px;">
      <a href="{website_url}" style="background:#FFB454; color:#14161A; padding:10px 18px;
         border-radius:7px; text-decoration:none; font-weight:600;">前往網站看更多</a>
    </p>
    <hr style="margin: 32px 0; border: none; border-top: 1px solid #E0E0E0;">
    <p style="font-size: 12px; color: #999;">這封信由「投影機情報站」自動寄送。</p>
  </div>
</body>
</html>
"""


def send_webhook(workflow: str, status: str, body: str = "", report_file: str = None) -> bool:
    env_key = f"N8N_WEBHOOK_{workflow.upper()}"
    url = os.environ.get(env_key)

    if not url:
        print(f"notify_n8n: {env_key} 未設定，略過通知", file=sys.stderr)
        return False

    fields = {
        "workflow": workflow,
        "status": status,
        "hostname": socket.gethostname(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "log_tail": body,
        "report_file": report_file or "",
    }

    headers = {}
    token = os.environ.get("N8N_WEBHOOK_TOKEN")
    if token:
        headers["X-Webhook-Token"] = token

    # 週報成功時，把 PDF 和訂閱名單一起夾帶上傳（見上方模組說明：n8n 連不出去，
    # 只能反過來由這台電腦主動送過去）。
    pdf_path = None
    if workflow == "weekly" and status == "success" and report_file:
        candidate = os.path.join("reports", os.path.splitext(report_file)[0] + ".pdf")
        if os.path.exists(candidate):
            pdf_path = candidate
        else:
            print(f"notify_n8n: 找不到 {candidate}，這次通知不附 PDF/訂閱名單", file=sys.stderr)

    try:
        if pdf_path:
            fields["subscribers"] = json.dumps(_load_subscriber_emails())
            md_path = os.path.join("reports", report_file)
            summary_text = "本週投影機產業動態，詳見附件 PDF。"
            if os.path.exists(md_path):
                with open(md_path, "r", encoding="utf-8") as f:
                    summary_text = _extract_summary(f.read())
            week_range = _week_range_label(report_file)
            fields["email_subject"] = (
                f"【投影機情報站】{week_range} 投影機產業週報" if week_range
                else "【投影機情報站】投影機產業週報"
            )
            fields["email_html"] = _build_email_html(
                summary_text, os.environ.get("WEBSITE_URL", "")
            )
            with open(pdf_path, "rb") as f:
                files = {"file": (os.path.basename(pdf_path), f, "application/pdf")}
                resp = requests.post(url, data=fields, files=files, headers=headers, timeout=60)
        else:
            resp = requests.post(url, json=fields, headers=headers, timeout=15)
        resp.raise_for_status()
        print(f"notify_n8n: 已通知 n8n（{workflow}/{status}）", file=sys.stderr)
        return True
    except Exception as e:  # 通知本身失敗不該讓呼叫端（.bat）爆掉
        print(f"notify_n8n: 通知 n8n 失敗：{e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python notify_n8n.py <workflow> <status> [report_file] [log 內容改用 stdin 餵入]", file=sys.stderr)
        sys.exit(1)

    wf = sys.argv[1]
    st = sys.argv[2]
    rf = sys.argv[3] if len(sys.argv) > 3 else None
    text = sys.stdin.read() if not sys.stdin.isatty() else ""
    sys.exit(0 if send_webhook(wf, st, text, report_file=rf) else 1)
