# 投影機情報站 — 專案架構與功能說明

> 這份文件是給 AI（Claude）當作製作簡報的參考資料用。內容涵蓋：這個網站是什麼、
> 使用者看到什麼、背後的資料流與模組、部署與自動化、近期改進、關鍵數字、已知限制。
> 需要向「零技術背景」聽眾說明時，優先用每節開頭的白話比喻。
> 最後更新：2026-09-07。

---

## 0. 一句話說明

**它自動到全球網站蒐集投影機產業新聞，用 AI 翻成中文、寫摘要、分類，整理成一個可以
搜尋、也可以直接問問題的網站——而且每天自動更新、幾乎零人工維運。**

三個價值：
1. **省時**：同事不用自己看外電、翻譯、剪貼，打開網站就有整理好的中文情報。
2. **不漏接**：十幾個來源每天自動掃一次，重要動態不會錯過。
3. **問了就答**：用白話問「最近雷射光源有什麼進展」，AI 只根據站內收錄的文章回答並附出處。

---

## 1. 使用者看到什麼（前端三個分頁）

前端是一個**純靜態單頁網站**（`index.html` + `app.js` + `style.css`），視覺主題是「放映室」
（暗色背景、投影燈的琥珀色為主色）。三個分頁讀的都是同一批資料，只是呈現方式不同。

| 分頁 | 內容 | 資料來源 |
|---|---|---|
| **最新情報** | 一則一則的文章卡片：中文標題、摘要、來源、分類、日期、「查看原文來源」連結。可用關鍵字 / 來源 / 分類即時篩選（全部在前端做）。 | `data/articles.json` |
| **月報 / 年報** | 系統定期彙整的報告：週報、月報、半年報、年報。部分報告附簡報檔（.pptx）與 PDF 可下載。 | `data/reports/*.md` + `data/reports-index.json` |
| **AI 問答** | 輸入問題，AI 只根據站內收錄的文章回答，下方列出參考來源。找不到相關內容會直說「資料不足」。 | 即時呼叫 `/api/ask`（Serverless Function） |

**「查看原文」連結的失效提示**：原文連在別人的網站，對方一旦下架或改網址就會變死連結。
系統每季自動巡一次所有原文連結，把失效的（HTTP 404/410）標記起來，前端在該篇文章與
AI 問答的出處顯示「⚠ 原文連結可能已失效，請參考本站摘要」。被網站防爬蟲擋下的（403/429）
不算失效，避免誤判。

---

## 2. 技術棧

| 層 | 用什麼 |
|---|---|
| 爬蟲 / 資料處理 | Python 3（`requests`、`feedparser`、`BeautifulSoup`、`numpy`） |
| AI | Google Gemini API（摘要 / 分類 / 報告寫作 / 問答）、Gemini Embedding（向量檢索）。透過官方 `google-genai` SDK，不自己養模型。 |
| 資料庫 | SQLite 單一檔案 `projector_intel.db`（本機 / 伺服器工作用） |
| 前端 | 原生 HTML / CSS / JavaScript，無框架。Markdown 用 `marked.js` 渲染。 |
| 部署 | Vercel（靜態檔案 + 2 個 Python Serverless Function） |
| 報告產出 | `python-pptx`（簡報）、`reportlab` / `matplotlib`（PDF 與統計圖） |
| 自動化排程 | n8n（Docker 容器，透過 SSH 呼叫伺服器上的 shell 腳本） |
| 訂閱者週報 | SMTP 寄信（`smtplib`），PDF 當附件 |
| 測試 | pytest |

---

## 3. 系統架構（大圖）

```
                 ┌─────────────────────────────────────────────┐
   每天 08:30 →  │  伺服器（/opt/projector-insight）              │
   (n8n 觸發)    │                                             │
                 │  scraper_example.py  ──►  ingest.py  ──►  Gemini │
                 │   (12 個來源:              │  翻譯/摘要/分類/評分/  │
                 │    RSS + HTML 列表頁)      │  判斷相關性 + 產生向量  │
                 │                           ▼                 │
                 │                    projector_intel.db (SQLite) │
                 │                           │                 │
                 │             export_static_data.py           │
                 │                           ▼                 │
                 │   data/  ├─ articles.json   (最新情報列表)     │
                 │          ├─ stats.json      (首頁統計)         │
                 │          ├─ rag.jsonl       (AI 問答檢索資料)   │
                 │          ├─ reports-index.json + reports/*.md  │
                 │          └─ (archive/ 原文快取，預設關閉)       │
                 │                           │                 │
                 │              git commit + push              │
                 └───────────────────────────┼─────────────────┘
                                             ▼
                              GitHub (coffee30233-gif/Project-Insight)
                                             │  push 觸發
                                             ▼
                 ┌─────────────────────────────────────────────┐
                 │  Vercel（自動重新部署）                        │
                 │   靜態檔案：index.html / app.js / style.css /  │
                 │             data/*                          │
                 │   Serverless Functions（即時運算）：           │
                 │     api/ask.py       AI 問答 (RAG)            │
                 │     api/subscribe.py 訂閱（寫回 GitHub）        │
                 └─────────────────────────────────────────────┘
```

