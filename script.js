(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const source = $('#sourceVideo');
  const input = $('#videoFile');
  const uploadZone = $('#uploadZone');
  const generateButton = $('#generateButton');
  const grid = $('#clipsGrid');
  const modal = $('#editorModal');
  const editorVideo = $('#editorVideo');
  const editorPreview = $('#editorPreview');
  let videoUrl = '';
  let clips = [];
  let activeClipId = null;
  let toastTimer;
  let musicOscillator = null;
  let musicGain = null;
  let musicContext = null;
  let exportBusy = false;

  const titles = ['Best Moment','Funny Part','Wait For It','The Big Reveal','This Is Crazy','Part One','Worth The Watch','Plot Twist','Golden Moment','Can You Believe This?'];
  const subtitles = ['Watch till the end 🔥','This is crazy!','Part 1 — let’s go','Wait for the best part…','You have to see this ✨','That moment though 👀','Here’s the secret','Plot twist!','This one hits different 💥','Don’t blink!'];
  const filters = ['Cinematic','Vivid','Black & White','Warm','Cool','Vintage'];
  const animations = ['Zoom In','Fade In','Pop Text','Shake'];
  const $toast = $('#toast');
  const fmt = (seconds) => { const n = Math.max(0, Math.floor(Number(seconds) || 0)); return `${String(Math.floor(n / 60)).padStart(2, '0')}:${String(n % 60).padStart(2, '0')}`; };
  const tell = (message) => { $toast.textContent = message; $toast.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $toast.classList.remove('show'), 2800); };
  const duration = () => Number.isFinite(source.duration) ? source.duration : 0;
  const currentClip = () => clips.find((clip) => clip.id === activeClipId);
  const clipLength = (clip) => Math.max(0, clip.end - clip.start);
  const readFile = (file) => {
    if (!file || !file.type.startsWith('video/')) { tell('Choose a video file to get started.'); return; }
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    videoUrl = URL.createObjectURL(file);
    source.src = videoUrl;
    source.load();
    $('#uploadTitle').textContent = file.name.length > 27 ? `${file.name.slice(0, 24)}…` : file.name;
    $('#uploadDetail').textContent = 'Video ready · ' + (file.size / 1024 / 1024).toFixed(1) + ' MB';
    $('#generatorHint').textContent = 'Video loaded. Choose your style and generate your clips.';
  };
  input.addEventListener('change', () => readFile(input.files?.[0]));
  uploadZone.addEventListener('click', (event) => { if (!event.target.closest('input')) input.click(); });
  uploadZone.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); } });
  ['dragover', 'dragenter'].forEach((name) => uploadZone.addEventListener(name, (event) => { event.preventDefault(); uploadZone.classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach((name) => uploadZone.addEventListener(name, (event) => { event.preventDefault(); uploadZone.classList.remove('dragging'); }));
  uploadZone.addEventListener('drop', (event) => readFile([...event.dataTransfer.files].find((file) => file.type.startsWith('video/'))));
  $$('.prompt-suggestions button').forEach((button) => button.addEventListener('click', () => { $('#promptInput').value = button.dataset.prompt; $('#promptInput').focus(); }));
  $('#clipCount').addEventListener('change', () => { generateButton.innerHTML = `<span class="button-spark">✦</span> Generate ${$('#clipCount').value} Clips with AI <span class="button-arrow">↗</span>`; });

  const rand = (items) => items[Math.floor(Math.random() * items.length)];
  const makeClip = (index, count, totalDuration, platform, style, prompt) => {
    const start = index * totalDuration / count;
    const end = (index + 1) * totalDuration / count;
    const toneTitle = style === 'Funny' ? ['Funniest Moment','Unexpected Laugh','Comedy Gold','The Funny Bit'] : style === 'Motivational' ? ['The Motivation','Keep Going','A Little Inspiration','Your Sign To Start'] : style === 'Educational' ? ['Aha! Moment','Quick Lesson','Here’s The Trick','Learn This'] : style === 'Cinematic' ? ['The Cinematic Cut','A Scene To Remember','The Visual Moment','Story In Seconds'] : titles;
    const promptText = prompt.toLowerCase();
    let caption = rand(subtitles);
    if (promptText.includes('funny')) caption = rand(['That escalated quickly 😂','I did NOT expect that','The funniest part 😭','Wait for the punchline 😂']);
    else if (promptText.includes('motivat')) caption = rand(['You’ve got this 💪','Keep showing up ✨','Your moment starts now','A reminder to keep going']);
    else if (promptText.includes('educat')) caption = rand(['Here’s the thing 💡','Quick tip you’ll remember','This changes everything','Here’s how it works']);
    const filterName = rand(filters);
    const animation = rand(animations);
    return { id: `${Date.now()}-${index}-${Math.random().toString(36).slice(2, 7)}`, index: index + 1, title: `Clip ${index + 1}: ${rand(toneTitle)}`, start, end, caption, filterName, animation, score: Math.floor(70 + Math.random() * 29), platform, style, prompt, subtitleOn: true, subtitleStyle: 'bold', filter: filterName.toLowerCase().replace('black & white', 'grayscale').replace(' ', '-'), animationKey: animation.toLowerCase().replace(' ', '-') , aspect: platform === 'youtube' ? '16:9' : '9:16', emoji: '', volume: .8, music: false };
  };
  const createThumb = async (clip) => {
    return new Promise((resolve) => {
      if (!videoUrl || !duration()) { resolve(''); return; }
      const thumbVideo = document.createElement('video');
      thumbVideo.muted = true; thumbVideo.preload = 'metadata'; thumbVideo.playsInline = true; thumbVideo.src = videoUrl;
      const done = (url = '') => { thumbVideo.removeAttribute('src'); thumbVideo.load(); resolve(url); };
      thumbVideo.addEventListener('loadedmetadata', () => { thumbVideo.currentTime = Math.min(clip.start + .15, Math.max(0, duration() - .05)); }, { once: true });
      thumbVideo.addEventListener('seeked', () => {
        try { const canvas = document.createElement('canvas'); canvas.width = 480; canvas.height = 270; const ctx = canvas.getContext('2d'); const scale = Math.max(canvas.width / thumbVideo.videoWidth, canvas.height / thumbVideo.videoHeight); const w = thumbVideo.videoWidth * scale, h = thumbVideo.videoHeight * scale; ctx.drawImage(thumbVideo, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h); done(canvas.toDataURL('image/jpeg', .72)); } catch { done(''); }
      }, { once: true });
      thumbVideo.addEventListener('error', () => done(''), { once: true });
      setTimeout(() => done(''), 3500);
    });
  };
  const filterClass = (name) => ({ 'Cinematic': 'cinematic', 'Vivid': 'vivid', 'Black & White': 'grayscale', 'Warm': 'sepia', 'Cool': 'cool', 'Vintage': 'vintage' }[name] || 'none');
  function renderClips() {
    $('#emptyClips').hidden = clips.length > 0;
    $('#clipSummary').textContent = clips.length ? `${clips.length} clips · ${$('#platform').selectedOptions[0].textContent}` : 'No clips yet';
    grid.innerHTML = '';
    clips.forEach((clip) => {
      const card = document.createElement('article'); card.className = 'clip-card'; card.dataset.id = clip.id;
      const thumb = document.createElement('div'); thumb.className = `clip-thumb filter-${filterClass(clip.filterName)}`; thumb.dataset.action = 'preview'; thumb.dataset.id = clip.id;
      if (clip.thumbnail) { const image = document.createElement('img'); image.src = clip.thumbnail; image.alt = `Preview frame for ${clip.title}`; thumb.append(image); }
      const layer = document.createElement('span'); layer.className = 'thumb-filter'; thumb.append(layer);
      thumb.insertAdjacentHTML('beforeend', `<span class="clip-index">CLIP ${String(clip.index).padStart(2, '0')}</span><span class="clip-score">✦ ${clip.score}%</span><span class="thumb-play">▶</span>`);
      const caption = document.createElement('span'); caption.className = 'thumb-caption'; caption.textContent = `${clip.emoji ? clip.emoji + ' ' : ''}${clip.caption}`; thumb.append(caption);
      const body = document.createElement('div'); body.className = 'clip-card-body';
      const heading = document.createElement('h3'); heading.textContent = clip.title;
      const meta = document.createElement('div'); meta.className = 'clip-meta'; meta.innerHTML = `<span>${fmt(clipLength(clip))} · ${fmt(clip.start)}–${fmt(clip.end)}</span><span>${clip.aspect}</span>`;
      const tags = document.createElement('div'); tags.className = 'clip-tags'; [clip.filterName, clip.animation, 'Captions'].forEach((tag) => { const el = document.createElement('span'); el.textContent = tag; tags.append(el); });
      const actions = document.createElement('div'); actions.className = 'clip-actions';
      actions.innerHTML = `<button data-action="preview" data-id="${clip.id}">▶ Preview</button><button data-action="edit" data-id="${clip.id}">✎ Edit</button><button class="download-card" data-action="download" data-id="${clip.id}">↓ Save</button>`;
      body.append(heading, meta, tags, actions); card.append(thumb, body); grid.append(card);
    });
  }
  generateButton.addEventListener('click', async () => {
    if (!videoUrl || !duration()) { tell('Upload a video before generating clips.'); uploadZone.scrollIntoView({ behavior: 'smooth', block: 'center' }); return; }
    generateButton.disabled = true;
    const count = Number($('#clipCount').value);
    const original = generateButton.innerHTML;
    generateButton.innerHTML = '<span class="button-spark">✦</span> Finding your moments…';
    $('#generatorHint').textContent = `Splitting your ${fmt(duration())} video into ${count} equal clips locally…`;
    await new Promise((resolve) => setTimeout(resolve, 350));
    const platform = $('#platform').value, style = $('#styleSelect').value, prompt = $('#promptInput').value.trim();
    clips = Array.from({ length: count }, (_, index) => makeClip(index, count, duration(), platform, style, prompt));
    renderClips();
    for (let i = 0; i < clips.length; i++) { clips[i].thumbnail = await createThumb(clips[i]); const img = $(`.clip-card[data-id="${clips[i].id}"] .clip-thumb img`); if (img && clips[i].thumbnail) img.src = clips[i].thumbnail; else if (!img && clips[i].thumbnail) { const image = document.createElement('img'); image.src = clips[i].thumbnail; image.alt = `Preview frame for ${clips[i].title}`; $(`.clip-card[data-id="${clips[i].id}"] .clip-thumb`).prepend(image); } }
    renderClips(); generateButton.disabled = false; generateButton.innerHTML = original; $('#generatorHint').textContent = `${count} clips created from equal sections of your video. Edit, preview, or download any clip.`;
    $('#my-clips').scrollIntoView({ behavior: 'smooth', block: 'start' }); tell(`${count} clips are ready to preview and edit.`);
  });

  function openEditor(clip) {
    if (!clip || !videoUrl) return;
    activeClipId = clip.id; editorVideo.pause(); editorVideo.src = videoUrl; editorVideo.load();
    $('#editorTitle').textContent = clip.title;
    $('#captionInput').value = clip.caption;
    $('#subtitleToggle').value = clip.subtitleOn ? 'on' : 'off';
    $('#subtitleStyle').value = clip.subtitleStyle || 'bold';
    $('#filterSelect').value = clip.filter || 'none';
    $('#animationSelect').value = clip.animationKey || 'none';
    $('#musicToggle').checked = Boolean(clip.music);
    $('#volumeSlider').value = Math.round((clip.volume ?? .8) * 100);
    $('#aspectSelect').value = clip.aspect || '9:16';
    $('#startSlider').min = 0; $('#startSlider').max = duration(); $('#startSlider').step = .05; $('#startSlider').value = clip.start;
    $('#endSlider').min = 0; $('#endSlider').max = duration(); $('#endSlider').step = .05; $('#endSlider').value = clip.end;
    editorVideo.currentTime = clip.start;
    setEditorState();
    modal.classList.add('open'); modal.setAttribute('aria-hidden', 'false'); document.body.style.overflow = 'hidden';
  }
  function closeEditor() { editorVideo.pause(); stopMusic(); modal.classList.remove('open'); modal.setAttribute('aria-hidden', 'true'); document.body.style.overflow = ''; activeClipId = null; }
  $('#closeEditor').addEventListener('click', closeEditor);
  modal.addEventListener('click', (event) => { if (event.target === modal) closeEditor(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && modal.classList.contains('open')) closeEditor(); });
  function setEditorState() {
    const clip = currentClip(); if (!clip) return;
    const start = Number($('#startSlider').value), end = Number($('#endSlider').value);
    clip.start = Math.min(start, Math.max(0, end - .1)); clip.end = Math.max(clip.start + .1, end);
    clip.caption = $('#captionInput').value; clip.subtitleOn = $('#subtitleToggle').value === 'on'; clip.subtitleStyle = $('#subtitleStyle').value;
    clip.filter = $('#filterSelect').value; clip.animationKey = $('#animationSelect').value; clip.music = $('#musicToggle').checked; clip.volume = Number($('#volumeSlider').value) / 100; clip.aspect = $('#aspectSelect').value;
    $('#startSlider').value = clip.start; $('#endSlider').value = clip.end;
    $('#startOutput').textContent = fmt(clip.start); $('#endOutput').textContent = fmt(clip.end);
    $('#editorRangeLabel').textContent = `${fmt(clip.start)} – ${fmt(clip.end)} · ${fmt(clipLength(clip))}`;
    const caption = $('#editorCaption'); caption.textContent = `${clip.emoji ? clip.emoji + ' ' : ''}${clip.caption}`; caption.hidden = !clip.subtitleOn;
    caption.className = `editor-caption style-${clip.subtitleStyle}`;
    editorPreview.className = `editor-preview ratio-${clip.aspect.replace(':', '-')} filter-${clip.filter} anim-${clip.animationKey}`;
    if (editorVideo.currentTime < clip.start || editorVideo.currentTime >= clip.end) editorVideo.currentTime = clip.start;
    renderClips();
  }
  ['captionInput', 'subtitleToggle', 'subtitleStyle', 'filterSelect', 'animationSelect', 'musicToggle', 'volumeSlider', 'aspectSelect', 'startSlider', 'endSlider'].forEach((id) => $(`#${id}`).addEventListener('input', setEditorState));
  $('#startSlider').addEventListener('change', () => { if (currentClip()) editorVideo.currentTime = currentClip().start; });
  $('#endSlider').addEventListener('change', () => { if (currentClip() && editorVideo.currentTime > currentClip().end) editorVideo.currentTime = currentClip().start; });
  $('#previewPlay').addEventListener('click', async () => {
    const clip = currentClip(); if (!clip) return;
    if (editorVideo.paused) { if (editorVideo.currentTime < clip.start || editorVideo.currentTime >= clip.end) editorVideo.currentTime = clip.start; try { await editorVideo.play(); } catch { tell('Tap play to preview your clip.'); } }
    else editorVideo.pause();
  });
  editorVideo.addEventListener('timeupdate', () => {
    const clip = currentClip(); if (!clip) return;
    $('#editorCurrent').textContent = fmt(editorVideo.currentTime);
    if (editorVideo.currentTime >= clip.end && !editorVideo.paused) { editorVideo.pause(); editorVideo.currentTime = clip.start; }
  });
  $('#stickerButton').addEventListener('click', () => {
    const clip = currentClip(); if (!clip) return;
    const choices = ['✨', '🔥', '😂', '💥', '👀', '❤️', '🚀', '💡'];
    clip.emoji = clip.emoji ? '' : choices[Math.floor(Math.random() * choices.length)];
    setEditorState(); tell(clip.emoji ? `Added ${clip.emoji} to the caption.` : 'Sticker removed.');
  });
  $('#saveClipButton').addEventListener('click', () => { setEditorState(); tell('Clip edits saved for this session.'); });
  $('#musicToggle').addEventListener('change', async () => { if ($('#musicToggle').checked) await startMusic(); else stopMusic(); });
  $('#volumeSlider').addEventListener('input', () => { if (musicGain) musicGain.gain.value = Number($('#volumeSlider').value) / 100 * .12; });
  async function startMusic() {
    try {
      const Audio = window.AudioContext || window.webkitAudioContext;
      if (!Audio) { $('#musicToggle').checked = false; tell('Sample tone is not supported in this browser.'); return; }
      musicContext ||= new Audio(); if (musicContext.state === 'suspended') await musicContext.resume();
      stopMusic(); musicOscillator = musicContext.createOscillator(); musicGain = musicContext.createGain();
      musicOscillator.type = 'sine'; musicOscillator.frequency.value = 440; musicGain.gain.value = Number($('#volumeSlider').value) / 100 * .12;
      musicOscillator.connect(musicGain); musicGain.connect(musicContext.destination); musicOscillator.start();
    } catch { tell('Could not start the sample tone.'); }
  }
  function stopMusic() { if (musicOscillator) { try { musicOscillator.stop(); } catch {} musicOscillator.disconnect(); musicOscillator = null; } if (musicGain) { musicGain.disconnect(); musicGain = null; } }

  grid.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-action]'); if (!button) return;
    const clip = clips.find((item) => item.id === button.dataset.id); if (!clip) return;
    if (button.dataset.action === 'edit') openEditor(clip);
    if (button.dataset.action === 'preview') openEditor(clip);
    if (button.dataset.action === 'download') { openEditor(clip); setTimeout(() => $('#downloadClipButton').click(), 120); }
  });
  const activeRecorderType = () => ['video/mp4;codecs=h264,aac','video/mp4','video/webm;codecs=vp9,opus','video/webm;codecs=vp8,opus','video/webm'].find((type) => window.MediaRecorder?.isTypeSupported(type)) || '';
  async function exportClip() {
    const clip = currentClip(); if (!clip || exportBusy) return;
    if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) { tell('Export requires a recent Chrome, Edge, or Firefox browser.'); return; }
    const mimeType = activeRecorderType(); if (!mimeType) { tell('This browser does not support video export.'); return; }
    exportBusy = true; const button = $('#downloadClipButton'); const original = button.textContent; button.disabled = true; button.textContent = 'Preparing…';
    editorVideo.pause();
    const canvas = document.createElement('canvas');
    const aspect = clip.aspect === '16:9' ? 16 / 9 : clip.aspect === '1:1' ? 1 : 9 / 16;
    const base = 720; canvas.width = aspect >= 1 ? base : Math.round(base * aspect); canvas.height = aspect >= 1 ? Math.round(base / aspect) : base;
    const ctx = canvas.getContext('2d'); let frameLoop; let recorder; let stream;
    try {
      editorVideo.currentTime = clip.start;
      await new Promise((resolve, reject) => { if (Math.abs(editorVideo.currentTime - clip.start) < .02) return resolve(); const timeout = setTimeout(() => reject(new Error('seek timed out')), 5000); editorVideo.addEventListener('seeked', () => { clearTimeout(timeout); resolve(); }, { once: true }); });
      stream = canvas.captureStream(30);
      const draw = () => {
        ctx.fillStyle = '#080808'; ctx.fillRect(0, 0, canvas.width, canvas.height);
        const sw = editorVideo.videoWidth || canvas.width, sh = editorVideo.videoHeight || canvas.height;
        ctx.save();
        const filterMap = { cinematic: 'contrast(1.15) saturate(.8)', vivid: 'saturate(1.5) contrast(1.06)', grayscale: 'grayscale(1)', sepia: 'sepia(.75)', vintage: 'sepia(.35) saturate(.8) contrast(1.1)', blur: 'saturate(1.2)' };
        ctx.filter = filterMap[clip.filter] || 'none';
        const scale = Math.min(canvas.width / sw, canvas.height / sh); const w = sw * scale, h = sh * scale;
        ctx.drawImage(editorVideo, (canvas.width - w) / 2, (canvas.height - h) / 2, w, h); ctx.filter = 'none';
        if (clip.subtitleOn && clip.caption) {
          const fontSize = Math.max(20, canvas.width * .075); ctx.font = `700 ${fontSize}px "Space Grotesk", sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          const text = `${clip.emoji ? clip.emoji + ' ' : ''}${clip.caption}`; const maxWidth = canvas.width * .88;
          const words = text.split(/\s+/); let line = '', lines = [];
          words.forEach((word) => { const candidate = line ? `${line} ${word}` : word; if (ctx.measureText(candidate).width > maxWidth && line) { lines.push(line); line = word; } else line = candidate; }); if (line) lines.push(line);
          const lineHeight = fontSize * 1.2; const y = canvas.height * .78 - (lines.length - 1) * lineHeight / 2;
          ctx.lineWidth = Math.max(4, fontSize * .13); ctx.lineJoin = 'round'; ctx.strokeStyle = '#000d'; ctx.fillStyle = clip.subtitleStyle === 'neon' ? '#f6afff' : '#fff';
          if (clip.subtitleStyle === 'classic') { ctx.fillStyle = '#000b'; ctx.fillRect(canvas.width * .05, y - lineHeight / 2, canvas.width * .9, lineHeight * lines.length); ctx.fillStyle = '#fff'; }
          lines.forEach((textLine, i) => { const yy = y + i * lineHeight; ctx.strokeText(textLine, canvas.width / 2, yy); ctx.fillText(textLine, canvas.width / 2, yy); });
        }
        ctx.restore();
      };
      draw(); frameLoop = setInterval(draw, 1000 / 30);
      const chunks = []; recorder = new MediaRecorder(stream, { mimeType, videoBitsPerSecond: 4500000 });
      recorder.ondataavailable = (event) => { if (event.data?.size) chunks.push(event.data); };
      const stopped = new Promise((resolve, reject) => { recorder.onstop = resolve; recorder.onerror = (event) => reject(event.error || new Error('recording failed')); });
      recorder.start(250); button.textContent = 'Exporting…'; await editorVideo.play();
      await new Promise((resolve) => { const watch = () => { if (editorVideo.currentTime >= clip.end || editorVideo.ended) { editorVideo.pause(); resolve(); } else requestAnimationFrame(watch); }; requestAnimationFrame(watch); });
      await new Promise((resolve) => setTimeout(resolve, 150)); recorder.stop(); await stopped;
      clearInterval(frameLoop); stream.getTracks().forEach((track) => track.stop());
      if (!chunks.length) throw new Error('empty export');
      const blob = new Blob(chunks, { type: mimeType }); const extension = mimeType.includes('mp4') ? 'mp4' : 'webm';
      const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = `clips-ai-${String(clip.index).padStart(2, '0')}.${extension}`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      button.textContent = 'Downloaded ✓'; tell(`Clip ${clip.index} downloaded as ${extension.toUpperCase()}.`);
    } catch (error) { console.error(error); if (recorder?.state !== 'inactive') { try { recorder.stop(); } catch {} } clearInterval(frameLoop); if (stream) stream.getTracks().forEach((track) => track.stop()); button.textContent = original; tell('Export did not finish. Try a shorter clip or another browser.'); }
    finally { exportBusy = false; button.disabled = false; editorVideo.pause(); if (currentClip()) editorVideo.currentTime = currentClip().start; stopMusic(); $('#musicToggle').checked = false; }
  }
  $('#downloadClipButton').addEventListener('click', exportClip);
  source.addEventListener('loadedmetadata', () => { if (duration() < .3) tell('This video is too short to create clips.'); });
  source.addEventListener('error', () => tell('Could not read that video. Try an MP4 or WebM file.'));
  $('#mobileMenu').addEventListener('click', () => $('.main-nav').classList.toggle('open'));
  $$('.main-nav a').forEach((link) => link.addEventListener('click', () => $('.main-nav').classList.remove('open')));
  window.addEventListener('beforeunload', () => { if (videoUrl) URL.revokeObjectURL(videoUrl); stopMusic(); });
})();
