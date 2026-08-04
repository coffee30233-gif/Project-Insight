"""
backfill_relevance.py
針對「相關性分類」功能上線之前就已經存在的舊文章（relevance 欄位是 NULL），
用已經存在的標題/摘要補做一次相關性判斷，不用重新讀取原文，比較省 Gemini 額度。

用法：
    python backfill_relevance.py

跑完會印出各等級的統計數字，並列出所有被判定為 Unrelated 的文章標題，
方便你確認判斷結果合理（如果覺得誤判，可以之後再手動修正，或調整
gemini_client.py 的 SYSTEM_PROMPT_F 判斷標準後重跑）。

注意：這支腳本只處理 relevance IS NULL 的文章，不會重複處理已經分類過的，
可以放心重複執行（例如上次跑到一半額度用完，之後直接重跑就會接著跑剩下的）。
"""
import time

import db
import gemini_client


def main():
    db.init_db()
    pending = db.get_articles_pending_relevance()
    print(f"待分類文章數：{len(pending)}")

    if not pending:
        print("沒有需要回溯分類的文章，全部都已經有相關性標記了。")
        return

    counts = {"Direct": 0, "Indirect": 0, "Maybe": 0, "Unrelated": 0}
    unrelated_titles = []
    failed = 0

    for i, article in enumerate(pending, start=1):
        title = article["title_zh"] or ""
        summary = article["summary_zh"] or ""
        if not title and not summary:
            print(f"[{i}/{len(pending)}] 標題與摘要都是空的，跳過：id={article['id']}")
            continue

        try:
            result = gemini_client.classify_relevance(title, summary)
        except Exception as e:
            print(f"[{i}/{len(pending)}] 分類失敗，跳過（下次重跑會再試一次）：{title[:30]}｜{e}")
            failed += 1
            continue

        relevance = result["relevance"]
        reason = result["reason"]
        db.update_relevance(article["id"], relevance, reason)
        counts[relevance] += 1

        print(f"[{i}/{len(pending)}] [{relevance}] {title[:40]}（{reason}）")
        if relevance == "Unrelated":
            unrelated_titles.append(title)

        time.sleep(0.5)  # 稍微間隔一下，減輕額度壓力

    print("\n===== 回溯分類完成 =====")
    print(f"Direct（直接相關）：{counts['Direct']} 篇")
    print(f"Indirect（間接相關）：{counts['Indirect']} 篇")
    print(f"Maybe（可能相關）：{counts['Maybe']} 篇")
    print(f"Unrelated（無關）：{counts['Unrelated']} 篇")
    if failed:
        print(f"分類失敗（下次重跑會自動重試）：{failed} 篇")

    if unrelated_titles:
        print("\n被判定為「無關」、之後不會出現在網站/報告的文章：")
        for t in unrelated_titles:
            print(f"  - {t}")
        print("\n如果覺得裡面有誤判，之後可以手動修正，或調整判斷標準後重跑 backfill_relevance.py")

    print("\n完成後記得執行：python export_static_data.py，再 git add/commit/push 讓網站更新。")


if __name__ == "__main__":
    main()