**核心設計原則：網站本體是「一疊靜態檔案」，不需要一直開著的伺服器。**
唯一的即時運算是「AI 問答」——它是一支「隨叫隨用、答完就休眠」的小程式（Serverless
Function），沒人使用時等於沒有東西在跑、在花錢。好處：便宜、快、幾乎不會壞。

---

## 4. 資料流 / Pipeline（每天自動跑一次）

可以把整條流程想成一間微型編輯部：

| 步驟 | 白話 | 檔案 |
|---|---|---|
| 1. 爬蟲抓取 | 去十幾個來源的更新清單，找出「還沒收錄過」的新文章 | `scraper_example.py` |
| 2. AI 翻譯 + 摘要 | 對每篇新文章：翻譯標題、寫中文摘要、分類、評重要性、判斷相關性 | `ingest.py` → `gemini_client.py` |
| 3. 產生向量 | 把「標題 + 摘要」轉成一串數字（embedding），供日後語意搜尋 | `embeddings.py` |
| 4. 寫入資料庫 | 結構化結果存進 SQLite | `db.py` |
| 5. 匯出成網頁檔案 | 把資料庫變成一疊 JSON / Markdown（前端要讀的格式） | `export_static_data.py` |
| 6. 部署上線 | git commit + push → Vercel 自動重新部署 | `daily_update.sh` |

- **1–2 想成「編輯」**：讀外電、翻譯、寫摘要、分類。
- **3–4 想成「歸檔」**：整理成電腦好查的格式，收進資料庫。
- **5–6 想成「出版」**：把資料庫變成網頁檔案，推上線。

### 第 2 步放大：AI 對每篇新文章做五件事（`gemini_client.process_article`）

1. **翻譯標題**（英日等外電 → 中文）
2. **寫中文摘要**（整篇濃縮成幾句話）
3. **分類**：市場數據 / 新品發布 / 技術動態 / 供應鏈
4. **評重要性**（分數，供排序與報告取用）
5. **判斷相關性**：Direct / Indirect / Maybe / **Unrelated**。判為 Unrelated 的（例如講筆電
   順帶提到投影機）會收起來——不進報告、不進 AI 問答、不產生向量，但仍留在資料庫當
   「已處理過」的記錄，避免爬蟲每天重複處理浪費 Gemini 額度。

---

## 5. 逐檔說明（重點模組）

### 資料進入
- **`scraper_example.py`** — 兩類爬蟲：
  - **RSS 來源**（6 個）：Reddit r/projectors、投影時代（含全文）、DigiTimes、
    TrendForce（Display / Consumer Elec）、IT之家。綜合性 feed 用 `PROJECTOR_KEYWORDS`
    過濾標題。
  - **HTML 列表頁**（6 個，無 RSS）：ZOL 投影機頻道、ZNDS 投影頻道、洛圖科技 RUNTO、
    ProjectorCentral、ProjectorReviews、199IT（間接取得奧維雲網 AVC 的數據）。
    詳情頁一律用 SEO meta 標籤（`og:title` / `description` / `article:published_time`）取資料，
    比針對每站硬寫 CSS selector 更耐用。
  - 共通：`normalize_url()`（去追蹤參數再去重）、`db.article_exists()` 先查重再抓詳情頁、
    RSS 用 `requests` 抓 + `socket.setdefaulttimeout(30)` 保底、失敗重試。
- **`ingest.py`** — 串接 `db` 與 `gemini_client`：去重 → 呼叫 Gemini → 寫回結構化結果 → 產生向量。
- **`import_research_articles.py`** — 一次性把過去的研究 / 媒體文章匯入（知乎、新浪科技、
  PRNewswire 等長尾來源就是這批）。
- **`backfill_*.py` / `check_data_coverage.py`** — 一次性回補工具（補向量、補相關性分類、檢查覆蓋率）。

