// Hype Toolkit UI (plain ES module): the website's design, data from the local hypekit HTTP API (/api/...).
// Pages share one pattern: big title, search, main segment + Filters panel (facet chips with counts), removable tags,
// a results bar (count, sort, star filter, select, play all) and the content. State lives in the URL hash.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const view = $('#view');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmt = t => t == null || !isFinite(t) ? '' : `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const hms = t => t == null ? '' : `${Math.floor(t / 3600)}:${String(Math.floor(t / 60) % 60).padStart(2, '0')}`;
const dur = t => !t ? '' : t >= 3600 ? `${Math.floor(t / 3600)} h ${Math.round(t / 60) % 60} min` : t >= 60 ? `${Math.round(t / 60)} min` : `${Math.round(t)} s`;
const num = n => Number(n || 0).toLocaleString('en-US');
const when = t => new Date(t * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }) + ', '
  + new Date(t * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
const el = html => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const list = v => (v || '').split(',').filter(Boolean);
const ICON = {
  play: '<svg viewBox="0 0 12 14"><path d="M0 0v14l12-7z"/></svg>',
  pause: '<svg viewBox="0 0 12 14"><path d="M0 0h4v14H0zM8 0h4v14H8z"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4 4"/></svg>',
  filter: '<svg viewBox="0 0 24 24"><path d="M4 6h16M7 12h10M10 18h4"/></svg>',
};
const KIND = { voice: 'Dialogue', music: 'Music', 'music part': 'Music part', sfx: 'Effect', ambience: 'Ambience', unused: 'Unused' };
const PAGES = [['sounds', 'Sounds'], ['dialogue', 'Dialogue'], ['textures', 'Textures'], ['models', 'Models'], ['saves', 'Saves']];
const ERAS = [['Vignette:6', 'Era I'], ['Vignette:9', 'Era II'], ['Vignette:11', 'Era III'], ['Vignette:12', 'Era IV']];
const PAGE = 120;

async function api(path, params = {}) {
  const u = new URL('/api/' + path, location.origin);
  for (const [k, v] of Object.entries(params)) if (v != null && v !== false && (v !== '' || k === 'ids')) u.searchParams.set(k, v);
  const r = await fetch(u);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function toast(msg, ms = 2800) {
  let t = $('.toast');
  if (!t) { t = el('<div class="toast"></div>'); document.body.append(t); }
  t.textContent = msg;
  clearTimeout(t._h);
  if (ms) t._h = setTimeout(() => t.remove(), ms);
  return t;
}

// ---- routing: #/<page>?<params> ---------------------------------------------------------------------------
function route() {
  const [p, qs] = location.hash.replace(/^#\/?/, '').split('?');
  return { page: p === 'script' ? 'dialogue' : p, params: Object.fromEntries(new URLSearchParams(qs || '')) };
}
function go(page, params = {}, replace = false) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== '' && v != null)).toString();
  const h = `#/${page}${qs ? '?' + qs : ''}`;
  if (replace) { history.replaceState(null, '', h); render(); } else location.hash = h;
}
function setParams(obj, replace = true) { const r = route(); Object.assign(r.params, obj); delete r.params.offset; go(r.page, r.params, replace); }
const setParam = (k, v) => setParams({ [k]: v });

let levels = [], levelName = {}, info = null;
const place = lv => levelName[lv] || lv;
const usedIn = lv => !lv?.length ? 'Not used' : lv.includes('Fix') ? 'Everywhere'
  : (s => s.size === 1 ? [...s][0] : `${s.size} places`)(new Set(lv.map(place)));

// ---- stars (favourites, kept in this browser) ---------------------------------------------------------------
const STARS = (() => { try { return JSON.parse(localStorage.getItem('hypekit-stars')) || {}; } catch { return {}; } })();
const stars = type => (STARS[type] ||= []);
const isStar = (type, id) => stars(type).includes(id);
function toggleStar(type, id) {
  const s = stars(type), i = s.indexOf(id);
  if (i >= 0) s.splice(i, 1); else s.push(id);
  localStorage.setItem('hypekit-stars', JSON.stringify(STARS));
  $$(`.star[data-type="${type}"][data-id="${CSS.escape(id)}"]`).forEach(b => b.classList.toggle('on', i < 0));
  return i < 0;
}
function starBtn(type, id) {
  const b = el(`<button class="star${isStar(type, id) ? ' on' : ''}" data-type="${type}" data-id="${esc(id)}" title="Star (S)" aria-label="Star">★</button>`);
  b.onclick = e => { e.stopPropagation(); e.preventDefault(); toggleStar(type, id); };
  return b;
}

// ---- selection (export a ZIP of many) ------------------------------------------------------------------------
const SEL = { on: false, type: null, ids: new Map() };            // id -> label
function selectMode(on, type) {
  SEL.on = on; SEL.type = type; SEL.ids.clear();
  view.classList.toggle('selecting', on);
  $$('.sel', view).forEach(x => x.classList.remove('sel'));
  $$('.act[data-select]').forEach(b => { b.classList.toggle('on', on); b.textContent = on ? 'Done' : 'Select'; });
  selbar();
}
function toggleSel(x) {
  const id = x.dataset.sel;
  if (!id) return;
  if (SEL.ids.has(id)) { SEL.ids.delete(id); x.classList.remove('sel'); } else { SEL.ids.set(id, x.dataset.label || id); x.classList.add('sel'); }
  selbar();
}
function selbar() {
  const b = $('#selbar');
  b.hidden = !SEL.on;
  if (!SEL.on) return;
  const n = SEL.ids.size;
  b.innerHTML = `<span class="n">${n} selected</span>`;
  const add = (label, fn, cls = 'act') => { const x = el(`<button class="${cls}">${label}</button>`); x.onclick = fn; b.append(x); return x; };
  add('Select all shown', () => { $$('[data-sel]', view).forEach(x => { if (!SEL.ids.has(x.dataset.sel)) toggleSel(x); }); });
  if (n) {
    add('Star', () => { SEL.ids.forEach((_, id) => { if (!isStar(SEL.type, id)) toggleStar(SEL.type, id); }); toast(`${n} starred`); });
    add(`Export ${n} as ZIP`, () => exportZip([...SEL.ids.keys()], SEL.type), 'act primary');
  }
  add('Cancel', () => selectMode(false));
}
async function exportZip(ids, type, state) {
  if (type === 'line') ids = ids.flatMap(id => (lineSounds[id] || []));
  if (!ids.length) return toast('Nothing to export: these lines have no voice recordings');
  const t = toast(`Packing ${ids.length} files…`, 0);
  try {
    const r = await fetch('/api/zip', { method: 'POST', body: JSON.stringify({ ids, state, name: `hype-${type}s-${ids.length}` }) });
    if (!r.ok) throw new Error((await r.json()).error);
    const a = el(`<a download="hype-${type}s-${ids.length}.zip"></a>`);
    a.href = URL.createObjectURL(await r.blob());
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    t.remove();
    toast(`Exported ${ids.length} files`);
  } catch (e) { t.remove(); toast(e.message, 5000); }
}

