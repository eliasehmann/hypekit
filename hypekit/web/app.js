// Hype Toolkit UI: plain ES module, talks only to the local hypekit HTTP API (/api/...).
const $ = (s, el = document) => el.querySelector(s);
const view = $('#view'), filters = $('#filters'), qbox = $('#q');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = t => t == null ? '' : `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const KINDS = [['', 'All'], ['voice', 'Dialogue'], ['music', 'Music'], ['sfx', 'Effects'], ['ambience', 'Ambience'], ['unused', 'Unused']];
const KIND_LABEL = { voice: 'Dialogue', music: 'Music', 'music part': 'Music part', sfx: 'Effect', ambience: 'Ambience', unused: 'Unused' };
const PAGE = 200;

async function api(path, params = {}) {
  const u = new URL('/api/' + path, location.origin);
  for (const [k, v] of Object.entries(params)) if (v !== '' && v != null && v !== false) u.searchParams.set(k, v);
  const r = await fetch(u);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function toast(msg, ms = 2600) {
  let t = $('.toast');
  if (!t) { t = document.createElement('div'); t.className = 'toast'; document.body.append(t); }
  t.textContent = msg;
  clearTimeout(t._h);
  if (ms) t._h = setTimeout(() => t.remove(), ms);
  return t;
}

// ---- routing: #/<page>?<params> ---------------------------------------------------------------------------
function route() {
  const [p, qs] = location.hash.replace(/^#\/?/, '').split('?');
  return { page: p || 'search', params: Object.fromEntries(new URLSearchParams(qs || '')) };
}
function go(page, params = {}, replace = false) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString();
  const h = `#/${page}${qs ? '?' + qs : ''}`;
  if (replace) history.replaceState(null, '', h); else location.hash = h;
  if (replace) render();
}
function setParam(k, v) { const r = route(); r.params[k] = v; go(r.page, r.params, true); }

let levels = null, levelName = {};
async function getLevels() {
  if (!levels) {
    levels = await api('levels');
    for (const l of levels) levelName[l.level] = l.place;
  }
  return levels;
}
const usedIn = lv => !lv?.length ? '' : lv.includes('Fix') ? 'Everywhere'
  : (s => s.size === 1 ? [...s][0] : `${s.size} places`)(new Set(lv.map(x => levelName[x] || x)));

// ---- pages ----------------------------------------------------------------------------------------------
async function render() {
  const { page, params } = route();
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('on', a.dataset.page === page));
  if (document.activeElement !== qbox) qbox.value = params.q || '';
  qbox.placeholder = { search: 'Search everything', sounds: 'Search sounds', script: 'Search dialogue', textures: 'Search textures', models: 'Search models' }[page] || 'Search';
  filters.innerHTML = '';
  view.classList.toggle('full', page === 'models');
  if (page !== 'models') M.key = null;
  await getLevels();
  const fn = { search: pageSearch, sounds: pageSounds, script: pageScript, textures: pageTextures, models: pageModels }[page] || pageSearch;
  try { await fn(params); } catch (e) { view.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  if (params.play && params.play !== cur?.id) api('get/' + encodeURIComponent(params.play)).then(s => play(s)).catch(e => toast(e.message));  // deep link: ?play=<sound id>
}

function seg(options, value, onPick) {
  const el = document.createElement('div');
  el.className = 'seg';
  for (const [v, label] of options) {
    const b = document.createElement('button');
    b.textContent = label;
    b.classList.toggle('on', (value || '') === v);
    b.onclick = () => onPick(v);
    el.append(b);
  }
  return el;
}

function soundRow(s) {
  const el = document.createElement('div');
  el.className = 'row' + (cur?.id === s.id ? ' cur' : '');
  el.dataset.id = s.id;
  el.innerHTML = `<button class="play" title="Play">▶</button><div class="ti">${esc(s.title)}</div>
    <div class="k">${esc(KIND_LABEL[s.kind] || s.kind)} · ${esc(s.format)}</div><div class="d">${fmt(s.seconds)}</div>
    <div class="u">${esc(usedIn(s.levels))}</div>`;
  $('.play', el).onclick = e => { e.stopPropagation(); play(s); };
  el.onclick = () => openSound(s.id);
  el.ondblclick = () => play(s);
  return el;
}