### AI 呼叫
- **`gemini_client.py`** — 封裝 Gemini 呼叫，含「多模型後援清單」：撞額度 / 限流就自動換
  下一個模型。
  - `FLASH_MODELS`（純 Flash / Flash-Lite，6 個）：單篇摘要、AI 問答。**不會**打到貴的 Pro。
  - `PRO_MODELS`（Pro 優先、撞額度退回 Flash，7 個）：月報 / 半年報 / 年報。
- **`embeddings.py`** — 文字轉向量（`gemini-embedding-2`，768 維）；`cosine_similarity_search()`
  把所有向量載入記憶體用 numpy 算 cosine 相似度，帶 `min_similarity` 門檻。
- **`rag.py`** — AI 問答核心（RAG）：問題轉向量 → 找最相關的 8 篇 → 把摘要 + 問題交給
  Gemini，嚴格規定「只能根據這些內容作答、要標出處、不足要老實說」。`MIN_SIMILARITY=0.30`，
  過濾後為空就直接回「資料不足」，不呼叫 Gemini。

### 資料庫
- **`db.py`** — SQLite 讀寫。單一 `articles` 表。查詢過濾邏輯：
  - `EXCLUDED_RELEVANCE = ("Unrelated",)` — 無關文章不進報告 / 問答。
  - `EXCLUDED_FROM_REPORTS = ("Reddit r/projectors",)` — Reddit 只在「最新情報」列表顯示，
    不進週 / 月 / 年報，也不進 AI 問答（內容多為使用者求助 / 討論帖，不算產業情報）。
  - Vercel 上（`IS_VERCEL`）`get_all_embedded_articles()` 改讀 `data/rag.jsonl`，不碰資料庫。

### 匯出 / 前端
- **`export_static_data.py`** — 把資料庫匯出成 `data/` 底下的靜態檔（見架構圖）。
- **`index.html` / `app.js` / `style.css`** — 前端。全部 `fetch("data/xxx.json")` 相對路徑載入，
  篩選 / 分頁都在瀏覽器做。
- **`api/ask.py`** — `/api/ask` Serverless Function（FastAPI），唯一即時運算。
- **`api/subscribe.py`** — `/api/subscribe`：把訂閱信箱透過 GitHub API 直接 commit 進
  `data/subscribers.json`（Vercel 檔案系統唯讀，不能寫本地檔）。

### 報告產出
- **`generate_weekly_report.py`** / `generate_monthly_report.py` / `generate_semiannual_report.py`
  / `generate_annual_report.py` — 依時間範圍撈文章 → Gemini 寫成 Markdown 報告。
- **`generate_weekly_pdf.py`** — Markdown → PDF（含分類統計圖，`matplotlib` + `reportlab`）。
- **`generate_slides.py`** — Markdown → .pptx 簡報。
- **`send_weekly_email.py`** — 讀 `data/subscribers.json`，把最新週報 PDF 當附件寄給訂閱者。

### 維運
- **`daily_update.sh`** — 每日 pipeline 主腳本（scraper → export → commit / push）。含 `flock`
  互斥鎖、`timeout 900` 包住爬蟲、逐步檢查 exit code、失敗寄告警信、每季觸發連結健檢。
- **`weekly_report.sh` / `monthly_report.sh`** — 週 / 月報 pipeline，結構同上。
- **`catch_up.sh`** — 每日更新的「安全網」：n8n 在主排程一小時後再呼叫一次，今天已成功
  就不動作，沒成功就補跑 `daily_update.sh`。
- **`check_links.py`** — 每季巡一次所有原文連結，把失效的標記到資料庫。
- **`notify.py`** — 任一 pipeline 步驟失敗時，用 `.env` 既有 SMTP 寄純文字告警信。

---

## 6. 資料庫 schema（`articles` 表，單表）

| 欄位 | 說明 |
|---|---|
| `id` | 主鍵 |
| `source_name` | 來源名稱 |
| `original_title` | 原始標題 |
| `url` | 原文網址（UNIQUE，正規化後） |
| `publish_date` | 發布日期 `YYYY-MM-DD`（已換算台灣時間） |
| `raw_content` | 原文內文 / 摘要片段（給 Gemini 產摘要用） |
| `title_zh` / `summary_zh` | Gemini 產出的中文標題 / 摘要 |
| `category` | 市場數據 / 新品發布 / 技術動態 / 供應鏈 |
| `importance` | 重要性分數 |
| `original_language` | 原文語言 |
| `keywords` / `mentioned_brands` | JSON 字串陣列 |
| `processed_at` | Gemini 處理完成時間（NULL = 尚未成功處理，會被重試） |
| `embedding` | 768 維向量的 JSON 字串（供 RAG） |
| `image_url` | 代表圖片網址 |
| `relevance` / `relevance_reason` | Direct / Indirect / Maybe / Unrelated + 理由 |
| `link_status` / `link_checked_at` / `link_final_url` | 原文連結健檢結果（ok / dead / blocked / error） |

