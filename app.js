// 「最新情報」「月報／年報」都改成讀取部署時一起打包的靜態 JSON/MD 檔案
// （data/，由 export_static_data.py 從你自己電腦上的資料庫產生），
// 不需要一個一直開著的後端。只有 AI 問答會即時打 /api/ask，這是部署在
// Vercel 上的 Serverless Function（見 api/ask.py），跟前端同網域，
// 不需要 config.js 設定網址。
const API = ""; // /api/ask 走同源請求，保留這個常數只是讓底下程式碼不用大改


// ---------------------------------------------------------------------------
// Tab 切換
// ---------------------------------------------------------------------------

document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
        document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById(`panel-${btn.dataset.panel}`).classList.add("active");
    });
});

// ---------------------------------------------------------------------------
// 最新情報：統計數字 + 文章列表（改讀靜態 JSON，篩選/分頁都在前端做）
// ---------------------------------------------------------------------------

let currentPage = 1;
const PAGE_SIZE = 20;
let allArticles = [];   // static/data/articles.json 整份載進記憶體
let archiveIds = new Set();  // data/archive/index.json：有「本站存檔」可退而求其次顯示的文章 id

// 原文連結由來源網站提供，我們無法保證它永遠有效。這句提示會在滑鼠移到連結上時出現，
// 連結被季度健檢（check_links.py）判定失效時則會直接顯示在卡片上。
const SOURCE_LINK_HINT = "原文連結由來源網站提供，若已失效請參考本站摘要";

async function loadStats() {
    const res = await fetch("data/stats.json");
    const stats = await res.json();

    const statStrip = document.getElementById("stat-strip");
    statStrip.innerHTML = `
        <div class="stat-item"><div class="value">${stats.total_articles}</div><div class="label">收錄文章</div></div>
        <div class="stat-item"><div class="value">${stats.total_sources}</div><div class="label">追蹤來源</div></div>
        <div class="stat-item"><div class="value">${stats.latest_publish_date || "—"}</div><div class="label">最新更新</div></div>
    `;

    const sourceSelect = document.getElementById("filter-source");
    Object.keys(stats.by_source).sort().forEach(name => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = `${name}（${stats.by_source[name]}）`;
        sourceSelect.appendChild(opt);
    });
}

function filterArticles() {
    const search = document.getElementById("filter-search").value.trim().toLowerCase();
    const source = document.getElementById("filter-source").value;
    const category = document.getElementById("filter-category").value;

    return allArticles.filter(a => {
        if (source && a.source_name !== source) return false;
        if (category && a.category !== category) return false;
        if (search) {
            const haystack = `${a.title_zh || ""} ${a.summary_zh || ""}`.toLowerCase();
            if (!haystack.includes(search)) return false;
        }
        return true;
    });
}

function renderSourceLink(article) {
    const href = escapeAttr(article.url);
    const isDead = article.link_status === "dead";
    const hint = escapeAttr(SOURCE_LINK_HINT);

    const link = `<a class="source-link${isDead ? " dead" : ""}" href="${href}"`
        + ` target="_blank" rel="noopener" title="${hint}">查看原文來源 ↗</a>`;

    if (!isDead) return link;

    // 連結已被健檢判定失效：顯示提示，若本站有存檔則提供退而求其次的入口
    const hasArchive = archiveIds.has(article.id);
    const archiveBtn = hasArchive
        ? ` <button class="archive-btn" data-archive-id="${article.id}">查看本站存檔內容</button>`
        : "";
    return `
        <div class="source-link-row">${link}</div>
        <div class="source-dead-note">
            ⚠ 這則原文連結可能已失效（來源網站已移除或更改網址）。${escapeHtml(SOURCE_LINK_HINT)}。${archiveBtn}
        </div>
    `;
}

function renderArticleCard(article) {
    const brands = (article.mentioned_brands || []).slice(0, 3)
        .map(b => `<span class="tag">${escapeHtml(b)}</span>`).join("");
    return `
        <div class="article-card">
            <div class="meta-row">
                <span class="tag category-${escapeHtml(article.category || "")}">${escapeHtml(article.category || "未分類")}</span>
                <span class="tag">${escapeHtml(article.source_name)}</span>
                ${brands}
                <span class="date">${escapeHtml(article.publish_date || "")}</span>
            </div>
            <h3>${escapeHtml(article.title_zh || article.original_title || "")}</h3>
            <p>${escapeHtml(article.summary_zh || "")}</p>
            ${renderSourceLink(article)}
        </div>
    `;
}

