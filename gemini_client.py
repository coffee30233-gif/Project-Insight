"""
gemini_client.py
封裝三個 Gemini API 呼叫：
  1. process_article()        -> 對應 Prompt A，單篇文章摘要/分類/評分（結構化 JSON 輸出）
  2. generate_monthly_report() -> 對應 Prompt B，月報彙整（Markdown 輸出）
  3. generate_annual_report()  -> 對應 Prompt C，年度報告彙整（以 12 份月報為輸入，Markdown 輸出）

使用官方 google-genai SDK。安裝：pip install google-genai
需先設定環境變數 GEMINI_API_KEY（於 https://aistudio.google.com 取得）。

模型選擇：
  - 單篇處理量大、要求較低 -> 用 gemini-2.5-flash-lite
  - 月報/年報需要跨篇比對與寫作品質 -> 用 gemini-2.5-flash
  依實際可用模型與費用調整，Gemini 模型版本更新頻率高，建議在
  https://ai.google.dev/gemini-api/docs/models 確認目前可用的模型 ID。
"""

import os
import json
import time
from datetime import datetime, timezone
from typing import List, Literal

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# 依帳號目前可用的模型，由快、額度寬鬆到重、額度緊排序，逐一嘗試直到成功：
# Flash 系列額度通常比 Pro 寬鬆、回應也快，優先嘗試；Pro 預覽版放中間；
# gemini-2.0-flash 是最後保底，即使前面全部撞額度，也還有機會成功。
MODEL_PRIORITY = [
    "gemini-3.6-flash",       # 最新 Flash（帳號可用時優先）
    "gemini-3.5-flash",       # 次優先 Flash
    "gemini-3.5-flash-lite",  # 成本更低
    "gemini-3.1-flash-lite",  # 備援
    "gemini-3-pro-preview",   # 最新 Pro 預覽版
    "gemini-3.1-pro-preview", # Pro 備援
    "gemini-pro-latest",      # 舊版 Pro 相容
    "gemini-2.5-flash-lite",  # 2.5 Lite
    "gemini-2.0-flash",       # 最後備援
]

# FLASH_MODELS／PRO_MODELS 這兩個名稱其他檔案（rag.py、generate_*_report.py）
# 都還在引用，保留名稱、但兩者都指向同一份完整的後援清單，不用同時改好幾個檔案。
FLASH_MODELS = MODEL_PRIORITY
PRO_MODELS = MODEL_PRIORITY

# 本機批次工作（月報／半年報／年報）用的預設重試設定：縮短成 1 次、等 5 秒，
# 額度不足時能更快跳到下一個模型，不用像以前一樣每個模型乾等 20 秒。
# AI 問答（rag.py）因為是使用者即時在等，另外用更短的 max_retry=1、retry_wait=3。
MAX_RETRY = 1
RETRY_WAIT = 5

_client = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("請先設定環境變數 GEMINI_API_KEY")
        _client = genai.Client(api_key=api_key)
    return _client


def call_gemini(model, contents, config, max_retry=None, retry_wait=None):
    """
    max_retry / retry_wait 可以針對個別呼叫覆寫預設值：
    - 月報／年報這類離線批次工作，願意多等一下換取成功率，用預設值（MAX_RETRY/RETRY_WAIT）即可
    - AI 問答這種使用者在等的即時呼叫，Vercel function 有 30 秒逾時限制，
      應該傳入較小的 max_retry/retry_wait，避免整個請求還沒重試完就先被平台判定逾時
    """
    max_retry = MAX_RETRY if max_retry is None else max_retry
    retry_wait = RETRY_WAIT if retry_wait is None else retry_wait

    client = get_client()

    models = model if isinstance(model, (list, tuple)) else [model]
    last_error = None

    for candidate in models:
        print(f"Trying Gemini model: {candidate}")

        for retry in range(max_retry):
            try:
                return client.models.generate_content(
                    model=candidate,
                    contents=contents,
                    config=config,
                )

            except Exception as e:
                msg = str(e).lower()

                if "404" in msg or "not_found" in msg or "no longer available" in msg:
                    print(f"Model {candidate} unavailable, trying next model...")
                    last_error = e
                    break

                if "429" in msg or "resource_exhausted" in msg:
                    print(f"Quota reached, waiting {retry_wait} seconds... ({retry+1}/{max_retry})")
                    time.sleep(retry_wait)
                    last_error = e
                    continue

                last_error = e
                raise

    raise RuntimeError("No available Gemini model.") from last_error