async function pagedList(container, load, makeRow) {
  let off = 0;
  const rows = document.createElement('div'); rows.className = 'rows';
  const count = document.createElement('div'); count.className = 'count';
  const more = document.createElement('button'); more.className = 'chip more'; more.textContent = 'Show more';
  container.append(count, rows, more);
  async function next() {
    more.classList.add('busy');
    const items = await load(off, PAGE);
    items.forEach(x => rows.append(makeRow(x)));
    off += items.length;
    more.hidden = items.length < PAGE;
    more.classList.remove('busy');
    count.textContent = off ? `${off}${more.hidden ? '' : '+'} results` : '';
    if (!off) rows.innerHTML = '<div class="empty">Nothing found</div>';
  }
  more.onclick = next;
  await next();
}

function levelSelect(value, onPick, all = true) {
  const sel = document.createElement('select');
  let html = all ? '<option value="">All places</option>' : '', place = null;
  for (const l of levels) {
    if (l.place !== place) { if (place !== null) html += '</optgroup>'; place = l.place; html += `<optgroup label="${esc(place)}">`; }
    html += `<option value="${esc(l.level)}"${value === l.level ? ' selected' : ''}>${esc(l.place)} · ${esc(l.level)}</option>`;
  }
  sel.innerHTML = html + '</optgroup>';
  sel.onchange = () => onPick(sel.value);
  return sel;
}

async function pageSounds(p) {
  filters.append(seg(KINDS, p.kind, v => setParam('kind', v)));
  filters.append(levelSelect(p.level, v => setParam('level', v)));
  view.innerHTML = '';
  await pagedList(view, (offset, limit) => api('sounds', { q: p.q, kind: p.kind, level: p.level, offset, limit }), soundRow);
}

async function pageScript(p) {
  const shared = p.shared === '1';
  const tog = document.createElement('button');
  tog.className = 'chip' + (shared ? ' on' : ''); tog.textContent = 'Shared lines';
  tog.title = 'Show lines that appear in many levels (pickups, menus)';
  tog.onclick = () => setParam('shared', shared ? '' : '1');
  filters.append(tog);
  view.innerHTML = '';
  const wrap = document.createElement('div'); wrap.className = 'script'; view.append(wrap);
  if (p.q) {                                     // search across all levels
    const lines = await api('lines', { q: p.q, common: shared, limit: 500 });
    wrap.innerHTML = `<div class="count">${lines.length}${lines.length === 500 ? '+' : ''} lines</div>`;
    let lv = null;
    for (const l of lines) {
      if (l.level !== lv) { lv = l.level; wrap.insertAdjacentHTML('beforeend', `<h2>${esc(levelName[lv] || lv)} · ${esc(lv)}</h2>`); }
      wrap.append(turnRow(l, true));
    }
    return;
  }
  const level = p.level || levels.find(l => l.level !== 'Fix')?.level;
  const prev = levels[levels.findIndex(l => l.level === level) - 1], next = levels[levels.findIndex(l => l.level === level) + 1];
  for (const [l, label] of [[prev, '‹'], [next, '›']]) { const b = document.createElement('button'); b.className = 'chip'; b.textContent = label; b.disabled = !l; b.title = l ? l.level : ''; b.onclick = () => l && setParam('level', l.level); filters.append(b); }
  filters.prepend(levelSelect(level, v => setParam('level', v), false));
  const lines = (await api('script/' + encodeURIComponent(level))).filter(l => shared || !l.common);
  wrap.insertAdjacentHTML('beforeend', `<h2>${esc(levelName[level] || level)} · ${esc(level)}</h2>`);
  let dlg = null;
  for (const l of lines) {
    if (l.dialog !== dlg) { dlg = l.dialog; if (dlg) wrap.insertAdjacentHTML('beforeend', `<div class="seqname">${esc(dlg)}</div>`); }
    wrap.append(turnRow(l));
  }
  if (!lines.length) wrap.insertAdjacentHTML('beforeend', '<div class="empty">No dialogue in this level</div>');
  if (p.line) { const el = document.querySelector(`[data-line="${CSS.escape(p.line)}"]`); el?.classList.add('cur'); el?.scrollIntoView({ block: 'center' }); }
}

