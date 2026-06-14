const API = {
    models: "/api/models",
    providers: "/api/providers",
    presets: "/api/presets",
    investigations: "/api/investigations",
    seeds: "/api/seeds",
    healthLLM: "/api/health/llm",
    healthSearch: "/api/health/search",
    torNewnym: "/api/tor/newnym",
    investigate: "/api/investigate",
    exportPdf: "/api/export/pdf",
};

const state = {
    models: [],
    providers: [],
    presets: [],
    investigations: [],
    tags: ["all"],
    seeds: [],
    selectedModel: "",
    threads: 4,
    maxResults: 50,
    maxScrape: 10,
    maxContentChars: 2000,
    selectedPreset: "",
    selectedPresetMeta: null,
    query: "",
    runResult: null,
    loadedInvestigation: null,
    selectedInvestigationId: null,
    selectedSeedId: null,
    seedFilter: "all",
    invStatusFilter: "all",
    invTagFilter: "all",
    health: {
        llm: null,
        search: null,
    },
    theme: "light",
};

let seedRefreshTimer = null;

function getEl(id) {
    return document.getElementById(id) || null;
}

const elements = {
    // Sidebar
    sidebar: getEl("sidebar"),
    sidebarToggle: getEl("sidebarToggle"),
    sidebarCollapseBtn: getEl("sidebarCollapseBtn"),
    brandReload: getEl("brandReload"),
    newChatBtn: getEl("newChatBtn"),
    invSearchInput: getEl("invSearchInput"),
    investigationList: getEl("investigationList"),
    openSeedsBtn: getEl("openSeedsBtn"),
    openHealthBtn: getEl("openHealthBtn"),
    openConfigBtn: getEl("openConfigBtn"),
    
    // Top Bar
    currentInvTitle: getEl("currentInvTitle"),
    exportPdfBtn: getEl("exportPdfBtn"),
    exportMdBtn: getEl("exportMdBtn"),
    themeToggle: getEl("themeToggle"),

    // Chat
    chatContainer: getEl("chatContainer"),
    welcomeScreen: getEl("welcomeScreen"),
    queryInput: getEl("queryInput"),
    searchForm: getEl("searchForm"),
    sendBtn: getEl("sendBtn"),
    stopBtn: getEl("stopBtn"),
    
    // Model Selector
    modelSelector: getEl("modelSelector"),
    currentModelBtn: getEl("currentModelBtn"),
    currentModelName: getEl("currentModelName"),
    modelDropdown: getEl("modelDropdown"),

    // Modals
    configModal: getEl("configModal"),
    healthModal: getEl("healthModal"),
    seedsModal: getEl("seedsModal"),
    completionModal: getEl("completionModal"),
    closeModalBtns: document.querySelectorAll(".close-modal"),
    completionReviewBtn: getEl("completionReviewBtn"),
    completionPdfBtn: getEl("completionPdfBtn"),
    completionMdBtn: getEl("completionMdBtn"),

    // Config Form
    modelSelect: getEl("modelSelect"),
    threadsInput: getEl("threadsInput"),
    threadsValue: getEl("threadsValue"),
    maxResultsInput: getEl("maxResultsInput"),
    maxResultsValue: getEl("maxResultsValue"),
    presetSelect: getEl("presetSelect"),
    customPresetFields: getEl("customPresetFields"),
    customPrompt: getEl("customPrompt"),
    savePresetBtn: getEl("savePresetBtn"),
    deletePresetBtn: getEl("deletePresetBtn"),
    newPresetName: getEl("newPresetName"),
    newPresetPrompt: getEl("newPresetPrompt"),
    createPresetBtn: getEl("createPresetBtn"),
    providerStatus: getEl("providerStatus"),

    // Health
    checkLlmBtn: getEl("checkLlmBtn"),
    checkSearchBtn: getEl("checkSearchBtn"),
    torNewnymBtn: getEl("torNewnymBtn"),
    healthOutput: getEl("healthOutput"),

    // Seeds
    seedUrlInput: getEl("seedUrlInput"),
    seedLabelInput: getEl("seedLabelInput"),
    addSeedBtn: getEl("addSeedBtn"),
    seedFilterSelect: getEl("seedFilterSelect"),
    seedList: getEl("seedList"),

    toast: getEl("toast"),
};

// --- Initialization ---

async function init() {
    setupEventListeners();
    await reloadAppState();
    loadTheme();
    loadSidebarState();
}

function loadTheme() {
    const savedTheme = localStorage.getItem("obscura-theme") || "light";
    setTheme(savedTheme);
}

function loadSidebarState() {
    const isCollapsed = localStorage.getItem("obscura-sidebar-collapsed") === "true";
    if (isCollapsed) {
        elements.sidebar.classList.add("collapsed");
    }
}

function setTheme(theme) {
    state.theme = theme;
    document.body.className = theme + "-mode";
    localStorage.setItem("obscura-theme", theme);
    const icon = elements.themeToggle.querySelector("i");
    if (theme === "dark") {
        icon.className = "fas fa-sun";
    } else {
        icon.className = "fas fa-moon";
    }
}

// --- UI Helpers ---

function showToast(message, type = "info") {
    elements.toast.textContent = message;
    elements.toast.className = `toast ${type}`;
    elements.toast.classList.remove("hidden");
    clearTimeout(window.toastTimer);
    window.toastTimer = setTimeout(() => {
        elements.toast.classList.add("hidden");
    }, 4200);
}

let investigationAbortController = null;

