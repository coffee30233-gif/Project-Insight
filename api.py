"""
api.py
本機開發測試用的整合伺服器（純本機用，Vercel 正式部署不會用到這支檔案，
已加進 .vercelignore；正式環境走的是純靜態檔案 + api/ask.py 這個獨立的
Serverless Function）。

提供：
  - GET  /                        首頁（index.html）
  - GET  /app.js, /style.css      前端資源
  - GET  /data/...                靜態資料（stats.json、articles.json、reports/*.md，
                                    由 export_static_data.py 產生）
  - POST /api/ask                 RAG 問答（跟 api/ask.py 邏輯相同，方便本機直接測試）

啟動方式：
  uvicorn api:app --reload --port 8000
啟動後直接打開 http://localhost:8000 就是網站首頁。
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="投影機情報站（本機開發伺服器）")

# 開發階段先全開，正式上線（Vercel）不會用到這支檔案，所以這裡的 CORS 設定不影響正式環境
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 前端靜態檔案（只公開必要的檔案/目錄，不把整個專案資料夾掛出去，
# 避免不小心把 .py、.env、projector_intel.db 等檔案也透過 HTTP 曝露出去）
# ---------------------------------------------------------------------------

app.mount("/data", StaticFiles(directory="data"), name="data")


@app.get("/")
def serve_index():
    return FileResponse("index.html")


@app.get("/app.js")
def serve_app_js():
    return FileResponse("app.js", media_type="application/javascript")


@app.get("/style.css")
def serve_style_css():
    return FileResponse("style.css", media_type="text/css")


# ---------------------------------------------------------------------------
# RAG 問答（跟 api/ask.py 邏輯相同，方便本機開發時不用另外跑 vercel dev 就能測）
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str


@app.post("/api/ask")
def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="請輸入問題")

    # 延遲載入，避免沒設定 GEMINI_API_KEY 時整個伺服器連啟動都失敗
    import rag
    try:
        return rag.answer_question(req.question)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