function turnRow(l, link = false) {
  const el = document.createElement('div');
  el.className = 'turn'; el.dataset.line = l.id;
  if (l.sounds?.length) el.dataset.sounds = ' ' + l.sounds.join(' ') + ' ';
  const ids = l.sounds || null;
  el.innerHTML = `<button class="play" title="${ids?.length || ids === null ? 'Play voice' : 'No voice recording'}"${ids && !ids.length ? ' disabled' : ''}>▶</button>
    <div class="who">${esc(l.speaker)}</div><div class="tx">${esc(l.text)}</div>`;
  $('.play', el).onclick = async () => {
    let sid = ids?.[0];
    if (!ids) sid = (await api('get/' + encodeURIComponent(l.id))).sounds?.[0]?.id;
    if (!sid) return toast('No voice recording for this line');
    play(await api('get/' + encodeURIComponent(sid)), el);
  };
  if (link) el.ondblclick = () => go('script', { level: l.level, line: l.id });
  el.onclick = e => { if (e.target.tagName !== 'BUTTON') openLine(l.id); };
  return el;
}

function texTile(t) {
  const el = document.createElement('div');
  el.className = 'tex';
  el.innerHTML = `<div class="img"><img loading="lazy" src="/api/png/${encodeURIComponent(t.id)}" alt=""></div>
    <div class="n" title="${esc(t.path)}">${esc(t.path.split('/').pop())}</div><div class="s">${t.width}×${t.height} · ${esc(t.format)}</div>`;
  el.onclick = () => openTexture(t);
  return el;
}

async function pageTextures(p) {
  filters.append(seg([['', 'All'], ['Textures', 'Textures'], ['Vignette', 'Screens']], p.archive, v => setParam('archive', v)));
  view.innerHTML = '';
  const holder = document.createElement('div'); view.append(holder);
  await pagedList(holder, (offset, limit) => api('textures', { q: p.q, archive: p.archive, offset, limit }), texTile);
  const rows = $('.rows', holder); rows.className = 'grid';
}

async function pageSearch(p) {
  view.innerHTML = '';
  if (!p.q) {
    const m = await api('info');
    view.innerHTML = `<div class="empty">Search sounds, dialogue and textures of your install.<br><br>
      ${m.sounds} sounds · ${m.lines} dialogue lines · ${m.textures} textures</div>`;
    return;
  }
  const r = await api('find', { q: p.q, limit: 30 });
  const sec = (title, n, page) => {
    const h = document.createElement('h2');
    h.innerHTML = `${title} <span style="color:var(--dim);font-weight:400">${n}${n === 30 ? '+' : ''}</span>`;
    if (n === 30) { const a = document.createElement('a'); a.className = 'chip'; a.style.marginLeft = '10px'; a.textContent = 'All'; a.href = `#/${page}?q=${encodeURIComponent(p.q)}`; h.append(a); }
    view.append(h);
  };
  if (r.sounds.length) { sec('Sounds', r.sounds.length, 'sounds'); const rows = document.createElement('div'); rows.className = 'rows'; r.sounds.forEach(s => rows.append(soundRow(s))); view.append(rows); }
  if (r.lines.length) { sec('Dialogue', r.lines.length, 'script'); r.lines.forEach(l => view.append(turnRow(l, true))); }
  if (r.textures.length) { sec('Textures', r.textures.length, 'textures'); const g = document.createElement('div'); g.className = 'grid'; r.textures.forEach(t => g.append(texTile(t))); view.append(g); }
  if (!r.sounds.length && !r.lines.length && !r.textures.length) view.innerHTML = '<div class="empty">Nothing found</div>';
}

// ---- models ---------------------------------------------------------------------------------------------
// The list + stage stay in place while only the selection (id, state) changes; the WebGL viewer is created once.
const M = { key: null, viewer: null, canvas: null, loaded: null, items: [] };

