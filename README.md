# 投影機情報站 — Pipeline 範例（Gemini API 版）

這是「爬蟲 → Gemini 摘要/分類 → 資料庫 → 月報/年報產生」的最小可運作範例，
用來把先前設計的三個 Prompt（單篇處理 / 月報彙整 / 年報彙整）接進實際程式碼流程。

## 檔案說明

| 檔案 | 用途 |
|---|---|
| `db.py` | SQLite schema 與讀寫函式 |
| `gemini_client.py` | 封裝三個 Gemini API 呼叫（Prompt A / Prompt B / Prompt C） |
| `ingest.py` | 單篇文章的去重 + 呼叫 Gemini + 寫入資料庫 |
| `scraper_example.py` | 兩種爬蟲範本：RSS 來源 / HTML 列表頁來源 |
| `generate_monthly_report.py` | 每月排程執行，產出月報 Markdown |
| `generate_annual_report.py` | 每年排程執行，讀取該年 12 份月報彙整成年度回顧 |
| `backfill_last_year.py` | 用分頁回溯的方式，補齊資料庫裡缺少的去年歷史文章 |
| `check_data_coverage.py` | 產年報前先檢查資料庫裡各月份實際有多少資料 |
| `embeddings.py` | 產生文章 embedding、向量相似度搜尋（RAG 檢索基礎） |
| `rag.py` | RAG 問答核心邏輯：檢索相關文章 + 呼叫 Gemini 生成有依據的回答 |
| `api.py` | FastAPI 後端：文章列表／報告／RAG 問答 API，並掛載前端網站 |
| `static/` | 網站前端（純 HTML/CSS/JS，不需要 Node.js） |
| `run_daily.py` / `run_monthly.py` / `run_annual.py` | 排程用執行入口，包含錯誤隔離、log 記錄、失敗通知 |
| `notify.py` | 輕量失敗通知模組（Slack webhook，未設定時自動略過） |
| `deploy/` | crontab 範例與 systemd service/timer 設定檔 |

## 安裝

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="你的 API Key"   # 於 https://aistudio.google.com 取得
```

## 執行方式

```bash
# 1. 初始化資料庫（第一次執行會自動建立 projector_intel.db）
python -c "import db; db.init_db()"

# 2. 執行爬蟲，抓取文章並寫入資料庫（會自動呼叫 Gemini 處理每篇文章）
python scraper_example.py

# 3. 產生上個月的月報
python generate_monthly_report.py
# 或指定年月
python generate_monthly_report.py 2026 7

# 4. 產生去年的年度回顧報告前，先看一下資料庫裡實際覆蓋了哪些月份
python check_data_coverage.py

# 5. 產生去年的年度回顧報告（不管現有資料涵蓋幾個月都可以直接跑，
#    有資料的月份自動彙整，沒資料的月份會誠實標註「資料缺失」）
python generate_annual_report.py
# 或指定年份
python generate_annual_report.py 2025

# 6. 【首次啟用網站前】幫資料庫裡既有的文章補產生 embedding（RAG 檢索用）
#    之後 ingest.py 在正常流程中會自動幫「新」文章產生 embedding，
#    這一步只需要在第一次導入這個功能時執行一次，補齊過去的文章。
python embeddings.py

# 7. 啟動網站（後端 API + 前端一起跑，不需要另外的 Node.js 伺服器）
uvicorn api:app --reload --port 8000
# 啟動後打開瀏覽器 http://localhost:8000 即為網站首頁
```

## 自動化排程

三個排程用的執行入口都已經包好錯誤處理、log 記錄、失敗通知，不需要直接呼叫
底層的 `scraper_example.py` / `generate_monthly_report.py` / `generate_annual_report.py`：

| 排程腳本 | 對應底層邏輯 | 執行頻率建議 |
|---|---|---|
| `run_daily.py` | 呼叫所有 `scraper_example.py` 的來源，單一來源失敗不影響其他來源 | 每天 |
| `run_monthly.py` | 產生上個月的月報 | 每月 1 號 |
| `run_annual.py` | 產生去年的年度報告（含自動補齊邏輯） | 每年 1 月初 |

三個腳本都會：
- 把 log 寫進 `logs/{daily,monthly,annual}-{今天日期}.log`
- 用 process exit code 回報成敗（0 = 全部成功，非 0 = 有問題），方便排程系統判斷
- 失敗時呼叫 `notify.notify_failure()`：有設定 `SLACK_WEBHOOK_URL` 環境變數就發 Slack
  通知，沒設定就只寫進 log，不會讓排程腳本本身失敗

### 選項 A：cron（簡單，多數 Linux/Mac 都內建）

```bash
crontab -e
# 貼上 deploy/crontab.example 的內容，記得把路徑跟 API key 換成實際值
```

### 選項 B：systemd timer（更穩定，機器關機/休眠錯過的排程會自動補跑）

適合筆電這種不會 24 小時開機的環境——cron 錯過執行時間就是錯過了，
systemd timer 設定 `Persistent=true` 後，機器一開機會自動補跑漏掉的排程。

**一鍵安裝（建議）**：

```bash
cd projector_intel
sudo bash deploy/install.sh
```

這個腳本會自動抓專案實際路徑、用你目前的使用者（而不是 root）設定執行權限、
複製設定檔到 `/etc/systemd/system/`、建立 `/etc/projector-intel.env`、
啟用三個 timer。跑完之後只需要做一件事：

```bash
sudo nano /etc/projector-intel.env   # 填入實際的 GEMINI_API_KEY（SLACK_WEBHOOK_URL 可選）
```

**手動安裝**（如果你想清楚知道每一步在做什麼，或 `install.sh` 在你的環境跑不動）：

```bash
# 1. 複製 .service 和 .timer 檔案，並把佔位符換成實際值
sed -e "s|__PROJECT_DIR__|$(pwd)|g" -e "s|__RUN_USER__|$USER|g" \
    deploy/projector-intel-daily.service | sudo tee /etc/systemd/system/projector-intel-daily.service
