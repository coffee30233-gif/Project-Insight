"""
export_static_data.py
在本機執行，把 projector_intel.db 裡的資料匯出成 static/data/ 底下的靜態檔案，
部署到 Vercel 時就不需要在 Serverless Function 裡即時查資料庫（除了 /api/ask 的
RAG 檢索仍然需要讀 projector_intel.db 本身，但那是唯讀，見 db.py 的說明）。

用法（在專案根目錄執行）：
    python export_static_data.py

會產生：
    data/stats.json           首頁統計數字（db.get_dashboard_stats()）
    data/articles.json        所有已處理文章（陣列，前端載進記憶體做篩選/分頁）
    data/reports-index.json   { "monthly": [...], "annual": [...] } 檔名清單
    data/reports/*.md         reports/ 目錄底下報告的原樣複製

（注意：路徑是專案根目錄下的 data/，不是 static/data/ —— index.html/app.js 都放在
根目錄，app.js 裡是用 fetch("data/stats.json") 這種相對路徑，對應的就是根目錄下的 data/）

跑完之後記得：
    git add data
    git commit -m "Update static data"
    git push
再重新部署（或等 Vercel 自動偵測到 push 後重新部署）。
"""
import json
import os
import re
import shutil

import config
import db

STATIC_DATA_DIR = "data"
REPORTS_SRC_DIR = "reports"
REPORTS_DST_DIR = os.path.join(STATIC_DATA_DIR, "reports")
ARCHIVE_DST_DIR = os.path.join(STATIC_DATA_DIR, "archive")


