"""
generate_weekly_pdf.py
把週報 Markdown（含 generate_weekly_report.py 產生的分類統計圖）排版成一份
正式的 PDF 文件，用於 email 附件與網站下載連結。

用法：
    python generate_weekly_pdf.py reports/2026-W31.md
    python generate_weekly_pdf.py                      # 自動抓 reports/ 底下最新的週報

產出：跟 .md 同檔名的 .pdf（例如 reports/2026-W31.pdf）

中文字型：優先使用 Windows 內建的「微軟正黑體」（msjh.ttc），這是標準 TrueType
格式，reportlab 可以直接內嵌使用。如果你不是在 Windows 上執行，或字型路徑不同，
請把下面 FONT_CANDIDATES 加上你系統裡實際的中文字型路徑（.ttf 或 .ttc 皆可，
但reportlab 不支援 OpenType/CFF 外框的字型，例如某些 Noto 字型的 .ttc 檔）。
"""
import glob
import os
import re
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

REPORTS_DIR = "reports"

# 跟網站一致的配色（同一組色票也用在 generate_weekly_report.py 的圖表上）
ROOM = HexColor("#14161A")   # 頁面底色（深）
SCREEN = HexColor("#F5F3EC")  # 主要文字（米白）
MIST = HexColor("#9096A1")    # 次要／輔助文字（灰）
LENS = HexColor("#4C7EFF")    # 強調色（藍，用於段落標題）
LAMP = HexColor("#FFB454")    # 強調色（琥珀，用於項目符號、標題重點）
DIVIDER = HexColor("#2A2E38")  # 分隔線（跟圖表座標軸同一色，深色底上剛好夠看又不搶戲）

FONT_CANDIDATES = [
    # Windows：微軟正黑體（優先，繁體）／新細明體／標楷體
    (r"C:\Windows\Fonts\msjh.ttc", 0),
    (r"C:\Windows\Fonts\mingliu.ttc", 0),
    (r"C:\Windows\Fonts\kaiu.ttf", 0),
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", 0),
    # Linux（如果剛好有裝 TrueType 版的思源黑體之類）
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]

FONT_NAME = "CJKFont"
_font_registered = False


def _register_font():
    """依序嘗試候選字型，成功一個就註冊起來給整份 PDF 用；都失敗則退回內建 CID 字型
    （仍可顯示中文，但文字複製/搜尋可能不準確，屬於降級但堪用的最後防線）。"""
    global _font_registered
    if _font_registered:
        return

    for path, index in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(FONT_NAME, path, subfontIndex=index))
                _font_registered = True
                print(f"使用字型：{path}")
                return
            except Exception as e:
                print(f"字型 {path} 載入失敗（{e}），改試下一個候選")
                continue

    print("找不到任何候選 TrueType 中文字型，改用 reportlab 內建 CID 字型"
          "（可能影響 PDF 文字複製/搜尋，但畫面顯示應該還是正常的）")
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
    globals()["FONT_NAME"] = "MSung-Light"
    _font_registered = True


def _paint_background(canvas, doc):
    """每一頁在排版內容畫上去之前，先把整頁填成深色底，跟網站/圖表風格一致。"""
    canvas.saveState()
    canvas.setFillColor(ROOM)
    canvas.rect(0, 0, doc.pagesize[0], doc.pagesize[1], stroke=0, fill=1)
    canvas.restoreState()


def _styles():
    return {
        "title": ParagraphStyle("title", fontName=FONT_NAME, fontSize=20, leading=27,
                                 textColor=SCREEN, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName=FONT_NAME, fontSize=10, leading=14,
                                    textColor=LAMP, spaceAfter=18),
        "h2": ParagraphStyle("h2", fontName=FONT_NAME, fontSize=14, leading=20,
                              textColor=LENS, spaceBefore=16, spaceAfter=8),
        "body": ParagraphStyle("body", fontName=FONT_NAME, fontSize=10.5, leading=17,
                                textColor=SCREEN, alignment=TA_LEFT),
        "bullet": ParagraphStyle("bullet", fontName=FONT_NAME, fontSize=10.5, leading=16,
                                  textColor=SCREEN, alignment=TA_LEFT,
                                  leftIndent=14, bulletIndent=0, spaceAfter=6),
        "footer": ParagraphStyle("footer", fontName=FONT_NAME, fontSize=8, leading=12,
                                  textColor=MIST),
    }


def _inline_to_html(text: str) -> str:
    """把 markdown 的 **粗體** 轉成 reportlab Paragraph 認得的 <b> 標籤。"""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def find_latest_weekly_report():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "*-W??.md")), reverse=True)
    return files[0] if files else None


def build_pdf(md_path: str, out_path: str):
    _register_font()
    styles = _styles()

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()

    title = ""
    story = []
    current_bullets = []

    def flush_bullets():
        if current_bullets:
            for b in current_bullets:
                bullet_html = (
                    '<font color="#FFB454">&#9679;</font>'
                    f'&nbsp;&nbsp;{_inline_to_html(b)}'
                )
                story.append(Paragraph(bullet_html, styles["bullet"]))
            story.append(Spacer(1, 4))
            current_bullets.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# ") and not title:
            title = line[2:].strip()
            story.append(Paragraph(title, styles["title"]))
            story.append(Paragraph("投影機情報站 · 週報", styles["subtitle"]))
            story.append(HRFlowable(width="100%", thickness=0.6, color=DIVIDER, spaceAfter=6))
            continue
        if line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(line[3:].strip(), styles["h2"]))
            continue
        if line.startswith(("- ", "* ")):
            current_bullets.append(line[2:].strip())
            continue
        # 一般段落文字（例如「本週重點」下面常常是一段話，不是條列）
        flush_bullets()
        story.append(Paragraph(_inline_to_html(line), styles["body"]))
        story.append(Spacer(1, 6))

    flush_bullets()

    # 內嵌分類統計圖（如果有的話）——圖表本身就是深色底，跟頁面背景無縫接軌
    chart_path = os.path.splitext(md_path)[0] + "-chart.png"
    if os.path.exists(chart_path):
        story.append(Spacer(1, 8))
        story.append(Image(chart_path, width=15.5 * cm, height=15.5 * cm * (3.2 / 7)))
        story.append(Spacer(1, 8))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.6, color=DIVIDER, spaceAfter=6))
    story.append(Paragraph(
        "本週報由投影機情報站自動彙整產生。完整歷史報告與 AI 問答，"
        "請至網站查看。", styles["footer"]))

    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm,
        title=title or "投影機情報站週報",
    )
    doc.build(story, onFirstPage=_paint_background, onLaterPages=_paint_background)


def main():
    md_path = sys.argv[1] if len(sys.argv) > 1 else find_latest_weekly_report()
    if not md_path or not os.path.exists(md_path):
        print("找不到週報 .md 檔案，請先執行 python generate_weekly_report.py")
        sys.exit(1)

    out_path = os.path.splitext(md_path)[0] + ".pdf"
    build_pdf(md_path, out_path)
    print(f"PDF 已產出：{out_path}")
    return out_path


if __name__ == "__main__":
    main()