// ---- shared pieces ------------------------------------------------------------------------------------------
function head(title, sub, controls = []) {
  const h = el(`<section class="head wrap"><h1>${esc(title)}</h1>${sub ? `<p class="sub">${sub}</p>` : ''}<div class="controls"></div></section>`);
  const c = $('.controls', h);
  controls.filter(Boolean).forEach(x => c.append(x));
  if (!c.children.length) c.remove();
  return h;
}
function field(placeholder, value, onInput) {
  const f = el(`<label class="field">${ICON.search}<input type="search" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false"></label>`);
  const inp = $('input', f);
  inp.value = value || '';
  inp.dataset.key = route().page;
  let t;
  inp.oninput = () => { clearTimeout(t); t = setTimeout(() => onInput(inp.value.trim()), 220); };
  return f;
}
function seg(options, value, onPick) {
  const s = el('<div class="seg"></div>');
  for (const [v, label] of options) {
    const b = el(`<button>${label}</button>`);
    b.classList.toggle('on', (value || '') === v);
    b.onclick = () => onPick(v);
    s.append(b);
  }
  return s;
}
function row(...xs) { const r = el('<div class="row"></div>'); xs.filter(Boolean).forEach(x => r.append(x)); return r; }
function pick(options, value, onPick, label) {
  const s = el(`<select class="pick" aria-label="${esc(label || '')}"></select>`);
  s.innerHTML = options.map(([v, l]) => `<option value="${esc(v)}"${(value || '') === v ? ' selected' : ''}>${esc(l)}</option>`).join('');
  s.onchange = () => onPick(s.value);
  return s;
}
function levelPick(value, onPick, all = true) {
  const s = el('<select class="pick" aria-label="Place"></select>');
  let html = all ? '<option value="">All places</option>' : '', pl = null;
  for (const l of levels) {
    if (l.place !== pl) { if (pl !== null) html += '</optgroup>'; pl = l.place; html += `<optgroup label="${esc(pl)}">`; }
    html += `<option value="${esc(l.level)}"${value === l.level ? ' selected' : ''}>${esc(l.place)}${l.place === l.level ? '' : ' · ' + esc(l.level)}</option>`;
  }
  s.innerHTML = html + '</optgroup>';
  s.onchange = () => onPick(s.value);
  return s;
}
function section(title, n, ...body) {
  const s = el(`<section class="section"><div class="wrap">${title ? `<h2>${esc(title)}${n != null ? `<small>${esc(n)}</small>` : ''}</h2>` : ''}</div></section>`);
  body.filter(Boolean).forEach(b => $('.wrap', s).append(b));
  return s;
}
function act(label, fn, cls = '') { const b = el(`<button class="act ${cls}">${label}</button>`); b.onclick = fn; return b; }
function selectAct(type) {
  const b = act(SEL.on && SEL.type === type ? 'Done' : 'Select', () => selectMode(!(SEL.on && SEL.type === type), type));
  b.dataset.select = type;
  b.title = 'Select several to star or export (X)';
  return b;
}
function starAct(p) {
  const b = act('★ Starred', () => setParam('starred', p.starred ? '' : '1'), p.starred ? 'on' : '');
  b.title = 'Only starred';
  return b;
}
function rbar(countHtml, ...acts) {
  const r = el(`<div class="rbar"><div class="count">${countHtml}</div><div class="acts"></div></div>`);
  acts.filter(Boolean).forEach(a => $('.acts', r).append(a));
  return r;
}
const hl = (text, q) => {                          // highlight the search words
  let s = esc(text);
  for (const w of (q || '').split(/\s+/).filter(x => x.length > 1).sort((a, b) => b.length - a.length)) {
    s = s.replace(new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/&/g, '&amp;').replace(/</g, '&lt;')})(?![^<]*>)`, 'gi'), '<mark>$1</mark>');
  }
  return s;
};

// ---- filters: a Filters button + panel of facet chips, and removable tags -------------------------------------
const UI = { open: {} };
const SIZE_L = { tiny: 'Up to 32 px', small: '64 px', medium: '128 px', large: '256 px', huge: '512 px and more' };
const LEN_L = { short: 'Short · under 3 s', medium: 'Medium · 3 to 30 s', long: 'Long · over 30 s' };
const FMT_L = { pal8: '8-bit palette', rgb565: 'RGB 565', argb1555: 'ARGB 1555 (cut-out)', argb4444: 'ARGB 4444 (soft alpha)' };
const CAT_L = { figure: 'Figures', pickup: 'Pickups', object: 'Objects' };
const SPEC = {
  sounds: [
    { key: 'level', label: 'Place', type: 'levels' },
    { key: 'speaker', label: 'Speaker', top: 24 },
    { key: 'length', label: 'Length', labels: LEN_L, order: ['short', 'medium', 'long'] },
    { key: 'format', label: 'Format' },
    { key: 'loop', label: 'Looping', type: 'toggle', text: 'Only sounds that loop' },
    { key: 'group', label: 'Sound designer group', top: 24 }],
  lines: [
    { key: 'level', label: 'Place', type: 'levels' },
    { key: 'speaker', label: 'Speaker', top: 30, title: true },
    { key: 'voiced', label: 'Voice', labels: { 1: 'With a voice recording', 0: 'Text only' }, order: ['1', '0'], single: true },
    { key: 'common', label: 'Shared lines', type: 'toggle', text: 'Include pickup and menu lines', nocount: true }],
  textures: [
    { key: 'folder', label: 'Folder', top: 24 },
    { key: 'format', label: 'Format', labels: FMT_L },
    { key: 'size', label: 'Size (longest side)', labels: SIZE_L, order: ['tiny', 'small', 'medium', 'large', 'huge'] },
    { key: 'alpha', label: 'Transparency', labels: { 1: 'With transparency', 0: 'Opaque' }, order: ['1', '0'], single: true }],
  persos: [{ key: 'level', label: 'Place', type: 'levels' }],
};
const nice = s => (s.length > 2 && s === s.toUpperCase() ? s.toLowerCase().replace(/(^|[ \-'])\p{L}/gu, m => m.toUpperCase()) : s)
  .replace(/\b(i{1,3}|iv|vi{0,3})\b/gi, m => m.toUpperCase());     // 'TASKAN III' / 'Taskan Iii' -> 'Taskan III'

function activeCount(spec, p) { return spec.reduce((n, g) => n + (p[g.key] ? (g.type === 'toggle' ? 1 : list(p[g.key]).length) : 0), 0); }

function filterButton(page, spec, p) {
  const n = activeCount(spec, p);
  const b = el(`<button class="fbtn${UI.open[page] ? ' open' : ''}" title="Filters (F)">${ICON.filter}Filters${n ? `<span class="n">${n}</span>` : ''}</button>`);
  b.onclick = () => { UI.open[page] = !UI.open[page]; render(); };
  return b;
}

function filterPanel(page, spec, p, facets) {
  if (!UI.open[page] || !facets) return null;
  const panel = el('<div class="fpanel"></div>');
  for (const g of spec) {
    const fc = facets[g.key];
    const cur = g.type === 'toggle' ? (p[g.key] ? ['1'] : []) : list(p[g.key]);
    const set = vals => setParam(g.key, vals.join(','));
    const chip = (v, label, n, dot) => {
      const on = cur.includes(String(v));
      const c = el(`<button class="fchip${on ? ' on' : ''}${!on && n === 0 ? ' zero' : ''}">${dot || ''}${esc(label)}${n != null && !g.nocount ? `<i>${num(n)}</i>` : ''}</button>`);
      c.onclick = () => set(g.single || g.type === 'toggle' ? (on ? [] : [String(v)]) : on ? cur.filter(x => x !== String(v)) : [...cur, String(v)]);
      return c;
    };
    const box = el(`<div class="fgroup"><h4>${esc(g.label)}</h4></div>`);
    if (g.type === 'toggle') {
      const c = el('<div class="chips"></div>'); c.append(chip('1', g.text, typeof fc === 'number' ? fc : null)); box.append(c);
    } else if (g.type === 'levels') {
      if (!fc || !Object.keys(fc).length) continue;
      let pl = null, c = null;
      for (const l of levels) {
        if (!(l.level in fc) && !cur.includes(l.level)) continue;
        if (l.place !== pl) { pl = l.place; box.append(el(`<div class="sub4">${esc(pl)}</div>`)); c = el('<div class="chips"></div>'); box.append(c); }
        c.append(chip(l.level, l.place === l.level ? l.level : l.level, fc[l.level] || 0));
      }
      for (const lv of Object.keys(fc)) if (!levels.some(l => l.level === lv)) { if (!c) { c = el('<div class="chips"></div>'); box.append(c); } c.append(chip(lv, lv, fc[lv])); }
    } else {
      if (!fc || !Object.keys(fc).length) continue;
      let entries = g.order ? g.order.filter(k => k in fc || cur.includes(k)).map(k => [k, fc[k] || 0]) : Object.entries(fc).sort((a, b) => b[1] - a[1]);
      const c = el('<div class="chips"></div>');
      const all = entries.length;
      const showAll = UI.open[page + ':' + g.key];
      if (g.top && !showAll) entries = entries.filter(([k], i) => i < g.top || cur.includes(k));
      for (const [k, n] of entries) c.append(chip(k, g.labels?.[k] || (g.title || g.key === 'speaker' ? nice(k) : k), n));
      if (g.top && all > g.top) {
        const m = el(`<button class="morechips">${showAll ? 'Fewer' : `All ${all}`}</button>`);
        m.onclick = () => { UI.open[page + ':' + g.key] = !showAll; render(); };
        c.append(m);
      }
      box.append(c);
    }
    panel.append(box);
  }
  const n = activeCount(spec, p);
  const foot = el(`<div class="foot"><span class="muted">${n ? `${n} filter${n > 1 ? 's' : ''} on` : 'Pick as many as you like: within a group any match, across groups all.'}</span></div>`);
  const done = el('<button class="act">Done</button>');
  done.onclick = () => { UI.open[page] = false; render(); };
  if (n) foot.append(row(act('Clear all', () => setParams(Object.fromEntries(spec.map(g => [g.key, ''])))), done));
  else foot.append(done);
  panel.append(foot);
  return panel;
}

function filterTags(spec, p) {
  const tags = el('<div class="tags"></div>');
  for (const g of spec) {
    const cur = g.type === 'toggle' ? (p[g.key] ? ['1'] : []) : list(p[g.key]);
    for (const v of cur) {
      const label = g.type === 'toggle' ? g.text : g.type === 'levels' ? `${place(v)}${place(v) === v ? '' : ' · ' + v}` : (g.labels?.[v] || (g.title || g.key === 'speaker' ? nice(v) : v));
      const t = el(`<button class="tag" title="Remove"><b>${esc(g.label)}</b>${esc(label)}<span>×</span></button>`);
      t.onclick = () => setParam(g.key, g.type === 'toggle' ? '' : cur.filter(x => x !== v).join(','));
      tags.append(t);
    }
  }
  if (p.starred) { const t = el('<button class="tag"><b>Only</b>Starred<span>×</span></button>'); t.onclick = () => setParam('starred', ''); tags.append(t); }
  if (tags.children.length > 1 && !UI.open[route().page]) { const c = el('<button class="tag clear">Clear all</button>'); c.onclick = () => setParams({ ...Object.fromEntries(spec.map(g => [g.key, ''])), starred: '' }); tags.append(c); }
  return tags.children.length ? tags : null;
}

function apiFilters(spec, p, type) {
  const f = { q: p.q };
  for (const g of spec) if (p[g.key]) f[g.key] = p[g.key];
  if (p.starred) f.ids = stars(type).join(',');
  return f;
}

// ---- items ----------------------------------------------------------------------------------------------
const playBtn = disabled => `<button class="play" aria-label="Play"${disabled ? ' disabled' : ''}>${ICON.play}</button>`;
const lineSounds = {};                                   // line id -> voice sound ids (for export / play)

function soundItem(s, q) {
  const x = el(`<div class="item${cur?.id === s.id ? ' cur' : ''}" data-id="${esc(s.id)}" data-sel="${esc(s.id)}" data-label="${esc(s.title)}">
    <span class="check"></span>${playBtn()}
    <div><div class="t">${hl(s.title, q)}</div><div class="s">${esc(KIND[s.kind] || s.kind)} · ${esc(usedIn(s.levels))}${s.loop ? ' · loops' : ''}</div></div>
    <div class="d">${fmt(s.seconds)}</div></div>`);
  x.insertBefore(starBtn('sound', s.id), $('.d', x));
  $('.play', x).onclick = e => { e.stopPropagation(); play(s); };
  x.onclick = () => SEL.on ? toggleSel(x) : openSound(s.id);
  x._rec = s;
  return x;
}

function lineRec(l, sid) {
  return { id: sid, title: `${nice(l.speaker || '')}${l.speaker ? ': ' : ''}${l.text}`, kind: 'voice', levels: [l.level], format: 'MPEG', line: l.id };
}

function turnItem(l, { withLevel = false, q = '' } = {}) {
  if (l.sounds) lineSounds[l.id] = l.sounds;
  const has = l.sounds ? l.sounds.length > 0 : true;
  const x = el(`<div class="turn" data-line="${esc(l.id)}" data-sel="${esc(l.id)}"${l.sounds?.length ? ` data-sounds=" ${esc(l.sounds.join(' '))} "` : ''}>
    <span class="check"></span>${playBtn(!has)}<div>${l.speaker ? `<div class="who">${esc(l.speaker)}</div>` : ''}<div class="tx">${hl(l.text, q)}</div>
    ${withLevel ? `<div class="lv">${esc(place(l.level))} · ${esc(l.level)}</div>` : ''}</div></div>`);
  x.append(starBtn('line', l.id));
  $('.play', x).onclick = async e => {
    e.stopPropagation();
    let sid = l.sounds?.[0];
    if (!l.sounds) { const r = await api('get/' + encodeURIComponent(l.id)); l.sounds = r.sounds.map(s => s.id); lineSounds[l.id] = l.sounds; sid = l.sounds[0]; }
    if (!sid) return toast('This line has no voice recording');
    play(lineRec(l, sid), x);
  };
  x.onclick = () => { if (SEL.on) return toggleSel(x); if (withLevel) go('dialogue', { level: l.level, line: l.id }); };
  x._rec = l;
  return x;
}

function textureCard(t, i, all) {
  const c = el(`<a class="card" href="#" data-id="${esc(t.id)}" data-sel="${esc(t.id)}"><span class="check"></span><div class="img"><img loading="lazy" alt="" src="/api/png/${encodeURIComponent(t.id)}"></div>
    <div class="cap"><b title="${esc(t.path)}">${esc(t.path.split('/').pop().replace(/\.gf$/i, ''))}</b><span>${t.width} × ${t.height} · ${esc(t.path.includes('/') ? t.path.split('/')[0] : t.archive)}</span></div></a>`);
  c.append(starBtn('texture', t.id));
  c.onclick = e => { e.preventDefault(); if (SEL.on) return toggleSel(c); lightbox(all, i); };
  return c;
}

// infinite list: first page given, more on demand
function more(container, load, make, total, got) {
  let off = got;
  const b = el('<button class="btn ghost loadmore">Show more</button>');
  b.hidden = off >= total;
  b.onclick = async () => {
    b.disabled = true;
    const items = await load(off);
    items.forEach(x => container.append(make(x)));
    off += items.length;
    b.hidden = !items.length || off >= total;
    b.disabled = false;
    markPlaying();
  };
  return b;
}

// ---- pages ----------------------------------------------------------------------------------------------
let lastPage = null;
async function render() {
  const { page, params } = route();
  if (params.filters === '1' && page !== lastPage) UI.open[page] = true;     // deep link with the Filters panel open
  $$('#links a').forEach(a => a.classList.toggle('on', a.dataset.page === page));
  const focused = document.activeElement?.matches?.('.field input') ? document.activeElement : null;
  const fn = { '': pageHome, search: pageSearch, sounds: pageSounds, dialogue: pageDialogue, textures: pageTextures,
    models: pageModels, saves: pageSaves }[page] || pageHome;
  const keepModels = page === 'models' && M.key && $('.stagebox', view);
  if (page !== 'models') M.key = null;
  if (page !== lastPage && SEL.on) selectMode(false);
  const y = scrollY, changed = page !== lastPage;
  try {
    await fn(params, keepModels);
  } catch (e) {
    view.replaceChildren(head('Something went wrong.', esc(e.message)));
  }
  if (changed) scrollTo(0, 0); else if (!params.line) scrollTo(0, y);
  document.body.classList.toggle('bare', params.bare === '1');      // bare=1: no page heading (screenshots)
  lastPage = page;
  view.classList.toggle('selecting', SEL.on);
  if (focused) {                                   // typing in a search field: keep the very same input focused
    const now = $('.field input', view);
    if (now && now !== focused && focused.dataset.key === page) { now.replaceWith(focused); focused.focus(); }
  }
  if (params.play && params.play !== cur?.id) api('get/' + encodeURIComponent(params.play)).then(s => play(s)).catch(e => toast(e.message));
}

function show(...nodes) {
  view.replaceChildren(...nodes.filter(Boolean));
  if (route().page !== lastPage) { view.classList.remove('fadein'); void view.offsetWidth; view.classList.add('fadein'); }
}

async function pageHome() {
  const [saves, st] = await Promise.all([api('saves').catch(() => []), api('q/persos', { limit: 1 }).catch(() => null)]);
  const eras = el(`<div class="eras">${ERAS.map(([id, n]) => `<figure><img alt="" src="/api/png/${id}"><figcaption>${n}</figcaption></figure>`).join('')}</div>`);
  const nums = el(`<div class="nums">
    <div><b>${num(info.sounds)}</b><span>sounds</span></div><div><b>${num(info.lines)}</b><span>lines of dialogue</span></div>
    <div><b>${num(info.textures)}</b><span>textures</span></div>
    <div><b>${st?.items ? num(st.total) : num(saves.length)}</b><span>${st?.items ? 'models' : 'save games'}</span></div></div>`);
  const tile = (page, t, p) => el(`<a class="tile" href="#/${page}"><h3>${t}</h3><p>${p}</p><span class="more">Open</span></a>`);
  const latest = saves[0];
  const nStars = Object.values(STARS).reduce((n, a) => n + a.length, 0);
  const tiles = el('<div class="tiles"></div>');
  tiles.append(
    tile('sounds', 'Sounds', 'Every voice, tune and effect, named, filtered and playable.'),
    tile('dialogue', 'Dialogue', 'The whole script, place by place. Listen to a scene like an audiobook.'),
    tile('textures', 'Textures', 'The game\'s own pictures, exactly as it draws them.'),
    tile('models', 'Models', 'Every figure in 3D, with all of its moves.'),
    tile('saves', 'Saves', latest ? `Last played in ${esc(latest.place)}, ${esc(when(latest.modified))}. Compare any two.` : 'Your save games, opened up.'),
    tile('search', nStars ? `${nStars} starred` : 'Search', nStars ? 'Everything you starred, one click away on every page.' : 'Find any line, sound or picture by a word. Press Ctrl K anywhere.'));
  const hero = head('Hype Toolkit.', 'Everything in your copy of Hype: The Time Quest, straight out of the game files.',
    [field('Search sounds, dialogue, textures and models', '', q => q && go('search', { q }))]);
  hero.classList.add('hero');
  const foot = el(`<div class="homefoot"><p>Reading <span class="path">${esc(info.game)}</span> · <a href="#">Change</a></p>
    <p>Ctrl K quick search · / search this page · J K move · Enter play · S star · X select · Space pause · N P next and previous</p></div>`);
  $('a', foot).onclick = e => { e.preventDefault(); gameSheet(); };
  show(hero, section('', null, eras), section('', null, nums), section('', null, tiles), section('', null, foot));
}

// ---- game folder: the setup screen (nothing found) and the settings card -----------------------------------
function folderForm() {
  const f = el(`<div class="folderform">
    <button class="btn" data-browse>Choose folder…</button>
    <div class="or">or paste its path</div>
    <div class="pathrow"><input class="pathin" type="text" spellcheck="false" placeholder="C:\\Program Files\\Hype - The Time Quest"><button class="btn ghost" data-use>Use</button></div>
    <p class="msg"></p></div>`);
  const msg = $('.msg', f), inp = $('.pathin', f), btns = $$('button', f);
  const busy = (on, text = '', bad = false) => { btns.forEach(b => { b.disabled = on; }); msg.textContent = text; msg.classList.toggle('bad', bad); };
  const choose = async manual => {
    if (manual !== undefined && !manual.trim()) return busy(false, 'Paste the folder path first.', true);
    busy(true, manual === undefined ? 'Pick the folder in the window that just opened…' : 'Opening the game…');
    const slow = setTimeout(() => { msg.textContent = 'Reading the game. The first time takes a few seconds…'; }, 1500);
    try {
      const r = await fetch(manual === undefined ? '/api/game/browse' : '/api/game', { method: 'POST', body: JSON.stringify({ folder: manual }) });
      const j = await r.json();
      clearTimeout(slow);
      if (j.cancelled) return busy(false);
      if (!r.ok) { if (j.folder) inp.value = j.folder; return busy(false, j.error || 'That did not work.', true); }
      busy(true, 'Done.');
      toast(`Now reading ${j.game}`);
      setTimeout(() => location.reload(), 400);
    } catch (e) { clearTimeout(slow); busy(false, e.message, true); }
  };
  $('[data-browse]', f).onclick = () => choose();
  $('[data-use]', f).onclick = () => choose(inp.value);
  inp.onkeydown = e => { if (e.key === 'Enter') choose(inp.value); };
  return f;
}

function setupScreen() {
  $('#links').hidden = true;
  $('#gamebtn').hidden = true;
  const h = head('Where is Hype?', 'The toolkit reads your own copy of Hype: The Time Quest. Show it the folder the game is installed in, the one with Gamedata inside.', [folderForm()]);
  h.classList.add('hero');
  view.replaceChildren(h, section('', null, el('<p class="muted" style="text-align:center;font-size:.9rem">The folder is remembered. Nothing in it is changed.</p>')));
}

async function gameSheet() {
  const g = await api('game');
  sbody.innerHTML = `<h3>Game folder</h3><p class="lead">The toolkit reads this copy of the game. Nothing in it is changed.</p>
    <div class="pathbox">${esc(g.game || 'none')}</div>
    ${info ? `<p class="muted" style="font-size:.88rem;margin:10px 0 0">${num(info.sounds)} sounds · ${num(info.lines)} lines · ${num(info.textures)} textures</p>` : ''}
    ${g.env ? `<p class="muted" style="font-size:.85rem">Set by HYPEKIT_GAME=${esc(g.env)}: that wins at the next start.</p>` : ''}
    <h4>Use another copy</h4>`;
  sbody.append(folderForm());
  sbody.append(el('<p class="muted" style="font-size:.85rem;margin-top:14px">Remembered for the next start. Each folder keeps its own index, so switching back is instant.</p>'));
  sheet.hidden = false;
}

async function pageSearch(p) {
  const q = p.q || '';
  const tab = p.tab || '';
  const h = head('Search.', q ? `Results for “${esc(q)}”` : 'Sounds, dialogue, textures and models.', [field('Search everything', q, v => setParam('q', v))]);
  if (!q) return show(h);
  const n = tab ? 200 : 8;
  const [s, l, t, m] = await Promise.all([api('q/sounds', { q, limit: n }), api('q/lines', { q, limit: n, common: 1 }), api('q/textures', { q, limit: n }),
    api('q/persos', { q, limit: n }).catch(() => ({ items: null }))]);
  const counts = { sounds: s.total, dialogue: l.total, textures: t.total, models: m.items ? m.total : 0 };
  $('.controls', h).append(seg([['', `All <i class="muted">${num(s.total + l.total + t.total + counts.models)}</i>`], ['sounds', `Sounds <i class="muted">${num(s.total)}</i>`],
    ['dialogue', `Dialogue <i class="muted">${num(l.total)}</i>`], ['textures', `Textures <i class="muted">${num(t.total)}</i>`], ['models', `Models <i class="muted">${num(counts.models)}</i>`]],
  tab, v => setParam('tab', v)));
  const out = [h];
  const all = (page, total, extra = {}) => total > n ? el(`<a class="more" href="#/${page}?${new URLSearchParams({ q, ...extra })}">All ${num(total)}</a>`) : null;
  if ((!tab || tab === 'sounds') && s.items.length) { const x = el('<div class="list"></div>'); s.items.forEach(i => x.append(soundItem(i, q))); out.push(section('Sounds', num(s.total), x, all('sounds', s.total))); }
  if ((!tab || tab === 'dialogue') && l.items.length) { const x = el('<div class="read"></div>'); l.items.forEach(i => x.append(turnItem(i, { withLevel: true, q }))); out.push(section('Dialogue', num(l.total), x, all('dialogue', l.total, { common: 1 }))); }
  if ((!tab || tab === 'textures') && t.items.length) { const x = el('<div class="cards"></div>'); t.items.forEach((i, k) => x.append(textureCard(i, k, t.items))); out.push(section('Textures', num(t.total), x, all('textures', t.total))); }
  if ((!tab || tab === 'models') && m.items?.length) { const x = el('<div class="cards" style="--card:220px"></div>'); m.items.forEach(g => x.append(modelCard(g, true))); out.push(section('Models', num(m.total), x, all('models', m.total))); }
  if (out.length === 1) out.push(el('<div class="empty">Nothing found.</div>'));
  show(...out);
  markPlaying();
}

async function pageSounds(p) {
  const spec = SPEC.sounds;
  const f = apiFilters(spec, p, 'sound');
  const r = await api('q/sounds', { ...f, kind: p.kind, sort: p.sort, limit: PAGE, facets: 1 });
  const fk = r.facets.kind, all = Object.entries(fk).reduce((n, [k, v]) => n + (k === 'music part' ? 0 : v), 0);
  const kinds = [['', 'All'], ['voice', 'Dialogue'], ['music', 'Music'], ['sfx', 'Effects'], ['ambience', 'Ambience'], ['unused', 'Unused']]
    .map(([k, l]) => [k, `${l}`]);
  const h = head('Sounds.', 'Every voice, tune and effect in the game, with its name, its place and its line.', [
    field('Search sounds, speakers, lines', p.q, v => setParam('q', v)),
    row(seg(kinds, p.kind, v => setParam('kind', v)), filterButton('sounds', spec, p)),
    filterPanel('sounds', spec, p, r.facets), filterTags(spec, p)]);
  $$('.seg button', h).forEach((b, i) => { const k = kinds[i][0]; b.title = `${num(k ? fk[k] || 0 : all)} sounds`; });
  const l = el('<div class="list"></div>');
  r.items.forEach(s => l.append(soundItem(s, p.q)));
  const sortP = pick([['', 'Game order'], ['title', 'Title A–Z'], ['long', 'Longest first'], ['short', 'Shortest first']], p.sort, v => setParam('sort', v), 'Sort');
  const bar = rbar(`<b>${num(r.total)}</b> sound${r.total === 1 ? '' : 's'}${r.seconds ? ` · ${dur(r.seconds)}` : ''}`,
    starAct(p), sortP, selectAct('sound'), r.total ? act(`${ICON.play} Play all`, () => playAll('sounds', { ...f, kind: p.kind, sort: p.sort }), 'primary') : null);
  const sec = section('', null, bar, r.items.length ? l : el('<div class="empty">No sounds match. Try fewer filters.</div>'),
    more(l, off => api('q/sounds', { ...f, kind: p.kind, sort: p.sort, limit: PAGE, offset: off }).then(x => x.items), s => soundItem(s, p.q), r.total, r.items.length));
  show(h, sec);
  markPlaying();
}

async function pageDialogue(p) {
  const spec = SPEC.lines;
  const filtering = p.q || p.speaker || p.voiced || p.starred || list(p.level).length > 1 || p.all;
  if (filtering) return dialogueList(p, spec);
  const level = p.level || levels.find(l => l.level !== 'Fix')?.level;
  const i = levels.findIndex(l => l.level === level), prev = levels[i - 1], next = levels[i + 1];
  const nav = (l, label, title) => { const b = el(`<button class="round" aria-label="${title}">${label}</button>`); b.disabled = !l; if (l) { b.title = l.place; b.onclick = () => setParams({ level: l.level, line: '' }); } return b; };
  const [lines0, fac] = await Promise.all([api('script/' + encodeURIComponent(level)), api('q/lines', { level, common: p.common, limit: 1, facets: 1 })]);
  const lines = lines0.filter(l => p.common || !l.common);
  const pSpec = spec.filter(g => g.key !== 'level');
  const h = head('Dialogue.', 'The whole script, place by place, with the voice that speaks each line.', [
    field('Search the dialogue', p.q, v => setParam('q', v)),
    row(nav(prev, '‹', 'Previous place'), levelPick(level, v => setParams({ level: v, line: '' }), false), nav(next, '›', 'Next place'), filterButton('dialogue', pSpec, p)),
    filterPanel('dialogue', pSpec, p, fac.facets), filterTags(pSpec, p)]);
  const r = el('<div class="read"></div>');
  let scene = null, who;
  for (const l of lines) {                         // a scene = consecutive lines of one speaker, named once
    const same = scene && l.speaker === who;
    if (!same) { scene = el('<div class="scene"></div>'); r.append(scene); who = l.speaker; }
    const t = turnItem(l);
    if (same) $('.who', t)?.remove();
    scene.append(t);
  }
  const voiced = lines.filter(l => l.sounds.length);
  const speakers = [...new Set(lines.map(l => l.speaker).filter(Boolean))];
  const bar = rbar(`<b>${esc(levels[i]?.place || level)}</b> · ${num(lines.length)} lines · ${num(voiced.length)} voiced${speakers.length ? ` · ${speakers.slice(0, 4).map(nice).join(', ')}${speakers.length > 4 ? ` and ${speakers.length - 4} more` : ''}` : ''}`,
    selectAct('line'), voiced.length ? act(`${ICON.play} Play the scene`, () => queue(voiced.map(l => lineRec(l, l.sounds[0]))), 'primary') : null);
  bar.style.cssText = 'max-width:760px;margin:0 auto 6px';
  show(h, section('', null, bar, lines.length ? r : el('<div class="empty">No dialogue in this place.</div>')));
  markPlaying();
  if (p.line) { const x = $(`[data-line="${CSS.escape(p.line)}"]`); if (x) { x.classList.add('cur'); x.scrollIntoView({ block: 'center' }); } }
}

async function dialogueList(p, spec) {
  const f = apiFilters(spec, p, 'line');
  const r = await api('q/lines', { ...f, sort: p.sort, limit: 200, facets: 1 });
  const h = head('Dialogue.', 'Every line in the game. Filter by who speaks, where, and whether it is voiced.', [
    field('Search the dialogue', p.q, v => setParam('q', v)),
    row(act('‹ Read place by place', () => go('dialogue', { level: list(p.level)[0] || '' })), filterButton('dialogue', spec, p)),
    filterPanel('dialogue', spec, p, r.facets), filterTags(spec, p)]);
  const box = el('<div class="read"></div>');
  let lv = null;
  const add = l => {
    if (l.level !== lv) { lv = l.level; box.append(el(`<h3 style="margin:26px 0 6px 6px">${esc(place(lv))} <span class="muted" style="font-weight:500;font-size:.9rem">${esc(lv)}</span></h3>`)); }
    return turnItem(l, { q: p.q });
  };
  r.items.forEach(l => box.append(add(l)));
  const sortP = pick([['', 'Game order'], ['speaker', 'Speaker'], ['long', 'Longest first']], p.sort, v => setParam('sort', v), 'Sort');
  const voiced = r.items.filter(l => l.sounds.length);
  const bar = rbar(`<b>${num(r.total)}</b> line${r.total === 1 ? '' : 's'}`, starAct(p), sortP, selectAct('line'),
    voiced.length ? act(`${ICON.play} Play ${voiced.length > 1 ? 'all ' + num(voiced.length) : ''}`, () => queue(voiced.map(l => lineRec(l, l.sounds[0]))), 'primary') : null);
  bar.style.cssText = 'max-width:760px;margin:0 auto 6px';
  const mb = more(box, off => api('q/lines', { ...f, sort: p.sort, limit: 200, offset: off }).then(x => x.items), l => { const t = add(l); box.append(t); return document.createComment(''); }, r.total, r.items.length);
  show(h, section('', null, bar, r.items.length ? box : el('<div class="empty">No lines match. Try fewer filters.</div>'), mb));
  markPlaying();
}

async function pageTextures(p) {
  const spec = SPEC.textures;
  const f = apiFilters(spec, p, 'texture');
  const r = await api('q/textures', { ...f, archive: p.archive, sort: p.sort, limit: PAGE, facets: 1 });
  const h = head('Textures.', 'The game\'s own pictures, decoded exactly as it draws them.', [
    field('Search texture names and folders', p.q, v => setParam('q', v)),
    row(seg([['', 'All'], ['Textures', 'Textures'], ['Vignette', 'Screens']], p.archive, v => setParam('archive', v)), filterButton('textures', spec, p)),
    filterPanel('textures', spec, p, r.facets), filterTags(spec, p)]);
  const size = p.grid || (p.archive === 'Vignette' ? 'l' : 'm');
  const g = el(`<div class="cards ${size}${p.archive === 'Vignette' ? ' wide' : ''}"></div>`);
  const items = r.items.slice();
  items.forEach((t, i) => g.append(textureCard(t, i, items)));
  const sortP = pick([['', 'Game order'], ['name', 'Name A–Z'], ['large', 'Largest first'], ['small', 'Smallest first'], ['folder', 'Folder']], p.sort, v => setParam('sort', v), 'Sort');
  const bar = rbar(`<b>${num(r.total)}</b> texture${r.total === 1 ? '' : 's'}`, starAct(p), sortP,
    seg([['s', 'S'], ['m', 'M'], ['l', 'L']], size, v => setParam('grid', v)), selectAct('texture'));
  show(h, section('', null, bar, items.length ? g : el('<div class="empty">No textures match. Try fewer filters.</div>'),
    more(g, off => api('q/textures', { ...f, archive: p.archive, sort: p.sort, limit: PAGE, offset: off }).then(x => x.items),
      t => { items.push(t); return textureCard(t, items.length - 1, items); }, r.total, r.items.length)));
}

// ---- models -------------------------------------------------------------------------------------------------
const M = { key: null, viewer: null, canvas: null, loaded: null, groups: [], raf: 0 };

function modelCard(g, link = false) {
  const x = g.places[0];
  const c = el(`<a class="card text" href="#/models?id=${encodeURIComponent(x.id)}" data-ids=" ${esc(g.places.map(y => y.id).join(' '))} " data-sel="${esc(x.id)}" data-label="${esc(g.name)}">
    <span class="check"></span><b><span class="cat ${g.category}"></span>${esc(g.name)}</b>
    <span>${num(g.parts)} parts · ${num(g.states)} moves · ${esc(g.places.length === 1 ? place(x.level) : g.places.length + ' places')}</span></a>`);
  c.append(starBtn('model', g.name));
  c.onclick = e => {
    if (link) return;
    e.preventDefault();
    if (SEL.on) return toggleSel(c);
    setParams({ id: x.id, state: '' });
    $('.stagebox')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };
  return c;
}

async function pageModels(p, keep) {
  const spec = SPEC.persos;
  const key = JSON.stringify([p.q, p.sort, p.level, p.category, p.starred, UI.open.models, stars('model').length]);
  if (!(keep && M.key === key)) {
    const f = apiFilters(spec, p, 'model');
    const r = await api('q/persos', { ...f, category: p.category, sort: p.sort, limit: 5000 });
    const hd = () => head('Models.', 'Every figure in the game in 3D, with all of its moves.');
    if (!r.items) return scanProgress(hd(), r.status);
    M.groups = r.items;
    const fc = r.facets.category;
    const h = head('Models.', 'Every figure in the game in 3D, with all of its moves.', [
      field('Search model names', p.q, v => setParam('q', v)),
      row(seg([['', 'All'], ['figure', 'Figures'], ['pickup', 'Pickups'], ['object', 'Objects']], p.category, v => setParams({ category: v, id: '', state: '' })), filterButton('models', spec, p)),
      filterPanel('models', spec, p, r.facets), filterTags(spec, p)]);
    $$('.seg button', h).forEach((b, i) => { const k = ['', 'figure', 'pickup', 'object'][i]; b.title = `${num(k ? fc[k] || 0 : Object.values(fc).reduce((a, b2) => a + b2, 0))} models`; });
    const stage = el(`<div class="stagebox"><div class="title"><b></b><span></span></div>
      <div class="tr"></div><div class="scrubber"><span class="t0">0:00</span><input type="range" min="0" max="1" step="0.001" value="0" aria-label="Frame"><span class="t1"></span></div>
      <div class="bar"></div><div class="msg"></div></div>`);
    if (!M.canvas) M.canvas = document.createElement('canvas');
    stage.prepend(M.canvas);
    const g = el('<div class="cards" style="--card:220px"></div>');
    const sortP = pick([['', 'Most detailed'], ['az', 'Name A–Z'], ['moves', 'Most moves'], ['places', 'In most places']], p.sort, v => setParam('sort', v), 'Sort');
    const bar = rbar(`<b>${num(M.groups.length)}</b> model${M.groups.length === 1 ? '' : 's'}`, starAct(p), sortP, selectAct('model'));
    let shown = 0;
    const mb = el('<button class="btn ghost loadmore">Show more</button>');
    const addCards = () => { M.groups.slice(shown, shown + PAGE).forEach(x => g.append(modelCard(x))); shown += PAGE; mb.hidden = shown >= M.groups.length; markModel(); };
    mb.onclick = addCards;
    addCards();
    show(h, section('', null, M.groups.length ? stage : el('<div class="empty">No models match. Try fewer filters.</div>')), section('', null, bar, g, mb));
    if (!M.groups.length) return;
    if (!M.viewer) { const { Viewer } = await import('./viewer.js'); M.viewer = new Viewer(M.canvas); }
    M.key = key;
    M.loaded = null;
  }
  const id = p.id || M.groups[0]?.places[0].id;
  if (!id) return;
  markModel(id);
  const want = `${id}|${p.state ?? ''}`;
  if (M.loaded === want) return;
  const same = M.loaded?.split('|')[0] === id;
  M.loaded = want;
  await showModel(id, p.state, same);
}

function markModel(id = route().params.id || M.groups[0]?.places[0].id) {
  $$('.card.text[data-ids]', view).forEach(c => c.classList.toggle('on', !!id && c.dataset.ids.includes(` ${id} `)));
}

function scanProgress(h, st) {
  const box = el(`<div class="scan"><p>Reading the 3D data of every place. This happens once and takes about a minute.</p>
    <div class="progress"><i></i></div><small></small></div>`);
  show(h, box);
  const tick = async () => {
    if (route().page !== 'models' || !box.isConnected) return;
    const r = await api('q/persos', { limit: 1 }).catch(() => null);
    const s = r?.status || st;
    if (s.state === 'ready') return render();
    if (s.state === 'error') { $('small', box).textContent = s.error; return; }
    $('i', box).style.width = `${s.total ? 100 * s.done / s.total : 2}%`;
    $('small', box).textContent = s.total ? `${s.done} of ${s.total} places · about ${Math.max(5, Math.round((s.total - s.done) * 1.6))} s left` : 'Starting…';
    setTimeout(tick, 1000);
  };
  tick();
}

async function showModel(id, state, sameModel) {
  const stage = $('.stagebox', view);
  if (!stage) return;
  const bar = $('.bar', stage), msg = $('.msg', stage), tr = $('.tr', stage), range = $('input[type=range]', stage);
  const grp = M.groups.find(g => g.places.some(x => x.id === id)) || { name: id, places: [{ id, level: id.split(':')[0] }] };
  const lv = (grp.places.find(x => x.id === id) || grp.places[0]).level;
  $('.title b', stage).textContent = grp.name;
  $('.title span', stage).textContent = `${CAT_L[grp.category] ? CAT_L[grp.category].slice(0, -1) + ' · ' : ''}${place(lv)}`;
  if (!sameModel) msg.innerHTML = '<div class="spinner"></div>';
  const inf = await api('perso/' + encodeURIComponent(id));
  const anims = inf.animations;
  const curState = state ?? String(anims.find(s => s.initial)?.index ?? anims[0]?.index ?? '');
  const k = anims.findIndex(s => String(s.index) === curState);
  const V = M.viewer;
  const b = (label, title, fn, dis, cls = 'round') => { const x = el(`<button class="${cls}" aria-label="${title}" title="${title}">${label}</button>`); x.disabled = !!dis; x.onclick = fn; return x; };
  bar.innerHTML = '';
  const pause = b(V.playing ? '❚❚' : '▶', 'Play / pause (Space)', () => { V.setPlaying(!V.playing); pause.textContent = V.playing ? '❚❚' : '▶'; });
  pause.style.fontSize = '.78rem';
  const sel = el('<select class="pick" aria-label="Move"></select>');
  sel.innerHTML = anims.map((s, j) => `<option value="${s.index}"${j === k ? ' selected' : ''}>Move ${j + 1} of ${anims.length}${s.initial ? ' · standing' : ''}</option>`).join('');
  sel.onchange = () => setParam('state', sel.value);
  const step = d => { const j = k + d; if (j >= 0 && j < anims.length) setParam('state', String(anims[j].index)); };
  M.step = step;
  const speeds = [0.25, 0.5, 1, 2];
  const sp = b(`${V.speed || 1}×`, 'Speed', () => { const nx = speeds[(speeds.indexOf(V.speed || 1) + 1) % speeds.length]; V.setSpeed(nx); sp.textContent = `${nx}×`; }, false, 'speed');
  if (grp.places.length > 1) {
    const where = el('<select class="pick" aria-label="Place"></select>');
    where.innerHTML = grp.places.map(x => `<option value="${esc(x.id)}"${x.id === id ? ' selected' : ''}>${esc(place(x.level))}</option>`).join('');
    where.onchange = () => setParams({ id: where.value, state: '' });
    bar.append(where);
  }
  const url = `/api/glb/${encodeURIComponent(id)}${curState !== '' ? '?state=' + curState : ''}`;
  const fname = `${(grp.name || id).replace(/[^\w-]+/g, '_')}${k >= 0 ? '_move' + (k + 1) : ''}`;
  const dl = el(`<a class="round" title="Download as glTF (.glb)" aria-label="Download" href="${url}" download="${esc(fname)}.glb">↓</a>`);
  dl.style.textDecoration = 'none';
  bar.append(pause, b('‹', 'Previous move ([)', () => step(-1), k <= 0), sel, b('›', 'Next move (])', () => step(1), k < 0 || k >= anims.length - 1), sp,
    b('⟲', 'Reset view', () => V.frameView()), dl);
  tr.innerHTML = '';
  const rot = b('↻', 'Turntable', () => { V.setAutoRotate(!V.autoRotate); rot.classList.toggle('on', V.autoRotate); });
  rot.classList.toggle('on', V.autoRotate);
  const shot = b('◉', 'Save a picture (PNG)', () => { const a = el(`<a download="${esc(fname)}.png"></a>`); a.href = V.screenshot(); a.click(); });
  const full = b('⤢', 'Full screen', () => document.fullscreenElement ? document.exitFullscreen() : stage.requestFullscreen());
  tr.append(rot, shot, full);
  try {
    const r = await V.load(url, { keepView: sameModel });
    msg.innerHTML = '';
    range.max = r.duration || 0;
    $('.t1', stage).textContent = r.frames ? `${r.frames} frames · ${r.duration.toFixed(1)} s` : 'still';
    $('.scrubber', stage).hidden = !r.duration;
    range.oninput = () => { V.setPlaying(false); pause.textContent = '▶'; V.seek(+range.value); };
    cancelAnimationFrame(M.raf);
    const loop = () => {
      if (!range.isConnected) return;
      if (V.playing && r.duration) { range.value = V.time % r.duration; $('.t0', stage).textContent = (V.time % r.duration).toFixed(2) + ' s'; }
      M.raf = requestAnimationFrame(loop);
    };
    loop();
  } catch (e) { msg.textContent = e.message || String(e); }
}

// ---- saves --------------------------------------------------------------------------------------------------
const CMP = { picking: false, ids: [] };
async function pageSaves(p) {
  if (p.compare) return saveCompare(list(p.compare));
  if (p.id) return saveDetail(p.id);
  let slots = await api('saves');
  if (p.sort === 'place') slots = slots.slice().sort((a, b) => a.place.localeCompare(b.place) || b.modified - a.modified);
  if (p.sort === 'time') slots = slots.slice().sort((a, b) => (b.playtime || 0) - (a.playtime || 0));
  const h = head('Saves.', slots.length ? 'Your save games, opened up: where you are, what you carry, what you have done.' : 'No save games yet.');
  const g = el('<div class="cards" style="--card:240px"></div>');
  for (const s of slots) {
    const c = el(`<a class="card text${CMP.ids.includes(s.id) ? ' picked' : ''}" href="#/saves?id=${encodeURIComponent(s.id)}"><b>${esc(s.place)}</b>
      <span>${esc(s.id.replace('SaveGame', 'Slot '))} · played ${hms(s.playtime)}</span><span>${esc(when(s.modified))}</span></a>`);
    c.onclick = e => {
      if (!CMP.picking) return;
      e.preventDefault();
      CMP.ids = CMP.ids.includes(s.id) ? CMP.ids.filter(x => x !== s.id) : [...CMP.ids, s.id].slice(-2);
      if (CMP.ids.length === 2) { CMP.picking = false; const ids = CMP.ids; CMP.ids = []; go('saves', { compare: ids.join(',') }); } else render();
    };
    g.append(c);
  }
  const cmp = act(CMP.picking ? 'Pick two slots… (cancel)' : 'Compare two', () => { CMP.picking = !CMP.picking; CMP.ids = []; render(); }, CMP.picking ? 'on' : '');
  const sortP = pick([['', 'Newest first'], ['place', 'Place'], ['time', 'Longest played']], p.sort, v => setParam('sort', v), 'Sort');
  show(h, slots.length ? section('', null, rbar(`<b>${slots.length}</b> save slots`, sortP, slots.length > 1 ? cmp : null), g) : null);
}

function statNums(s, base) {
  const d = (a, b) => base == null || a == null || b == null || a === b ? '' : `<span class="delta ${a > b ? 'up' : 'down'}">${a > b ? '+' : ''}${a - b}</span>`;
  const nb = (v, max, label, bv) => `<div><b>${v ?? '–'}${max != null ? `<small> / ${max}</small>` : ''}${d(v, bv)}</b><span>${label}</span></div>`;
  return el(`<div class="nums save-nums">${nb(s.health, s.health_max, 'health', base?.health)}${nb(s.mana, s.mana_max, 'mana', base?.mana)}${nb(s.gold, s.gold_max, 'gold', base?.gold)}${nb(s.eras.length, 4, 'eras open', base?.eras.length)}</div>`);
}

async function saveDetail(id) {
  show(el('<section class="head wrap"><div class="spinner"></div></section>'));
  const s = await api('save/' + encodeURIComponent(id));
  const top = el(`<section class="head wrap"><a class="back" href="#/saves">Saves</a><h1>${esc(s.place)}.</h1>
    <p class="sub">${esc(s.id.replace('SaveGame', 'Slot '))} · checkpoint “${esc(s.checkpoint)}” · played ${hms(s.playtime)} · saved ${esc(when(s.modified))}${s.debug ? ' · debug mode on' : ''}</p></section>`);
  const li = (a, b, sel) => `<li${sel ? ' class="sel"' : ''}>${esc(a)}<span>${esc(b ?? '')}</span></li>`;
  const inv = el(`<div class="panel"><h3>Inventory</h3><ul>${s.inventory.map(i => li(i.name, i.count != null ? '× ' + i.count : (i.selected ? 'in hand' : ''), i.selected)).join('') || '<li>Empty</li>'}</ul></div>`);
  const arm = el(`<div class="panel"><h3>Armour</h3><ul>${s.armour.map(a => `<li>Armour ${a.n}<span class="pieces">${Array.from({ length: a.pieces }, (_, j) => `<i class="${a.pieces_damaged.includes(j + 1) ? 'bad' : ''}"></i>`).join('')}</span></li>`).join('')}</ul>
    <p class="muted" style="font-size:.85rem;margin:12px 0 0">Green pieces are whole, red ones damaged.</p></div>`);
  const jour = el(`<div class="panel"><h3>Journey</h3><ul>${li('Eras open', s.eras.map(e => ['I', 'II', 'III', 'IV'][e - 1]).join(' · ') || 'none')}${li('Map destination', s.map_destinations.join(', ') || 'none')}${li('Saved values', num(s.records))}</ul></div>`);
  const byEl = {};
  for (const sp of s.spells) (byEl[sp.element] ||= []).push(sp);
  const cols2 = el('<div class="cols"></div>');
  ['Ice', 'Fire', 'Lightning'].forEach(e => cols2.append(el(`<div class="panel el-${e.toLowerCase()}"><h3>${e}</h3><ul>${(byEl[e] || []).map(x => li(x.name.split(':').pop().trim(), x.selected ? 'selected' : '', x.selected)).join('') || '<li>None yet</li>'}</ul></div>`)));
  const cols1 = el('<div class="cols"></div>'); cols1.append(inv, arm, jour);
  const flags = el(`<div class="flags">${s.flags.map(f => `<span class="chip" title="${esc(f.note)}">#${f.index}<b>${f.value}</b>${f.note ? `&nbsp;· ${esc(f.note)}` : ''}</span>`).join('') || '<span class="muted">None</span>'}</div>`);
  const tools = rbar('', act('Compare with…', () => { CMP.picking = true; CMP.ids = [id]; go('saves'); }),
    act('Download JSON', () => { const a = el(`<a download="${esc(id)}.json"></a>`); a.href = URL.createObjectURL(new Blob([JSON.stringify(s, null, 1)], { type: 'application/json' })); a.click(); }));
  show(top, section('', null, statNums(s)), section('Belongings', null, cols1), section('Spells', s.spells.length, cols2),
    section('Story flags', s.flags.length, flags), section('', null, tools));
}

async function saveCompare(ids) {
  show(el('<section class="head wrap"><div class="spinner"></div></section>'));
  const [a, b] = await Promise.all(ids.map(id => api('save/' + encodeURIComponent(id))));
  const name = s => `${s.id.replace('SaveGame', 'Slot ')}`;
  const top = el(`<section class="head wrap"><a class="back" href="#/saves">Saves</a><h1>Compare.</h1>
    <div class="vs"><div><h3>${esc(a.place)}</h3><p class="muted">${esc(name(a))} · ${esc(when(a.modified))}</p></div><div class="muted">→</div>
    <div><h3>${esc(b.place)}</h3><p class="muted">${esc(name(b))} · ${esc(when(b.modified))}</p></div></div></section>`);
  const inv = m => Object.fromEntries(m.inventory.map(i => [i.name, i.count ?? 1]));
  const ia = inv(a), ib = inv(b);
  const items = [...new Set([...Object.keys(ia), ...Object.keys(ib)])].sort();
  const row2 = (n, x, y) => x === y ? '' : `<li>${esc(n)}<span>${x == null ? '<b class="new">new</b>' : y == null ? '<b class="gone">gone</b>' : `<span class="a">${x}</span><span class="b">${y}</span>`}</span></li>`;
  const invRows = items.map(n => row2(n, ia[n], ib[n])).join('');
  const sa = new Set(a.spells.map(s => s.name)), sb = new Set(b.spells.map(s => s.name));
  const spellRows = [...new Set([...sa, ...sb])].filter(n => sa.has(n) !== sb.has(n)).map(n => `<li>${esc(n.split(':').pop().trim())}<span>${sb.has(n) ? '<b class="new">learned</b>' : '<b class="gone">lost</b>'}</span></li>`).join('');
  const fa = Object.fromEntries(a.flags.map(f => [f.index, f.value])), fb = Object.fromEntries(b.flags.map(f => [f.index, f.value]));
  const notes = Object.fromEntries([...a.flags, ...b.flags].map(f => [f.index, f.note]));
  const flagRows = [...new Set([...Object.keys(fa), ...Object.keys(fb)])].map(Number).sort((x, y) => x - y)
    .filter(i => fa[i] !== fb[i]).map(i => `<li>#${i}${notes[i] ? ` <span class="muted">${esc(notes[i])}</span>` : ''}<span><span class="a">${fa[i] ?? 0}</span><span class="b">${fb[i] ?? 0}</span></span></li>`).join('');
  const cols = el('<div class="cols diff"></div>');
  cols.append(el(`<div class="panel"><h3>Inventory</h3><ul>${invRows || '<li>No change</li>'}</ul></div>`),
    el(`<div class="panel"><h3>Spells</h3><ul>${spellRows || '<li>No change</li>'}</ul></div>`),
    el(`<div class="panel"><h3>Story flags</h3><ul>${flagRows || '<li>No change</li>'}</ul></div>`));
  show(top, section('', null, statNums(b, a)), section('What changed', null, cols));
}

