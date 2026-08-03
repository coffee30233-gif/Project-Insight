"""
rag.py
RAG（Retrieval-Augmented Generation）問答核心邏輯：
  1. 把使用者問題轉成向量
  2. 用 embeddings.cosine_similarity_search() 找出最相關的文章
  3. 把檢索到的文章摘要當作上下文，連同問題一起交給 Gemini 生成回答
  4. 回傳「回答 + 引用來源清單」，前端可以把來源列在回答下方

設計原則：只讓模型根據「檢索到的文章」回答，不足的地方要老實說「目前資料
不足」，避免模型憑空生成看起來合理但沒有根據的市場數據。
"""

from google.genai import types

import embeddings
import gemini_client  # 重用同一個 Gemini client 設定

SYSTEM_PROMPT = """\
你是「投影機情報站」網站上的 AI 問答助手，只能根據下方提供的「檢索到的文章」
回答使用者的問題，這些文章都是本站資料庫中已收錄、經過摘要的投影機產業新聞。

規則：
1. 只使用檢索到的文章內容作答，不可使用你自己既有的知識補充數字或事實。
   如果檢索到的文章不足以回答問題，要老實說「目前資料庫中沒有足夠的資訊
   回答這個問題」，並可以建議使用者換個問法或縮小範圍。
2. 回答中的每個重點，盡量註明是根據哪篇文章（可用文章標題簡稱），
   方便使用者對照下方列出的來源清單。
3. 若不同文章對同一件事有不同數字或說法，並列呈現，不要自行判斷取捨。
4. 語氣專業、直接，避免「根據我的知識」這類暗示你在用檢索外的資訊回答的說法。
5. 用繁體中文回答，控制在 150-350 字，不需要之後再补充「更多資訊請參考...」
   這類贅語，來源清單前端會另外顯示。
"""


def answer_question(question: str, top_k: int = 8) -> dict:
    """
    回傳格式：
    {
      "answer": "生成的回答文字",
      "sources": [
        {"title_zh": ..., "source_name": ..., "url": ..., "publish_date": ...,
         "similarity": 0.83},
        ...
      ]
    }
    """
    query_vector = embeddings.embed_query(question)
    retrieved = embeddings.cosine_similarity_search(query_vector, top_k=top_k)

    if not retrieved:
        return {
            "answer": "資料庫目前還沒有可供檢索的文章（可能是還沒執行過爬蟲，"
                      "或還沒有文章完成 embedding 處理），暫時無法回答這個問題。",
            "sources": [],
        }

    context_blocks = []
    for i, article in enumerate(retrieved, start=1):
        context_blocks.append(
            f"[文章{i}] 標題：{article['title_zh']}\n"
            f"來源：{article['source_name']}｜發布日期：{article['publish_date']}｜"
            f"分類：{article['category']}\n"
            f"摘要：{article['summary_zh']}"
        )
    context_text = "\n\n".join(context_blocks)

    prompt = f"""使用者問題：{question}

以下是檢索到的相關文章（依相關度排序）：

{context_text}

請根據上述文章回答使用者問題。"""

    # AI 問答是使用者即時在等的請求，Vercel function 有 30 秒逾時限制，所以這裡：
    # 1. 改用 FLASH_MODELS（額度較寬鬆、回應較快），不跟月報/年報共用重量級的 PRO_MODELS
    # 2. 大幅縮短重試等待秒數（每個模型最多等 3 秒重試一次），寧可快速換下一個模型，
    #    也不要每個模型都乾等 10 秒、疊加起來超過平台的逾時上限
    response = gemini_client.call_gemini(
        model=gemini_client.FLASH_MODELS,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
        ),
        max_retry=1,
        retry_wait=3,
    )

    sources = [
        {
            "title_zh": a["title_zh"],
            "source_name": a["source_name"],
            "url": a["url"],
            "publish_date": a["publish_date"],
            "similarity": round(a["similarity"], 3),
        }
        for a in retrieved
    ]

    return {"answer": response.text, "sources": sources}