async function pageModels(p) {
  filters.append(seg([['', 'Most parts'], ['az', 'A–Z']], p.sort, v => setParam('sort', v)));
  filters.append(levelSelect(p.level, v => setParam('level', v)));
  const key = JSON.stringify([p.q, p.sort, p.level]);
  if (M.key !== key || !view.querySelector('.models')) {
    const r = await api('persos', { q: p.q, level: p.level });
    if (!r.items) return scanProgress(r.status);
    M.key = key;
    const groups = new Map();
    for (const x of r.items) (groups.get(x.name) || groups.set(x.name, []).get(x.name)).push(x);
    M.items = [...groups.values()];
    if (p.sort === 'az') M.items.sort((a, b) => a[0].name.localeCompare(b[0].name));
    else M.items.sort((a, b) => b[0].parts - a[0].parts || b[0].states - a[0].states || a[0].name.localeCompare(b[0].name));
    view.innerHTML = `<div class="models"><div class="mlist"><div class="count">${M.items.length} models</div></div>
      <div class="stage"><div class="tools"></div><div class="msg"></div></div></div>`;
    const list = $('.mlist', view);
    for (const g of M.items) {
      const el = document.createElement('div');
      el.className = 'mitem'; el.dataset.ids = ' ' + g.map(x => x.id).join(' ') + ' ';
      const lv = g.length === 1 ? (levelName[g[0].level] || g[0].level) : `${g.length} levels`;
      el.innerHTML = `<div class="n">${esc(g[0].name)}</div><div class="s">${g[0].parts} parts · ${g[0].states} states · ${esc(lv)}</div>`;
      el.onclick = () => setParam('id', g[0].id) ;
      list.append(el);
    }
    if (!M.canvas) M.canvas = document.createElement('canvas');
    $('.stage', view).insertBefore(M.canvas, $('.msg', view));
    if (!M.viewer) { const { Viewer } = await import('./viewer.js'); M.viewer = new Viewer(M.canvas); }
    M.loaded = null;
  }
  const id = p.id || M.items[0]?.[0].id;
  if (!id) { $('.msg', view).textContent = 'Nothing found'; return; }
  view.querySelectorAll('.mitem').forEach(e => e.classList.toggle('on', e.dataset.ids.includes(` ${id} `)));
  const want = `${id}|${p.state ?? ''}`;
  if (M.loaded === want) return;
  await showModel(id, p.state, M.loaded?.split('|')[0] === id);
  M.loaded = want;
}

async function scanProgress(st) {
  view.innerHTML = `<div class="scan">Reading the 3D data of every level, once.<div class="barbg"><div class="barfg"></div></div>
    <small></small></div>`;
  const tick = async () => {
    if (route().page !== 'models' || !$('.scan', view)) return;
    const r = await api('persos', {}).catch(() => null);
    const s = r?.status || st;
    if (s.state === 'ready') return render();
    if (s.state === 'error') { $('.scan small', view).textContent = s.error; return; }
    $('.barfg', view).style.width = `${s.total ? 100 * s.done / s.total : 2}%`;
    $('.scan small', view).textContent = s.total ? `${s.done} / ${s.total} levels${s.level ? ' · ' + s.level : ''} · about ${Math.max(5, Math.round((s.total - s.done) * 1.6))} s left` : 'Starting…';
    setTimeout(tick, 1000);
  };
  tick();
}