function setLoading(active) {
    elements.sendBtn.disabled = active;
    elements.stopBtn.classList.toggle("hidden", !active);
    const icon = elements.sendBtn.querySelector("i");
    if (active) {
        icon.className = "fas fa-spinner fa-spin";
    } else {
        icon.className = "fas fa-paper-plane";
    }
}

function openModal(modal) {
    modal.style.display = "block";
}

function closeModal(modal) {
    modal.style.display = "none";
}

// --- API Logic ---

async function fetchJSON(url, options = {}) {
    try {
        // Add cache-buster to GET requests
        const fetchUrl = options.method === 'POST' || options.method === 'PUT' || options.method === 'DELETE' 
            ? url 
            : `${url}${url.includes('?') ? '&' : '?'}_t=${Date.now()}`;

        const response = await fetch(fetchUrl, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });
        if (!response.ok) {
            const body = await response.text();
            throw new Error(body || response.statusText);
        }
        return response.status === 204 ? null : response.json();
    } catch (error) {
        throw new Error(error.message || "Network error");
    }
}

async function reloadAppState() {
    try {
        // Load everything but don't let one failure stop others
        const results = await Promise.allSettled([
            fetchJSON(API.models),
            fetchJSON(API.providers),
            fetchJSON(API.presets),
            fetchJSON(API.investigations),
            fetchJSON(API.seeds),
        ]);

        if (results[0].status === 'fulfilled') state.models = results[0].value.models || [];
        if (results[1].status === 'fulfilled') state.providers = results[1].value.providers || [];
        if (results[2].status === 'fulfilled') state.presets = results[2].value.presets || [];
        if (results[3].status === 'fulfilled') {
            state.investigations = results[3].value.investigations || [];
            state.tags = results[3].value.tags || [];
        }
        if (results[4].status === 'fulfilled') state.seeds = results[4].value.seeds || [];

        renderSelectOptions();
        renderProviderStatus();
        renderPresetOptions();
        renderInvestigationList();
        renderSeedList();

            // If there are pending seeds, keep refreshing them until they complete.
            if (state.seeds.some(seed => !seed.crawled)) {
                startSeedRefreshTimer();
            }
        
        console.log("App state reloaded. Presets count:", state.presets.length);
    } catch (error) {
        console.error("Reload error:", error);
        showToast(`Unable to load app data: ${error.message}`, "error");
    }
}

async function refreshSeedsFromServer() {
    try {
        const data = await fetchJSON(API.seeds);
        if (Array.isArray(data.seeds)) {
            state.seeds = data.seeds;
            renderSeedList();
        }
    } catch (error) {
        console.warn("Seed refresh failed:", error);
    }
}

function startSeedRefreshTimer() {
    stopSeedRefreshTimer();
    seedRefreshTimer = setInterval(async () => {
        const pendingSeeds = state.seeds.some(seed => !seed.crawled);
        if (!pendingSeeds) {
            stopSeedRefreshTimer();
            return;
        }
        await refreshSeedsFromServer();
    }, 3000);
}

function stopSeedRefreshTimer() {
    if (seedRefreshTimer) {
        clearInterval(seedRefreshTimer);
        seedRefreshTimer = null;
    }
}

async function refreshPresetsOnly() {
    try {
        const data = await fetchJSON(API.presets);
        state.presets = data.presets || [];
        renderPresetOptions();
    } catch (error) {
        console.error("Failed to refresh presets:", error);
    }
}

// --- Rendering ---

function renderSelectOptions() {
    elements.modelSelect.innerHTML = "";
    elements.modelDropdown.innerHTML = "";
    
    state.models.forEach((model) => {
        // Update Config Modal Select
        const option = document.createElement("option");
        option.value = model.key;
        option.textContent = model.label;
        elements.modelSelect.appendChild(option);

        // Update Search Interface Dropdown
        const item = document.createElement("div");
        item.className = `model-item ${state.selectedModel === model.key ? 'active' : ''}`;
        item.textContent = model.label;
        item.onclick = () => {
            selectModel(model.key);
            elements.modelDropdown.classList.add("hidden");
            elements.modelSelector.classList.remove("open");
        };
        elements.modelDropdown.appendChild(item);
    });

    if (state.models.length > 0 && !state.selectedModel) {
        state.selectedModel = state.models[0].key;
    }
    
    elements.modelSelect.value = state.selectedModel;
    
    const currentModel = state.models.find(m => m.key === state.selectedModel);
    if (currentModel) {
        elements.currentModelName.textContent = currentModel.label;
    }
}

function selectModel(modelKey) {
    state.selectedModel = modelKey;
    elements.modelSelect.value = modelKey;
    
    const model = state.models.find(m => m.key === modelKey);
    if (model) {
        elements.currentModelName.textContent = model.label;
        showToast(`Model switched to ${model.label}`, "success");
    }
    
    // Update active class in dropdown
    document.querySelectorAll(".model-item").forEach(item => {
        item.classList.toggle("active", item.textContent === (model ? model.label : ""));
    });
}

function renderProviderStatus() {
    elements.providerStatus.innerHTML = "";
    state.providers.forEach((provider) => {
        const statusClass = provider.statusLevel || "neutral";
        const item = document.createElement("div");
        item.className = `provider-item ${statusClass}`;
        const envKey = provider.envKey || "";
        const actionLabel = provider.hasValue ? "Update" : "Set Key";
        const actionIcon = provider.fieldKind === "url" ? "fa-link" : "fa-key";

        item.innerHTML = `
            <div class="provider-row">
                <div class="provider-info">
                    <strong>${provider.name}</strong>
                    <span class="provider-status">${provider.message}</span>
                </div>
                <button class="provider-edit-btn" data-env-key="${envKey}" title="${actionLabel}">
                    <i class="fas ${actionIcon}"></i> ${actionLabel}
                </button>
            </div>
        `;
        elements.providerStatus.appendChild(item);
    });

    elements.providerStatus.querySelectorAll(".provider-edit-btn").forEach((btn) => {
        btn.addEventListener("click", () => openProviderKeyModal(btn.dataset.envKey));
    });
}

