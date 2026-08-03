"""
send_weekly_email.py
讀取 data/subscribers.json 的訂閱名單，把最新一份週報（或指定的週報檔案）
轉成 email 內容，透過 SMTP（Gmail 或 Outlook）寄給所有訂閱者。

用法：
    python send_weekly_email.py                      # 自動抓 reports/ 底下最新的週報
    python send_weekly_email.py reports/2026-W30.md   # 指定週報檔案

執行前提：
1. .env 裡要設定好 SMTP 相關變數（見下方 SMTP_HOST 等）
2. 先 git pull，確保 data/subscribers.json 是最新的訂閱名單
   （網站上的訂閱表單是透過 GitHub API 直接 commit 到這個檔案）

.env 需要的變數：
    SMTP_HOST=smtp.gmail.com          # Gmail 用這個；Outlook/Office365 用 smtp.office365.com
    SMTP_PORT=587
    SMTP_USER=your-account@gmail.com
    SMTP_PASSWORD=xxxx xxxx xxxx xxxx  # Gmail 要用「應用程式密碼」，不是登入密碼
    SMTP_FROM_NAME=投影機情報站
    WEBSITE_URL=https://your-site.vercel.app
"""
import glob
import json
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

try:
    import markdown as md
except ImportError:
    print("缺少 markdown 套件，請先執行：pip install markdown")
    sys.exit(1)

REPORTS_DIR = "reports"
SUBSCRIBERS_PATH = os.path.join("data", "subscribers.json")


def find_latest_weekly_report() -> str | None:
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*-W??.md")), reverse=True)
    return files[0] if files else None


def load_subscribers() -> list[str]:
    if not os.path.exists(SUBSCRIBERS_PATH):
        return []
    with open(SUBSCRIBERS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [s["email"] for s in data]


def build_email_html(report_md: str, website_url: str) -> str:
    body_html = md.markdown(report_md, extensions=["extra"])
    return f"""\
<html>
<body style="font-family: -apple-system, Arial, sans-serif; max-width: 680px; margin: 0 auto; color: #1B1D22;">
  <div style="padding: 24px;">
    {body_html}
    <hr style="margin: 32px 0; border: none; border-top: 1px solid #E0E0E0;">
    <p style="font-size: 13px; color: #888;">
      這封信由「投影機情報站」自動寄送。想看更多歷史報告、或使用 AI 問答，
      歡迎前往 <a href="{website_url}">{website_url}</a>。
    </p>
  </div>
</body>
</html>
"""


def send_email(smtp_host, smtp_port, smtp_user, smtp_password, from_name,
                to_emails: list[str], subject: str, html_body: str):
    for to_email in to_emails:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{smtp_user}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to_email], msg.as_string())

        print(f"已寄出：{to_email}")


def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else find_latest_weekly_report()
    if not report_path or not os.path.exists(report_path):
        print("找不到週報檔案，請先執行 python generate_weekly_report.py")
        sys.exit(1)

    print(f"使用週報：{report_path}")
    with open(report_path, "r", encoding="utf-8") as f:
        report_md = f.read()

    subscribers = load_subscribers()
    if not subscribers:
        print("目前沒有任何訂閱者（data/subscribers.json 是空的），不寄送。")
        return
    print(f"訂閱者數量：{len(subscribers)}")

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_name = os.environ.get("SMTP_FROM_NAME", "投影機情報站")
    website_url = os.environ.get("WEBSITE_URL", "")

    if not all([smtp_host, smtp_user, smtp_password]):
        print("請先在 .env 設定 SMTP_HOST / SMTP_USER / SMTP_PASSWORD")
        sys.exit(1)

    # 從週報第一行「# 2026-07-21 ～ 2026-07-27 投影機產業週報」取標題當信件主旨
    first_line = report_md.splitlines()[0].lstrip("# ").strip()
    subject = f"【投影機情報站】{first_line}"

    html_body = build_email_html(report_md, website_url)

    send_email(smtp_host, smtp_port, smtp_user, smtp_password, from_name,
               subscribers, subject, html_body)

    print(f"\n完成，共寄出 {len(subscribers)} 封信。")


if __name__ == "__main__":
    main()