async function loadArchiveIndex() {
    // 只有在 config.ENABLE_ORIGINAL_CACHE 開啟時 export_static_data.py 才會產生這個檔案，
    // 關閉時這裡會 404 / 解析失敗，靜默當作「沒有任何存檔」即可。
    try {
        const res = await fetch("data/archive/index.json");
        if (!res.ok) return;
        archiveIds = new Set(await res.json());
    } catch (_) {
        /* 沒有存檔，維持空集合 */
    }
}

async function loadArticlesData() {
    await loadArchiveIndex();
    const res = await fetch("data/articles.json");
    allArticles = await res.json();
    renderArticles(1, false);
}

// 「查看本站存檔內容」：點下去才去抓 data/archive/{id}.json（失效連結通常沒幾則，
// 不值得在首頁一次載入全部存檔內容）
document.getElementById("article-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".archive-btn");
    if (!btn) return;
    openArchive(btn.dataset.archiveId);
});

async function openArchive(id) {
    let data;
    try {
        const res = await fetch(`data/archive/${id}.json`);
        if (!res.ok) throw new Error(String(res.status));
        data = await res.json();
    } catch (_) {
        alert("存檔內容載入失敗，請稍後再試。");
        return;
    }

    const overlay = document.createElement("div");
    overlay.className = "archive-overlay";
    const finalUrl = data.link_final_url && data.link_final_url !== data.url
        ? `<div class="archive-meta">來源網站目前的網址：<a href="${escapeAttr(data.link_final_url)}" target="_blank" rel="noopener">${escapeHtml(data.link_final_url)}</a></div>`
        : "";
    overlay.innerHTML = `
        <div class="archive-modal" role="dialog" aria-modal="true">
            <button class="archive-close" aria-label="關閉">✕</button>
            <div class="archive-banner">
                以下是<strong>本站當初為了產生摘要而保存的原文內容</strong>，並非來源網站的即時頁面，
                可能不完整、也可能與最新版本有出入。原始連結：
                <a href="${escapeAttr(data.url)}" target="_blank" rel="noopener">${escapeHtml(data.url)}</a>
            </div>
            ${finalUrl}
            <h3>${escapeHtml(data.title_zh || data.original_title || "")}</h3>
            <div class="archive-sub">${escapeHtml(data.source_name || "")}｜${escapeHtml(data.publish_date || "")}</div>
            <pre class="archive-body">${escapeHtml(data.raw_content || "（沒有存檔內容）")}</pre>
        </div>
    `;
    const close = () => overlay.remove();
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    overlay.querySelector(".archive-close").addEventListener("click", close);
    document.addEventListener("keydown", function esc(e) {
        if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
    });
    document.body.appendChild(overlay);
}

function renderArticles(page = 1, append = false) {
    currentPage = page;
    const filtered = filterArticles();
    const pageItems = filtered.slice(0, page * PAGE_SIZE);

    const listEl = document.getElementById("article-list");
    if (pageItems.length === 0) {
        listEl.innerHTML = `<div class="ask-empty">沒有符合條件的文章</div>`;
    } else {
        listEl.innerHTML = pageItems.map(renderArticleCard).join("");
    }

    const loadMoreBtn = document.getElementById("load-more");
    loadMoreBtn.style.display = pageItems.length < filtered.length ? "block" : "none";
}

document.getElementById("load-more").addEventListener("click", () => {
    renderArticles(currentPage + 1, true);
});

let filterDebounce;
["filter-search", "filter-source", "filter-category"].forEach(id => {
    document.getElementById(id).addEventListener("input", () => {
        clearTimeout(filterDebounce);
        filterDebounce = setTimeout(() => renderArticles(1, false), 300);
    });
});

// ---------------------------------------------------------------------------
// 月報／年報
// ---------------------------------------------------------------------------

