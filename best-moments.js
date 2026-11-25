(() => {
  'use strict';
  const panel = document.querySelector('#clipper .creator-panel');
  if (!panel || document.querySelector('#bestMomentsPanel')) return;

  const style = document.createElement('style');
  style.textContent = `
    .best-moments-panel{margin:0 20px 20px;padding:18px;border:1px solid #392b45;border-radius:16px;background:#151219;color:#f7f4fa}
    .best-moments-panel label,.best-moments-panel button{font:inherit}
    .best-moments-panel .ai-toggle{display:flex;align-items:center;gap:10px;font-weight:700;cursor:pointer}
    .best-moments-panel .ai-toggle input{accent-color:#a855f7;width:18px;height:18px}
    .best-moments-panel .ai-import{display:grid;grid-template-columns:1fr auto;gap:9px;margin-top:14px}
    .best-moments-panel input[type=url]{min-width:0;padding:12px;border:1px solid #39333e;border-radius:10px;background:#0d0c0f;color:#fff}
    .best-moments-panel button{padding:10px 14px;border:0;border-radius:10px;background:#a855f7;color:#fff;font-weight:700;cursor:pointer}
    .best-moments-panel button:disabled{opacity:.55;cursor:wait}
    .best-moments-panel .ai-note,.best-moments-panel .ai-status{margin:10px 0 0;color:#b8adbd;font-size:13px}
    .best-moments-panel .moment-list{display:grid;gap:10px;margin-top:14px}
    .best-moments-panel .moment-card{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:8px;padding:12px;border:1px solid #332c38;border-radius:12px}
    .best-moments-panel .moment-card small{display:block;color:#b8adbd;margin-top:4px}
    .best-moments-panel .moment-card .secondary{background:#29242e}
    @media(max-width:600px){.best-moments-panel{margin:0 12px 14px;padding:14px}.best-moments-panel .ai-import{grid-template-columns:1fr}.best-moments-panel .moment-card{grid-template-columns:1fr 1fr}.best-moments-panel .moment-card strong{grid-column:1/-1}.best-moments-panel .moment-card button{width:100%}}
  `;
  document.head.append(style);
  const section = document.createElement('section');
  section.className = 'best-moments-panel';
  section.id = 'bestMomentsPanel';
  section.innerHTML = `
    <label class="ai-toggle"><input id="useAiBestMoments" type="checkbox"> USE AI TO FIND BEST MOMENTS</label>
    <p class="ai-note">Off by default. When enabled, free audio-energy and available caption analysis finds up to four non-overlapping 15–30 second clips. Use videos you have permission to process.</p>
    <div class="ai-import"><input id="aiVideoUrl" type="url" placeholder="Public YouTube or TikTok URL" aria-label="Video URL"><button id="aiFindButton" type="button">Import video</button></div>
    <p class="ai-status" id="aiMomentStatus" role="status" aria-live="polite"></p>
    <div class="moment-list" id="aiMomentResults"></div>`;
  const generatorGrid = panel.querySelector('.generator-grid');
  (generatorGrid || panel).insertAdjacentElement('afterend', section);

  const toggle = section.querySelector('#useAiBestMoments');
  const urlInput = section.querySelector('#aiVideoUrl');
  const button = section.querySelector('#aiFindButton');
  const status = section.querySelector('#aiMomentStatus');
  const results = section.querySelector('#aiMomentResults');
  let apiBase = localStorage.getItem('clips-api-base') || '';
  let jobId = '';
  const formatTime = (seconds) => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  const setStatus = (message) => { status.textContent = message; };
  const api = (path) => `${apiBase.replace(/\/$/, '')}${path}`;

  async function request(path, options) {
    const response = await fetch(api(path), options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  async function analyze() {
    if (!toggle.checked) return;
    if (!urlInput.value.trim()) { setStatus('Paste a video URL first.'); return; }
    if (!apiBase) {
      apiBase = window.prompt('Enter your deployed FastAPI HTTPS URL (for example, https://your-service.onrender.com):', '');
      if (!apiBase) { setStatus('Set the backend URL to use AI moment analysis.'); return; }
      apiBase = apiBase.trim();
      localStorage.setItem('clips-api-base', apiBase);
    }
    button.disabled = true;
    results.replaceChildren();
    try {
      setStatus('Importing video…');
      const imported = await request('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: urlInput.value.trim() }) });
      jobId = imported.job_id;
      setStatus('Analyzing audio peaks and available captions…');
      const analysis = await request(`/api/import/${jobId}/best-moments`, { method: 'POST' });
      setStatus(`AI found ${analysis.count} best moments · ${analysis.method}.`);
      analysis.moments.forEach((moment, index) => {
        const card = document.createElement('article');
        card.className = 'moment-card';
        const description = document.createElement('strong');
        description.textContent = `AI Found ${analysis.count} Best Moments — ${formatTime(moment.start)}–${formatTime(moment.end)}`;
        const detail = document.createElement('small');
        detail.textContent = `${moment.reason} · Score ${moment.score}`;
        description.append(detail);
        const preview = document.createElement('button');
        preview.type = 'button'; preview.className = 'secondary'; preview.textContent = 'Preview';
        const download = document.createElement('button');
        download.type = 'button'; download.textContent = 'Download';
        let clipUrl = '';
        const getClip = async () => {
          if (clipUrl) return clipUrl;
          const clip = await request(`/api/import/${jobId}/clip`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ start: moment.start, end: moment.end }) });
          clipUrl = api(clip.download_url);
          return clipUrl;
        };
        preview.addEventListener('click', async () => {
          preview.disabled = true;
          try {
            const url = await getClip();
            const player = document.createElement('video');
            player.controls = true; player.playsInline = true; player.src = url;
            const oldPlayer = results.querySelector('video');
            if (oldPlayer) oldPlayer.remove();
            card.insertAdjacentElement('afterend', player);
            await player.play();
          } catch (error) { setStatus(error.message); }
          finally { preview.disabled = false; }
        });
        download.addEventListener('click', async () => {
          download.disabled = true;
          try { const url = await getClip(); const link = document.createElement('a'); link.href = url; link.download = `clips-ai-moment-${index + 1}.mp4`; link.click(); }
          catch (error) { setStatus(error.message); }
          finally { download.disabled = false; }
        });
        card.append(description, preview, download);
        results.append(card);
      });
    } catch (error) {
      setStatus(error.message || 'Could not analyze this video.');
    } finally {
      button.disabled = false;
    }
  }

  toggle.addEventListener('change', () => {
    button.textContent = toggle.checked ? 'Find best moments' : 'Import video';
    if (!toggle.checked) setStatus('AI analysis is off. Your existing local upload workflow is unchanged.');
  });
  button.addEventListener('click', analyze);
})();