// ---- sheet (sound details) + lightbox (textures) -----------------------------------------------------------
const sheet = $('#sheet'), sbody = $('#sheet-body');
const closeSheet = () => { sheet.hidden = true; };
$('#sheet-close').onclick = closeSheet;
sheet.onclick = e => { if (e.target === sheet) closeSheet(); };
const defs = pairs => '<dl>' + pairs.filter(([, v]) => v !== '' && v != null).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('') + '</dl>';

async function openSound(id) {
  const s = await api('get/' + encodeURIComponent(id));
  sbody.innerHTML = `<h3>${esc(s.title)}</h3><p class="lead">${esc(KIND[s.kind] || s.kind)} · ${esc(usedIn(s.levels))}</p>
    <div class="actions"><button class="btn" id="s-play">▶ Play</button>
    <a class="btn ghost" href="/api/wav/${encodeURIComponent(s.id)}" download="${esc(s.id.replace(':', '_'))}.wav">Download WAV</a></div>
    ${defs([['Length', fmt(s.seconds)], ['Format', `${s.format} · ${s.rate} Hz · ${s.channels === 2 ? 'stereo' : 'mono'}`],
      ['Places', (s.levels || []).map(l => place(l)).filter((v, i, a) => a.indexOf(v) === i).join(', ')], ['Group', s.group_name],
      ['Speaker', s.speaker], ['Loops', s.loop ? (s.loop_start ? `from ${fmt(s.loop_start)}` : 'yes') : ''], ['ID', s.id], ['File', s.file_name]])}
    ${s.lines?.length ? '<h4>Dialogue</h4><div class="links-list" id="s-lines"></div>' : ''}
    ${s.parts?.length ? `<h4>Parts · ${s.parts.length}</h4><div class="links-list" id="s-parts"></div>` : ''}`;
  $('.actions', sbody).append(starBtn('sound', s.id));
  $('.actions .star', sbody).style.opacity = 1;
  $('#s-play').onclick = () => play(s);
  s.lines?.forEach(l => { const a = el(`<a href="#">${esc(l.text)}<small>${esc(l.speaker)} · ${esc(place(l.level))}</small></a>`); a.onclick = e => { e.preventDefault(); closeSheet(); go('dialogue', { level: l.level, line: l.id }); }; $('#s-lines').append(a); });
  s.parts?.forEach((pid, i) => { const a = el(`<a href="#">Part ${i + 1}<small>${esc(pid)}</small></a>`); a.onclick = e => { e.preventDefault(); openSound(pid); }; $('#s-parts').append(a); });
  sheet.hidden = false;
}

