"""
import_research_articles.py
把 AI 助手在整理 2025 年度／半年報、2026 上半年報告時，透過網路搜尋蒐集到的
「原始來源文章」匯入 projector_intel.db，並產生 embedding，讓 AI 問答（/api/ask）
能夠檢索、回答 2025-2026 上半年相關的市場問題。

跟平常 scraper_example.py 的差別：
- scraper_example.py 是「抓網頁 → 呼叫 Gemini 摘要」
- 這支腳本是「AI 助手已經幫忙讀過來源、寫好摘要」，只需要寫進資料庫＋產生 embedding，
  不會再呼叫 Gemini 重新摘要一次（省成本），但還是會呼叫 Gemini 的 embedding API
  （這一步一定要有 GEMINI_API_KEY 才能執行）。

用法：
    python import_research_articles.py

執行後，可以用 python generate_monthly_report.py <年> <月> 之類的指令，
針對這些月份重新產生月報（前提是同一個月至少有幾篇文章）。
"""
import db
import gemini_client
import embeddings

# 每筆資料對應資料庫的一篇「文章」。summary_zh 是 AI 助手整理搜尋結果後，
# 用自己的話重寫的摘要（不是原文逐字翻譯），category 對應網站篩選用的四個分類：
# 市場數據／新品發布／技術動態／供應鏈。
DATA = [
    {
        "source_name": "洛图科技RUNTO",
        "original_title": "全球投影机出货量上半年下滑4%",
        "url": "http://runtotech.com/MarketInsights/info_itemid_5969_lcid_12.html",
        "publish_date": "2025-09-18",
        "title_zh": "2025年上半年全球投影機出貨900.3萬台，年減4.2%",
        "summary_zh": "洛圖科技數據顯示，2025年上半年全球投影機出貨量為900.3萬台，同比下降4.2%，銷售額40.5億美元，同比下降8.6%。中國作為最大單一市場，上半年出貨285.0萬台，年減13.5%，全球佔比由35.1%降至31.7%。",
        "category": "市場數據",
        "importance": 4,
        "keywords": ["洛圖科技", "出貨量", "全球市場", "中國市場", "上半年"],
        "mentioned_brands": [],
    },
    {
        "source_name": "OFweek激光网",
        "original_title": "洛图科技：激光投影逆势增长，预测2027年全球市场规模突破300万台",
        "url": "https://laser.ofweek.com/2026-07/ART-240002-8420-30693158.html",
        "publish_date": "2026-07-20",
        "title_zh": "2025年全球投影機出貨1920.6萬台年減4.8%，雷射投影逆勢成長3.7%",
        "summary_zh": "洛圖科技數據顯示，2025年全球投影機出貨量為1920.6萬台，同比下降4.8%；但雷射投影出貨230.8萬台，逆勢成長3.7%。中國雷射投影出貨占全球比重達42.3%，但中國本身年減10.2%，主因宏觀環境偏弱與大屏電視價格下探的擠壓。",
        "category": "市場數據",
        "importance": 5,
        "keywords": ["洛圖科技", "全年出貨量", "雷射投影", "年減4.8%"],
        "mentioned_brands": [],
    },
    {
        "source_name": "OFweek显示网",
        "original_title": "2025年中国智能投影市场销量下跌14%；2026年关注能效新国标",
        "url": "https://display.ofweek.com/2026-01/ART-230001-8120-30680044.html",
        "publish_date": "2026-01-26",
        "title_zh": "2025年中國智能投影全年零售520.3萬台，年減13.9%",
        "summary_zh": "洛圖科技《中國智能投影零售市場月度追蹤》報告顯示，2025年中國智能投影（不含雷射電視）全通路銷量520.3萬台，年減13.9%，銷售額83.6億人民幣，年減16.5%，是繼2023年後第二次年度負成長。全年品牌排名小米居冠，哈趣升至第五，大眼橙第四季靠平價新品躍居單季第一。",
        "category": "市場數據",
        "importance": 5,
        "keywords": ["洛圖科技", "年度回顧", "品牌排名", "小米", "大眼橙"],
        "mentioned_brands": ["小米", "哈趣", "大眼橙", "小明", "飛利浦"],
    },
    {
        "source_name": "ZNDS资讯",
        "original_title": "2025年中国万元以上超高端投影市场销量翻倍增长",
        "url": "https://n.znds.com/article/news/69217.html",
        "publish_date": "2026-01-26",
        "title_zh": "2025年中國萬元以上超高端投影銷量翻倍，DMD晶片商用化帶動DLP陣營",
        "summary_zh": "德州儀器2025年推出0.39吋4K DMD晶片（4.5微米微鏡），10月率先應用於極米Z9X 4K與當貝D7X Pro，推動DLP陣營中高階競爭力。同年中國萬元以上超高端投影銷量翻倍成長，DLP市場前四品牌（極米、堅果、當貝、Vidda）合計份額超過94%。",
        "category": "技術動態",
        "importance": 4,
        "keywords": ["DMD晶片", "德州儀器", "超高端市場", "DLP"],
        "mentioned_brands": ["極米", "堅果", "當貝", "Vidda"],
    },
    {
        "source_name": "知乎",
        "original_title": "2025Q3中国智能投影销量下滑11.5%；热点聚焦能效新国标和万元市场",
        "url": "https://zhuanlan.zhihu.com/p/1965884523226063500",
        "publish_date": "2025-10-26",
        "title_zh": "2025年Q3中國智能投影線上銷售額年減11.5%，DLP份額回升至27.3%",
        "summary_zh": "洛圖科技線上監測數據顯示，2025年第三季中國智能投影線上市場銷售額年減11.5%。DLP技術線上份額升至27.3%（年增5.0pp），均價下降近300元至3445元；1LCD線上份額降至71.7%（降5pp）。DLP市場前四品牌（極米、堅果、當貝、Vidda）合計份額超過94%。",
        "category": "市場數據",
        "importance": 3,
        "keywords": ["洛圖科技", "Q3", "DLP", "1LCD", "均價"],
        "mentioned_brands": ["極米", "堅果", "當貝", "Vidda"],
    },
    {
        "source_name": "流媒体网",
        "original_title": "2025年11月中国客厅智能设备线上零售市场数据总结报告",
        "url": "https://lmtw.com/mzw/content/detail/id/249951/keyword_id/-1",
        "publish_date": "2026-01-03",
        "title_zh": "2025年11月中國智能投影：大眼橙躍居單月銷量冠軍",
        "summary_zh": "2025年11月，中國智能投影市場品牌排名出現明顯洗牌，大眼橙（旗下C3 Air為當月最暢銷機型）躍居當月銷量榜首位，其後依序為小米、康佳、哈趣，TOP4品牌合計銷量份額達47.0%，年增5.9個百分點，顯示平價價格帶競爭在年末白熱化。",
        "category": "市場數據",
        "importance": 3,
        "keywords": ["洛圖科技", "11月", "大眼橙", "品牌排名", "C3 Air"],
        "mentioned_brands": ["大眼橙", "小米", "康佳", "哈趣"],
    },
    {
        "source_name": "知乎",
        "original_title": "2025上半年中国客厅智能设备线上零售市场数据总结报告",
        "url": "https://zhuanlan.zhihu.com/p/1941294282951614542",
        "publish_date": "2025-08-20",
        "title_zh": "2025年上半年中國智能投影線上市場171.7萬台，年減8.1%",
        "summary_zh": "2025年上半年，中國智能投影線上監測市場銷量171.7萬台，年減8.1%，銷售額27.4億人民幣，年減5.3%。雷射光源份額達14.3%，4K銷量份額突破一成（11.1%），變焦產品銷額占比23.4%，AI大模型搭載產品銷量占比6.6%。75吋以上尺寸銷量占比21.9%。",
        "category": "市場數據",
        "importance": 4,
        "keywords": ["洛圖科技", "上半年", "線上市場", "雷射光源", "4K"],
        "mentioned_brands": [],
    },
    {
        "source_name": "流媒体网",
        "original_title": "2025Q1中国智能投影销量达143万台,基本持平",
        "url": "https://lmtw.com/mzw/content/detail/id/242242",
        "publish_date": "2025-04-15",
        "title_zh": "2025年第一季中國智能投影銷量約143萬台，近乎持平",
        "summary_zh": "2025年第一季中國智能投影銷量約143萬台，較去年同期基本持平。主因是2024年第四季國補政策延續性不明加上雙11大促，提前透支了部分2025年第一季的需求，加上消費者持幣觀望第二季618大促，導致第一季銷售動能疲弱。",
        "category": "市場數據",
        "importance": 3,
        "keywords": ["洛圖科技", "Q1", "國補政策", "618大促"],
        "mentioned_brands": [],
    },
    {
        "source_name": "新浪科技",
        "original_title": "2026年上半年中国智能投影市场销量205.6万台，同比下降26%",
        "url": "https://finance.sina.com.cn/tech/roll/2026-07-27/doc-inikfxcf0665618.shtml",
        "publish_date": "2026-07-27",
        "title_zh": "2026年上半年中國智能投影銷量205.6萬台，年減26.0%",
        "summary_zh": "洛圖科技報告顯示，2026年上半年中國智能投影市場（不含雷射電視）全通路銷量205.6萬台，年減26.0%，銷售額33.4億人民幣，年減27.0%。TOP10品牌銷量、銷額份額分別超過70%、85%，集中度較去年同期提升。極米量額雙冠，大眼橙銷量份額13.1%排名第二。",
        "category": "市場數據",
        "importance": 5,
        "keywords": ["洛圖科技", "2026上半年", "極米", "大眼橙", "品牌集中度"],
        "mentioned_brands": ["極米", "大眼橙", "康佳", "堅果", "Vidda", "當貝"],
    },
    {
        "source_name": "中关村在线",
        "original_title": "2026上半年智能投影销量下滑26%，亮度升级驱动结构性转型",
        "url": "https://projector.zol.com.cn/1220/12208298.html",
        "publish_date": "2026-07-25",
        "title_zh": "2026年上半年投影機亮度結構性升級：入門機型份額下滑14.9pp",
        "summary_zh": "2026年上半年中國智能投影全通路出貨205.6萬台，年減26%，第二季銷量不足百萬台，為近五年最低。500流明以下入門機型銷量占比57.5%，仍居主流但年減14.9個百分點；500-1000、1000-1500、3000流明以上各檔位份額分別年增6.6、10.0、1.6個百分點，顯示消費者逐漸從比價轉向兼顧亮度與畫質。",
        "category": "市場數據",
        "importance": 4,
        "keywords": ["洛圖科技", "亮度升級", "Q2", "入門機型"],
        "mentioned_brands": [],
    },
    {
        "source_name": "新浪科技",
        "original_title": "投影没人买了！2026上半年中国市场大跌近三成：Q2创5年新低",
        "url": "https://finance.sina.com.cn/tech/roll/2026-07-25/doc-iniiyptk9060752.shtml",
        "publish_date": "2026-07-25",
        "title_zh": "2026上半年投影機市場大跌近三成，需求透支加上上游元件漲價",
        "summary_zh": "分析指出，2026年上半年中國智能投影市場下滑近三成，主因是國補以舊換新提前透支需求、消費疲軟、其他大屏顯示設備分流，以及存儲晶片等上游元器件漲價傳導至終端售價，抑制部分購買需求。極米在量額兩端持續穩坐龍頭，並將三色雷射技術延伸至工程投影領域。",
        "category": "供應鏈",
        "importance": 4,
        "keywords": ["需求透支", "上游元件漲價", "工程投影"],
        "mentioned_brands": ["極米"],
    },
    {
        "source_name": "快科技",
        "original_title": "存储芯片涨价引发连锁反应 投影仪2026年将迎涨价潮",
        "url": "https://news.mydrivers.com/1/1087/1087717.htm",
        "publish_date": "2025-12-10",
        "title_zh": "記憶體晶片漲價恐引發2026年投影機漲價潮",
        "summary_zh": "三星、SK海力士自2025年4月起停止DDR4生產、轉向DDR5與HBM產能，導致DDR4現貨價飆升，反超DDR5。投影機成本結構中鏡頭、顯示晶片、記憶體占比高，加上電源被動元件採購成本同比上漲約28%，業界預期2026年新品可能面臨「減配」或「漲價」的抉擇。",
        "category": "供應鏈",
        "importance": 4,
        "keywords": ["記憶體漲價", "DDR4", "DDR5", "供應鏈成本"],
        "mentioned_brands": [],
    },
    {
        "source_name": "ProjectorCentral",
        "original_title": "The Evolution of Lifestyle Projectors and USTs at CES 2025",
        "url": "https://www.projectorcentral.com/CES-2025-Projectors-UST-Report.htm",
        "publish_date": "2025-01-16",
        "title_zh": "CES 2025：生活風格投影機與超短焦成展場主軸",
        "summary_zh": "CES 2025上，NexiGo推出搭載ALPD 5.0 Pro雷射光源的4K Aurora Pro MKII；Yaber K300S以不到9吋厚度做到RGB三色雷射超短焦、近全DCI-P3覆蓋；Samsung展出觸控互動的三色雷射超短焦Premiere 5；LG也發表新概念投影機，顯示超短焦與生活風格投影機是本屆展會焦點。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["CES 2025", "超短焦", "生活風格投影機"],
        "mentioned_brands": ["NexiGo", "Yaber", "Samsung", "LG"],
    },
    {
        "source_name": "Notebookcheck",
        "original_title": "Xgimi Ascend: New concept combines UST projector, screen and soundbar",
        "url": "https://www.notebookcheck.net/Xgimi-Ascend-New-concept-combines-UST-projector-screen-and-soundbar.941413.0.html",
        "publish_date": "2025-01-05",
        "title_zh": "極米CES 2025發表Ascend概念機，整合超短焦、螢幕與聲霸",
        "summary_zh": "極米在CES 2025發表Ascend概念產品，結合Aura 2超短焦投影機與可電動伸縮的抗光螢幕，並在螢幕底座內建Harman Kardon 60W聲霸。Aura 2採DLP技術，混合LED與雷射光源，亮度達2300 ISO流明，投射比0.18:1。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["Ascend概念機", "超短焦", "Harman Kardon"],
        "mentioned_brands": ["極米", "XGIMI"],
    },
    {
        "source_name": "Notebookcheck",
        "original_title": "CES 2025 | Jmgo N1S 4K compact triple laser projector launching globally",
        "url": "https://www.notebookcheck.net/Jmgo-N1S-4K-compact-triple-laser-projector-launching-globally.943306.0.html",
        "publish_date": "2025-01-07",
        "title_zh": "堅果N1S系列CES 2025全球鋪貨，三色雷射4K投影機",
        "summary_zh": "堅果在CES 2025展出N1S系列三款機型：N1S 4K（三色雷射）、N1S SE（三色雷射）、N1S Nano（LED光源，較便宜）。N1S 4K先前已在中國上市，此次宣布擴大到全球市場銷售。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["N1S系列", "三色雷射", "全球鋪貨"],
        "mentioned_brands": ["堅果", "JMGO"],
    },
    {
        "source_name": "ProjectorCentral",
        "original_title": "Anker Announces New Flagship Nebula X1 4K Triple-Laser Projector",
        "url": "https://www.projectorcentral.com/anker-announces-new-flagship-nebula-x1.htm",
        "publish_date": "2025-04-23",
        "title_zh": "Anker發表旗艦Nebula X1，業界首見液冷散熱三色雷射投影機",
        "summary_zh": "Anker發表新旗艦Nebula X1，4K解析度、三色雷射光源、3500 ANSI流明，具備自動微雲台、業界首見液冷散熱系統、14件式玻璃鏡頭。支援AI空間自適應功能，可自動偵測環境並調整投影位置、對焦、梯形校正與亮度。5月21日以2999美元上市。",
        "category": "新品發布",
        "importance": 4,
        "keywords": ["Nebula X1", "液冷散熱", "三色雷射"],
        "mentioned_brands": ["Anker", "Nebula"],
    },
    {
        "source_name": "Engadget",
        "original_title": "Anker's Soundcore Nebula X1 Pro is the ultimate party projector",
        "url": "https://www.engadget.com/home/home-theater/ankers-soundcore-nebula-x1-pro-is-the-ultimate-party-projector-130255687.html",
        "publish_date": "2025-09-04",
        "title_zh": "Anker於IFA 2025發表Nebula X1 Pro，整合160W重低音喇叭",
        "summary_zh": "Anker在IFA 2025發表Nebula X1 Pro，將Nebula X1投影機與160W重低音喇叭結合，重達72.4磅，具備伸縮把手與輪子維持可攜性。喇叭以彈簧式懸浮設計避免震動干擾雷射投影畫質，兩側可展開80W聲霸組成7.1.4環繞聲。9月23日於Kickstarter預購，售價4000-5000美元。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["Nebula X1 Pro", "IFA 2025", "Kickstarter"],
        "mentioned_brands": ["Anker", "Nebula"],
    },
    {
        "source_name": "GSMGoTech",
        "original_title": "Game Changer for Movie Nights: Anker's New Nebula P1 Projector",
        "url": "https://www.gsmgotech.com/2025/10/game-changer-for-movie-nights-ankers.html",
        "publish_date": "2025-10-08",
        "title_zh": "Anker推出平價可拆式喇叭投影機Nebula P1",
        "summary_zh": "Anker正式在美國推出Nebula P1可攜式投影機，主打全球首款配備可拆式喇叭的可攜投影機，售價799美元（限時優惠719美元），並附贈價值169美元的100吋戶外投影幕組。兩顆10W喇叭可磁吸拆卸放置於房間各處。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["Nebula P1", "可拆式喇叭", "可攜投影機"],
        "mentioned_brands": ["Anker", "Nebula"],
    },
    {
        "source_name": "XGIMI官方部落格",
        "original_title": "XGIMI at IFA 2025 Recap: Bright 4K UHD Laser Projector HORIZON 20 and TITAN",
        "url": "https://us.xgimi.com/blogs/news/xgimi-at-ifa-2025-recap-4k-uhd-laser-projector",
        "publish_date": "2025-09-16",
        "title_zh": "極米IFA 2025發表Horizon 20系列與首款商用機TITAN",
        "summary_zh": "極米在IFA 2025發表Horizon 20系列（Horizon 20／20 Pro／20 Max），最高5700 ISO流明、支援Dolby Vision、240Hz更新率、原生Netflix，並首度加入光學變焦。同時發表TITAN，是極米首款商用機種，4K解析度、5000流明，主打會議室與活動場域，象徵極米從消費市場跨入專業商用市場。",
        "category": "新品發布",
        "importance": 4,
        "keywords": ["Horizon 20", "TITAN", "IFA 2025", "商用投影機"],
        "mentioned_brands": ["極米", "XGIMI"],
    },
    {
        "source_name": "PRNewswire",
        "original_title": "Aurzen Redefines Portable Entertainment with New Projector Lineup for Every Lifestyle at IFA 2025",
        "url": "https://www.prnewswire.com/news-releases/aurzen-redefines-portable-entertainment-with-new-projector-lineup-for-every-lifestyle-at-ifa-2025-302540914.html",
        "publish_date": "2025-09-03",
        "title_zh": "Aurzen於IFA 2025展出ZIP模組化與EAZZE系列可攜投影機",
        "summary_zh": "Aurzen在IFA 2025展出三大產品線：模組化口袋投影機ZIP系列、音效整合的BOOM系列、平價的EAZZE系列。其中D1R Cube是全球首款搭載Roku OS的投影機，9月開賣；D1 Max具備950 ANSI流明、原生1080p、Google TV系統，預計2025年第四季上市。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["Aurzen", "ZIP系列", "Roku OS"],
        "mentioned_brands": ["Aurzen"],
    },
    {
        "source_name": "Hisense USA",
        "original_title": "Hisense Unveils Next-Gen Laser Home Cinema Power at CES 2026",
        "url": "https://www.hisense-usa.com/post/hisense-unveils-next-gen-laser-home-cinema-power-at-ces-2026-extending-multi-color-display-leadersh",
        "publish_date": "2025-12-22",
        "title_zh": "海信預告CES 2026新旗艦雷射電視XR10，6000流明液冷散熱",
        "summary_zh": "海信預告將於CES 2026發表新一代旗艦雷射電視XR10，採用LPU 3.0數位雷射引擎、純RGB三色雷射光源，峰值亮度達6000 ANSI流明，支援65至300吋畫面。內建16片全玻璃鏡頭、自動光圈系統與全密封液冷散熱系統，並具備四鏡頭加雙ToF感測的自動安裝校正功能。",
        "category": "新品發布",
        "importance": 4,
        "keywords": ["XR10", "雷射電視", "液冷散熱"],
        "mentioned_brands": ["海信", "Hisense"],
    },
    {
        "source_name": "CEPRO",
        "original_title": "Hisense Expands Color Technology Across TVs, MicroLED, and Laser Projection at CES 2026",
        "url": "https://www.cepro.com/news/hisense-expands-color-technology-across-tvs-microled-and-laser-projection-at-ces-2026/624447/",
        "publish_date": "2026-01-05",
        "title_zh": "海信CES 2026正式發表XR10雷射電視與PX4-PRO超短焦",
        "summary_zh": "海信在CES 2026正式發表旗艦雷射電視XR10（6000 ANSI流明、純RGB三色雷射）與PX4-PRO超短焦投影機（由3000流明升級至3500 ANSI流明），同時展示新一代RGB MiniLED電視與全球首款RGBY MicroLED顯示器163MX，展現多原色顯示技術策略。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["CES 2026", "XR10", "PX4-PRO"],
        "mentioned_brands": ["海信", "Hisense"],
    },
    {
        "source_name": "PRNewswire",
        "original_title": "Formovie Showcases Advanced Display Technologies and Smart Projector Innovations at CES 2026",
        "url": "https://www.prnewswire.com/news-releases/formovie-showcases-advanced-display-technologies-and-smart-projector-innovations-at-ces-2026-302654814.html",
        "publish_date": "2026-01-07",
        "title_zh": "Formovie CES 2026展出液冷技術與Xming Chapter One投影機",
        "summary_zh": "Formovie與子品牌Xming在CES 2026展出液冷技術方案，透過優化核心元件與散熱架構提升單片LCD投影機的亮度、光電效率與系統穩定性。搭載此技術的Xming Chapter One智慧投影機可達2000 ISO流明，同時維持低噪音運作。",
        "category": "技術動態",
        "importance": 3,
        "keywords": ["液冷技術", "Xming", "單片LCD"],
        "mentioned_brands": ["Formovie", "Xming"],
    },
    {
        "source_name": "Epson US",
        "original_title": "CES 2026: Epson's Lifestudio Continues to Lead the Industry as One of the First Projector Lines to Integrate Google TV with Gemini",
        "url": "https://news.epson.com/news/ces-2026-gemini-google-ai-projectors",
        "publish_date": "2026-01-06",
        "title_zh": "Epson CES 2026宣布Lifestudio系列整合Google TV與Gemini AI",
        "summary_zh": "Epson宣布旗下Lifestudio系列投影機（搭載聯發科智慧投影平台）將整合Google TV與Gemini AI助理，提供語音控制、個人化推薦與更流暢的串流體驗，是業界最早將生成式AI助理整合進投影機產品線的案例之一。",
        "category": "技術動態",
        "importance": 3,
        "keywords": ["Google TV", "Gemini AI", "Lifestudio"],
        "mentioned_brands": ["Epson"],
    },
    {
        "source_name": "AVS Forum",
        "original_title": "New and/or updated HT projectors shown at CES 2026",
        "url": "https://www.avsforum.com/threads/new-and-or-updated-ht-projectors-shown-at-ces-2026.3339384/",
        "publish_date": "2026-01-10",
        "title_zh": "CES 2026家庭劇院投影機盤點：XGIMI Titan Noir Max、AWOL Aetherion系列",
        "summary_zh": "CES 2026上，極米發表旗艦Titan Noir Max，是家庭劇院定位的4K投影機全球首發機種，具備新一代動態光圈系統。AWOL Vision發表Aetherion Max／Pro系列超短焦RGB雷射投影機，3300 ISO流明、PixelLock精密光學引擎，支援1ms級低延遲電競模式，預計2026年3月上市。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["Titan Noir Max", "Aetherion", "CES 2026"],
        "mentioned_brands": ["極米", "XGIMI", "AWOL Vision"],
    },
    {
        "source_name": "IT之家",
        "original_title": "洛图科技：2026 年上半年中国智能投影市场销量同比下降 26.0%、销售额下滑 27.0%",
        "url": "https://www.ithome.com/0/981/764.htm",
        "publish_date": "2026-07-26",
        "title_zh": "2026上半年投影機新品：ViewSonic三色雷射、堅果N5S、明基i800",
        "summary_zh": "洛圖科技報告確認2026年上半年中國智能投影銷量205.6萬台、年減26.0%，FHD占約六成市場、4K UHD銷量占比14.7%（年增3.6pp）。同期新品包括ViewSonic上架LX720-4KC Ultra（純三色雷射、支援1440P 120Hz/4K 60Hz，6999元）、堅果5月發表N5S系列（Ultra Max款號稱全球首發4K 120Hz）、明基上架i800系列（4K、3000 ISO流明）。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["洛圖科技", "ViewSonic", "堅果N5S", "明基i800", "4K UHD"],
        "mentioned_brands": ["ViewSonic", "堅果", "JMGO", "明基", "BenQ"],
    },

    # --- 以下為第二批：專業商用大型場館、頂級家庭劇院、電競/主題娛樂投影機 ---
    {
        "source_name": "TechPowerUp",
        "original_title": "BenQ Expands its Short Throw Projector Lineup",
        "url": "https://www.techpowerup.com/346475/benq-expands-its-short-throw-projector-lineup",
        "publish_date": "2026-03-24",
        "title_zh": "BenQ擴大短焦投影機陣容，主打高爾夫模擬與沉浸式場域",
        "summary_zh": "BenQ發表四款短焦/超短焦投影機新品（LU895UST、LH860ST、LK830ST、LW830ST），鎖定高爾夫模擬、運動模擬、沉浸式空間與投影對映等非傳統應用場景。搭載BenQ Screen Fill技術，可自動校正非標準螢幕與不規則長寬比，減少安裝校正時間。反映傳統投影機大盤下滑之際，廠商轉向利基應用場景尋找成長動能。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["BenQ", "短焦投影機", "高爾夫模擬", "沉浸式場域"],
        "mentioned_brands": ["BenQ", "明基"],
    },
    {
        "source_name": "Commercial Integrator",
        "original_title": "BenQ Launches the BR9708 4K Cinema-Grade Projector for Immersive Attractions",
        "url": "https://www.commercialintegrator.com/news/benq-br9708-4k-cinema-grade-projector/144707/",
        "publish_date": "2025-12-01",
        "title_zh": "BenQ發表BR9708，主打主題樂園與沉浸式娛樂場域的電影級投影機",
        "summary_zh": "BenQ在IAAPA Expo 2025發表BR9708，是專為暗黑乘坐設施、沉浸式景點、密室逃脫等主題娛樂場域設計的4K投影機，售價低於1萬美元。具備100% DCI-P3色域覆蓋、1200:1原生對比度、七點式出廠校色，定位在以較親民價格提供接近電影院等級的色彩表現。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["BR9708", "主題娛樂", "IAAPA", "沉浸式景點"],
        "mentioned_brands": ["BenQ", "明基"],
    },
    {
        "source_name": "TechRadar",
        "original_title": "BenQ's sharp-looking new 4K projectors promise HDMI 2.1 with ultra-low lag for gaming",
        "url": "https://www.techradar.com/televisions/projectors/benqs-sharp-looking-new-4k-projectors-promise-hdmi-2-1-with-ultra-low-lag-for-gaming-plus-great-streaming-and-connectivity-options",
        "publish_date": "2025-10-01",
        "title_zh": "BenQ發表TK705i/TK705STi電競4K投影機，支援HDMI 2.1超低延遲",
        "summary_zh": "BenQ發表TK705i與TK705STi兩款智慧4K家用投影機，亮度達3000 ANSI流明，足以應付一般照明環境。支援HDMI 2.1與超低延遲，主打遊戲玩家與串流影音使用者，同時具備良好的連接性與智慧串流功能。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["TK705i", "電競投影機", "HDMI 2.1", "低延遲"],
        "mentioned_brands": ["BenQ", "明基"],
    },
    {
        "source_name": "ProjectorCentral",
        "original_title": "Optoma Adds ZU920TNL and ZU820TNL ProScene Commercial Laser Projectors",
        "url": "https://www.projectorcentral.com/new-product-announcements.cfm",
        "publish_date": "2026-03-05",
        "title_zh": "Optoma推出ZU920TNL、ZU820TNL商用雷射工程投影機",
        "summary_zh": "Optoma發表ZU920TNL與ZU820TNL兩款ProScene系列商用雷射投影機，鎖定企業會議室、教育與大型場館等工程投影應用。同期業界其他商用動向包括Panasonic在ISE 2026展出MEVIX系列擴充陣容，以及XGIMI TITAN Noir系列導入動態光圈系統。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["Optoma", "ProScene", "商用雷射投影機", "工程投影"],
        "mentioned_brands": ["Optoma", "奧圖碼", "Panasonic", "XGIMI", "極米"],
    },
    {
        "source_name": "CEPRO",
        "original_title": "JVC to Showcase 'World's Smallest' 4K D-ILA Projector at CEDIA Expo/CIX 2025",
        "url": "https://www.cepro.com/news/jvc-to-showcase-worlds-smallest-4k-d-ila-projector-at-cedia-expo-cix-2025/621183/",
        "publish_date": "2025-08-15",
        "title_zh": "JVC於CEDIA 2025展出號稱全球最小的4K D-ILA投影機DLA-NZ700",
        "summary_zh": "JVC在CEDIA Expo/CIX 2025展出DLA-NZ700（Reference Series型號為DLA-RS2200），採用0.69吋原生4K D-ILA面板與BLU-Escent雷射技術，亮度2300流明、光源壽命2萬小時，體積較前代縮小35%，適合空間有限的安裝場景。原生對比度達80,000:1，售價9,999.95美元。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["JVC", "D-ILA", "DLA-NZ700", "CEDIA"],
        "mentioned_brands": ["JVC"],
    },
    {
        "source_name": "Projector Reviews",
        "original_title": "Best 4K Projectors for 2026",
        "url": "https://www.projectorreviews.com/best-4k-projectors/",
        "publish_date": "2026-02-27",
        "title_zh": "JVC旗艦DLA-RS4200／DLA-NZ900：業界最高原生對比度15萬比1",
        "summary_zh": "JVC旗艦機種DLA-RS4200（DLA-NZ900）採用第三代D-ILA面板，原生對比度達150,000:1為業界最高，BLU-Escent雷射光源亮度3300流明，並支援8K/e-shiftX技術，可產生超過3530萬個可定址像素。售價32,999.95美元，是JVC至今最高階的家庭劇院投影機。同系列入門款DLA-NZ500售價6,999.95美元。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["JVC旗艦", "D-ILA", "原生對比度", "8K/e-shiftX"],
        "mentioned_brands": ["JVC"],
    },
    {
        "source_name": "HomeTheaterReview",
        "original_title": "JVC LX-NZ30 4K HDR Laser Projector vs Sony VPLXW5000ES Comparison",
        "url": "https://hometheaterreview.com/vs/jvc-lx-nz30-4k-hdr-laser-projector-vs-sony-vplxw5000es-4k-hdr-laser-home-theater-projector-comparison/",
        "publish_date": "2025-11-12",
        "title_zh": "頂級家庭劇院投影機比較：JVC LX-NZ30 vs Sony VPL-XW5000ES",
        "summary_zh": "評測比較JVC LX-NZ30與Sony VPL-XW5000ES兩款高階家庭劇院投影機。Sony採用SXRD面板，訴求極致黑位表現與24分貝的低噪音運作，主打完全遮光的專用影音室；JVC則以約六成價格提供約八成的性能表現，性價比更高。反映高階家庭劇院市場中Sony與JVC兩大品牌的技術路線與定位差異。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["JVC", "Sony", "SXRD", "家庭劇院投影機"],
        "mentioned_brands": ["JVC", "Sony", "索尼"],
    },
    {
        "source_name": "ProjectorCentral",
        "original_title": "Panasonic Showcases Expanded MEVIX Lineup of Projectors and Displays at ISE",
        "url": "https://www.projectorcentral.com/panasonic-expanded-mevix-video-lineup-ise2026.htm",
        "publish_date": "2026-02-13",
        "title_zh": "Panasonic於ISE 2026發表2萬流明RGB雷射投影機PT-HTQ20",
        "summary_zh": "Panasonic在ISE 2026發表PT-HTQ20，是該公司首款支援Rec.2020色域的單晶片DLP RGB雷射投影機，採用新開發的VIVID PRIME RGB雷射光源技術，色域覆蓋逾95% Rec.2020，亮度達2萬流明、4K輸出，鎖定沉浸式娛樂場館應用。同時發表VMQ85系列4K LCD工程投影機，主打高爾夫模擬等沉浸式應用。",
        "category": "新品發布",
        "importance": 3,
        "keywords": ["Panasonic", "PT-HTQ20", "ISE 2026", "Rec.2020"],
        "mentioned_brands": ["Panasonic", "松下"],
    },
    {
        "source_name": "Blooloop",
        "original_title": "From invisible tech to visible wonder: inside ISE 2026",
        "url": "https://blooloop.com/ise-2026-review/",
        "publish_date": "2026-02-23",
        "title_zh": "ISE 2026觀展：Barco QDX平台擴充、Digital Projection慶30週年",
        "summary_zh": "ISE 2026（逾9.2萬人次參觀）上，Barco為QDX平台新增三款RGB機型，涵蓋主題娛樂與高階裝置應用的RGB及雷射磷光體選項，並展出多投影機自動校正工具。Digital Projection則慶祝成立30週年，展出主打大型高衝擊力場域的高亮度雷射投影機與三晶片DLP技術。反映商用工程投影市場持續朝向沉浸式體驗與主題娛樂應用發展。",
        "category": "新品發布",
        "importance": 2,
        "keywords": ["Barco", "ISE 2026", "Digital Projection", "商用投影機"],
        "mentioned_brands": ["Barco", "巴可", "Digital Projection"],
    },
]