# ---------------------------------------------------------------------------
# Prompt A：單篇文章處理
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_A = """\
你是「投影機產業情報站」的資料處理引擎。你的任務是將輸入的單篇文章原文，
轉換成結構化的繁體中文摘要資料，供後續資料庫儲存與月報彙整使用。

規則：
1. 摘要必須是你自己的改寫，不可整段抄錄原文，控制在 80-150 字。
2. 分類只能從下列四類中選一個最貼切的：
   - 市場數據（出貨量、市佔率、零售通路數據等統計性內容）
   - 新品發布（新機型、新規格、新品牌動態）
   - 技術動態（光源技術、面板技術、顯示架構如 3LCD/DLP/LCoS 等深度技術內容）
   - 供應鏈（面板/晶片供應、產能、上下游廠商動態）
3. 若文章橫跨多類，選擇「篇幅占比最大」的一類。
4. 重要度評分 1-5：
   5分=具產業指標意義的統計報告/重大技術突破；3分=一般新品發布/常規市場評論；
   1分=小型韌體更新/單一用戶心得。
5. 若原文非中文，摘要仍需輸出繁體中文，並標註原文語言。
"""


class ArticleAnalysis(BaseModel):
    title_zh: str = Field(description="繁體中文標題，若原文非中文需翻譯")
    summary_zh: str = Field(description="80-150字繁體中文摘要")
    category: Literal["市場數據", "新品發布", "技術動態", "供應鏈"]
    importance: int = Field(ge=1, le=5)
    original_language: str = Field(description="例如 zh-CN, zh-TW, en")
    keywords: List[str]
    mentioned_brands: List[str]


def process_article(source_name: str, original_title: str, url: str,
                     publish_date: str, raw_content: str) -> dict:
    """呼叫 Gemini 處理單篇文章，回傳符合 ArticleAnalysis 結構的 dict。"""

    user_prompt = f"""\
來源網站：{source_name}
原文標題：{original_title}
原文連結：{url}
發布日期：{publish_date}
原文內容：
{raw_content}
"""

    response = call_gemini(
        model=FLASH_MODELS,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_A,
            response_mime_type="application/json",
            response_schema=ArticleAnalysis,
            temperature=0.3,
    ),
)

    analysis = ArticleAnalysis.model_validate_json(response.text)
    return analysis.model_dump()


# ---------------------------------------------------------------------------
# Prompt B：月報彙整
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_B = """\
你是「投影機產業情報站」的月報主編，負責將一個月內蒐集到的所有文章摘要，
彙整成一份給產業人士閱讀的繁體中文市場簡報。

寫作原則：
1. 這是彙整報告，不是逐篇列點翻譯——要找出趨勢、比對數據、歸納共識或分歧，
   而不是把每篇摘要複製貼上。
2. 每一項重點結論後方，用括號附上來源網站名稱，例如（洛圖科技、AVC）。
3. 若不同來源對同一件事給出不同數字，需並列呈現並註明差異，不要自行取捨或平均。
4. 語氣專業、精簡，避免行銷式誇飾用語。
5. 若某分類當月資料稀少，該節簡短註明「本月無重大更新」，不要硬湊字數。
6. 只使用輸入資料中出現的數字與事實，不要自行推算或補齊缺漏的統計數據。
7. 輸出格式為 Markdown。
"""