const lb = $('#lightbox');
const LB = { items: [], i: 0, zoom: 'fit', bg: 'check' };
function lightbox(items, i) { LB.items = items; LB.i = i; drawLightbox(); lb.hidden = false; }
function drawLightbox() {
  const t = LB.items[LB.i];
  if (!t) return;
  const src = `/api/png/${encodeURIComponent(t.id)}`;
  const z = LB.zoom === 'fit' ? '' : ` style="width:${t.width * +LB.zoom}px;height:${t.height * +LB.zoom}px"`;
  lb.className = `lightbox bg-${LB.bg}`;
  lb.innerHTML = `<button class="lbclose" aria-label="Close">×</button>
    ${LB.items.length > 1 ? '<button class="lbnav l" aria-label="Previous">‹</button><button class="lbnav r" aria-label="Next">›</button>' : ''}
    <div class="stagewrap"><img alt="" src="${src}" class="${LB.zoom === 'fit' ? 'fit' : ''}"${z}></div>
    <div class="cap">${esc(t.path)}<span>${t.width} × ${t.height} · ${esc(FMT_L[t.format] || t.format)} · ${LB.i + 1} of ${LB.items.length}</span>
    <a href="${src}" download="${esc(t.path.replace(/\//g, '_').replace(/\.gf$/i, ''))}.png">Download PNG</a></div><div class="lbtools"></div>`;
  const tools = $('.lbtools', lb);
  tools.append(seg([['fit', 'Fit'], ['1', '1×'], ['2', '2×'], ['4', '4×']], LB.zoom, v => { LB.zoom = v; drawLightbox(); }),
    seg([['check', 'Checker'], ['black', 'Black'], ['white', 'White']], LB.bg, v => { LB.bg = v; drawLightbox(); }));
  tools.append(starBtn('texture', t.id));
  $('.star', tools).style.opacity = 1;
  $('.lbclose', lb).onclick = () => { lb.hidden = true; };
  $('.stagewrap', lb).onclick = e => { if (e.target.tagName !== 'IMG') lb.hidden = true; };
  if ($('.lbnav.l', lb)) { $('.lbnav.l', lb).onclick = () => lbStep(-1); $('.lbnav.r', lb).onclick = () => lbStep(1); }
}
const lbStep = d => { LB.i = (LB.i + d + LB.items.length) % LB.items.length; drawLightbox(); };