sudo cp deploy/projector-intel-daily.timer /etc/systemd/system/
# 其餘 monthly / annual 依同樣方式處理

# 2. 設定環境變數檔案
sudo cp deploy/projector-intel.env.example /etc/projector-intel.env
sudo chmod 600 /etc/projector-intel.env
sudo nano /etc/projector-intel.env   # 填入實際的 GEMINI_API_KEY、SLACK_WEBHOOK_URL

# 3. 啟用並啟動三個 timer
sudo systemctl daemon-reload
sudo systemctl enable --now projector-intel-daily.timer
sudo systemctl enable --now projector-intel-monthly.timer
sudo systemctl enable --now projector-intel-annual.timer
```

**檢查排程狀態、看 log**：

```bash
systemctl list-timers | grep projector-intel      # 確認下次執行時間
journalctl -u projector-intel-daily.service -f    # 即時看爬蟲執行的 log
```

**移除排程**（如果之後想拆掉）：

```bash
sudo systemctl disable --now projector-intel-daily.timer projector-intel-monthly.timer projector-intel-annual.timer
sudo rm /etc/systemd/system/projector-intel-*.service /etc/systemd/system/projector-intel-*.timer
sudo systemctl daemon-reload
```

### 失敗通知設定（可選）

到 Slack 建立一個 Incoming Webhook（Slack App 設定裡搜尋 "Incoming Webhooks"），
拿到 webhook 網址後設定環境變數：

```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"
```

之後任何排程失敗都會發訊息到你設定的 Slack 頻道。沒有設定這個環境變數也完全
沒問題，排程照常運作，只是失敗時只能自己去看 log 檔案。

**提醒**：`run_daily.py` 目前的邏輯是「只要有一個來源失敗就發通知」，如果你的
來源清單裡常態性有一兩個不穩定（例如某網站三不五時連不上），這個通知可能會
有點吵。可以視情況調整 `run_daily.py` 裡的判斷邏輯，例如改成「連續 N 天失敗
才通知」，或針對特定來源設定白名單不觸發通知。

## 年報缺失月份的自動補齊邏輯

`generate_annual_report.py` 遇到某個月報檔案不存在時，會分兩種情況處理：

- **資料庫裡有該月的原始文章**（爬蟲當時有跑，只是忘了產月報）→ **自動補齊**：
  會自動呼叫 Gemini 用資料庫裡的資料補產生月報並存檔，年報照常使用。
- **資料庫裡連該月的原始文章都沒有**（爬蟲當時根本沒跑）→ **無法自動補齊**。
  我們串接的來源（RSS、列表頁）大多只提供「目前最新」的文章列表，沒有依日期
  查詢的歷史封存機制，爬蟲抓不到已經從列表頁洗掉的舊文章。這種情況年報仍會
  產出，但該月會被誠實標註「資料缺失」，不會杜撰內容。

**要避免這種缺口，最根本的做法是照上面的 cron 排程，讓爬蟲每天固定執行**——
資料一旦進了資料庫就不會消失，之後隨時都能回頭產生任何一個月的月報或年報。

## 用分頁回溯補齊去年的歷史資料（`backfill_last_year.py`）——目前狀態：無可用來源

`backfill_last_year.py` 提供了一套通用框架（逐頁抓取、檢查文章發布日期、
落在目標年份的才寫入資料庫、翻到日期早於目標年份就自動停止）。

**⚠️ 2026-07 實測結果：目前沒有已確認可用的分頁回溯來源。**
原本猜測 ZOL 投影機頻道的「更多」列表頁有網址分頁，但實測後發現該頁面
**沒有第二頁**——網址不會因為翻頁而改變，很可能是用 JavaScript「載入更多」
或滾動載入（AJAX）實作，背景資料透過額外的 API 請求取得，不是單純網址分頁。
用 `requests` 抓固定網址無法取得更多資料，除非能抓到背後實際呼叫的 API
網址（需要瀏覽器開發者工具的「網路」面板才能看到，不是目前工具鏈能做到的事）。

```bash
python backfill_last_year.py 2025     # 目前會印出「無可用來源」的說明並結束
```

`PAGINATED_SOURCES` 目前是空清單。如果之後想繼續嘗試找可行來源，驗證步驟是：

1. 打開目標網站的新聞列表頁，滑到底部找「上一頁/下一頁」或頁碼連結
2. 點下一頁，觀察網址列是否真的改變（如果沒變，就跟 ZOL 一樣是 AJAX，此路不通）
3. 若網址有變，把規則填進 `backfill_last_year.py` 的 `PAGINATED_SOURCES`
4. 先小範圍測試（例如只翻 3-5 頁），確認抓到的 `publish_date` 有正確落在
   預期年份區間，再放心讓它跑到 `MAX_PAGES` 上限

回溯完成後直接執行 `python generate_annual_report.py {year}` 即可——年報腳本
會自動偵測資料庫裡新補進的資料並產生對應月報。

在此之前，實際可行的路線是：

1. **直接用資料庫裡「現有」的資料**跑 `generate_annual_report.py`——缺的月份
   會誠實標「資料缺失」，不會硬湊內容。這是目前最務實的做法。
2. **讓 `scraper_example.py` 之後穩定每天執行**，讓資料持續累積，這樣明年、
   後年就不會再遇到今年這種歷史缺口問題。

## 各來源目前的驗證狀態（2026-07 確認，含後續補強驗證）

| 來源 | 狀態 | 說明 |
|---|---|---|
| 投影時代 (PJTime) | ✅ 可用（RSS） | `http://rss.pjtime.com/Projector.xml`，`description` 欄位直接是完整全文 |
| ZOL 投影機頻道 | ✅ 可用（HTML） | 列表頁 `list.html`（GBK 編碼）+ 文章頁 meta 標籤 |
| DigiTimes | ✅ 可用（RSS，需過濾） | `https://www.digitimes.com/rss/daily.xml` 是綜合性 daily feed，需用關鍵字過濾投影機相關內容 |
| TrendForce | ✅ 可用（RSS，需過濾） | Display 版 `feed/Display.html`、消費電子版 `feed/Consumer_electronics.html`，同樣需過濾 |
| IT之家 | ✅ 可用（RSS，需過濾） | 官方全站 RSS `https://www.ithome.com/rss/`，沒有投影機專屬頻道 RSS，需過濾 |
| ZNDS投影頻道 | ✅ 可用（HTML） | `news.znds.com` 有獨立投影頻道，無 RSS，首頁需過濾 |
| 洛圖科技 (RUNTO) | ✅ 可用（HTML，需過濾） | `runtotech.com` 是涵蓋多品類的「市場洞察」入口，無 RSS，需過濾。也可考慮改監控搜尋結果，因報告常被其他媒體轉載 |
| ProjectorCentral | ✅ 可用（HTML） | 首頁沒有公開 RSS 連結，改用新聞列表頁 `news-and-articles.cfm` |
| **ProjectorReviews** | ✅ 可用（HTML） | 維護良好的 `industry-news/` 列表頁，內容更新到 2026-07，另有獨立的 Reviews 評測區塊可額外整合 |
| Reddit r/projectors | ⚠️ 機制可信，但無法直接測試 | `.rss` 是 Reddit 平台標準功能，理論上任何 subreddit 都適用，但搜尋工具目前無法回傳 reddit.com 網址本身讓我 fetch 驗證，建議你自己手動確認一次 |
| AVS Forum | ❌ 目前無法自動抓取 | 對自動化請求直接回傳 402（疑似機器人偵測），需要改用瀏覽器自動化等其他策略 |
| **SID** | ⚠️ 確認不建議自動化 | 官網 `sid.org` 有新聞區塊，但內容多半是泛用顯示技術新聞、非投影機專屬，核心出版品（Journal of SID、Information Display）大多需要 Wiley 會員權限才能看全文，更新頻率也低（年會為主），維持人工定期查看即可 |
| 奧維雲網 (AVC) | ⚠️ 官網非新聞入口 | `avc-mr.com` 是 B2B 數據服務官網，沒有可瀏覽的報告文章列表；其投影機報告多半是透過 IT之家、ZNDS、新浪科技等媒體轉載曝光。建議改成監控「奧維雲網 投影」相關搜尋結果，而不是直接爬官網 |