REPORT_TEMPLATE = """\
以下是 {year} 年 {month} 月，投影機情報站蒐集到的全部文章結構化資料（JSON 陣列）：

{articles_json}

請依下列結構產出本月市場簡報：

# {year} 年 {month} 月 投影機產業月報

## 一、本月摘要（3-5句話總覽本月最重要的變化）

## 二、市場數據

## 三、新品與品牌動態

## 四、技術動態

## 五、供應鏈觀察

## 六、本月關注品牌／技術關鍵字

## 附錄：本月參考來源
（依 category 分組列出本月所有文章的標題、來源網站與連結）

僅輸出上述結構的 Markdown 內容，不要額外前言或結語。
"""


def generate_monthly_report(year: int, month: int, articles: list[dict]) -> str:
    """呼叫 Gemini 彙整月報，回傳 Markdown 字串。"""

    prompt = REPORT_TEMPLATE.format(
        year=year,
        month=month,
        articles_json=json.dumps(articles, ensure_ascii=False, indent=2),
    )

    response = call_gemini(
        model=PRO_MODELS,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_B,
            temperature=0.4,
        ),
)
    return response.text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Prompt C：年度報告彙整
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_C = """\
你是「投影機產業情報站」的年度回顧主編，負責將一整年（12份）月報彙整成一份
給產業人士閱讀的繁體中文年度市場總結報告。

輸入是該年度已產出的月報全文（Markdown），不是原始文章，因此你不需要再做
「單篇摘要」層級的改寫，而是要做更高一層的工作：找出全年的趨勢線、轉折點、
季度或上下半年對比、以及貫穿全年的關鍵議題。

寫作原則：
1. 這是「年度回顧」，核心價值在於「跨月比對」——例如某項數據從年初到年末
   如何變化、哪個月份出現轉折、上半年與下半年的差異、全年是否有一致的技術
   或品牌趨勢。不要把 12 篇月報的內容依序簡單串接或條列。
2. 若不同月份的月報對同一件事（如某品牌全年市占）有不同或更新後的數字，
   以較新、較完整的月報數字為準，並在文中註明數字曾經修正或更新。
3. 每一項重點結論後方，用括號附上來源月份，例如（3月）、（Q2）。
4. 語氣專業、精簡，避免行銷式誇飾用語。
5. 若某月份的月報缺失，在對應段落簡短註明「該月資料缺失」，不要憑空杜撰
   缺失月份的內容。
6. 只使用輸入的月報中出現的數字與事實，不要自行推算或補齊缺漏的統計數據。
7. 輸出格式為 Markdown。
"""

ANNUAL_TEMPLATE = """\
以下是 {year} 年度，投影機情報站逐月產出的月報全文（依月份排序，缺失的月份
會標註「（本月無月報資料）」）：

{monthly_reports_text}

請依下列結構產出年度市場總結報告：

# {year} 年度 投影機產業回顧

## 一、年度摘要（5-8句話總覽全年最重要的變化與轉折點）

## 二、市場數據年度回顧
（全年出貨/銷售趨勢、上下半年或分季對比、主要品牌全年排名變化，
若有調降/調升預測等修正也請點出）

## 三、技術演進年度觀察
（全年在光源技術、面板技術、顯示架構等方面的重要進展，依時間順序點出關鍵節點）

## 四、新品與品牌年度盤點
（重點品牌全年動態、新品發布密集的月份、全年產品趨勢，如價格帶/技術路線變化）

## 五、供應鏈年度觀察
（面板/晶片供應、產能變化的全年脈絡）

## 六、年度關鍵轉折點（Timeline）
（用時間軸列出 3-6 個全年最重要的事件或數據轉折，並註明對應月份）

## 七、明年關注重點
（依全年趨勢，指出幾個值得在下一年持續追蹤的方向；僅能基於輸入資料中已出現
的線索合理推論，不可無中生有）

## 附錄：各月月報索引
（列出 1-12 月是否有對應月報資料，方便讀者回頭查閱原始月報）

僅輸出上述結構的 Markdown 內容，不要額外前言或結語。
"""


