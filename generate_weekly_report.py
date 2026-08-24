"""
generate_weekly_report.py
產生過去 7 天（週一到週日）的投影機產業週報，讀取資料庫裡這段期間內、
已完成 Gemini 處理的文章彙整而成。

視覺元素的選擇邏輯（避免硬塞一張沒有意義的圖）：
1. 如果本週文章數量夠多、分類也有變化（>=3 篇、>=2 種分類），才畫「本週文章分類統計」
   長條圖——資料點太少的長條圖無法傳達任何洞察，直接跳過。
2. 沒有畫圖表的情況下，改抓本週「重要度最高」且有原始配圖（image_url）的文章，
   下載那張圖片當作視覺點綴。
3. 兩者都沒有（資料太少、也沒有文章配圖）就完全不附圖，純文字呈現。

用法：
    python generate_weekly_report.py              # 預設抓「上一個完整的週一到週日」
    python generate_weekly_report.py 2026-07-20    # 抓指定週一所在那一週（週一到週日）

產出檔案：
    reports/{年}-W{週數}.md          週報內文
    reports/{年}-W{週數}-chart.png   分類統計圖（只有資料夠豐富時才會產生）
    reports/{年}-W{週數}-image.*     文章原始配圖（只有沒畫圖表、且有配圖可用時才會產生）
"""
import os
import sys
from collections import Counter
from datetime import date, timedelta

import requests

import db
import gemini_client

REPORTS_DIR = "reports"

# 跟網站一致的配色
ROOM = "#14161A"
SCREEN = "#F5F3EC"
MIST = "#9096A1"
LENS = "#4C7EFF"
LAMP = "#FFB454"

CATEGORY_COLORS = {
    "市場數據": LENS,
    "新品發布": LAMP,
    "技術動態": "#8B7FD6",
    "供應鏈": "#5FB89C",
}

# 圖表最少要有這麼多篇文章、且橫跨這麼多種分類，才算「有意義」，否則不畫
MIN_ARTICLES_FOR_CHART = 3
MIN_CATEGORIES_FOR_CHART = 2


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _is_chart_meaningful(articles: list[dict]) -> bool:
    if len(articles) < MIN_ARTICLES_FOR_CHART:
        return False
    categories = {a["category"] for a in articles if a.get("category")}
    return len(categories) >= MIN_CATEGORIES_FOR_CHART


def _draw_category_chart(articles: list[dict], out_path: str) -> bool:
    """畫本週文章分類統計長條圖，回傳是否有成功產生。"""
    import matplotlib
    matplotlib.use("Agg")  # 不需要顯示視窗，純輸出檔案
    import matplotlib.pyplot as plt

    # 盡量找一個裝置上有的中文字型，找不到就讓 matplotlib 用預設（英文/數字仍會正常顯示）
    for font_name in ["WenQuanYi Zen Hei", "Microsoft JhengHei", "Microsoft YaHei", "PingFang TC",
                       "Noto Sans CJK TC", "SimHei", "Arial Unicode MS"]:
        if font_name in {f.name for f in matplotlib.font_manager.fontManager.ttflist}:
            plt.rcParams["font.sans-serif"] = [font_name]
            break
    plt.rcParams["axes.unicode_minus"] = False

    counts = Counter(a["category"] for a in articles)
    categories = list(counts.keys())
    values = [counts[c] for c in categories]
    colors = [CATEGORY_COLORS.get(c, MIST) for c in categories]

    fig, ax = plt.subplots(figsize=(7, 3.2), dpi=150)
    fig.patch.set_facecolor(ROOM)
    ax.set_facecolor(ROOM)

    bars = ax.bar(categories, values, color=colors, width=0.55)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                str(v), ha="center", va="bottom", color=SCREEN, fontsize=11)

    ax.set_title("本週文章分類統計", color=SCREEN, fontsize=13, pad=12)
    ax.tick_params(colors=MIST, labelsize=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color("#2A2E38")
    ax.set_yticks([])

    fig.tight_layout()
    fig.savefig(out_path, facecolor=ROOM)
    plt.close(fig)
    return True


def _download_article_image(articles: list[dict], out_path_base: str) -> str | None:
    """挑本週重要度最高、且有 image_url 的文章，下載它的圖片。成功回傳實際檔案路徑，失敗回傳 None。"""
    candidates = [a for a in articles if a.get("image_url")]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a.get("importance") or 0, reverse=True)

    for article in candidates:
        image_url = article["image_url"]
        try:
            resp = requests.get(
                image_url, timeout=10,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ProjectorMarketBot/1.0)"},
            )
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            ext = ".jpg"
            if "png" in content_type:
                ext = ".png"
            elif "webp" in content_type:
                ext = ".webp"
            elif "gif" in content_type:
                ext = ".gif"

            out_path = out_path_base + ext
            with open(out_path, "wb") as f:
                f.write(resp.content)
            print(f"已下載文章配圖：{image_url} → {out_path}（來自：{article['title_zh']}）")
            return out_path
        except Exception as e:
            print(f"下載圖片失敗（{image_url}）：{e}，改試下一篇候選文章")
            continue

    return None


def main():
    if len(sys.argv) == 2:
        anchor = date.fromisoformat(sys.argv[1])
    else:
        # 預設抓「上一個完整的週一到週日」：今天所在週的週一，往前推 7 天
        anchor = _monday_of(date.today()) - timedelta(days=7)

    start = _monday_of(anchor)
    end = start + timedelta(days=6)
    year, week, _ = start.isocalendar()

    print(f"週報範圍：{start.isoformat()} ～ {end.isoformat()}（{year} 年第 {week} 週）")

    articles = db.get_articles_by_date_range(start.isoformat(), end.isoformat())
    print(f"讀到 {len(articles)} 篇文章")

    if not articles:
        print("這一週完全沒有文章資料，週報會產出但內容會標註「本週無資料」。")

    report_md = gemini_client.generate_weekly_report(start.isoformat(), end.isoformat(), articles)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    base_name = f"{year}-W{week:02d}"
    out_path = os.path.join(REPORTS_DIR, f"{base_name}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_md)
    print(f"週報已產出：{out_path}")

    # 先清掉舊圖，避免這次沒產生新圖時，PDF 誤用到上次殘留的舊檔案
    chart_path = os.path.join(REPORTS_DIR, f"{base_name}-chart.png")
    image_path_base = os.path.join(REPORTS_DIR, f"{base_name}-image")
    if os.path.exists(chart_path):
        os.remove(chart_path)
    for ext in (".jpg", ".png", ".webp", ".gif"):
        p = image_path_base + ext
        if os.path.exists(p):
            os.remove(p)

    if _is_chart_meaningful(articles):
        _draw_category_chart(articles, chart_path)
        print(f"分類統計圖已產出：{chart_path}（資料量足夠，適合畫統計圖）")
    else:
        print(f"本週文章數量不多或分類太單一（未達 {MIN_ARTICLES_FOR_CHART} 篇/"
              f"{MIN_CATEGORIES_FOR_CHART} 種分類），統計圖沒有意義，改找文章配圖")
        image_path = _download_article_image(articles, image_path_base)
        if not image_path:
            print("這週沒有文章配圖可用，週報維持純文字，不附圖")

    return out_path


if __name__ == "__main__":
    main()
