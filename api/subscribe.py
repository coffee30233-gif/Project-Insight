"""
api/subscribe.py
Vercel Serverless Function，對應路由 /api/subscribe（POST）。

因為 Vercel 上的 projector_intel.db 是唯讀的（見 db.py 的說明），沒辦法直接
把訂閱信箱寫進資料庫，所以這裡改用「透過 GitHub API 把信箱寫進
data/subscribers.json、直接 commit 回 repo」的做法——不需要額外申請資料庫服務，
訂閱名單本身也會保留在 GitHub 的版本紀錄裡。

本機執行 python send_weekly_email.py 寄週報時，只要先 git pull，
就能讀到最新的訂閱名單。

需要的環境變數（在 Vercel 專案 Settings → Environment Variables 設定）：
    GITHUB_TOKEN   - GitHub Personal Access Token，需要有這個 repo 的
                     "Contents" 讀寫權限（fine-grained token 選 Read and write）
    GITHUB_REPO    - 格式 "owner/repo"，例如 "coffee30233-gif/Project-Insight"
    GITHUB_BRANCH  - 通常是 "main"
"""
import json
import os
import re
import base64
import urllib.request
import urllib.error

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUBSCRIBERS_PATH = "data/subscribers.json"


class SubscribeRequest(BaseModel):
    email: str


def _github_api(method: str, url: str, payload: dict | None = None):
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("尚未設定 GITHUB_TOKEN 環境變數")

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "projector-insight-subscribe")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"message": body}


def _add_subscriber(email: str) -> str:
    repo = os.environ.get("GITHUB_REPO")
    branch = os.environ.get("GITHUB_BRANCH", "main")
    if not repo:
        raise RuntimeError("尚未設定 GITHUB_REPO 環境變數")

    contents_url = f"https://api.github.com/repos/{repo}/contents/{SUBSCRIBERS_PATH}"

    status, result = _github_api("GET", f"{contents_url}?ref={branch}")

    if status == 200:
        current_content = base64.b64decode(result["content"]).decode("utf-8")
        subscribers = json.loads(current_content)
        sha = result["sha"]
    elif status == 404:
        subscribers = []
        sha = None
    else:
        raise RuntimeError(f"讀取訂閱名單失敗：{result.get('message', status)}")

    existing_emails = {s["email"].lower() for s in subscribers}
    if email.lower() in existing_emails:
        return "already_subscribed"

    subscribers.append({"email": email, "subscribed_at": _now_iso()})

    new_content = json.dumps(subscribers, ensure_ascii=False, indent=2)
    new_content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("ascii")

    payload = {
        "message": f"Add subscriber: {email}",
        "content": new_content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    status, result = _github_api("PUT", contents_url, payload)
    if status not in (200, 201):
        raise RuntimeError(f"寫入訂閱名單失敗：{result.get('message', status)}")

    return "subscribed"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _handle_subscribe(req: SubscribeRequest):
    email = req.email.strip()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="請輸入有效的 email 格式")

    try:
        result = _add_subscriber(email)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    if result == "already_subscribed":
        return {"message": "這個信箱已經訂閱過囉"}
    return {"message": "訂閱成功！下週一起會收到週報"}


@app.post("/")
def subscribe_root(req: SubscribeRequest):
    return _handle_subscribe(req)


@app.post("/api/subscribe")
def subscribe_full_path(req: SubscribeRequest):
    return _handle_subscribe(req)