def generate_annual_report(year: int, monthly_reports: list[dict]) -> str:
    """
    彙整年度報告。

    monthly_reports: 依月份排序的 list，每筆為 {"month": int, "content": str|None}。
    content 為 None 表示該月無月報資料，會在 prompt 中標註缺失。
    """

    parts = []
    for item in monthly_reports:
        month = item["month"]
        content = item.get("content")
        if content:
            parts.append(f"### {month} 月月報\n\n{content}")
        else:
            parts.append(f"### {month} 月月報\n\n（本月無月報資料）")
    monthly_reports_text = "\n\n---\n\n".join(parts)

    prompt = ANNUAL_TEMPLATE.format(
        year=year,
        monthly_reports_text=monthly_reports_text,
    )

    response = call_gemini(
        model=PRO_MODELS,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_C,
            temperature=0.4,
        ),
)
    return response.text


# ---------------------------------------------------------------------------
# Prompt D：半年報彙整
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_D = """\
你是「投影機產業情報站」的半年報主編，負責將半年（6 份）月報彙整成一份
給產業人士閱讀的繁體中文半年度市場總結報告。

輸入是該半年已產出的月報全文（Markdown），不是原始文章，因此你不需要再做
「單篇摘要」層級的改寫，而是要做更高一層的工作：找出半年內的趨勢線、轉折點、
月與月之間的對比，以及貫穿整個半年的關鍵議題。

寫作原則：
1. 這是「半年回顧」，核心價值在於「跨月比對」——不要把 6 篇月報的內容依序
   簡單串接或條列，要找出半年內數據與趨勢的變化脈絡。
2. 若不同月份的月報對同一件事有不同或更新後的數字，以較新、較完整的月報
   數字為準，並在文中註明數字曾經修正或更新。
3. 每一項重點結論後方，用括號附上來源月份，例如（3月）。
4. 語氣專業、精簡，避免行銷式誇飾用語。
5. 若某月份的月報缺失，在對應段落簡短註明「該月資料缺失」，不要憑空杜撰
   缺失月份的內容。
6. 只使用輸入的月報中出現的數字與事實，不要自行推算或補齊缺漏的統計數據。
7. 輸出格式為 Markdown。
"""

SEMIANNUAL_TEMPLATE = """\
以下是 {year} 年{half_label}，投影機情報站逐月產出的月報全文（依月份排序，
缺失的月份會標註「（本月無月報資料）」）：

{monthly_reports_text}

請依下列結構產出半年度市場總結報告：

# {year} 年{half_label} 投影機產業回顧

## 一、半年摘要（4-6句話總覽這半年最重要的變化與轉折點）

## 二、市場數據回顧
（這半年的出貨/銷售趨勢、月與月之間的對比、主要品牌排名變化，
若有調降/調升預測等修正也請點出）

## 三、技術演進觀察
（這半年在光源技術、面板技術、顯示架構等方面的重要進展，依時間順序點出關鍵節點）

## 四、新品與品牌盤點
（重點品牌這半年的動態、新品發布密集的月份、產品趨勢，如價格帶/技術路線變化）

## 五、供應鏈觀察
（面板/晶片供應、產能變化的脈絡）

## 六、關鍵轉折點（Timeline）
（用時間軸列出 3-5 個這半年最重要的事件或數據轉折，並註明對應月份）

## 七、{outlook_label}
（依這半年的趨勢，指出幾個值得繼續追蹤的方向；僅能基於輸入資料中已出現
的線索合理推論，不可無中生有）

## 附錄：各月月報索引
（列出這 6 個月是否有對應月報資料，方便讀者回頭查閱原始月報）

僅輸出上述結構的 Markdown 內容，不要額外前言或結語。
"""


