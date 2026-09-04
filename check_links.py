"""
check_links.py
定期（預設每季，由 daily_update.sh 在 1/4/7/10 月 1 號觸發）逐篇檢查
「查看原文」連結是否還活著，把結果寫回 articles.link_status，讓失效連結在使用者
點到之前就先被標記出來。

用法（在專案根目錄、venv 內執行）：
    python check_links.py                # 全部重檢
    python check_links.py --stale-days 80  # 只檢查沒檢查過或 80 天前檢查過的
    python check_links.py --limit 100     # 最多檢查 100 篇（分批跑用）

link_status 的值：
    ok      連結正常（HTTP 2xx）
    dead    來源網站已移除（HTTP 404 / 410）—— 前端會顯示「原文連結可能已失效」
    blocked 被來源網站的防爬蟲擋下（401 / 403 / 429）—— 當成正常，不提示使用者
    error   連線逾時、DNS 失敗、5xx 等暫時性問題 —— 下次會自動重檢
跑完會把資料庫變更留在本機，交給 daily_update.sh 一起 git commit / push。
"""

import argparse
import sys
import time

import requests

import db
import gemini_client  # 只借用 now_iso()，統一時間字串格式

# User-Agent 沿用 scraper_example.py 的設定：不自報 bot 身分，降低被來源網站
# 針對性封鎖的機率（那會造成大量 false positive）。
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    # 有些 CDN 對「只要 HTML」的請求比較寬容
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DEAD_CODES = {404, 410}
BLOCKED_CODES = {401, 403, 429}
HEAD_REJECT_CODES = {403, 405, 501}  # 這些多半代表「這站不吃 HEAD」，改用 GET 再試一次

REQUEST_TIMEOUT = 20   # 秒
SLEEP_BETWEEN = 1.0    # 每篇之間停一下，別把來源網站打太兇
RETRY_ON_ERROR = 1     # 暫時性錯誤重試次數


def _classify(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "ok"
    if status_code in DEAD_CODES:
        return "dead"
    if status_code in BLOCKED_CODES:
        return "blocked"
    if 300 <= status_code < 400:
        # requests 預設會跟隨轉址；還停在 3xx 通常是轉址迴圈或缺 Location
        return "error"
    if status_code >= 500:
        return "error"
    # 其餘 4xx（400、451…）：不確定，保守當暫時性錯誤，下次再看
    return "error"


def check_one(url: str) -> tuple[str, str | None]:
    """回傳 (status, final_url)。final_url 只有在成功拿到回應時才有值。"""
    last_exc: Exception | None = None
    for attempt in range(RETRY_ON_ERROR + 1):
        try:
            resp = requests.head(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                                 allow_redirects=True)
            if resp.status_code in HEAD_REJECT_CODES or resp.status_code == 405:
                resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT,
                                    allow_redirects=True, stream=True)
                resp.close()
            return _classify(resp.status_code), resp.url
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < RETRY_ON_ERROR:
                time.sleep(3)

    print(f"    ! 連線失敗：{type(last_exc).__name__}: {last_exc}")
    return "error", None


def main():
    parser = argparse.ArgumentParser(description="檢查文章原文連結是否失效")
    parser.add_argument("--stale-days", type=int, default=None,
                        help="只檢查沒檢查過或超過 N 天前檢查過的（預設：全部重檢）")
    parser.add_argument("--limit", type=int, default=None,
                        help="最多檢查幾篇")
    args = parser.parse_args()

    db.init_db()  # 確保 link_status 等欄位已經 migrate 出來
    targets = db.get_articles_for_link_check(stale_days=args.stale_days, limit=args.limit)
    total = len(targets)
    print(f"待檢查 {total} 篇文章的原文連結"
          + (f"（stale-days={args.stale_days}）" if args.stale_days else "（全部重檢）"))

    counts: dict[str, int] = {}
    dead_list: list[tuple[int, str]] = []
    changed_list: list[tuple[int, str, str]] = []

    for i, art in enumerate(targets, 1):
        url = art["url"]
        prev = art["link_status"]
        status, final_url = check_one(url)
        counts[status] = counts.get(status, 0) + 1

        stored_final = final_url if (final_url and final_url != url) else None
        db.update_link_status(art["id"], status, gemini_client.now_iso(), stored_final)

        marker = "→ " + status
        if prev and prev != status:
            marker += f"（原本 {prev}）"
            changed_list.append((art["id"], prev, status))
        if status == "dead":
            dead_list.append((art["id"], url))
        if stored_final:
            marker += f"  [轉址到 {stored_final}]"
        print(f"[{i}/{total}] #{art['id']} {marker}  {url}")

        if i < total:
            time.sleep(SLEEP_BETWEEN)

    print("\n===== 檢查完成 =====")
    for status in ("ok", "blocked", "error", "dead"):
        if status in counts:
            print(f"  {status:8s}: {counts[status]}")

    if changed_list:
        print(f"\n狀態有變動的 {len(changed_list)} 篇：")
        for aid, prev, now in changed_list:
            print(f"  #{aid}: {prev} → {now}")

    if dead_list:
        print(f"\n⚠ 判定失效（dead）的 {len(dead_list)} 篇原文連結：")
        for aid, url in dead_list:
            print(f"  #{aid}  {url}")
    else:
        print("\n沒有新的失效連結。")

    summary = db.get_link_check_summary()
    print(f"\n資料庫目前累計：{summary['by_status']}")


if __name__ == "__main__":
    sys.exit(main())