**額外發現（非原始 12 個來源，可選加入）**：TechRadar 有專屬的投影機標籤 RSS
`https://www.techradar.com/sg/feeds/tag/projectors`，已確認是有效的 RSS/XML
資源，內容是投影機專屬的英文媒體報導，品質不錯，可視需要加進 `RSS_SOURCES`。

## 接上剩餘來源的步驟

1. 打開目標網站的文章列表頁，用瀏覽器開發者工具（右鍵→檢查）確認：
   - 每篇文章外層的容器 selector
   - 標題、連結、日期各自的 selector
2. 把這些 selector 填進 `scraper_example.py` 的 `HTML_LIST_SOURCES`（或
   `RSS_SOURCES`，如果該站有提供 RSS）。
3. 若文章詳細頁的正文 selector 與列表頁不同，記得同步調整 `_fetch_article_detail()`。
4. 先用單一來源小量測試（例如只跑 5 篇），確認 Gemini 回傳的 `category` /
   `importance` 是否合理，再放大到全量爬取。

## 網站與 AI 問答（RAG）架構說明

```
使用者瀏覽器
    │
    ├─ GET /               → static/index.html + style.css + app.js（純前端，無需 Node.js）
    ├─ GET /api/stats       → 首頁統計數字
    ├─ GET /api/articles    → 文章列表（來源/分類/年月/關鍵字過濾 + 分頁）
    ├─ GET /api/reports      → 列出可看的月報/年報
    ├─ GET /api/reports/{f}  → 取得指定報告 Markdown 內容
    └─ POST /api/ask        → RAG 問答
            │
            ├─ 1. embeddings.embed_query()：把問題轉成向量
            ├─ 2. embeddings.cosine_similarity_search()：
            │      在資料庫所有文章的 embedding 中找出最相關的 top-k 篇
            └─ 3. rag.answer_question()：
                   把檢索到的文章摘要當上下文，連同問題一起交給 Gemini 生成回答，
                   回傳「回答 + 引用來源清單」
```