def generate_semiannual_report(year: int, half: int, monthly_reports: list[dict]) -> str:
    """
    彙整半年報。

    half: 1 表示上半年（1-6月），2 表示下半年（7-12月）
    monthly_reports: 依月份排序的 list，每筆為 {"month": int, "content": str|None}。
    """
    half_label = "上半年" if half == 1 else "下半年"
    outlook_label = "下半年關注重點" if half == 1 else "明年關注重點"

    parts = []
    for item in monthly_reports:
        month = item["month"]
        content = item.get("content")
        if content:
            parts.append(f"### {month} 月月報\n\n{content}")
        else:
            parts.append(f"### {month} 月月報\n\n（本月無月報資料）")
    monthly_reports_text = "\n\n---\n\n".join(parts)

    prompt = SEMIANNUAL_TEMPLATE.format(
        year=year,
        half_label=half_label,
        outlook_label=outlook_label,
        monthly_reports_text=monthly_reports_text,
    )

    response = call_gemini(
        model=PRO_MODELS,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_D,
            temperature=0.4,
        ),
    )
    return response.text


# ---------------------------------------------------------------------------
# Prompt E：週報彙整（給每週寄送給同事的 email 用，語氣比月報/年報更輕快、
# 篇幅更短，方便同事花 2-3 分鐘就能看完）
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_E = """\
你是「投影機情報站」的週報編輯，負責把過去一週蒐集到的投影機產業文章，
整理成一份給公司同事看的繁體中文週報，會直接寄送 email，所以：

1. 篇幅要精簡，同事花 2-3 分鐘就要能看完重點，不要長篇大論
2. 語氣像是「這週你該知道的投影機產業動態」，比月報/年報更輕快、口語一點，
   但還是要專業、不要浮誇
3. 如果這週資料很少（例如只有 1-2 篇），就誠實只講這 1-2 件事，不要硬湊字數
   或無中生有
4. 只使用輸入文章中出現的事實與數字，不要自行推算或補充外部知識
5. 每項重點後方用括號註明來源媒體名稱，方便同事想深入了解時查證
6. 輸出格式為 Markdown
"""

WEEKLY_TEMPLATE = """\
以下是 {start_date} 到 {end_date} 這一週，投影機情報站蒐集到的文章列表
（含來源、標題、摘要、分類）：

{articles_text}

請依下列結構產出週報：

# {start_date} ～ {end_date} 投影機產業週報

## 本週重點（3-5 句話）

## 市場與品牌動態
（本週跟出貨、銷售、品牌排名、新品發布相關的重點，如果沒有相關內容可以省略此段）

## 技術與供應鏈
（本週跟技術演進、晶片、供應鏈相關的重點，如果沒有相關內容可以省略此段）

## 下週關注
（1-3 個值得留意的方向，僅能基於本週資料中已出現的線索合理推論）

僅輸出上述結構的 Markdown 內容，不要額外前言或結語。如果某個段落完全沒有
對應的內容，直接省略整個段落（不要留空標題）。
"""


def generate_weekly_report(start_date: str, end_date: str, articles: list[dict]) -> str:
    """
    彙整週報。

    start_date/end_date: "YYYY-MM-DD" 格式
    articles: db.get_articles_by_date_range() 回傳的文章列表
    """
    if not articles:
        return (
            f"# {start_date} ～ {end_date} 投影機產業週報\n\n"
            "本週沒有蒐集到任何相關文章，暫無週報內容。\n"
        )

    parts = []
    for a in articles:
        parts.append(
            f"- 【{a['source_name']}】{a['title_zh']}（{a['category']}）\n"
            f"  {a['summary_zh']}"
        )
    articles_text = "\n".join(parts)

    prompt = WEEKLY_TEMPLATE.format(
        start_date=start_date,
        end_date=end_date,
        articles_text=articles_text,
    )

    response = call_gemini(
        model=FLASH_MODELS,  # 週報篇幅短、時效性高，用 Flash 系列，額度寬鬆、速度快
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT_E,
            temperature=0.4,
        ),
    )
    return response.text