def export_stats():
    stats = db.get_dashboard_stats()
    # 原文連結健檢的統計（見 check_links.py），順便讓前端/自己能看到失效連結有幾條
    stats["link_check"] = db.get_link_check_summary()
    path = os.path.join(STATIC_DATA_DIR, "stats.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"已寫入 {path}（共 {stats['total_articles']} 篇文章、{stats['total_sources']} 個來源）")


def export_archive():
    """
    「原文快取 fallback」：只有 config.ENABLE_ORIGINAL_CACHE = True 時才會產出。
    把連結已失效（link_status = 'dead'）的文章原文內容寫成 data/archive/{id}.json，
    另外寫一份 data/archive/index.json 列出有存檔的文章 id，前端據此決定要不要顯示
    「查看本站存檔內容」按鈕。關閉時會把整個 data/archive/ 清掉，確保不會外流。
    """
    if not config.ENABLE_ORIGINAL_CACHE:
        if os.path.isdir(ARCHIVE_DST_DIR):
            shutil.rmtree(ARCHIVE_DST_DIR)
            print("原文快取未啟用（config.ENABLE_ORIGINAL_CACHE = False）—— 已清除 data/archive/")
        else:
            print("原文快取未啟用（config.ENABLE_ORIGINAL_CACHE = False）—— 略過")
        return

    os.makedirs(ARCHIVE_DST_DIR, exist_ok=True)
    dead = db.get_dead_articles_for_archive()
    kept_ids = set()
    for art in dead:
        kept_ids.add(art["id"])
        payload = {
            "id": art["id"],
            "source_name": art["source_name"],
            "original_title": art["original_title"],
            "title_zh": art["title_zh"],
            "url": art["url"],
            "link_final_url": art["link_final_url"],
            "publish_date": art["publish_date"],
            "raw_content": art["raw_content"],
        }
        with open(os.path.join(ARCHIVE_DST_DIR, f"{art['id']}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    # 清掉已經不再是 dead（來源網站又把文章補回去了）的舊存檔檔案
    for name in os.listdir(ARCHIVE_DST_DIR):
        if name == "index.json":
            continue
        stem = name[:-5] if name.endswith(".json") else None
        if stem and stem.isdigit() and int(stem) not in kept_ids:
            os.remove(os.path.join(ARCHIVE_DST_DIR, name))

    with open(os.path.join(ARCHIVE_DST_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(kept_ids), f)
    print(f"已寫入 {ARCHIVE_DST_DIR}/（{len(kept_ids)} 篇失效連結的原文存檔）")


def export_articles():
    """把「所有」已處理文章一次撈出來（不分頁），前端自己做篩選/分頁。
    文章量變得很大（例如上萬篇）之後，這個做法會讓 articles.json 變得很肥，
    到時候可以考慮改成前端分批載入，但目前規模這樣做最簡單、也最快。"""
    all_items = []
    page = 1
    page_size = 500
    while True:
        result = db.list_articles(page=page, page_size=page_size)
        all_items.extend(result["items"])
        if len(all_items) >= result["total"]:
            break
        page += 1

    path = os.path.join(STATIC_DATA_DIR, "articles.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"已寫入 {path}（共 {len(all_items)} 篇文章）")


def export_reports_index_and_files():
    """
    複製 reports/ 底下的 .md（與同檔名的 .pptx，如果存在）到 data/reports/，
    並產生 reports-index.json。每筆報告是 {"file": "2025-annual.md", "hasSlides": true,
    "hasPdf": true} 這種物件，hasSlides／hasPdf 代表有沒有對應的 .pptx／.pdf 可以下載。

    依檔名判斷報告類型：
      - {年}-annual.md     → 年度報告
      - {年}-h1.md / -h2.md → 半年報（上半年／下半年）
      - {年}-W{週}.md       → 週報
      - {年}-{月}.md        → 月報
    """
    os.makedirs(REPORTS_DST_DIR, exist_ok=True)

    monthly, weekly, semiannual, annual = [], [], [], []
    if os.path.isdir(REPORTS_SRC_DIR):
        for filename in os.listdir(REPORTS_SRC_DIR):
            if not filename.endswith(".md"):
                continue
            shutil.copyfile(
                os.path.join(REPORTS_SRC_DIR, filename),
                os.path.join(REPORTS_DST_DIR, filename),
            )

            pptx_filename = filename[:-3] + ".pptx"
            pptx_src = os.path.join(REPORTS_SRC_DIR, pptx_filename)
            has_slides = os.path.isfile(pptx_src)
            if has_slides:
                shutil.copyfile(pptx_src, os.path.join(REPORTS_DST_DIR, pptx_filename))

            pdf_filename = filename[:-3] + ".pdf"
            pdf_src = os.path.join(REPORTS_SRC_DIR, pdf_filename)
            has_pdf = os.path.isfile(pdf_src)
            if has_pdf:
                shutil.copyfile(pdf_src, os.path.join(REPORTS_DST_DIR, pdf_filename))

            entry = {"file": filename, "hasSlides": has_slides, "hasPdf": has_pdf}
            if filename.endswith("-annual.md"):
                annual.append(entry)
            elif filename.endswith("-h1.md") or filename.endswith("-h2.md"):
                semiannual.append(entry)
            elif re.match(r"^\d{4}-W\d{2}\.md$", filename):
                weekly.append(entry)
            else:
                monthly.append(entry)

    monthly.sort(key=lambda e: e["file"], reverse=True)
    weekly.sort(key=lambda e: e["file"], reverse=True)
    semiannual.sort(key=lambda e: e["file"], reverse=True)
    annual.sort(key=lambda e: e["file"], reverse=True)

    path = os.path.join(STATIC_DATA_DIR, "reports-index.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"weekly": weekly, "monthly": monthly, "semiannual": semiannual, "annual": annual},
            f, ensure_ascii=False, indent=2,
        )

    all_entries = weekly + monthly + semiannual + annual
    slides_count = sum(1 for e in all_entries if e["hasSlides"])
    pdf_count = sum(1 for e in all_entries if e["hasPdf"])
    print(
        f"已寫入 {path}（週報 {len(weekly)} 份、月報 {len(monthly)} 份、半年報 {len(semiannual)} 份、"
        f"年報 {len(annual)} 份，其中 {slides_count} 份有附簡報、{pdf_count} 份有附 PDF，"
        f"檔案已複製到 {REPORTS_DST_DIR}）"
    )


def main():
    os.makedirs(STATIC_DATA_DIR, exist_ok=True)
    db.init_db()
    export_stats()
    export_articles()
    export_reports_index_and_files()
    export_archive()
    print("\n完成。接下來：git add data && git commit && git push，再重新部署 Vercel。")


if __name__ == "__main__":
    main()