---

## 7. AI 問答（RAG）怎麼做到不亂講

白話：**先「找資料」再「讓 AI 照著資料寫」**，所以出處可查、比較不會幻想。

1. 把使用者問題轉成一串數字（向量）——讓電腦能用數學比較「意思接近」的文章，不只是比對關鍵字。
2. 從資料庫所有文章中，找語意最接近的 8 篇（cosine 相似度）。相似度低於 0.30 的丟掉。
3. 若過濾後一篇都不剩 → 直接回「目前資料庫中找不到足夠相關的文章」，**不呼叫 Gemini**。
4. 否則把這 8 篇的摘要 + 問題交給 Gemini，附嚴格指示：只能用這些內容作答、每個重點標出處、
   不足要老實說、用繁體中文、150–350 字。
5. 回傳「答案 + 參考來源清單」，使用者可以點來源自己核對。

（業界術語：RAG = Retrieval-Augmented Generation，檢索增強生成。）

---

## 8. 部署與「為什麼沒有伺服器」

- 網站 = 首頁 + 樣式 + 整理好的資料（一堆 JSON / MD），全都是**靜態檔案**。訪客打開
  網站只是把檔案下載到瀏覽器，不需要後端即時運算 → 便宜、快、幾乎不會壞。
- **唯一例外：AI 問答**。它需要「當下」運算（轉向量、找文章、呼叫 Gemini），所以獨立成
  一支 Serverless Function（`api/ask.py`）：有人問才啟動，答完就休眠。
- 全站託管在 **Vercel**。每次 GitHub 收到 push 就自動重新部署。
- Vercel 的檔案系統是唯讀的，所以：訂閱寫入走 GitHub API、AI 問答的檢索資料改讀
  `data/rag.jsonl`（不帶整顆資料庫）。

---

## 9. 自動化與排程（n8n）

n8n 是一個「把重複工作串起來自動執行」的工具，跑在 Docker 容器裡，透過 **SSH** 呼叫
伺服器上的 shell 腳本（背景執行 `nohup … &`，觸發後立刻回傳）。

| 工作 | 排程（Asia/Taipei） | 做什麼 |
|---|---|---|
| 每日更新 | 每天 08:30 | `daily_update.sh`：爬蟲 → AI 處理 → 匯出 → commit / push |
| 每日更新-安全網 | 每天 09:30 | `catch_up.sh`：今天沒成功就補跑（防 SSH 瞬斷等造成整天掉） |
| 每週報告 | 每週一 09:00 | `weekly_report.sh`：產週報 + PDF + 簡報 → push → 寄信給訂閱者 |
| 每月報告 | 每月 1 號 | `monthly_report.sh`：產上個月月報 + 簡報 |
| 每季連結健檢 | 由 `daily_update.sh` 在 1/4/7/10 月 1 號自動觸發 | `check_links.py` |

**可靠性設計**：
- 每支 pipeline 腳本逐步檢查 exit code，任一步失敗 → 收斂成 `FAILED` 旗標 → 結束後寄
  **告警信**（附 log 尾巴）到維運信箱。
- `daily_update.sh` 用 `timeout --kill-after=60 900` 包住爬蟲：任何來源「接受連線但不回應」
  最多拖 15 分鐘就被中止，不會卡死好幾天擋住整條流程。
- `flock` 互斥鎖：主排程與安全網搶同一把，不會兩個爬蟲並跑。
- n8n 節點層級 Retry 間隔上限只有 5 秒，擋不住較長的瞬斷 → 靠「安全網排程 + 告警信」補。

---

## 10. 近期改進（2026-09 這一輪）