async function showModel(id, state, sameModel) {
  const tools = $('.stage .tools', view), msg = $('.stage .msg', view);
  const g = M.items.find(g => g.some(x => x.id === id)) || [{ id, name: id, level: id.split(':')[0] }];
  const rec = g.find(x => x.id === id) || g[0];
  msg.textContent = 'Loading…';
  const info = await api('perso/' + encodeURIComponent(id));
  const cur = state ?? String(info.animations.find(s => s.initial)?.index ?? '');
  tools.innerHTML = `<span class="ti">${esc(rec.name)}</span>`;
  if (g.length > 1) {
    const sel = document.createElement('select');
    sel.innerHTML = g.map(x => `<option value="${esc(x.id)}"${x.id === id ? ' selected' : ''}>${esc(levelName[x.level] || x.level)} · ${esc(x.level)}</option>`).join('');
    sel.onchange = () => go('models', { ...route().params, id: sel.value, state: '' }, true);
    tools.append(sel);
  }
  const ss = document.createElement('select');
  ss.title = 'Animation (state)';
  ss.innerHTML = info.animations.map(s => `<option value="${s.index}"${String(s.index) === cur ? ' selected' : ''}>State ${s.index} · ${s.frames} frames${s.initial ? ' · initial' : ''}</option>`).join('');
  ss.onchange = () => setParam('state', ss.value);
  const step = d => { const i = ss.selectedIndex + d; if (i >= 0 && i < ss.options.length) setParam('state', ss.options[i].value); };
  const prev = Object.assign(document.createElement('button'), { className: 'chip', textContent: '‹', title: 'Previous state', onclick: () => step(-1) });
  const next = Object.assign(document.createElement('button'), { className: 'chip', textContent: '›', title: 'Next state', onclick: () => step(1) });
  const pause = Object.assign(document.createElement('button'), { className: 'chip', textContent: M.viewer.playing ? 'Pause' : 'Play' });
  pause.onclick = () => { M.viewer.setPlaying(!M.viewer.playing); pause.textContent = M.viewer.playing ? 'Pause' : 'Play'; };
  const reset = Object.assign(document.createElement('button'), { className: 'chip', textContent: 'Reset view', onclick: () => M.viewer.frameView() });
  const url = `/api/glb/${encodeURIComponent(id)}${cur !== '' ? '?state=' + cur : ''}`;
  const dlA = Object.assign(document.createElement('a'), { className: 'chip', textContent: 'GLB', href: url, download: `${rec.name || id.replace(':', '_')}${cur !== '' ? '_state' + cur : ''}.glb`, title: 'Download as glTF binary' });
  tools.append(ss, prev, next, pause, reset, dlA);
  try {
    const r = await M.viewer.load(url, { keepView: sameModel });
    msg.textContent = '';
    tools.insertAdjacentHTML('beforeend', `<span class="count" style="padding:0">${r.frames} frames · ${r.duration.toFixed(1)} s</span>`);
  } catch (e) { msg.textContent = e.message || String(e); }
}

// ---- drawer ---------------------------------------------------------------------------------------------
const drawer = $('#drawer'), dbody = $('#drawer-body');
$('#drawer-close').onclick = () => { drawer.hidden = true; };
const dl = pairs => '<dl>' + pairs.filter(([, v]) => v !== '' && v != null).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('') + '</dl>';

async function openSound(id) {
  const s = await api('get/' + encodeURIComponent(id));
  dbody.innerHTML = `<h3>${esc(s.title)}</h3>
    <div class="btns"><button class="chip" id="d-play">▶ Play</button><a class="chip" href="/api/wav/${encodeURIComponent(s.id)}" download="${esc(s.id.replace(':', '_'))}.wav">Download WAV</a></div>
    ${dl([['ID', s.id], ['Kind', KIND_LABEL[s.kind] || s.kind], ['Format', s.format], ['Length', fmt(s.seconds)],
      ['Audio', `${s.rate} Hz · ${s.channels === 2 ? 'stereo' : 'mono'}`], ['Used in', (s.levels || []).map(l => levelName[l] ? `${levelName[l]} (${l})` : l).join(', ')],
      ['Group', s.group_name], ['Speaker', s.speaker], ['Dialog', s.dialog], ['File', s.file_name], ['Part', s.part],
      ['Loop', s.loop ? (s.loop_start ? `from ${fmt(s.loop_start)}` : 'yes') : '']])}
    ${s.lines?.length ? '<h2>Dialogue</h2><div class="links" id="d-lines"></div>' : ''}
    ${s.parts?.length ? `<h2>Parts · ${s.parts.length}</h2><div class="links" id="d-parts"></div>` : ''}`;
  $('#d-play').onclick = () => play(s);
  const ln = $('#d-lines');
  s.lines?.forEach(l => { const a = document.createElement('a'); a.innerHTML = `${esc(l.text)}<small>${esc(l.speaker)} · ${esc(levelName[l.level] || l.level)}</small>`; a.onclick = () => go('script', { level: l.level, line: l.id }); ln.append(a); });
  const pt = $('#d-parts');
  s.parts?.forEach((pid, i) => { const a = document.createElement('a'); a.innerHTML = `Part ${i + 1}<small>${esc(pid)}</small>`; a.onclick = () => openSound(pid); pt.append(a); });
  drawer.hidden = false;
}

