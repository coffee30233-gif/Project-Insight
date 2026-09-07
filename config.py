# 注意：模型選擇與重試設定都在 gemini_client.py（FLASH_MODELS / PRO_MODELS /
# MAX_RETRY / RETRY_WAIT）。這裡以前有一組 SUMMARY_MODEL / REPORT_MODEL / BATCH_SIZE /
# MAX_RETRY / RETRY_WAIT，但全專案沒有任何檔案 import 它們、值也早就過時，已移除以免誤導。

# 「原文快取 fallback」：當 check_links.py 把某篇文章的原文連結標記為 dead（來源網站
# 已移除或改網址）時，export_static_data.py 會把資料庫裡存的 raw_content 匯出成
# data/archive/{id}.json，前端在該文章卡片提供「查看本站存檔內容」按鈕。
#
# 預設關閉：raw_content 是「為了產生摘要」而抓下來的原文片段，公開重刊可能涉及來源
# 網站的著作權／授權條款。確認你要收錄的來源允許（或改成只存自己有權重刊的來源）
# 之後，再把這個設成 True。
ENABLE_ORIGINAL_CACHE = False