// ---- player + queue -------------------------------------------------------------------------------------------
const audio = $('#audio'), canvas = $('#wave'), pp = $('#pp'), loopBtn = $('#p-loop');
let cur = null, peaks = null, loopOn = false, token = 0;
const Q = { list: [], i: -1 };
const setPP = () => { pp.innerHTML = audio.paused ? ICON.play : ICON.pause; pp.classList.toggle('play-i', audio.paused); document.body.classList.toggle('paused', audio.paused); };

function markPlaying() {
  $$('.item.cur, .turn.cur').forEach(x => { if (!(route().params.line && x.dataset.line === route().params.line)) x.classList.remove('cur'); });
  $$('.play .eq').forEach(x => { x.parentElement.innerHTML = ICON.play; });
  if (!cur) return;
  $$(`.item[data-id="${CSS.escape(cur.id)}"], .turn[data-sounds*=" ${CSS.escape(cur.id)} "]`).forEach(x => {
    x.classList.add('cur');
    const b = $('.play', x);
    if (b) b.innerHTML = '<span class="eq"><i></i><i></i><i></i></span>';
  });
}

function queue(recs, start = 0) {
  Q.list = recs; Q.i = start;
  if (recs.length) play(recs[start], null, true);
  toast(recs.length > 1 ? `Playing ${recs.length} in a row` : 'Playing');
}
async function playAll(table, f) {
  const r = await api('q/' + table, { ...f, limit: 500 });
  queue(r.items);
}
function step(d) {
  if (Q.list.length < 2) return;
  const i = Q.i + d;
  if (i < 0 || i >= Q.list.length) return;
  Q.i = i;
  play(Q.list[i], null, true);
}

