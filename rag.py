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
3. 下方文章已依「發布日期新到舊」排序（文章1 最新）。當問題問的是「最新 /
   目前 / 現在 / 今年 / 最近」這類時效性內容時：
   - 以發布日期最新的文章為主軸回答；
   - 較舊、明顯已被較新文章取代的資訊（例如更早一代的產品、更早的展會），
     可以略過，或簡短帶過並標註「（較早期資訊）」，不要跟最新資訊平起平坐地並列。
4. 若不同文章對「同一時間點的同一件事」給出不同數字或說法（而不是單純新舊差異），
   才並列呈現、不要自行取捨。
5. 語氣專業、直接，避免「根據我的知識」這類暗示你在用檢索外的資訊回答的說法。
6. 用繁體中文回答，控制在 150-350 字，不需要之後再补充「更多資訊請參考...」
   這類贅語，來源清單前端會另外顯示。
"""


# 低於這個 cosine 相似度就當作「檢索不到相關內容」。gemini-embedding-2 的檢索向量
# 對真正相關的文章通常落在 0.5 以上，0.3 以下多半是沾不上邊——寧可回「資料不足」，
# 也不要拿幾篇不相關的文章硬湊答案。門檻可視實際問答品質再微調。
MIN_SIMILARITY = 0.30


def _build_context(retrieved: list[dict]) -> str:
    """把檢索到的文章排成給模型看的上下文——依發布日期新到舊
    （相似度排序留給前端的來源清單）。問「最新」時 LLM 對前面內容權重較高，
    配合 SYSTEM_PROMPT 規則 3 會偏向近期。"""
    for_context = sorted(
        retrieved, key=lambda a: a.get("publish_date") or "", reverse=True
    )
    blocks = []
    for i, a in enumerate(for_context, start=1):
        blocks.append(
            f"[文章{i}] 標題：{a['title_zh']}\n"
            f"來源：{a['source_name']}｜發布日期：{a['publish_date']}｜"
            f"分類：{a['category']}\n"
            f"摘要：{a['summary_zh']}"
        )
    return "\n\n".join(blocks)


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
    retrieved = embeddings.cosine_similarity_search(
        query_vector, top_k=top_k, min_similarity=MIN_SIMILARITY
    )

    if not retrieved:
        return {
            "answer": "目前資料庫中找不到與這個問題足夠相關的文章，暫時無法回答。"
                      "可以換個問法、或把範圍縮小到具體的品牌／技術／時間再試試。",
            "sources": [],
        }

    prompt = f"""使用者問題：{question}

以下是檢索到的相關文章，已依「發布日期新到舊」排序（文章1 最新）：

{_build_context(retrieved)}

請根據上述文章回答使用者問題。"""

    # AI 問答是使用者即時在等的請求，Vercel function 有 30 秒逾時限制，所以這裡：
    # 1. 改用 FLASH_MODELS（額度較寬鬆、回應較快），不跟月報/年報共用重量級的 PRO_MODELS
    # 2. max_retry=1（只跑一輪 model 清單），429 就快速換下一個 model
    # 3. pace_calls=False：不套用批次節流閥（那是給爬蟲/報告用的，會讓每次問答硬等數秒）
    response = gemini_client.call_gemini(
        model=gemini_client.FLASH_MODELS,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3,
        ),
        max_retry=1,
        retry_wait=3,
        pace_calls=False,
    )

    sources = [
        {
            "title_zh": a["title_zh"],
            "source_name": a["source_name"],
            "url": a["url"],
            "publish_date": a["publish_date"],
            "similarity": round(a["similarity"], 3),
            # 由 check_links.py 季度健檢填入；前端只在值為 "dead" 時顯示失效提示
            "link_status": a.get("link_status"),
        }
        for a in retrieved
    ]

    return {"answer": response.text, "sources": sources}