let _activeProviderKey = null;

function openProviderKeyModal(envKey) {
    const provider = state.providers.find((p) => p.envKey === envKey);
    if (!provider) return;
    _activeProviderKey = envKey;

    const modal = getEl("providerKeyModal");
    const title = getEl("providerKeyModalTitle");
    const hint = getEl("providerKeyModalHint");
    const label = getEl("providerKeyInputLabel");
    const input = getEl("providerKeyInput");
    const feedback = getEl("providerKeyFeedback");

    const isUrl = provider.fieldKind === "url";
    title.textContent = `${provider.name} — ${isUrl ? "Base URL" : "API Key"}`;
    label.textContent = isUrl ? "Base URL" : "API Key";
    hint.textContent = provider.hasValue
        ? `A value is already saved for ${provider.name}. Enter a new one to replace it.`
        : `Enter your ${provider.name} ${isUrl ? "base URL" : "API key"}. It will be saved to the .env file.`;
    input.type = isUrl ? "text" : "password";
    input.value = "";
    input.placeholder = isUrl ? "https://host:port/" : "sk-...";
    feedback.textContent = "";
    feedback.className = "provider-feedback";

    openModal(modal);
    setTimeout(() => input.focus(), 50);
}

function closeProviderKeyModal() {
    const modal = getEl("providerKeyModal");
    if (modal) closeModal(modal);
    _activeProviderKey = null;
}

async function saveProviderKey() {
    const envKey = _activeProviderKey;
    if (!envKey) return;
    const input = getEl("providerKeyInput");
    const feedback = getEl("providerKeyFeedback");
    const saveBtn = getEl("providerKeySaveBtn");
    const value = (input.value || "").trim();

    if (!value) {
        feedback.textContent = "Please enter a value.";
        feedback.className = "provider-feedback error";
        return;
    }

    try {
        feedback.textContent = "Saving…";
        feedback.className = "provider-feedback";
        if (saveBtn) saveBtn.disabled = true;

        const data = await fetchJSON(API.providers, {
            method: "POST",
            body: JSON.stringify({ envKey, value }),
        });
        state.providers = data.providers || [];

        try {
            const modelsData = await fetchJSON(API.models);
            state.models = modelsData.models || [];
            renderModelOptions();
        } catch (_) { /* non-fatal */ }

        renderProviderStatus();
        closeProviderKeyModal();
        showToast(`${envKey} saved`, "success");
    } catch (err) {
        feedback.textContent = `Save failed: ${err.message}`;
        feedback.className = "provider-feedback error";
    } finally {
        if (saveBtn) saveBtn.disabled = false;
    }
}

function renderPresetOptions() {
    elements.presetSelect.innerHTML = "";
    state.presets.forEach((preset) => {
        const option = document.createElement("option");
        option.value = preset.key;
        option.textContent = preset.label;
        elements.presetSelect.appendChild(option);
    });
    if (state.presets.length > 0 && !state.selectedPreset) {
        state.selectedPreset = state.presets[0].key;
    }
    elements.presetSelect.value = state.selectedPreset;
    updateCustomPresetFields();
}

function updateCustomPresetFields() {
    const selected = state.presets.find((p) => p.key === state.selectedPreset);
    if (selected && selected.custom) {
        elements.customPresetFields.classList.remove("hidden");
        elements.customPrompt.value = selected.system_prompt || "";
        state.selectedPresetMeta = selected;
    } else {
        elements.customPresetFields.classList.add("hidden");
        state.selectedPresetMeta = null;
    }
}

function renderInvestigationList(filter = "") {
    elements.investigationList.innerHTML = "";
    const filtered = state.investigations.filter(inv => 
        inv.query.toLowerCase().includes(filter.toLowerCase())
    );

    if (filtered.length === 0) {
        elements.investigationList.innerHTML = '<div class="history-item">No investigations found</div>';
        return;
    }

    filtered.slice(0, 20).forEach(inv => {
        const item = document.createElement("div");
        item.className = `history-item ${state.selectedInvestigationId === inv.id ? 'active' : ''}`;
        item.onclick = () => selectInvestigation(inv.id);
        
        const icon = document.createElement("i");
        icon.className = "fas fa-comment-alt history-icon";
        item.appendChild(icon);

        const text = document.createElement("span");
        text.className = "sidebar-label";
        text.textContent = inv.query.length > 25 ? inv.query.substring(0, 25) + "..." : inv.query;
        text.title = inv.query;
        
        const delBtn = document.createElement("button");
        delBtn.className = "delete-btn";
        delBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
        delBtn.title = "Delete investigation";
        delBtn.onclick = (e) => {
            e.stopPropagation();
            handleDeleteInvestigation(inv.id);
        };

        item.appendChild(text);
        item.appendChild(delBtn);
        elements.investigationList.appendChild(item);
    });
}

