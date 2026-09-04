SUMMARY_MODEL = "gemini-2.5-flash-lite"
REPORT_MODEL = "gemini-2.5-flash"

BATCH_SIZE = 10

MAX_RETRY = 5
RETRY_WAIT = 60

# 「原文快取 fallback」：當 check_links.py 把某篇文章的原文連結標記為 dead（來源網站
# 已移除或改網址）時，export_static_data.py 會把資料庫裡存的 raw_content 匯出成
# data/archive/{id}.json，前端在該文章卡片提供「查看本站存檔內容」按鈕。
#
# 預設關閉：raw_content 是「為了產生摘要」而抓下來的原文片段，公開重刊可能涉及來源
# 網站的著作權／授權條款。確認你要收錄的來源允許（或改成只存自己有權重刊的來源）
# 之後，再把這個設成 True。
ENABLE_ORIGINAL_CACHE = False