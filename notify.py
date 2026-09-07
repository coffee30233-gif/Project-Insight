"""
notify.py
出問題時寄一封純文字告警信給維運者，重用 .env 裡既有的 SMTP 設定
（跟 send_weekly_email.py 同一組）。收件人取 ALERT_EMAIL，沒設定就寄給 SMTP_USER 自己。

用法：
    # 從程式呼叫
    import notify; notify.send_alert("每日爬蟲失敗", "……log 尾巴……")

    # 從 shell：把 log 尾巴用 stdin 餵進來
    tail -c 4000 logs/daily_20260907.log | python notify.py "每日更新失敗 2026-09-07"
"""
import os
import ssl
import sys
import smtplib
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()


def send_alert(subject: str, body: str = "") -> bool:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_name = os.environ.get("SMTP_FROM_NAME", "投影機情報站")
    to_addr = os.environ.get("ALERT_EMAIL") or user

    if not all([host, user, password, to_addr]):
        print("notify: SMTP 或 ALERT_EMAIL 未設定，略過告警信", file=sys.stderr)
        return False

    msg = MIMEText(body or "(無內容)", "plain", "utf-8")
    msg["Subject"] = f"[投影機情報站] {subject}"
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        print(f"notify: 已寄出告警信給 {to_addr}", file=sys.stderr)
        return True
    except Exception as e:  # 告警本身失敗不該讓呼叫端爆掉
        print(f"notify: 告警信寄送失敗：{e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    subj = sys.argv[1] if len(sys.argv) > 1 else "未指定標題的告警"
    text = sys.stdin.read() if not sys.stdin.isatty() else " ".join(sys.argv[2:])
    sys.exit(0 if send_alert(subj, text) else 1)