function renderSeedList() {
    elements.seedList.innerHTML = "";
    const filteredSeeds = state.seeds.filter(seed => {
        if (state.seedFilter === 'crawled') return !!seed.crawled;
        if (state.seedFilter === 'uncrawled') return !seed.crawled;
        return true;
    });

    if (filteredSeeds.length === 0) {
        elements.seedList.innerHTML = '<div class="history-item">No seeds found</div>';
        return;
    }

    filteredSeeds.forEach(seed => {
        const item = document.createElement("div");
        item.className = `seed-item ${state.selectedSeedId === seed.id ? 'active' : ''}`;
        item.onclick = () => selectSeed(seed.id);
        
        const info = document.createElement("div");
        info.className = "seed-info";
        info.innerHTML = `
            <strong>${seed.name || seed.url}</strong>
            <small>${seed.url}</small>
        `;

        const actions = document.createElement("div");
        actions.className = "seed-actions";
        
        const status = document.createElement("div");
        status.className = `seed-status ${seed.crawled ? 'success' : 'pending'}`;
        status.textContent = seed.crawled ? 'Crawled' : 'Pending';

        const delBtn = document.createElement("button");
        delBtn.className = "delete-btn";
        delBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
        delBtn.title = "Delete seed";
        delBtn.onclick = (e) => {
            e.stopPropagation();
            handleDeleteSeed(seed.id);
        };

        actions.appendChild(status);
        actions.appendChild(delBtn);
        
        item.appendChild(info);
        item.appendChild(actions);
        elements.seedList.appendChild(item);
    });
}

async function selectSeed(id) {
    if (state.selectedSeedId === id && elements.chatContainer.children.length > 0) return;
    
    state.selectedSeedId = id;
    const seed = state.seeds.find(s => s.id === id);
    if (!seed) return;

    elements.chatContainer.innerHTML = "";
    elements.currentInvTitle.textContent = seed.name || seed.url;
    elements.welcomeScreen.classList.add("hidden");

    addMessage("ai", `### Seed Content: ${seed.url}\n\n${seed.content || "This seed has not been crawled yet or has no content."}`);
    
    renderSeedList();
    if (window.innerWidth < 768) {
        elements.sidebar.classList.remove("open");
    }
}

function addMessage(role, content) {
    elements.welcomeScreen.classList.add("hidden");
    const msgDiv = document.createElement("div");
    msgDiv.className = `message message-${role}`;
    
    const avatar = document.createElement("img");
    avatar.className = "message-avatar";
    avatar.src = "frontend/assets/logo.jpeg";
    
    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";
    
    const header = document.createElement("div");
    header.className = "message-header";
    header.innerHTML = `<strong>${role === 'user' ? 'Analyst' : 'OBSCURA AI'}</strong>`;
    
    const body = document.createElement("div");
    body.className = "message-body";
    if (role === "ai") {
        body.innerHTML = formatMarkdown(content);
    } else {
        body.textContent = content;
    }

    const actions = document.createElement("div");
    actions.className = "message-actions";
    if (role === "user") {
        const editBtn = document.createElement("button");
        editBtn.className = "action-btn";
        editBtn.title = "Edit";
        editBtn.innerHTML = '<i class="fas fa-edit"></i>';
        editBtn.onclick = () => {
            elements.queryInput.value = content;
            elements.queryInput.focus();
        };
        actions.appendChild(editBtn);
    } else {
        const copyBtn = document.createElement("button");
        copyBtn.className = "action-btn";
        copyBtn.title = "Copy";
        copyBtn.innerHTML = '<i class="fas fa-copy"></i>';
        copyBtn.onclick = () => {
            navigator.clipboard.writeText(content);
            showToast("Copied to clipboard", "success");
        };

        const likeBtn = document.createElement("button");
        likeBtn.className = "action-btn";
        likeBtn.title = "Like";
        likeBtn.innerHTML = '<i class="fas fa-thumbs-up"></i>';
        likeBtn.onclick = () => {
            likeBtn.classList.toggle("active");
            showToast("Feedback received", "success");
        };

        const dislikeBtn = document.createElement("button");
        dislikeBtn.className = "action-btn";
        dislikeBtn.title = "Dislike";
        dislikeBtn.innerHTML = '<i class="fas fa-thumbs-down"></i>';
        dislikeBtn.onclick = () => {
            dislikeBtn.classList.toggle("active");
            showToast("Feedback received", "success");
        };

        const regenBtn = document.createElement("button");
        regenBtn.className = "action-btn";
        regenBtn.title = "Regenerate";
        regenBtn.innerHTML = '<i class="fas fa-rotate"></i>';
        regenBtn.onclick = () => {
            if (state.selectedSeedId) {
                handleSeedCrawl(state.selectedSeedId);
            } else {
                // Get query from the user message immediately preceding this AI message
                const userMsg = msgDiv.previousElementSibling;
                if (userMsg && userMsg.classList.contains('message-user')) {
                    const queryText = userMsg.querySelector('.message-body').textContent;
                    handleSearch(null, queryText);
                } else if (state.query) {
                    handleSearch(null, state.query);
                } else {
                    showToast("No query found to regenerate", "warning");
                }
            }
        };

        actions.appendChild(copyBtn);
        actions.appendChild(likeBtn);
        actions.appendChild(dislikeBtn);
        actions.appendChild(regenBtn);
    }
    
    contentDiv.appendChild(header);
    contentDiv.appendChild(body);
    contentDiv.appendChild(actions);
    
    msgDiv.appendChild(avatar);
    msgDiv.appendChild(contentDiv);
    elements.chatContainer.appendChild(msgDiv);
    elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
}