def main():
    db.init_db()
    inserted, skipped, embedded_failed = 0, 0, 0

    for item in DATA:
        if db.article_exists(item["url"]):
            print(f"略過已存在：{item['title_zh']}")
            skipped += 1
            continue

        article_id = db.insert_raw_article(
            source_name=item["source_name"],
            original_title=item["original_title"],
            url=item["url"],
            publish_date=item["publish_date"],
            raw_content=item["summary_zh"],  # 沒有完整原文，用摘要頂替
        )

        analysis = {
            "title_zh": item["title_zh"],
            "summary_zh": item["summary_zh"],
            "category": item["category"],
            "importance": item["importance"],
            "original_language": "zh" if item["source_name"] not in (
                "ProjectorCentral", "Notebookcheck", "Engadget", "GSMGoTech",
                "PRNewswire", "Hisense USA", "CEPRO", "Epson US", "AVS Forum",
                "XGIMI官方部落格", "TechPowerUp", "Commercial Integrator",
                "TechRadar", "HomeTheaterReview", "Projector Reviews", "Blooloop",
            ) else "en",
            "keywords": item["keywords"],
            "mentioned_brands": item["mentioned_brands"],
        }
        db.update_processed_fields(article_id, analysis, gemini_client.now_iso())
        print(f"已寫入：[{item['category']}] {item['title_zh']}")
        inserted += 1

        try:
            vector = embeddings.embed_article(item["title_zh"], item["summary_zh"])
            db.set_embedding(article_id, vector)
        except Exception as e:
            print(f"  ⚠ embedding 產生失敗：{e}")
            embedded_failed += 1

    print(f"\n完成。新增 {inserted} 篇（略過 {skipped} 篇已存在），"
          f"其中 {embedded_failed} 篇 embedding 產生失敗（AI 問答暫時搜不到這幾篇，"
          f"之後可執行 python -c \"import embeddings; embeddings.backfill_embeddings()\" 補上）。")


if __name__ == "__main__":
    main()
