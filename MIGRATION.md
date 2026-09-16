# 把整條爬蟲/報告管線搬離這台機器 — 遷移手冊

> 目標：把 `/opt/projector-insight` 這整套（爬蟲、AI 處理、資料庫、報告產生、寄信）
> 搬到公司自己的伺服器上，由公司的 n8n 觸發。**Vercel 上的網站本身不用動**——
> 它只讀 GitHub repo 裡的 `data/`，跟運算跑在哪台機器無關（見 `PROJECT_OVERVIEW.md`
> 第 9 節）。這份文件只處理「運算 + 排程」怎麼從這台 Hetzner 機器換到別的地方。

## 0. 搬過去之前，先決定一件事

**目標環境是什麼？** 這會決定下面怎麼做：

- **(A) 公司有一台可以裝東西的 Linux 伺服器/VM**（最接近現況，改動最小）→ 照本文件
  第 1–4 節做，架構跟現在幾乎一樣，只是換一台機器。
- **(B) 公司沒有專屬伺服器，只想用 n8n + 現成雲端資源**（沒有長駐機器）→ 這套
  「爬蟲跑 20 分鐘、寫檔案、git push」的做法不適合純 n8n 雲端方案，建議改用
  **GitHub Actions 排程 workflow**（免費額度通常夠用，每天 checkout repo 跑一次）。
  這是完全不同的實作方式，需要另外規劃，這份文件不涵蓋，需要的話再另外討論。

以下預設是情境 (A)。

## 1. 需要從這台機器帶走的東西

| 項目 | 為什麼需要 | 怎麼帶走 |
|---|---|---|
| **整個 repo** | 程式碼、`data/`、報告 | 新機器直接 `git clone`，不用從這裡複製 |
| **`projector_intel.db`** | **唯一「不在 git 裡」的狀態**——累積至今的原始文章、AI 處理結果、去重紀錄、embedding。這是遷移裡最重要、也是唯一沒辦法用 git 重建的東西 | `scp` 直接從這台機器複製過去（見第 3 節），或跟我說一聲我幫你在這裡打包成檔案傳給你 |
| **`.env` 的機密值** | GEMINI_API_KEY、SMTP 帳密等 | **不要複製這個檔案本身過去**（避免明碼在兩台機器間傳來傳去）。用 `.env.example`（已加進這次的改動）當範本，在新機器上重新填值 |
| **git 推送權限** | 每天要 `git push` 回 GitHub | 這台機器目前用 HTTPS + Personal Access Token（`~/.git-credentials`），新機器要重新設定一組（見第 2 節），**不要**把這台的 token 複製過去——新開一組、之後可以單獨撤銷 |

## 2. 新機器上的環境設定

```bash
# 1. 基本套件（Ubuntu/Debian 系列；其他發行版指令對應調整）
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip git

# 2. clone repo
cd /opt   # 或你們習慣的路徑；下面都假設還是 /opt/projector-insight
git clone https://github.com/coffee30233-gif/Project-Insight.git projector-insight
cd projector-insight

# 3. Python 環境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt   # requirements-dev 是測試用，非必要

# 4. git 推送權限（HTTPS + token，跟這台機器同做法）
#    去 GitHub → Settings → Developer settings → Personal access tokens
#    建一組「只對這個 repo、只要 Contents 讀寫」的 fine-grained token
git config --global credential.helper store
git config --global user.email "你們的自動化用信箱"
git config --global user.name "projector-insight-bot"
# 第一次 git push 時輸入帳號 + 剛剛那組 token，之後會存進 ~/.git-credentials

# 5. .env
cp .env.example .env
# 編輯 .env，把 GEMINI_API_KEY / SMTP_* 等值填進去（跟這台機器目前的值一樣即可，
# 或趁這次機會換成公司信箱——見下方寄件人那段）

# 6. 資料庫（見第 3 節先在舊機器打包）
#    把拿到的 projector_intel.db 放到新的 /opt/projector-insight/projector_intel.db

# 7. 跑一次驗證
python -c "import db; db.init_db(); print('文章數:', __import__('sqlite3').connect('projector_intel.db').execute('SELECT COUNT(*) FROM articles').fetchone()[0])"
python export_static_data.py   # 應該匯出跟這台機器一樣的篇數，data/ 內容應該幾乎不變（git diff 應該很小）
pytest                         # 應該 35 passed
```

## 3. 打包資料庫

在**這台**機器上執行（我可以直接幫你做）：

```bash
cd /opt/projector-insight
tar -czf projector_intel.db.tar.gz projector_intel.db
```

然後：
- 兩台機器之間可以互通的話：`scp projector_intel.db.tar.gz <新機器>:/opt/projector-insight/`
- 不行的話：跟我說一聲，我把這個檔案送給你，你再傳到新機器。

**注意時機**：資料庫每天早上 08:30（台北）之後會被更新一次。建議挑一個當天更新
**之後**的時間點打包，並在切換排程那天，新舊兩台不要同一天都各自更新（見第 5 節）。

## 4. 排程：公司 n8n 怎麼接

新機器上跑好第 2 節的設定後，公司 n8n 這邊：

1. 用**這次一起產出的 4 個 workflow JSON**（`投影機情報站-每日更新.json` 等）
   Import from File 匯入。
2. 建一個新的 **SSH credential**：host 是新機器的位址、user 看你們新機器的帳號設定，
   private key 用公司 n8n 這邊產生的一組（把**公鑰**加進新機器的
   `~/.ssh/authorized_keys`）。
3. 四個 workflow 的 SSH 節點都要重新指到這組新 credential（匯入後舊的
   credential 參照會失效，正常現象）。
4. 四個 workflow 裡的指令路徑 `/opt/projector-insight/xxx.sh` 要跟新機器上
   repo 實際的路徑一致（如果新機器路徑不是 `/opt/projector-insight`，記得改）。
5. 排程時區確認是 **Asia/Taipei**（cron 表達式本身沒有時區資訊，是由 n8n 的
   `GENERIC_TIMEZONE` 環境變數決定——公司 n8n 要設成台北時間，不然全部會跑錯時間）。

## 5. 切換當天的檢查清單

1. 新機器手動跑一次 `bash daily_update.sh`，確認 log 顯示 `[FAILED=0]`、
   git push 成功、跟這台機器目前的 commit 是同一條分支往前推進（不是分岔）。
2. 公司 n8n 的 4 個 workflow **先啟用**，這台機器（本地 n8n）的**先不要關**，
   並行觀察 1–2 天。
3. 確認沒有「同一天出現兩筆 Daily update commit」（代表兩邊都在跑）——如果
   發生，先把其中一邊的 workflow 停用，只留一邊。
4. 穩定後，把這台機器（本地 n8n）的 4 個 workflow 停用（不刪，留著當備援）。
   跟我說一聲我可以直接在這裡幫你關。
5. 這台機器的 `projector_intel.db`、`.env`、`logs/` 可以留著當備援一陣子，
   確認新機器穩定運作幾週後再考慮清掉。

## 6. 遷移後這台機器還留著什麼

- Vercel 的網站部署**完全不受影響**——它只認 GitHub repo，不認是哪台機器 push 的。
- 這台機器上其他無關的服務（n8n 跑的其他 workflow、alphaforge 等）不受這次遷移影響。
- 如果之後想把這台機器整個關掉，要先確認上面那些其他服務也都遷移或不需要了——
  這不在本次遷移範圍內。