function reportLabel(filename) {
    if (filename.endsWith("-annual.md")) {
        return `${filename.slice(0, 4)} 年度回顧`;
    }
    if (filename.endsWith("-h1.md")) {
        return `${filename.slice(0, 4)} 年 上半年`;
    }
    if (filename.endsWith("-h2.md")) {
        return `${filename.slice(0, 4)} 年 下半年`;
    }
    const weeklyMatch = filename.match(/^(\d{4})-W(\d{2})\.md$/);
    if (weeklyMatch) {
        return `${weeklyMatch[1]} 年 第 ${parseInt(weeklyMatch[2])} 週`;
    }
    const [year, month] = filename.replace(".md", "").split("-");
    return `${year} 年 ${parseInt(month)} 月`;
}

function reportListItem(item) {
    // 相容兩種格式：舊資料是純檔名字串，新資料是 {file, hasSlides, hasPdf} 物件
    const file = typeof item === "string" ? item : item.file;
    const hasSlides = typeof item === "string" ? false : !!item.hasSlides;
    const hasPdf = typeof item === "string" ? false : !!item.hasPdf;
    return `<li><button data-file="${file}" data-slides="${hasSlides}" data-pdf="${hasPdf}">${reportLabel(file)}</button></li>`;
}

async function loadReportList() {
    const res = await fetch("data/reports-index.json");
    const data = await res.json();

    const annualEl = document.getElementById("annual-report-list");
    const semiannualEl = document.getElementById("semiannual-report-list");
    const monthlyEl = document.getElementById("monthly-report-list");
    const weeklyEl = document.getElementById("weekly-report-list");

    annualEl.innerHTML = data.annual.length
        ? data.annual.map(reportListItem).join("")
        : `<li style="color:var(--text-muted); font-size:0.82rem; padding:6px 10px;">尚無年度報告</li>`;

    semiannualEl.innerHTML = (data.semiannual || []).length
        ? data.semiannual.map(reportListItem).join("")
        : `<li style="color:var(--text-muted); font-size:0.82rem; padding:6px 10px;">尚無半年報</li>`;

    monthlyEl.innerHTML = data.monthly.length
        ? data.monthly.map(reportListItem).join("")
        : `<li style="color:var(--text-muted); font-size:0.82rem; padding:6px 10px;">尚無月報</li>`;

    weeklyEl.innerHTML = (data.weekly || []).length
        ? data.weekly.map(reportListItem).join("")
        : `<li style="color:var(--text-muted); font-size:0.82rem; padding:6px 10px;">尚無週報</li>`;

    document.querySelectorAll("#annual-report-list button, #semiannual-report-list button, #monthly-report-list button, #weekly-report-list button")
        .forEach(btn => btn.addEventListener("click", () => openReport(btn.dataset.file, btn.dataset.slides === "true", btn.dataset.pdf === "true", btn)));
}

async function openReport(filename, hasSlides, hasPdf, btnEl) {
    document.querySelectorAll(".report-list-col button").forEach(b => b.classList.remove("active"));
    if (btnEl) btnEl.classList.add("active");

    const viewer = document.getElementById("report-viewer");
    const toolbar = document.getElementById("report-toolbar");
    const downloadPptxBtn = document.getElementById("report-download-pptx-btn");
    const downloadPdfBtn = document.getElementById("report-download-pdf-btn");
    toolbar.style.display = "none";
    downloadPptxBtn.style.display = "none";
    downloadPdfBtn.style.display = "none";
    viewer.innerHTML = `<div class="empty-state">載入中…</div>`;

    const res = await fetch(`data/reports/${filename}`);
    if (!res.ok) {
        viewer.innerHTML = `<div class="empty-state">載入失敗</div>`;
        return;
    }
    const markdownText = await res.text();
    viewer.innerHTML = marked.parse(markdownText);

    let showToolbar = false;

    if (hasSlides) {
        const pptxFilename = filename.replace(/\.md$/, ".pptx");
        downloadPptxBtn.href = `data/reports/${pptxFilename}`;
        downloadPptxBtn.download = pptxFilename;
        downloadPptxBtn.style.display = "inline-flex";
        showToolbar = true;
    }

    if (hasPdf) {
        const pdfFilename = filename.replace(/\.md$/, ".pdf");
        downloadPdfBtn.href = `data/reports/${pdfFilename}`;
        downloadPdfBtn.download = pdfFilename;
        downloadPdfBtn.style.display = "inline-flex";
        showToolbar = true;
    }

    if (showToolbar) {
        toolbar.style.display = "flex";
    }
}