function formatMarkdown(text) {
    if (!text) return "";
    
    let html = text.trim();

    // Remove leading/trailing dashes or horizontal rules if they wrap the whole content
    html = html.replace(/^[\s\n]*---[\s\n]*/, '').replace(/[\s\n]*---[\s\n]*$/, '');

    // Headers
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    html = html.replace(/^#### (.*$)/gim, '<h4>$1</h4>');

    // Bold & Italic
    html = html.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/__(.*?)__/g, '<strong>$1</strong>');
    html = html.replace(/_(.*?)_/g, '<em>$1</em>');

    // Tables
    html = html.replace(/^\|(.+)\|$/gim, (match) => {
        const cells = match.split('|').filter(c => c.trim() !== '');
        if (match.includes('---')) return ''; // Skip separator rows
        return `<tr>${cells.map(c => `<td>${c.trim()}</td>`).join('')}</tr>`;
    });
    // Wrap table rows in <table>
    html = html.replace(/(<tr>(?:.|\n)*?<\/tr>)/g, '<table>$1</table>');
    // Fix multiple tables being created for adjacent rows
    html = html.replace(/<\/table>[\s\n]*<table>/g, '');

    // Lists
    html = html.replace(/^\s*[\-\*+]\s+(.*)$/gim, '<li>$1</li>');
    html = html.replace(/(<li>(?:.|\n)*?<\/li>)/g, '<ul>$1</ul>');
    html = html.replace(/<\/ul>[\s\n]*<ul>/g, '');

    html = html.replace(/^\s*\d+\.\s+(.*)$/gim, '<li>$1</li>');
    html = html.replace(/(<li>(?:.|\n)*?<\/li>)/g, '<ol>$1</ol>');
    html = html.replace(/<\/ol>[\s\n]*<ol>/g, '');

    // Paragraphs
    const lines = html.split('\n');
    html = lines.map(line => {
        if (line.trim() === '') return '';
        if (line.startsWith('<h') || line.startsWith('<ul') || line.startsWith('<ol') || line.startsWith('<table') || line.startsWith('<tr') || line.startsWith('<li')) {
            return line;
        }
        return `<p>${line}</p>`;
    }).join('\n');

    return html;
}

// --- Actions ---

async function handleSearch(e, queryOverride = null) {
    if (e) e.preventDefault();
    const query = queryOverride || elements.queryInput.value.trim();
    if (!query) return;

    if (!queryOverride) {
        addMessage("user", query);
        elements.queryInput.value = "";
    } else {
        // If we are regenerating, remove the last AI message (the error one)
        const lastMsg = elements.chatContainer.lastElementChild;
        if (lastMsg && lastMsg.classList.contains('message-ai')) {
            lastMsg.remove();
        }
    }
    
    state.query = query;
    elements.queryInput.style.height = "auto";
    
    setLoading(true);
    addMessage("ai", "Initializing investigation pipeline...");
    const aiMsgElement = elements.chatContainer.lastElementChild.querySelector(".message-body");

    investigationAbortController = new AbortController();

    const payload = {
        query,
        model: state.selectedModel,
        preset: state.selectedPreset,
        threads: state.threads,
        max_results: state.maxResults,
        max_scrape: state.maxScrape,
        max_content_chars: state.maxContentChars,
    };

    const steps = [
        { key: 'refining', label: 'Refine' },
        { key: 'searching', label: 'Search' },
        { key: 'filtering', label: 'Filter' },
        { key: 'scraping', label: 'Scrape' },
        { key: 'generating', label: 'Report' }
    ];

    const getActiveStep = (status) => {
        const s = status.toLowerCase();
        if (s.includes('refining')) return 0;
        if (s.includes('searching')) return 1;
        if (s.includes('filtering')) return 2;
        if (s.includes('scraping')) return 3;
        if (s.includes('generating')) return 4;
        return 0;
    };

    try {
        const response = await fetch(API.investigate, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            signal: investigationAbortController.signal
        });

        if (!response.ok) {
            const errorText = await response.text();
            let errorMessage = errorText;
            try {
                const errorObj = JSON.parse(errorText);
                errorMessage = errorObj.error || errorText;
            } catch(e) {}
            throw new Error(errorMessage || response.statusText);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const data = JSON.parse(line.substring(6));
                    if (data.error) {
                        throw new Error(data.error);
                    }
                    if (data.done) {
                        state.runResult = data;
                        state.selectedInvestigationId = data.id || data.inv_id;
                        aiMsgElement.innerHTML = formatMarkdown(data.summary);
                        elements.currentInvTitle.textContent = query;
                        await reloadInvestigations();
                        
                        // Show completion modal
                        openModal(elements.completionModal);
                    } else if (data.status) {
                        const activeIndex = getActiveStep(data.status);
                        
                        const stepperHtml = steps.map((step, i) => `
                            <div class="step ${i === activeIndex ? 'active' : (i < activeIndex ? 'completed' : '')}">
                                <div class="step-dot">${i < activeIndex ? '<i class="fas fa-check"></i>' : (i + 1)}</div>
                                <span class="step-label">${step.label}</span>
                            </div>
                        `).join('');

                        aiMsgElement.innerHTML = `
                            <div class="investigation-status-container">
                                <div class="loading-card">
                                    <div class="loading-header">
                                        <div class="loading-title-group">
                                            <p class="loading-title">Investigation in Progress</p>
                                            <p class="loading-subtitle">${data.status}</p>
                                        </div>
                                        <div class="loading-spinner-container">
                                            <div class="circular-loader"></div>
                                        </div>
                                    </div>
                                    
                                    <div class="progress-stepper">
                                        ${stepperHtml}
                                    </div>

                                    <div class="skeleton-container">
                                        <div class="skeleton skeleton-title"></div>
                                        <div class="skeleton skeleton-line"></div>
                                        <div class="skeleton skeleton-line"></div>
                                        <div class="skeleton skeleton-line short"></div>
                                    </div>
                                </div>
                            </div>
                        `;
                    }
                }
            }
        }
    } catch (error) {
        if (error.name === 'AbortError') {
            aiMsgElement.innerHTML = `<span style="color: #f59e0b"><i class="fas fa-exclamation-triangle"></i> Investigation stopped by user.</span>`;
            showToast("Investigation stopped", "warning");
        } else {
            aiMsgElement.innerHTML = `<span style="color: #ef4444">Error: ${error.message}</span>`;
            showToast(error.message, "error");
        }
    } finally {
        setLoading(false);
        investigationAbortController = null;
    }
}

