"""
generate_weekly_report.py
產生過去 7 天（週一到週日）的投影機產業週報，讀取資料庫裡這段期間內、
已完成 Gemini 處理的文章彙整而成，並額外畫一張「本週文章分類統計」長條圖
（跟網站配色一致），供 PDF／簡報使用，讓週報不會只有純文字看起來死板。

用法：
    python generate_weekly_report.py              # 預設抓「上一個完整的週一到週日」
    python generate_weekly_report.py 2026-07-20    # 抓指定週一所在那一週（週一到週日）

產出檔案：
    reports/{年}-W{週數}.md          週報內文
    reports/{年}-W{週數}-chart.png   分類統計圖（文章數為 0 時不會產生）
"""
import os
import sys
from collections import Counter
from datetime import date, timedelta

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


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _draw_category_chart(articles: list[dict], out_path: str) -> bool:
    """畫本週文章分類統計長條圖，回傳是否有成功產生（沒有文章就不畫）。"""
    if not articles:
        return False

    import matplotlib
    matplotlib.use("Agg")  # 不需要顯示視窗，純輸出檔案
    import matplotlib.pyplot as plt

    # 盡量找一個裝置上有的中文字型，找不到就讓 matplotlib 用預設（英文/數字仍會正常顯示）
    for font_name in ["Microsoft JhengHei", "Microsoft YaHei", "PingFang TC",
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

    chart_path = os.path.join(REPORTS_DIR, f"{base_name}-chart.png")
    if _draw_category_chart(articles, chart_path):
        print(f"分類統計圖已產出：{chart_path}")
    else:
        if os.path.exists(chart_path):
            os.remove(chart_path)  # 這週沒資料，清掉舊圖避免混用到上週的圖
        print("這週沒有文章資料，略過畫圖")

    return out_path


if __name__ == "__main__":
    main()