// ---------------------------------------------------------------------------
// AI 問答（RAG）
// ---------------------------------------------------------------------------

const askMessages = document.getElementById("ask-messages");
const askInput = document.getElementById("ask-input");
const askSendBtn = document.getElementById("ask-send");

function appendUserMessage(text) {
    const emptyState = askMessages.querySelector(".ask-empty");
    if (emptyState) emptyState.remove();
    askMessages.insertAdjacentHTML("beforeend", `
        <div class="msg user"><div class="bubble">${escapeHtml(text)}</div></div>
    `);
    askMessages.scrollTop = askMessages.scrollHeight;
}

function appendTypingIndicator() {
    const id = `typing-${Date.now()}`;
    askMessages.insertAdjacentHTML("beforeend", `
        <div class="msg assistant" id="${id}">
            <div class="bubble typing-dots"><span></span><span></span><span></span></div>
        </div>
    `);
    askMessages.scrollTop = askMessages.scrollHeight;
    return id;
}

function renderAssistantMessage(typingId, answer, sources) {
    const sourcesHtml = sources.length
        ? `<div class="sources">${sources.map(s => {
            const isDead = s.link_status === "dead";
            return `
            <div class="source-chip${isDead ? " dead" : ""}">
                ${escapeHtml(s.source_name)}｜${escapeHtml(s.publish_date || "")}｜
                <a href="${escapeAttr(s.url)}" target="_blank" rel="noopener" title="${escapeAttr(SOURCE_LINK_HINT)}">${escapeHtml(s.title_zh)}</a>${isDead ? ` <span class="chip-dead-flag">⚠ 原文連結可能已失效</span>` : ""}
            </div>
          `;
          }).join("")}</div>`
        : "";

    document.getElementById(typingId).innerHTML = `
        <div class="bubble">${escapeHtml(answer)}</div>
        ${sourcesHtml}
    `;
    askMessages.scrollTop = askMessages.scrollHeight;
}

async function sendQuestion() {
    const question = askInput.value.trim();
    if (!question) return;

    askInput.value = "";
    askSendBtn.disabled = true;
    appendUserMessage(question);
    const typingId = appendTypingIndicator();

    try {
        const res = await fetch(`${API}/api/ask`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "發生錯誤");
        renderAssistantMessage(typingId, data.answer, data.sources || []);
    } catch (err) {
        renderAssistantMessage(typingId, `發生錯誤：${err.message}`, []);
    } finally {
        askSendBtn.disabled = false;
    }
}

askSendBtn.addEventListener("click", sendQuestion);
askInput.addEventListener("keydown", e => { if (e.key === "Enter") sendQuestion(); });

// ---------------------------------------------------------------------------
// 工具函式
// ---------------------------------------------------------------------------

function escapeHtml(str) {
    if (str == null) return "";
    return String(str)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function escapeAttr(str) {
    return escapeHtml(str);
}

// ---------------------------------------------------------------------------
// 週報訂閱
// ---------------------------------------------------------------------------

function initSubscribeForm() {
    const form = document.getElementById("subscribe-form");
    if (!form) return;

    const emailInput = document.getElementById("subscribe-email");
    const btn = document.getElementById("subscribe-btn");
    const messageEl = document.getElementById("subscribe-message");

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const email = emailInput.value.trim();
        if (!email) return;

        btn.disabled = true;
        messageEl.textContent = "訂閱中…";
        messageEl.className = "subscribe-message";

        try {
            const res = await fetch("/api/subscribe", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email }),
            });
            const data = await res.json();

            if (res.ok) {
                messageEl.textContent = data.message || "訂閱成功！";
                messageEl.className = "subscribe-message success";
                emailInput.value = "";
            } else {
                messageEl.textContent = data.detail || "訂閱失敗，請稍後再試";
                messageEl.className = "subscribe-message error";
            }
        } catch (err) {
            messageEl.textContent = "訂閱失敗，請稍後再試";
            messageEl.className = "subscribe-message error";
        } finally {
            btn.disabled = false;
        }
    });
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

loadStats();
loadArticlesData();
loadReportList();
initSubscribeForm();