async function play(s, rowEl, fromQueue = false) {
  if (!fromQueue) { Q.list = []; Q.i = -1; }
  const my = ++token;
  cur = s;
  markPlaying();
  rowEl?.classList.add('cur');
  $('#player').hidden = false; document.body.classList.add('playing');
  $('#p-title').textContent = s.title;
  $('#p-sub').textContent = [KIND[s.kind] || s.kind, usedIn(s.levels)].filter(Boolean).join(' · ');
  $('#p-dl').href = `/api/wav/${encodeURIComponent(s.id)}`; $('#p-dl').download = s.id.replace(':', '_') + '.wav';
  $('#p-q').textContent = Q.list.length > 1 ? `${Q.i + 1} / ${Q.list.length}` : '';
  $('#p-prev').disabled = !(Q.list.length > 1 && Q.i > 0);
  $('#p-next').disabled = !(Q.list.length > 1 && Q.i < Q.list.length - 1);
  loopOn = !!s.loop && s.kind === 'music' && Q.list.length < 2; loopBtn.classList.toggle('on', loopOn);
  peaks = null; draw();
  const slow = setTimeout(() => toast(s.format === 'MPEG' || s.format === 'Track' ? 'Decoding, the first time only…' : 'Loading…', 0), 400);
  let buf;
  try {
    const r = await fetch(`/api/wav/${encodeURIComponent(s.id)}`);
    if (!r.ok) throw new Error((await r.json()).error);
    buf = await r.arrayBuffer();
  } catch (e) { clearTimeout(slow); toast(e.message, 5000); return; } finally { clearTimeout(slow); if ($('.toast')?.textContent.endsWith('…')) $('.toast').remove(); }
  if (my !== token) return;
  if (audio.src) URL.revokeObjectURL(audio.src);
  audio.src = URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  audio.play().catch(() => {});
  peaks = wavPeaks(buf); draw();
  if (s.line) { const x = $(`.turn[data-line="${CSS.escape(s.line)}"]`); if (x && Q.list.length > 1) x.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
}

function wavPeaks(buf, n = 400) {                     // 16-bit PCM WAV (what the API serves) -> n peaks 0..1
  const dv = new DataView(buf);
  let o = 12, chans = 1, data = null;
  while (o + 8 <= buf.byteLength) {
    const id = String.fromCharCode(...new Uint8Array(buf, o, 4)), size = dv.getUint32(o + 4, true);
    if (id === 'fmt ') chans = dv.getUint16(o + 10, true);
    if (id === 'data') { data = new Int16Array(buf, o + 8, Math.floor(Math.min(size, buf.byteLength - o - 8) / 2)); break; }
    o += 8 + size + (size & 1);
  }
  if (!data) return null;
  const frames = Math.floor(data.length / chans), stp = Math.max(1, Math.floor(frames / n)), out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    let m = 0;
    for (let f = i * stp, e = Math.min(frames, f + stp); f < e; f += 3) { const v = Math.abs(data[f * chans]); if (v > m) m = v; }
    out[i] = m;
  }
  let mx = 1; for (const v of out) if (v > mx) mx = v;
  return out.map(v => Math.sqrt(v / mx));
}

