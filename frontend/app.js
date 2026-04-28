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

    const toneTabs     = document.querySelectorAll('.tone-btn');
    const btnGo        = document.getElementById('btn-summarize');

    const loadingEl    = document.getElementById('loading-indicator');
    const loadingText  = document.getElementById('loading-text');

    const outputActs   = document.getElementById('output-actions');
    const btnCopy      = document.getElementById('btn-copy');

    const emptyState   = document.getElementById('empty-state');
    const summaryEl    = document.getElementById('summary-content');
    const toast        = document.getElementById('toast');

    // --- State ---
    let currentTone    = 'Hook';
    let currentVideoId = null;
    let isGenerating   = false;

    // --- Analytics Helper ---
    function trackEvent(eventName, params = {}) {
        if (window.logFirebaseEvent && window.firebaseAnalytics) {
            window.logFirebaseEvent(window.firebaseAnalytics, eventName, params);
        }
    }

    // --- Marked.js ---
    marked.setOptions({ gfm: true, breaks: true });

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

    // --- Tones ---
    toneTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            if (isGenerating) return;
            toneTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentTone = tab.dataset.tone;
            trackEvent('tone_changed', { tone: currentTone });
        });
    });

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

        trackEvent('summary_requested', { video_id: currentVideoId, tone: currentTone });
        begin();

        try {
            setTimeout(() => { if (isGenerating) loadingText.textContent = 'Generating with Gemini AI...'; }, 1500);

            const res  = await fetch('/summarize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ youtube_url: url, tone: currentTone })
            });
            const data = await res.json();
            
            if (res.ok) {
                trackEvent('summary_completed', { video_id: currentVideoId, tone: currentTone });
                render(data.summary || 'No summary.');
            } else {
                trackEvent('summary_error', { video_id: currentVideoId, error: data.detail });
                render(`**Error:** ${data.detail || 'Unknown error'}`);
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

    // --- Copy ---
    btnCopy.addEventListener('click', () => {
        const t = summaryEl.innerText;
        if (!t) return;
        navigator.clipboard.writeText(t)
            .then(() => {
                showToast('Copied to clipboard');
                trackEvent('summary_copied', { video_id: currentVideoId, tone: currentTone });
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