async function selectInvestigation(id) {
    if (state.selectedInvestigationId === id && elements.chatContainer.children.length > 1) return;
    
    state.runResult = null; // Clear recent run result when selecting a history item
    
    // Check if we already have the full investigation data in state
    const cachedInv = state.investigations.find(inv => inv.id === id);
    
    const loadInv = (inv) => {
        state.loadedInvestigation = inv;
        state.selectedInvestigationId = id;
        state.selectedSeedId = null;
        
        elements.chatContainer.innerHTML = "";
        elements.currentInvTitle.textContent = inv.query;
        
        addMessage("user", inv.query);
        addMessage("ai", inv.summary);
        
        renderInvestigationList();
        if (window.innerWidth < 768) {
            elements.sidebar.classList.remove("open");
        }
    };

    if (cachedInv && cachedInv.summary) {
        loadInv(cachedInv);
        return;
    }

    try {
        const inv = await fetchJSON(`${API.investigations}/${id}`);
        // Update the item in the investigations list so it's cached for next time
        const index = state.investigations.findIndex(i => i.id === id);
        if (index !== -1) {
            state.investigations[index] = inv;
        }
        loadInv(inv);
    } catch (error) {
        showToast("Failed to load investigation", "error");
    }
}

async function reloadInvestigations() {
    const data = await fetchJSON(API.investigations);
    state.investigations = data.investigations || [];
    renderInvestigationList();
}

async function handleSeedCrawl(id) {
    showToast("Re-crawling seed...", "info");
    try {
        const res = await fetchJSON(`${API.seeds}/${id}/crawl`, { method: "POST" });
        if (res.result) {
            showToast("Seed crawled successfully", "success");
            const data = await fetchJSON(API.seeds);
            state.seeds = data.seeds || [];
            selectSeed(id);
        }
    } catch (e) {
        showToast("Crawl failed: " + e.message, "error");
    }
}

async function handleDeleteInvestigation(id) {
    if (!confirm("Are you sure you want to delete this investigation?")) return;
    try {
        await fetchJSON(`${API.investigations}/${id}`, { method: "DELETE" });
        showToast("Investigation deleted", "success");
        if (state.selectedInvestigationId === id) {
            elements.newChatBtn.click();
        }
        await reloadInvestigations();
    } catch (e) {
        showToast("Delete failed: " + e.message, "error");
    }
}

async function handleDeleteSeed(id) {
    if (!confirm("Are you sure you want to delete this seed?")) return;
    try {
        await fetchJSON(`${API.seeds}/${id}`, { method: "DELETE" });
        showToast("Seed deleted", "success");
        if (state.selectedSeedId === id) {
            state.selectedSeedId = null;
            elements.chatContainer.innerHTML = "";
            elements.welcomeScreen.classList.remove("hidden");
        }
        const data = await fetchJSON(API.seeds);
        state.seeds = data.seeds || [];
        renderSeedList();
    } catch (e) {
        showToast("Delete failed: " + e.message, "error");
    }
}

// --- Event Listeners ---