| 主題 | 內容 |
|---|---|
| **原文連結失效偵測** | 新增 `check_links.py` + DB 三個欄位；每季自動巡連結，前端顯示「連結可能已失效，請參考本站摘要」；預留「原文快取」功能（`ENABLE_ORIGINAL_CACHE`，因著作權考量預設關閉）。 |
| **爬蟲效能** | 先查重再抓詳情頁（整趟從 ~22 分鐘 → 2–3 分鐘；ZOL 205 個連結原本走 4 分鐘、現在 3 秒）。RSS 加逾時、修好重試迴圈（原本每來源每天 parse 3 次）。附帶修好 Reddit RSS（先前長期回傳 0 篇）。 |
| **Reddit 分流** | Reddit r/projectors 恢復供文後，只進「最新情報」列表，不進報告與 AI 問答。 |
| **DB 不進 git** | AI 問答改讀 `data/rag.jsonl`（逐行、可 delta），`projector_intel.db` 移出 git —— `.git` 從此不再每天長 8 MB。 |
| **AI 問答相似度門檻** | 檢索不到相關內容就誠實回「資料不足」，不硬湊答案。 |
| **維運告警 + 安全網** | `notify.py` 失敗告警信；`catch_up.sh` 補跑排程；`flock` 互斥鎖。 |
| **一致性清理** | 模型清單拆成 FLASH / PRO（單篇摘要不再誤用貴的 Pro）；移除死掉的 `config.py` 常數與過時的 `.service` 檔；三支維運腳本納入 git、API key 改讀 `.env`。 |
| **測試** | 導入 pytest（24 個測試）：網址正規化、日期跨時區、關鍵字過濾、DB 過濾行為、`rag.jsonl` 讀取。 |

---

## 11. 關鍵數字（2026-09-07）

| 項目 | 數字 |
|---|---|
| 資料庫文章總數 | 872（已 AI 處理 806） |
| 進入 AI 問答檢索的文章 | 574（排除 Reddit 與 Unrelated 後） |
| 爬蟲設定的來源 | 12（6 RSS + 6 HTML 列表頁） |
| 資料庫出現過的來源名稱 | 約 30（含一次性匯入的長尾來源） |
| 主要來源（篇數） | ZOL 385、Reddit 173、ProjectorReviews 118、ProjectorCentral 55、IT之家 41、DigiTimes 30 |
| 分類分布 | 新品發布 566、市場數據 149、技術動態 67、供應鏈 24 |
| 報告 | 月報 16 份、週報 7 份、半年報 3 份、年報 1 份 |
| 週報訂閱者 | 3 |
| 向量維度 | 768（`gemini-embedding-2`） |
| 每日 pipeline 耗時 | 正常日 2–3 分鐘（優化前 ~22 分鐘） |
| `data/rag.jsonl` | 4.3 MB／574 行 |
| Serverless Functions | 2（`api/ask.py`、`api/subscribe.py`） |

---

## 12. 已知限制 / 待辦

- **`articles.json` 整包載入**：前端一次載入全部文章（目前 674 篇 / ~540 KB）在記憶體篩選。
  到幾千篇後手機會吃力，屆時要改成伺服器端分頁或按月切檔。（尚未做）
- **`.git` 歷史**：舊的資料庫 blob 還在歷史裡（`.git` 約 73 MB）。已止血、不再成長；
  真要瘦身需 `git filter-repo` 重寫歷史 + force push，對接著部署的 repo 風險高。
- **`import_research_articles.py` 的長尾來源**（知乎、新浪科技等）是一次性匯入，不在每日爬蟲範圍。
- **報告的 PDF / PPTX 仍進 git**：每週增加約 150 KB，比資料庫小很多，暫時可接受。
- **爬蟲的 `filter=True` 綜合來源**（RUNTO、199IT）在資料庫沒有的連結仍會逐篇抓詳情頁，
  可再用「列表頁錨文字預篩」省一批請求。

---

## 13. 名詞表（給零技術背景聽眾）

| 名詞 | 白話 |
|---|---|
| 爬蟲 | 自動去網頁上抓內容的程式 |
| RSS | 網站主動提供的「更新清單」，方便程式訂閱 |
| API | 程式對程式的窗口；我們透過它呼叫 Gemini |
| Gemini / LLM | Google 的大型語言模型，負責翻譯、摘要、回答 |
| 向量 (embedding) | 把一段文字變成一串數字座標，意思接近的座標也接近 |
| RAG | 先檢索資料、再讓 AI 照資料回答的做法 |
| 資料庫 (SQLite) | 存所有文章的地方，這裡用單一檔案型資料庫 |
| 靜態網站 | 純檔案組成、不需即時運算的網站 |
| Serverless Function | 隨叫隨用、用完即休眠的小程式 |
| Vercel | 網站託管平台（放靜態檔案 + Serverless Function） |
| n8n | 自動化排程工具（把重複工作串起來自動執行） |
| commit / push | 把變更記錄進版本控制（git）、再上傳到 GitHub |
| Serverless 檔案系統唯讀 | 那支小程式不能寫檔案，所以訂閱要透過 GitHub API 寫回 |
