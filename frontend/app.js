// ========================================
// Video2Gyaan — App Logic
// ========================================

document.addEventListener('DOMContentLoaded', () => {

    // --- Elements ---
    const htmlEl       = document.documentElement;
    const themeBtn     = document.getElementById('theme-toggle');
    const iconSun      = document.getElementById('icon-sun');
    const iconMoon     = document.getElementById('icon-moon');

    const urlInput     = document.getElementById('youtube-url');
    const urlError     = document.getElementById('url-error');

    const videoPreview = document.getElementById('video-preview');
    const videoThumb   = document.getElementById('video-thumbnail');
    const videoTitle   = document.getElementById('video-title');
    const videoIdEl    = document.getElementById('video-id-display');


    const selLanguage  = document.getElementById('sel-language');
    const chipTones    = document.querySelectorAll('#chip-tone .chip');
    const chipPlatforms = document.querySelectorAll('#chip-platform .chip');

    const btnGo        = document.getElementById('btn-summarize');

    const loadingEl    = document.getElementById('loading-indicator');
    const loadingText  = document.getElementById('loading-text');

    const outputActs   = document.getElementById('output-actions');
    const btnCopy      = document.getElementById('btn-copy');
    const btnShare     = document.getElementById('btn-share');

    const emptyState   = document.getElementById('empty-state');
    const summaryEl    = document.getElementById('summary-content');
    const toast        = document.getElementById('toast');
    const historyList  = document.getElementById('history-list');

    // Share modal
    const shareOverlay    = document.getElementById('share-modal-overlay');
    const shareClose      = document.getElementById('share-modal-close');
    const shareLinkInput  = document.getElementById('share-link-input');
    const btnCopyLink     = document.getElementById('btn-copy-link');
    const shareGenerating = document.getElementById('share-generating');

    // --- State ---
    let currentVideoId = null;
    let isGenerating   = false;
    let currentSummaryMd = '';   
    let currentShareId   = null; 
    
    let generationConfig = {
        language: 'English',
        tone: 'Professional 💼',
        platform: 'Summary'
    };

    // --- Analytics Helper ---
    function trackEvent(eventName, params = {}) {
        if (window.logFirebaseEvent && window.firebaseAnalytics) {
            window.logFirebaseEvent(window.firebaseAnalytics, eventName, params);
        }
    }

    // --- Marked.js ---
    marked.setOptions({ gfm: true, breaks: true });

    // --- History ---
    const MAX_HISTORY = 5;

    function getHistory() {
        try {
            return JSON.parse(localStorage.getItem('v2g-history')) || [];
        } catch { return []; }
    }

    function saveToHistory(vid, title, summary, url) {
        let h = getHistory();
        // Remove existing to place it at the top
        h = h.filter(x => x.vid !== vid);
        h.unshift({ vid, title, summary, url });
        if (h.length > MAX_HISTORY) h = h.slice(0, MAX_HISTORY);
        localStorage.setItem('v2g-history', JSON.stringify(h));
        renderHistory();
    }

    function renderHistory() {
        const h = getHistory();
        if (h.length === 0) {
            historyList.innerHTML = '<li class="history-empty">No recent summaries</li>';
            return;
        }
        
        historyList.innerHTML = '';
        h.forEach(item => {
            const li = document.createElement('li');
            li.className = 'history-item';
            
            const title = document.createElement('div');
            title.className = 'history-title';
            title.textContent = item.title || 'Unknown Title';
            
            const urlEl = document.createElement('div');
            urlEl.className = 'history-url';
            urlEl.textContent = item.url || '';
            
            li.appendChild(title);
            li.appendChild(urlEl);
            
            li.addEventListener('click', () => {
                urlInput.value = item.url;
                currentVideoId = item.vid;
                showPreview(item.vid);
                render(item.summary);
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
            
            historyList.appendChild(li);
        });
    }

    // Initial render
    renderHistory();

    // --- Theme ---
    function initTheme() {
        const saved = localStorage.getItem('v2g-theme');
        if (saved) { setTheme(saved); return; }
        if (window.matchMedia?.('(prefers-color-scheme: light)').matches) setTheme('light');
    }

    function setTheme(t) {
        htmlEl.setAttribute('data-theme', t);
        localStorage.setItem('v2g-theme', t);
        iconSun.style.display  = t === 'light' ? 'none'  : 'block';
        iconMoon.style.display = t === 'light' ? 'block' : 'none';
    }

    themeBtn.addEventListener('click', () => {
        const newTheme = htmlEl.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
        setTheme(newTheme);
        trackEvent('theme_toggled', { theme: newTheme });
    });

    initTheme();


    selLanguage.addEventListener('change', (e) => {
        generationConfig.language = e.target.value;
        trackEvent('language_changed', { language: generationConfig.language });
    });

    function setupChips(chips, configKey) {
        chips.forEach(chip => {
            chip.addEventListener('click', () => {
                if (isGenerating) return;
                chips.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                generationConfig[configKey] = chip.dataset.val;
                trackEvent(`${configKey}_changed`, { value: generationConfig[configKey] });
            });
        });
    }

    setupChips(chipTones, 'tone');
    setupChips(chipPlatforms, 'platform');

    // --- URL Parsing ---
    function extractVideoId(url) {
        const patterns = [
            /(?:v=|\/)([A-Za-z0-9_-]{11})/,
            /(?:embed\/)([A-Za-z0-9_-]{11})/,
            /youtu\.be\/([A-Za-z0-9_-]{11})/,
            /^([A-Za-z0-9_-]{11})$/
        ];
        for (const p of patterns) {
            const m = url.trim().match(p);
            if (m) return m[1];
        }
        return null;
    }

    let debounce;
    urlInput.addEventListener('input', () => {
        const url = urlInput.value.trim();
        urlInput.classList.remove('has-error');
        urlError.textContent = '';

        if (!url) {
            videoPreview.style.display = 'none';
            currentVideoId = null;
            return;
        }

        const vid = extractVideoId(url);
        if (!vid) {
            urlInput.classList.add('has-error');
            urlError.textContent = 'Invalid YouTube URL';
            videoPreview.style.display = 'none';
            currentVideoId = null;
            return;
        }

        if (vid !== currentVideoId) {
            currentVideoId = vid;
            showPreview(vid);
        }
    });

    function showPreview(vid) {
        videoThumb.src = `https://img.youtube.com/vi/${vid}/mqdefault.jpg`;
        videoTitle.textContent = 'Loading title...';
        videoIdEl.textContent  = vid;
        videoPreview.style.display = 'flex';

        clearTimeout(debounce);
        debounce = setTimeout(async () => {
            try {
                const r = await fetch(`https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v=${vid}&format=json`);
                videoTitle.textContent = r.ok ? (await r.json()).title : 'Title unavailable';
            } catch {
                videoTitle.textContent = 'Title unavailable';
            }
        }, 500);
    }

    // --- Summarize ---
    btnGo.addEventListener('click', async () => {
        if (isGenerating) return;

        const url = urlInput.value.trim();
        if (!url)           { showErr('Please enter a YouTube URL'); return; }
        if (!currentVideoId){ showErr('Invalid YouTube URL'); return; }

        trackEvent('summary_requested', { video_id: currentVideoId, config: generationConfig });
        begin();

        try {
            setTimeout(() => { if (isGenerating) loadingText.textContent = 'Generating with Gemini AI...'; }, 1500);

            const res  = await fetch('/summarize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ youtube_url: url, generationConfig: generationConfig })
            });

            if (!res.ok) {
                const data = await res.json();
                trackEvent('summary_error', { video_id: currentVideoId, error: data.detail });
                render(`**Error:** ${data.detail || 'Unknown error'}`);
                return;
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let summaryText = "";
            
            // Prepare UI for streaming output
            loadingEl.style.display = 'none';
            emptyState.style.display = 'none';
            summaryEl.style.display = 'block';
            outputActs.style.display = 'flex';
            summaryEl.innerHTML = '<span class="typing-cursor"></span>';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunkStr = decoder.decode(value, { stream: true });
                const lines = chunkStr.split("\n");
                
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            if (data.type === 'chunk') {
                                summaryText += data.text;
                                summaryEl.innerHTML = marked.parse(summaryText);
                            } else if (data.type === 'error') {
                                summaryText += `\n\n**Error:** ${data.detail}`;
                                summaryEl.innerHTML = marked.parse(summaryText);
                            } else if (data.type === 'done') {
                                trackEvent('summary_completed', { video_id: currentVideoId, config: generationConfig });
                                currentSummaryMd = summaryText;
                                currentShareId = null; // reset cached share ID for new summary
                                saveToHistory(currentVideoId, videoTitle.textContent, summaryText, url);
                            }
                        } catch (e) {}
                    }
                }
            }
        } catch (e) {
            trackEvent('summary_error', { video_id: currentVideoId, error: 'Connection Error' });
            render('**Connection Error:** Make sure the backend is running.');
        } finally {
            end();
        }
    });

    function showErr(msg) {
        urlInput.classList.add('has-error');
        urlError.textContent = msg;
    }

    function begin() {
        isGenerating = true;
        btnGo.disabled = true;
        urlInput.disabled = true;
        emptyState.style.display    = 'none';
        summaryEl.style.display     = 'none';
        outputActs.style.display    = 'none';
        loadingEl.style.display     = 'flex';
        loadingText.textContent     = 'Fetching transcript...';
    }

    function end() {
        isGenerating = false;
        btnGo.disabled = false;
        urlInput.disabled = false;
        loadingEl.style.display = 'none';
    }

    function render(md) {
        summaryEl.innerHTML      = marked.parse(md);
        summaryEl.style.display  = 'block';
        outputActs.style.display = 'flex';
        emptyState.style.display = 'none';
    }

    // --- Share ---
    function openShareModal() {
        shareOverlay.classList.add('open');
    }
    function closeShareModal() {
        shareOverlay.classList.remove('open');
    }

    shareClose.addEventListener('click', closeShareModal);
    shareOverlay.addEventListener('click', (e) => {
        if (e.target === shareOverlay) closeShareModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeShareModal();
    });

    btnShare.addEventListener('click', async () => {
        if (!currentSummaryMd) return;

        openShareModal();

        // Reuse cached share ID if available
        if (currentShareId) {
            shareLinkInput.value = `${window.location.origin}/s/${currentShareId}`;
            return;
        }

        // Show generating state
        shareLinkInput.value = '';
        shareGenerating.classList.add('active');
        btnCopyLink.disabled = true;

        try {
            const res = await fetch('/share', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    summary_md: currentSummaryMd,
                    video_id: currentVideoId,
                    video_title: videoTitle.textContent,
                    tone: generationConfig.tone,
                    youtube_url: urlInput.value.trim()
                })
            });

            if (!res.ok) throw new Error('Share failed');
            const data = await res.json();
            currentShareId = data.share_id;
            const shareUrl = `${window.location.origin}/s/${currentShareId}`;
            shareLinkInput.value = shareUrl;
            trackEvent('summary_shared', { video_id: currentVideoId, share_id: currentShareId });
        } catch (err) {
            showToast('Could not generate share link');
            closeShareModal();
        } finally {
            shareGenerating.classList.remove('active');
            btnCopyLink.disabled = false;
        }
    });

    btnCopyLink.addEventListener('click', () => {
        const url = shareLinkInput.value;
        if (!url) return;
        navigator.clipboard.writeText(url).then(() => {
            btnCopyLink.textContent = 'Copied!';
            btnCopyLink.classList.add('copied');
            setTimeout(() => {
                btnCopyLink.textContent = 'Copy';
                btnCopyLink.classList.remove('copied');
            }, 2000);
            showToast('Share link copied! 🎉');
        }).catch(() => showToast('Copy failed'));
    });

    // --- Copy ---
    btnCopy.addEventListener('click', () => {
        const t = summaryEl.innerText;
        if (!t) return;
        navigator.clipboard.writeText(t)
            .then(() => {
                showToast('Copied to clipboard');
                trackEvent('summary_copied', { video_id: currentVideoId });
            })
            .catch(() => showToast('Copy failed'));
    });

    // --- Toast ---
    let toastTimer;
    function showToast(msg) {
        toast.textContent = msg;
        toast.classList.add('show');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.remove('show'), 2400);
    }
});