function setupEventListeners() {
    // Mobile Sidebar toggle (hamburger)
    elements.sidebarToggle.onclick = () => {
        elements.sidebar.classList.toggle("open");
    };

    // Desktop Sidebar collapse
    elements.sidebarCollapseBtn.onclick = () => {
        const isCollapsed = elements.sidebar.classList.toggle("collapsed");
        localStorage.setItem("obscura-sidebar-collapsed", isCollapsed);
    };

    // Reload app when clicking the OBSCURA brand title
    if (elements.brandReload) {
        elements.brandReload.onclick = () => {
            window.location.reload();
        };
    }

    // New Chat
    elements.newChatBtn.onclick = () => {
        state.loadedInvestigation = null;
        state.selectedInvestigationId = null;
        state.selectedSeedId = null;
        elements.chatContainer.innerHTML = "";
        elements.chatContainer.appendChild(elements.welcomeScreen);
        elements.welcomeScreen.classList.remove("hidden");
        elements.currentInvTitle.textContent = "New Investigation";
        renderInvestigationList();
    };

    // Search investigations
    elements.invSearchInput.oninput = (e) => {
        renderInvestigationList(e.target.value);
    };

    // Modals
    elements.openConfigBtn.onclick = () => openModal(elements.configModal);
    elements.openHealthBtn.onclick = () => openModal(elements.healthModal);
    elements.openSeedsBtn.onclick = () => {
        openModal(elements.seedsModal);
        refreshSeedsFromServer();
        startSeedRefreshTimer();
    };

    elements.closeModalBtns.forEach(btn => {
        btn.onclick = () => {
            closeModal(elements.configModal);
            closeModal(elements.healthModal);
            closeModal(elements.seedsModal);
            closeModal(elements.completionModal);
            closeProviderKeyModal();
            stopSeedRefreshTimer();
        };
    });

    const providerKeyModal = getEl("providerKeyModal");
    const providerKeySaveBtn = getEl("providerKeySaveBtn");
    const providerKeyCancelBtn = getEl("providerKeyCancelBtn");
    const providerKeyInput = getEl("providerKeyInput");
    if (providerKeySaveBtn) providerKeySaveBtn.onclick = saveProviderKey;
    if (providerKeyCancelBtn) providerKeyCancelBtn.onclick = closeProviderKeyModal;
    if (providerKeyInput) {
        providerKeyInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                saveProviderKey();
            } else if (e.key === "Escape") {
                closeProviderKeyModal();
            }
        });
    }

    window.onclick = (e) => {
        if (e.target === elements.configModal) closeModal(elements.configModal);
        if (e.target === elements.healthModal) closeModal(elements.healthModal);
        if (e.target === elements.seedsModal) closeModal(elements.seedsModal);
        if (e.target === elements.completionModal) closeModal(elements.completionModal);
        if (e.target === providerKeyModal) closeProviderKeyModal();
        if (e.target === elements.seedsModal) stopSeedRefreshTimer();
        
        // Close model dropdown when clicking outside
        if (!elements.modelSelector.contains(e.target)) {
            elements.modelDropdown.classList.add("hidden");
            elements.modelSelector.classList.remove("open");
        }
    };

    // Model Selector
    elements.currentModelBtn.onclick = (e) => {
        e.stopPropagation();
        const isOpen = elements.modelSelector.classList.toggle("open");
        elements.modelDropdown.classList.toggle("hidden", !isOpen);
    };

    // Completion Modal Actions
    elements.completionReviewBtn.onclick = () => {
        closeModal(elements.completionModal);
        elements.chatContainer.scrollTop = elements.chatContainer.scrollHeight;
    };

    elements.completionPdfBtn.onclick = () => {
        closeModal(elements.completionModal);
        elements.exportPdfBtn.click();
    };

    elements.completionMdBtn.onclick = () => {
        closeModal(elements.completionModal);
        elements.exportMdBtn.click();
    };

    // Theme Toggle
    elements.themeToggle.onclick = () => {
        setTheme(state.theme === "light" ? "dark" : "light");
    };

    // Config Form
    elements.modelSelect.onchange = (e) => selectModel(e.target.value);
    elements.threadsInput.oninput = (e) => {
        state.threads = e.target.value;
        elements.threadsValue.textContent = e.target.value;
    };
    elements.maxResultsInput.oninput = (e) => {
        state.maxResults = e.target.value;
        elements.maxResultsValue.textContent = e.target.value;
    };
    elements.presetSelect.onchange = (e) => {
        state.selectedPreset = e.target.value;
        updateCustomPresetFields();
    };

    // Search Form
    elements.searchForm.onsubmit = handleSearch;
    elements.stopBtn.onclick = () => {
        if (investigationAbortController) {
            investigationAbortController.abort();
        }
    };
    elements.queryInput.onkeydown = (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSearch();
        }
    };
    elements.queryInput.oninput = () => {
        elements.queryInput.style.height = "auto";
        elements.queryInput.style.height = elements.queryInput.scrollHeight + "px";
    };

    // Suggested Prompts
    document.querySelectorAll(".prompt-suggestion").forEach(btn => {
        btn.onclick = () => {
            elements.queryInput.value = btn.textContent;
            handleSearch();
        };
    });

    // Exports
    elements.exportPdfBtn.onclick = async () => {
        let content = null;
        let metadata = {
            query: "Seed Content",
            refined_query: "",
            model: "N/A",
            preset: "N/A",
            sources: [],
        };

        if (state.selectedSeedId) {
            const seed = state.seeds.find(s => s.id === state.selectedSeedId);
            if (seed) {
                content = seed.content;
                metadata.query = seed.name || seed.url;
            }
        } else {
            const activeInv = state.runResult || state.loadedInvestigation;
            if (activeInv) {
                content = activeInv.summary;
                metadata = {
                    query: activeInv.query,
                    refined_query: activeInv.refined_query,
                    model: activeInv.model,
                    preset: activeInv.preset,
                    sources: activeInv.sources || [],
                    timestamp: activeInv.timestamp,
                    status: activeInv.status,
                    tags: activeInv.tags,
                };
            }
        }

        if (!content) return showToast("No content available to export", "warning");

        showToast("Generating PDF...");
        try {
            const payload = {
                summary: content,
                metadata: metadata,
            };
            const response = await fetch(API.exportPdf, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: "Unknown server error" }));
                throw new Error(errorData.error || "PDF export failed");
            }
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `obscura_report_${new Date().toISOString().slice(0, 10)}.pdf`;
            a.click();
            URL.revokeObjectURL(url);
            showToast("PDF downloaded", "success");
        } catch (error) {
            showToast(`PDF download failed: ${error.message}`, "error");
        }
    };

    elements.exportMdBtn.onclick = () => {
        let content = null;
        let filename = "summary";

        if (state.selectedSeedId) {
            const seed = state.seeds.find(s => s.id === state.selectedSeedId);
            if (seed) {
                content = seed.content;
                filename = (seed.name || "seed").replace(/[^a-z0-9]/gi, '_').toLowerCase();
            }
        } else {
            const activeInv = state.runResult || state.loadedInvestigation;
            if (activeInv) {
                content = activeInv.summary;
                filename = activeInv.query.replace(/[^a-z0-9]/gi, '_').toLowerCase();
            }
        }

        if (!content) return showToast("No content available to export", "warning");

        const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `${filename}_${new Date().toISOString().slice(0, 10)}.md`;
        link.click();
        URL.revokeObjectURL(link.href);
        showToast("Markdown downloaded", "success");
    };

    // Health Checks
    elements.checkLlmBtn.onclick = async () => {
        elements.healthOutput.innerHTML = "Checking LLM...";
        try {
            const res = await fetchJSON(API.healthLLM, {
                method: "POST",
                body: JSON.stringify({ model: state.selectedModel })
            });
            elements.healthOutput.innerHTML = res.status.join("<br>");
        } catch (e) {
            elements.healthOutput.innerHTML = "Error: " + e.message;
        }
    };

    elements.checkSearchBtn.onclick = async () => {
        elements.healthOutput.innerHTML = "Checking Search Engines...";
        try {
            const res = await fetchJSON(API.healthSearch, { method: "POST" });
            elements.healthOutput.innerHTML = res.status.join("<br>");
        } catch (e) {
            elements.healthOutput.innerHTML = "Error: " + e.message;
        }
    };

    if (elements.torNewnymBtn) {
        elements.torNewnymBtn.onclick = async () => {
            elements.healthOutput.innerHTML = "Requesting a new Tor circuit...";
            try {
                const res = await fetchJSON(API.torNewnym, { method: "POST" });
                let line = res.message || res.status || "Done.";
                if (res.exit_ip) line += `<br>New exit IP: ${res.exit_ip}`;
                elements.healthOutput.innerHTML = line;
                showToast(res.status === "ok" ? "New Tor identity established." : (res.message || "Tor request failed."),
                          res.status === "ok" ? "success" : "error");
            } catch (e) {
                elements.healthOutput.innerHTML = "Error: " + e.message;
            }
        };
    }

    // Seeds
    elements.addSeedBtn.onclick = async () => {
        const url = elements.seedUrlInput.value.trim();
        const name = elements.seedLabelInput.value.trim();
        if (!url) return;
        try {
            const result = await fetchJSON(API.seeds, {
                method: "POST",
                body: JSON.stringify({ url, name })
            });
            const newSeed = result.seed;
            if (newSeed) {
                state.seeds.unshift(newSeed);
            }
            elements.seedUrlInput.value = "";
            elements.seedLabelInput.value = "";
            showToast("Seed added");
            renderSeedList();
            if (newSeed && !newSeed.crawled) {
                startSeedRefreshTimer();
            }
        } catch (e) {
            showToast(e.message, "error");
        }
    };

    elements.seedFilterSelect.onchange = (e) => {
        state.seedFilter = e.target.value;
        renderSeedList();
    };

    // Create Preset / Domain
    if (elements.createPresetBtn) {
        elements.createPresetBtn.addEventListener('click', async () => {
            const name = elements.newPresetName.value.trim();
            const system_prompt = elements.newPresetPrompt.value.trim();
            
            console.log("Adding domain:", name);

            if (!name || !system_prompt) {
                showToast("Domain name and prompt are required", "warning");
                return;
            }

            elements.createPresetBtn.disabled = true;
            const originalText = elements.createPresetBtn.textContent;
            elements.createPresetBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Adding...';

            try {
                const res = await fetchJSON(API.presets, {
                    method: "POST",
                    body: JSON.stringify({ name, system_prompt })
                });
                
                console.log("Domain added response:", res);

                elements.newPresetName.value = "";
                elements.newPresetPrompt.value = "";
                showToast(`Domain "${name}" added successfully`, "success");
                
                // Immediately update local state and render before reloading everything
                if (res.preset) {
                    state.presets.push(res.preset);
                    state.selectedPreset = res.preset.key;
                    renderPresetOptions();
                }

                // Still reload the full state in the background to be sure
                reloadAppState();
            } catch (e) {
                console.error("Failed to add domain:", e);
                showToast("Error: " + e.message, "error");
            } finally {
                elements.createPresetBtn.disabled = false;
                elements.createPresetBtn.textContent = originalText;
            }
        });
    }

    // Save existing preset
    if (elements.savePresetBtn) {
        elements.savePresetBtn.addEventListener('click', async () => {
            if (!state.selectedPresetMeta || !state.selectedPresetMeta.id) return;
            const system_prompt = elements.customPrompt.value.trim();
            try {
                await fetchJSON(`${API.presets}/${state.selectedPresetMeta.id}`, {
                    method: "PUT",
                    body: JSON.stringify({ system_prompt })
                });
                showToast("Domain updated", "success");
                await reloadAppState();
            } catch (e) {
                showToast(e.message, "error");
            }
        });
    }

    // Delete existing preset
    if (elements.deletePresetBtn) {
        elements.deletePresetBtn.addEventListener('click', async () => {
            if (!state.selectedPresetMeta || !state.selectedPresetMeta.id) return;
            if (!confirm("Are you sure you want to delete this custom domain?")) return;
            try {
                await fetchJSON(`${API.presets}/${state.selectedPresetMeta.id}`, {
                    method: "DELETE"
                });
                showToast("Domain deleted", "success");
                state.selectedPreset = "";
                await reloadAppState();
            } catch (e) {
                showToast(e.message, "error");
            }
        });
    }
}

// Start the app
init();