async function openLine(id) {
  const l = await api('get/' + encodeURIComponent(id));
  dbody.innerHTML = `<h3>${esc(l.text)}</h3>${dl([['Speaker', l.speaker], ['Level', `${levelName[l.level] || l.level} (${l.level})`], ['Dialog', l.dialog], ['ID', l.id], ['Shared', l.common ? 'yes' : '']])}
    ${l.sounds?.length ? '<h2>Voice</h2><div class="links" id="d-snd"></div>' : '<div class="count">No voice recording</div>'}
    <div class="btns"><button class="chip" id="d-open">Open in script</button></div>`;
  const sn = $('#d-snd');
  l.sounds?.forEach(s => { const a = document.createElement('a'); a.innerHTML = `▶ ${esc(s.title)}<small>${esc(s.id)}</small>`; a.onclick = async () => play(await api('get/' + encodeURIComponent(s.id))); sn.append(a); });
  $('#d-open').onclick = () => go('script', { level: l.level, line: l.id });
  drawer.hidden = false;
}

function openTexture(t) {
  const src = `/api/png/${encodeURIComponent(t.id)}`;
  const name = t.path.replace(/\//g, '_').replace(/\.gf$/i, '') + '.png';
  dbody.innerHTML = `<h3>${esc(t.path.split('/').pop())}</h3><div class="big"><img src="${src}" alt=""></div>
    <div class="btns"><a class="chip" href="${src}" download="${esc(name)}">Download PNG</a></div>
    ${dl([['ID', t.id], ['Path', t.path], ['Size', `${t.width}×${t.height}`], ['Format', t.format], ['Mipmaps', t.mips], ['Archive', t.archive], ['Error', t.error]])}`;
  drawer.hidden = false;
}

// ---- player ---------------------------------------------------------------------------------------------
const audio = $('#audio'), canvas = $('#wave'), pp = $('#pp'), loopBtn = $('#p-loop');
let cur = null, peaks = null, loopOn = false, playToken = 0;

async function play(s, rowEl) {
  const token = ++playToken;
  cur = s;
  document.querySelectorAll('.row.cur, .turn.cur').forEach(e => e.classList.remove('cur'));
  document.querySelectorAll(`.row[data-id="${CSS.escape(s.id)}"]`).forEach(e => e.classList.add('cur'));
  document.querySelectorAll(`.turn[data-sounds*=" ${CSS.escape(s.id)} "]`).forEach(e => e.classList.add('cur'));
  rowEl?.classList.add('cur');
  $('#player').hidden = false; document.body.classList.add('playing');
  $('#p-title').textContent = s.title;
  $('#p-sub').textContent = [KIND_LABEL[s.kind] || s.kind, s.format, usedIn(s.levels)].filter(Boolean).join(' · ');
  $('#p-dl').href = `/api/wav/${encodeURIComponent(s.id)}`; $('#p-dl').download = s.id.replace(':', '_') + '.wav';
  loopOn = !!s.loop && s.kind === 'music'; loopBtn.classList.toggle('on', loopOn);
  peaks = null; draw();
  const slow = setTimeout(() => toast(s.format === 'MPEG' || s.format === 'Track' ? 'Decoding (first time per bank)…' : 'Loading…', 0), 350);
  let buf;
  try {
    const r = await fetch(`/api/wav/${encodeURIComponent(s.id)}`);
    if (!r.ok) throw new Error((await r.json()).error);
    buf = await r.arrayBuffer();
  } catch (e) { clearTimeout(slow); toast(e.message, 5000); return; } finally { clearTimeout(slow); $('.toast')?.remove(); }
  if (token !== playToken) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  audio.play().catch(() => {});
  peaks = wavPeaks(buf); draw();
}

function wavPeaks(buf, n = 600) {               // 16-bit PCM WAV (what the API serves) -> n peak values 0..1
  const dv = new DataView(buf);
  let o = 12, chans = 1, data = null;
  while (o + 8 <= buf.byteLength) {
    const id = String.fromCharCode(...new Uint8Array(buf, o, 4)), size = dv.getUint32(o + 4, true);
    if (id === 'fmt ') chans = dv.getUint16(o + 10, true);
    if (id === 'data') { data = new Int16Array(buf, o + 8, Math.floor(Math.min(size, buf.byteLength - o - 8) / 2)); break; }
    o += 8 + size + (size & 1);
  }
  if (!data) return null;
  const frames = Math.floor(data.length / chans), step = Math.max(1, Math.floor(frames / n)), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let m = 0;
    for (let f = i * step, e = Math.min(frames, f + step); f < e; f += 3) { const v = Math.abs(data[f * chans]); if (v > m) m = v; }
    out[i] = m;
  }
  let mx = 1; for (const v of out) if (v > mx) mx = v;
  return out.map(v => v / mx);
}