**RAG 的檢索設計**：這個範例規模（預期幾百到幾千篇文章）用「把所有 embedding
讀進記憶體、numpy 算 cosine similarity」的做法，不需要額外的向量資料庫，延遲
很低、部署也簡單。文章數量成長到數萬篇以上時，才需要考慮換成專門的向量資料庫
（如 sqlite-vec、Chroma、pgvector）。

**為什麼回答會拒答/說資料不足**：`rag.py` 的 system prompt 明確要求模型只能
根據「檢索到的文章」回答，檢索不到相關內容時要老實說資料不足，不可以用模型
自己的知識庫補內容——這是為了避免使用者以為某個數字或說法「來自本站資料庫」，
但實際上是模型自己編的。

**embedding 何時產生**：正常流程下，`ingest.py` 處理完一篇文章、寫入摘要之後
會自動呼叫 `embeddings.embed_article()` 產生並儲存 embedding，不需要額外操作。
只有「導入 RAG 功能前就已經存在的舊文章」才需要手動跑一次
`python embeddings.py` 補齊。

**正式上線前的安全性提醒**：
- `api.py` 目前 CORS 設定是 `allow_origins=["*"]`（全開），正式環境請改成白名單
  網域，避免任意網站呼叫你的 API。
- `/api/reports/{filename}` 有做檔名格式白名單驗證（只接受 `YYYY-MM.md` 或
  `YYYY-annual.md` 格式），避免路徑穿越風險，新增報告類型時記得同步更新
  `REPORT_FILENAME_PATTERN`。
- `/api/ask` 目前沒有速率限制，公開上線前建議加上（例如用 slowapi 套件），
  避免被大量呼叫導致 Gemini API 費用暴增。

## 重要提醒

- **爬取頻率**：中文站點（洛圖科技、投影時代、AVC、ZNDS、ZOL）對高頻請求較敏感，
  範例中每篇間隔 2 秒，正式環境建議視情況拉長，並考慮加入隨機延遲。
- **版權**：`raw_content` 只存下來給 Gemini 做摘要用，資料庫裡的 `summary_zh`
  是模型改寫過的摘要，不是原文——月報與網站呈現時只使用改寫後的摘要 + 原文連結，
  不要把 `raw_content` 直接顯示在前端。
- **模型名稱會變動**：Gemini 模型迭代速度快，`gemini_client.py` 裡的
  `FLASH_MODEL` / `PRO_MODEL` 請定期到
  https://ai.google.dev/gemini-api/docs/models 確認目前可用的模型 ID。
- **去重**：`db.article_exists()` 是用 `url` 去重，若同一則新聞被多站轉載、
  網址不同但內容相同，目前的範例不會自動合併，如需要可以在月報 Prompt 裡
  額外要求模型「識別跨來源重複報導並合併」。
