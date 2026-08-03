"""
api/ask.py
Vercel Serverless Function，對應路由 /api/ask（POST）。

跟舊版 api.py（整套 FastAPI 伺服器）不一樣，這裡刻意只做「AI 問答」這一件事：
- 「最新情報」「月報／年報」都改成讀取部署時打包好的靜態 JSON/MD 檔案
  （專案根目錄的 data/，由 export_static_data.py 產生），不需要一直開著的後端。
- 只有這個問答功能需要「即時」運算（把問題轉向量、做相似度檢索、呼叫 Gemini 生成回答），
  所以獨立成一個輕量的 Serverless Function。

注意：這個檔案會讀取專案根目錄打包進部署的 projector_intel.db（唯讀），
所以部署前一定要先在本機跑過 export_static_data.py（或至少確保 db.py 用的
projector_intel.db 是最新的、且沒有被 .gitignore 排除在部署之外）。
"""
import os
import sys

# Vercel 執行這個檔案時，工作目錄不一定是專案根目錄，這裡把根目錄加進
# sys.path，才能 import 到同一層的 db.py / gemini_client.py / embeddings.py / rag.py。
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()


class AskRequest(BaseModel):
    question: str


def _handle_ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="請輸入問題")

    import rag  # 延遲載入：避免沒設定 GEMINI_API_KEY 時，整個 function 連 import 都失敗
    try:
        return rag.answer_question(req.question)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# Vercel 對 Python function 的路徑對應規則在不同版本行為略有差異，
# 這裡把 "/" 和 "/api/ask" 都註冊，確保不管實際打進來的路徑是哪一種都能正確處理。
@app.post("/")
def ask_root(req: AskRequest):
    return _handle_ask(req)


@app.post("/api/ask")
def ask_full_path(req: AskRequest):
    return _handle_ask(req)