function draw() {
  const dpr = devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w * dpr) { canvas.width = w * dpr; canvas.height = h * dpr; }
  const g = canvas.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  const pos = audio.duration ? audio.currentTime / audio.duration : 0;
  if (!peaks) { g.fillStyle = '#26272d'; g.fillRect(0, h / 2 - 1, w, 2); g.fillStyle = '#e8b04a'; g.fillRect(0, h / 2 - 1, w * pos, 2); return; }
  const bw = w / peaks.length;
  for (let i = 0; i < peaks.length; i++) {
    const v = Math.max(1, peaks[i] * (h - 6) / 2);
    g.fillStyle = i / peaks.length < pos ? '#e8b04a' : '#3a3b42';
    g.fillRect(i * bw, h / 2 - v, Math.max(1, bw - .5), v * 2);
  }
  if (cur?.loop_start && audio.duration) { g.fillStyle = '#f5f5f7'; g.fillRect(cur.loop_start / audio.duration * w, 4, 1, h - 8); }
}

function tick() { draw(); $('#p-time').textContent = `${fmt(audio.currentTime)} / ${fmt(audio.duration || 0)}`; if (!audio.paused) requestAnimationFrame(tick); }
audio.onplay = () => { pp.textContent = '❚❚'; tick(); };
audio.onpause = () => { pp.textContent = '▶'; tick(); };
audio.onloadedmetadata = () => {
  tick();
  if (cur && cur.seconds == null) { cur.seconds = audio.duration; document.querySelectorAll(`.row[data-id="${CSS.escape(cur.id)}"] .d`).forEach(d => { d.textContent = fmt(audio.duration); }); }
};
audio.onended = () => { if (loopOn) { audio.currentTime = cur?.loop_start || 0; audio.play(); } };
pp.onclick = () => audio.src && (audio.paused ? audio.play() : audio.pause());
loopBtn.onclick = () => { loopOn = !loopOn; loopBtn.classList.toggle('on', loopOn); };
canvas.onclick = e => { if (audio.duration) { audio.currentTime = e.offsetX / canvas.clientWidth * audio.duration; tick(); } };
addEventListener('resize', draw);
addEventListener('keydown', e => {
  if (e.target.matches('input, select, textarea')) { if (e.key === 'Escape') e.target.blur(); return; }
  if (e.code === 'Space' && audio.src) { e.preventDefault(); pp.click(); }
  if (e.key === 'Escape') drawer.hidden = true;
  if (e.key === '/') { e.preventDefault(); qbox.focus(); }
});

// ---- search box + start ---------------------------------------------------------------------------------
let qTimer;
qbox.oninput = () => { clearTimeout(qTimer); qTimer = setTimeout(() => setParam('q', qbox.value.trim()), 220); };
addEventListener('hashchange', render);
api('info').then(m => {
  $('#info').innerHTML = `${esc(m.game)}<br>${m.sounds} sounds · ${m.lines} lines<br>${m.textures} textures${m.vgmstream ? '' : '<br><b style="color:var(--accent)">vgmstream missing: no MPEG</b>'}<br>v${esc(m.version)}`;
}).catch(e => { $('#info').textContent = e.message; });
render();