function draw() {
  const dpr = devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w) return;
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const g = canvas.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
  const cs = getComputedStyle(document.documentElement);
  const on = cs.getPropertyValue('--blue').trim(), off = cs.getPropertyValue('--line-strong').trim();
  const pos = audio.duration ? audio.currentTime / audio.duration : 0;
  if (!peaks) { g.fillStyle = off; g.fillRect(0, h / 2 - 1, w, 2); g.fillStyle = on; g.fillRect(0, h / 2 - 1, w * pos, 2); return; }
  const n = Math.min(peaks.length, Math.floor(w / 3)), bw = w / n;
  for (let i = 0; i < n; i++) {
    const v = Math.max(1.5, peaks[Math.floor(i * peaks.length / n)] * (h - 4) / 2);
    g.fillStyle = i / n < pos ? on : off;
    g.beginPath(); g.roundRect(i * bw, h / 2 - v, Math.max(1.5, bw - 1.2), v * 2, 1); g.fill();
  }
}

function tick() { draw(); $('#p-cur').textContent = fmt(audio.currentTime) || '0:00'; $('#p-dur').textContent = fmt(audio.duration) || '0:00'; if (!audio.paused) requestAnimationFrame(tick); }
audio.onplay = () => { setPP(); tick(); };
audio.onpause = () => { setPP(); tick(); };
audio.onloadedmetadata = () => {
  tick();
  if (cur && cur.seconds == null) { cur.seconds = audio.duration; $$(`.item[data-id="${CSS.escape(cur.id)}"] .d`).forEach(d => { d.textContent = fmt(audio.duration); }); }
};
audio.onended = () => {
  if (loopOn) { audio.currentTime = cur?.loop_start || 0; audio.play(); return; }
  if (Q.list.length > 1 && Q.i < Q.list.length - 1) step(1);
};
pp.onclick = () => audio.src && (audio.paused ? audio.play() : audio.pause());
$('#p-prev').onclick = () => step(-1);
$('#p-next').onclick = () => step(1);
loopBtn.onclick = () => { loopOn = !loopOn; loopBtn.classList.toggle('on', loopOn); };
$('#p-close').onclick = () => { audio.pause(); cur = null; Q.list = []; $('#player').hidden = true; document.body.classList.remove('playing'); markPlaying(); };
canvas.onclick = e => { if (audio.duration) { audio.currentTime = e.offsetX / canvas.clientWidth * audio.duration; tick(); } };
addEventListener('resize', draw);
setPP();

