"""
send_weekly_email.py
讀取 data/subscribers.json 的訂閱名單，把最新一份週報轉成 email，
**PDF 版本（含分類統計圖表）當附件**寄給所有訂閱者，信件本文只放簡短重點
＋PDF 附件說明＋回網站的連結（完整內容看附件的 PDF，比較不死板）。

用法：
    python send_weekly_email.py                      # 自動抓 reports/ 底下最新的週報
    python send_weekly_email.py reports/2026-W30.md   # 指定週報檔案

執行前提：
1. .env 裡要設定好 SMTP 相關變數（見下方 SMTP_HOST 等）
2. 先 git pull，確保 data/subscribers.json 是最新的訂閱名單
   （網站上的訂閱表單是透過 GitHub API 直接 commit 到這個檔案）
3. 如果對應的 .pdf 還沒產生，這支腳本會自動呼叫 generate_weekly_pdf.py 產生

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
import re
import smtplib
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()

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


def ensure_pdf(md_path: str) -> str:
    """確保這份週報的 PDF 存在，不存在就呼叫 generate_weekly_pdf.py 產生。"""
    pdf_path = os.path.splitext(md_path)[0] + ".pdf"
    if not os.path.exists(pdf_path):
        print("PDF 還沒產生，先執行 generate_weekly_pdf.py...")
        import generate_weekly_pdf
        generate_weekly_pdf.build_pdf(md_path, pdf_path)
    return pdf_path


def extract_summary(report_md: str) -> str:
    """抓「本週重點」段落的文字，放進信件本文當摘要（信件本文精簡，完整內容看附件 PDF）。"""
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


def build_email_html(summary_text: str, website_url: str) -> str:
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


def send_email(smtp_host, smtp_port, smtp_user, smtp_password, from_name,
                to_emails: list[str], subject: str, html_body: str, pdf_path: str):
    pdf_filename = os.path.basename(pdf_path)
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    for to_email in to_emails:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = f"{from_name} <{smtp_user}>"
        msg["To"] = to_email

        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(html_body, "html", "utf-8"))
        msg.attach(alt_part)

        attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(attachment)

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

    pdf_path = ensure_pdf(report_path)

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_name = os.environ.get("SMTP_FROM_NAME", "投影機情報站")
    website_url = os.environ.get("WEBSITE_URL", "")

    if not all([smtp_host, smtp_user, smtp_password]):
        print("請先在 .env 設定 SMTP_HOST / SMTP_USER / SMTP_PASSWORD")
        sys.exit(1)

    first_line = report_md.splitlines()[0].lstrip("# ").strip()
    subject = f"【投影機情報站】{first_line}"

    summary_text = extract_summary(report_md)
    html_body = build_email_html(summary_text, website_url)

    send_email(smtp_host, smtp_port, smtp_user, smtp_password, from_name,
               subscribers, subject, html_body, pdf_path)

    print(f"\n完成，共寄出 {len(subscribers)} 封信（含 PDF 附件）。")


if __name__ == "__main__":
    main()