// ---- quick search (Ctrl+K) -------------------------------------------------------------------------------------
const pal = $('#palette');
function openPalette(start = '') {
  pal.innerHTML = `<div class="box"><input placeholder="Search everything, or type a page name" spellcheck="false"><div class="res"></div>
    <div class="help"><span><kbd>↑</kbd> <kbd>↓</kbd> choose</span><span><kbd>Enter</kbd> open or play</span><span><kbd>Esc</kbd> close</span></div></div>`;
  pal.hidden = false;
  const inp = $('input', pal), res = $('.res', pal);
  let hits = [], k = 0, t;
  const paint = () => {
    res.innerHTML = '';
    let grp = null;
    hits.forEach((h, i) => {
      if (h.g !== grp) { grp = h.g; res.append(el(`<div class="grp">${esc(grp)}</div>`)); }
      const x = el(`<div class="hit${i === k ? ' on' : ''}"><span class="k">${h.icon}</span><span class="t">${esc(h.t)}</span><span class="s">${esc(h.s || '')}</span></div>`);
      x.onmouseenter = () => { k = i; $$('.hit', res).forEach((y, j) => y.classList.toggle('on', j === k)); };
      x.onclick = () => run(h);
      res.append(x);
    });
    if (!hits.length && inp.value) res.append(el('<div class="grp">Nothing found</div>'));
    $('.hit.on', res)?.scrollIntoView({ block: 'nearest' });
  };
  const run = h => { pal.hidden = true; h.go(); };
  const search = async () => {
    const q = inp.value.trim();
    const pages = [['', 'Home'], ...PAGES, ['search', 'Search']].filter(([, n]) => !q || n.toLowerCase().startsWith(q.toLowerCase()))
      .map(([p, n]) => ({ g: 'Pages', icon: '→', t: n, go: () => go(p) }));
    if (!q) { hits = pages; k = 0; return paint(); }
    const [s, l, x, m] = await Promise.all([api('q/sounds', { q, limit: 5 }), api('q/lines', { q, limit: 5, common: 1 }), api('q/textures', { q, limit: 4 }),
      api('q/persos', { q, limit: 4 }).catch(() => ({ items: null }))]);
    if (q !== inp.value.trim()) return;
    hits = [...pages,
      ...s.items.map(i => ({ g: 'Sounds', icon: '♪', t: i.title, s: fmt(i.seconds), go: () => play(i) })),
      ...l.items.map(i => ({ g: 'Dialogue', icon: '“', t: i.text, s: nice(i.speaker || ''), go: () => go('dialogue', { level: i.level, line: i.id }) })),
      ...x.items.map((i, j) => ({ g: 'Textures', icon: '▦', t: i.path.split('/').pop(), s: `${i.width}×${i.height}`, go: () => lightbox(x.items, j) })),
      ...(m.items || []).map(i => ({ g: 'Models', icon: '◆', t: i.name, s: CAT_L[i.category], go: () => go('models', { id: i.places[0].id }) })),
      { g: 'More', icon: '⌕', t: `All results for “${q}”`, go: () => go('search', { q }) }];
    k = Math.min(k, hits.length - 1);
    paint();
  };
  inp.oninput = () => { clearTimeout(t); k = 0; t = setTimeout(search, 140); };
  inp.onkeydown = e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); k = Math.min(k + 1, hits.length - 1); paint(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); k = Math.max(k - 1, 0); paint(); }
    if (e.key === 'Enter' && hits[k]) run(hits[k]);
    if (e.key === 'Escape') pal.hidden = true;
  };
  pal.onclick = e => { if (e.target === pal) pal.hidden = true; };
  inp.value = start;
  search();
  inp.focus();
}

// ---- keyboard ------------------------------------------------------------------------------------------------
function moveFocus(d) {
  const xs = $$('.item, .turn, .card', view).filter(x => x.offsetParent);
  if (!xs.length) return;
  const i = xs.findIndex(x => x.classList.contains('kb'));
  xs.forEach(x => x.classList.remove('kb'));
  const n = xs[Math.max(0, Math.min(xs.length - 1, i < 0 ? 0 : i + d))];
  n.classList.add('kb');
  n.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); return pal.hidden ? openPalette() : (pal.hidden = true); }
  if (e.key === 'Escape') { closeSheet(); lb.hidden = true; pal.hidden = true; if (SEL.on) selectMode(false); if (e.target.matches('input, select')) e.target.blur(); return; }
  if (e.target.matches('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
  if (!lb.hidden) { if (e.key === 'ArrowLeft') lbStep(-1); if (e.key === 'ArrowRight') lbStep(1); return; }
  const kb = $('.kb', view);
  const k = e.key.toLowerCase();
  if (e.code === 'Space') {
    e.preventDefault();
    if (route().page === 'models' && M.viewer && !audio.src) { $('.stagebox .bar .round')?.click(); return; }
    if (audio.src) pp.click();
    return;
  }
  if (k === '/') { e.preventDefault(); const f = $('.field input', view); if (f) f.focus(); else go('search'); return; }
  if (k === 'j' || e.key === 'ArrowDown' && kb) { e.preventDefault(); return moveFocus(1); }
  if (k === 'k' || e.key === 'ArrowUp' && kb) { e.preventDefault(); return moveFocus(-1); }
  if (e.key === 'Enter' && kb) { const b = $('.play', kb); if (b && !b.disabled && !SEL.on) b.click(); else kb.click(); return; }
  if (k === 's' && kb) { $('.star', kb)?.click(); return; }
  if (k === 'x') { if (kb && SEL.on) toggleSel(kb); else $('.act[data-select]', view)?.click(); return; }
  if (k === 'f') { const b = $('.fbtn', view); if (b) b.click(); return; }
  if (k === 'n') step(1);
  if (k === 'p') step(-1);
  if (route().page === 'models' && M.step) { if (e.key === ']') M.step(1); if (e.key === '[') M.step(-1); }
});

// ---- start ----------------------------------------------------------------------------------------------
$('#links').innerHTML = PAGES.map(([p, n]) => `<a href="#/${p}" data-page="${p}">${n}</a>`).join('')
  + `<a href="#" id="kbtn" class="kbtn" title="Quick search (Ctrl K)" aria-label="Quick search">${ICON.search}</a>`;
$('#kbtn').onclick = e => { e.preventDefault(); openPalette(); };
$('#theme').onclick = () => {
  const light = document.documentElement.dataset.theme !== 'light';
  if (light) document.documentElement.dataset.theme = 'light'; else delete document.documentElement.dataset.theme;
  localStorage.setItem('hypekit-theme', light ? 'light' : 'modern');
  draw();
};
addEventListener('hashchange', render);
$('#gamebtn').onclick = () => gameSheet();
api('info').then(async i => {
  if (i.needs_game) return setupScreen();          // nothing found on its own: ask for the folder
  const lv = await api('levels');
  info = i; levels = lv;
  for (const l of lv) levelName[l.level] = l.place;
  render();
  const k = new URLSearchParams(location.search).get('k');     // ?k=<text>: open quick search with it
  if (k != null) openPalette(k);
  if (new URLSearchParams(location.search).has('game')) gameSheet();   // ?game: open the game folder card
}).catch(e => { view.replaceChildren(head('Not connected.', esc(e.message))); });
