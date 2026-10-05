const API = '/api';

const DIVISIONS = [
  'heavyweight','light heavyweight','middleweight','welterweight',
  'lightweight','featherweight','bantamweight','flyweight'
];
const DIV_LABELS = {
  'heavyweight':       'Heavyweight 265 lbs',
  'light heavyweight': 'Light Heavyweight 205 lbs',
  'middleweight':      'Middleweight 185 lbs',
  'welterweight':      'Welterweight 170 lbs',
  'lightweight':       'Lightweight 155 lbs',
  'featherweight':     'Featherweight 145 lbs',
  'bantamweight':      'Bantamweight 135 lbs',
  'flyweight':         'Flyweight 125 lbs',
};
const DIV_SHORT = {
  'heavyweight':'HW','light heavyweight':'LHW','middleweight':'MW',
  'welterweight':'WW','lightweight':'LW','featherweight':'FW',
  'bantamweight':'BW','flyweight':'FL'
};
const DIV_COLORS = {
  'heavyweight':'#E8281E','light heavyweight':'#FF4444','middleweight':'#AA44AA',
  'welterweight':'#4455FF','lightweight':'#FF8C00','featherweight':'#44AA44',
  'bantamweight':'#44AACC','flyweight':'#22CCAA'
};
const PLOTLY_LAYOUT = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor:  'rgba(0,0,0,0)',
  font: { color: '#f5f5f5', family: 'Inter, system-ui, sans-serif' },
  margin: { l: 50, r: 20, t: 40, b: 50 },
};

(function loadFonts() {
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = 'https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700;800&display=swap';
  document.head.appendChild(l);
})();

async function apiFetch(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

// Win/loss streak as an arrow icon + number + letter. Shape (up/down) and the W/L letter carry
// the meaning, so colour is never the only signal. opts.tip adds a keyboard-focusable CSS tooltip
// (use it where no ancestor clips overflow); otherwise a native title is used.
const TREND_UP   = '<svg class="trend-ico" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" focusable="false"><path d="M6 1.5 11 10.5H1z" fill="currentColor"/></svg>';
const TREND_DOWN = '<svg class="trend-ico" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true" focusable="false"><path d="M6 10.5 1 1.5h10z" fill="currentColor"/></svg>';

function streakBadge(streak, opts) {
  const n = Math.abs(streak || 0);
  if (n < 3) return '';
  const up = streak > 0;
  const text = up ? `Racha: ${n} victorias seguidas` : `Racha: ${n} derrotas seguidas`;
  const tipAttrs = opts && opts.tip ? `data-tip="${text}" tabindex="0"` : `title="${text}"`;
  return `<span class="trend ${up ? 'trend-up' : 'trend-down'}" role="img" aria-label="${text}" ${tipAttrs}>`
       + `${up ? TREND_UP : TREND_DOWN}<span class="trend-num" aria-hidden="true">${n}${up ? 'W' : 'L'}</span></span>`;
}

function champBadge() {
  return '<span class="badge-champ">C</span>';
}

function escapeHtml(s) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => map[c]);
}

function stripAccents(s) {
  return String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '');
}

function slugify(name) {
  return stripAccents(name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

// Division badge: text label + colour dot (the label, not the colour, identifies the division).
function divBadge(div) {
  return `<span class="badge-div"><i style="background:${DIV_COLORS[div] || '#888'}"></i>${DIV_SHORT[div] || ''}</span>`;
}

function populateDivSelect(el) {
  DIVISIONS.forEach(d => {
    const o = document.createElement('option');
    o.value = d; o.textContent = DIV_LABELS[d];
    el.appendChild(o);
  });
}

function populateFighterSelect(el, rankings) {
  el.innerHTML = '';
  rankings.forEach(f => {
    const o = document.createElement('option');
    o.value = f.fighter_id;
    o.textContent = (f.is_champion ? '[C] ' : '') + f.fighter_name + ' (' + f.elo.toFixed(0) + ')';
    el.appendChild(o);
  });
}

function divSlug(d) { return d.replace(/ /g, '%20'); }

// ── Fighter index (search + deep links) ───────────────────────────────────
// Built only from endpoints the API already serves. "active" = current rankings,
// "all" = all-time rankings (adds retired fighters).
const FighterIndex = (() => {
  const cache = {};
  const norm = s => stripAccents(s).toLowerCase();

  async function build(alltime) {
    const settled = await Promise.allSettled(DIVISIONS.map(d =>
      apiFetch(`/rankings/${divSlug(d)}${alltime ? '/alltime' : ''}`).then(rows => rows.map(f => ({
        id: f.fighter_id, name: f.fighter_name, division: d, elo: f.elo, record: f.record,
        active: alltime ? f.active !== false : true,
        champion: !!f.is_champion, visitor: !!f.visitor, norm: norm(f.fighter_name),
      })))
    ));
    const byId = new Map();
    settled.forEach(r => {
      if (r.status !== 'fulfilled') return;
      r.value.forEach(e => {
        const prev = byId.get(e.id);
        if (!prev || (prev.visitor && !e.visitor)) byId.set(e.id, e);
      });
    });
    return [...byId.values()];
  }

  return {
    norm,
    get(alltime) {
      const key = alltime ? 'all' : 'active';
      if (!cache[key]) {
        cache[key] = build(alltime).then(list => {
          if (!list.length) delete cache[key];   // don't cache a total failure
          return list;
        });
      }
      return cache[key];
    },
  };
})();

// /peleador/<slug>?id=<fighter_id> — the id is exact; the slug keeps the URL readable.
function fighterUrl(f) {
  return `/peleador/${slugify(f.name)}?id=${encodeURIComponent(f.id)}`;
}

window.UFCelo = { FighterIndex, slugify, fighterUrl };

// ── Inject nav ────────────────────────────────────────────────────────────
(function () {
  const rawPath = window.location.pathname;
  const page = rawPath.startsWith('/peleador/')
    ? 'fighter.html'
    : (rawPath.split('/').pop() || 'index.html');
  const links = [
    ['index.html',      'Home',        '/'],
    ['rankings.html',   'Rankings',    '/rankings.html'],
    ['fighter.html',    'Fighter',     '/fighter.html'],
    ['comparison.html', 'Comparison',  '/comparison.html'],
    ['matchmaking.html','Matchmaking', '/matchmaking.html'],
    ['p4p.html',        'P4P',         '/p4p.html'],
  ];
  const bare = f => f.replace(/\.html$/, '');
  const isActive = f => bare(page) === bare(f);
  const html = `<nav class="navbar">
  <a href="/" class="nav-brand">UFC<span>elo</span>.gg</a>
  <div class="nav-search" id="nav-search" role="search">
    <button type="button" class="nav-search-toggle" id="nav-search-toggle" aria-label="Buscar peleador" aria-expanded="false">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    </button>
    <div class="nav-search-field">
      <svg class="nav-search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="nav-search-input" type="search" placeholder="Buscar peleador…  ( / )" autocomplete="off" spellcheck="false"
             role="combobox" aria-label="Buscar peleador" aria-autocomplete="list" aria-expanded="false" aria-controls="nav-search-list">
      <button type="button" class="nav-search-close" id="nav-search-close" aria-label="Cerrar búsqueda">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
      </button>
      <div class="nav-search-panel" id="nav-search-panel" hidden>
        <ul id="nav-search-list" role="listbox" aria-label="Resultados"></ul>
        <label class="nav-search-opt"><input type="checkbox" id="nav-search-retired"> Incluir retirados</label>
      </div>
    </div>
  </div>
  <button class="nav-hamburger" id="nav-hamburger" aria-label="Toggle menu">
    <svg width="22" height="22" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <line x1="3" y1="6" x2="19" y2="6"/>
      <line x1="3" y1="11" x2="19" y2="11"/>
      <line x1="3" y1="16" x2="19" y2="16"/>
    </svg>
  </button>
  <div class="nav-links" id="nav-links">
    ${links.map(([f,l,h]) => `<a href="${h}"${isActive(f)?' class="active"':''}>${l}</a>`).join('')}
    <span id="visit-counter" style="color:var(--muted);font-size:0.78rem;padding:4px 8px;opacity:0.7;" title="Total page visits"></span>
  </div>
</nav>`;
  document.body.insertAdjacentHTML('afterbegin', html);

  // Hamburger toggle
  const navBtn = document.getElementById('nav-hamburger');
  const navLinks = document.getElementById('nav-links');
  if (navBtn && navLinks) {
    navBtn.addEventListener('click', e => { e.stopPropagation(); navLinks.classList.toggle('open'); });
    navLinks.querySelectorAll('a').forEach(a => a.addEventListener('click', () => navLinks.classList.remove('open')));
    document.addEventListener('click', e => {
      if (!navBtn.contains(e.target) && !navLinks.contains(e.target)) navLinks.classList.remove('open');
    });
  }

  function _showVisits(n) {
    const navEl = document.getElementById('visit-counter');
    if (navEl) navEl.textContent = `👁 ${n.toLocaleString()}`;
    const homeEl = document.getElementById('home-visit-num');
    if (homeEl) homeEl.textContent = n.toLocaleString();
  }

  // Only landing on Home counts as a visit; every other page just reads the total.
  const isHome = page === 'index.html' || page === 'index';
  fetch(API + '/visits', { method: isHome ? 'POST' : 'GET' })
    .then(r => r.ok ? r.json() : null)
    .then(d => { if (d && d.total) _showVisits(d.total); })
    .catch(() => {});

  initSearch();
})();

// ── Global fighter search (Fuse.js fuzzy match over the fighter index) ────
function initSearch() {
  const box     = document.getElementById('nav-search');
  const input   = document.getElementById('nav-search-input');
  const panel   = document.getElementById('nav-search-panel');
  const list    = document.getElementById('nav-search-list');
  const retired = document.getElementById('nav-search-retired');
  const toggle  = document.getElementById('nav-search-toggle');
  const closeBt = document.getElementById('nav-search-close');
  if (!box || !input) return;

  let entries = [], fuse = null, mode = null, results = [], activeIdx = -1, ticket = 0;
  let fusePromise = null;

  function loadFuse() {
    if (window.Fuse) return Promise.resolve();
    if (!fusePromise) {
      fusePromise = new Promise(resolve => {
        const sc = document.createElement('script');
        sc.src = 'https://cdnjs.cloudflare.com/ajax/libs/fuse.js/7.0.0/fuse.min.js';
        sc.onload = sc.onerror = () => resolve();   // on failure we fall back to substring search
        document.head.appendChild(sc);
      });
    }
    return fusePromise;
  }

  async function prepare() {
    const want = retired.checked ? 'all' : 'active';
    if (fuse !== null && mode === want) return;
    const [idx] = await Promise.all([FighterIndex.get(want === 'all'), loadFuse()]);
    entries = idx;
    fuse = window.Fuse
      ? new Fuse(entries, { keys: ['norm'], threshold: 0.35, ignoreLocation: true, minMatchCharLength: 2 })
      : false;
    mode = want;
  }

  function search(q) {
    const nq = FighterIndex.norm(q.trim());
    if (nq.length < 2) return [];
    const hits = fuse ? fuse.search(nq, { limit: 30 }).map(r => r.item) : entries.filter(e => e.norm.includes(nq));
    // exact substring matches first, then the best fuzzy hits; ties keep Fuse order
    const sub = hits.filter(e => e.norm.includes(nq));
    const rest = hits.filter(e => !e.norm.includes(nq));
    return [...sub, ...rest].slice(0, 8);
  }

  function open(isOpen) {
    panel.hidden = !isOpen;
    input.setAttribute('aria-expanded', String(isOpen));
    if (!isOpen) { activeIdx = -1; input.removeAttribute('aria-activedescendant'); }
  }

  function setActive(i) {
    const items = list.querySelectorAll('[role=option]');
    if (!items.length) return;
    activeIdx = (i + items.length) % items.length;
    items.forEach((el, k) => {
      const on = k === activeIdx;
      el.classList.toggle('active', on);
      el.setAttribute('aria-selected', String(on));
      if (on) { input.setAttribute('aria-activedescendant', el.id); el.scrollIntoView({ block: 'nearest' }); }
    });
  }

  function render(q) {
    if (q.trim().length < 2) { open(false); return; }
    if (!results.length) {
      const hint = retired.checked ? '' : '. Prueba incluyendo retirados.';
      list.innerHTML = `<li class="sr-empty" role="presentation">Sin resultados para «${escapeHtml(q.trim())}»${hint}</li>`;
    } else {
      list.innerHTML = results.map((f, i) => `
        <li role="presentation"><a class="sr-item" role="option" id="sr-opt-${i}" aria-selected="false" href="${fighterUrl(f)}">
          <span class="sr-main">
            <span class="sr-name">${f.champion ? champBadge() : ''}${escapeHtml(f.name)}</span>
            <span class="sr-meta">${divBadge(f.division)}<span class="sr-rec">${escapeHtml(f.record || '—')}</span>${f.active ? '' : '<span class="sr-ret">Retirado</span>'}</span>
          </span>
          <span class="sr-elo" aria-label="ELO ${Math.round(f.elo)}">${Math.round(f.elo)}</span>
        </a></li>`).join('');
    }
    open(true);
    if (results.length) setActive(0);
  }

  async function run() {
    const q = input.value, my = ++ticket;
    if (q.trim().length < 2) { render(q); return; }
    try { await prepare(); } catch (e) { return; }
    if (my !== ticket) return;      // a newer keystroke superseded this one
    results = search(q);
    render(q);
  }

  // Mobile: the field collapses to an icon and expands over the navbar.
  function openMobile()  { box.classList.add('search-open');    toggle.setAttribute('aria-expanded', 'true'); }
  function closeMobile() { box.classList.remove('search-open'); toggle.setAttribute('aria-expanded', 'false'); }

  input.addEventListener('input', run);
  input.addEventListener('focus', () => { prepare().catch(() => {}); if (results.length && input.value.trim().length >= 2) open(true); });
  retired.addEventListener('change', () => { fuse = null; run(); input.focus(); });

  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (panel.hidden) run(); else setActive(activeIdx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIdx - 1); }
    else if (e.key === 'Enter') {
      const el = list.querySelector('[role=option].active');
      if (el) { e.preventDefault(); window.location.href = el.getAttribute('href'); }
    } else if (e.key === 'Escape') {
      if (!panel.hidden) open(false); else closeMobile();
    }
  });

  document.addEventListener('mousedown', e => { if (!box.contains(e.target)) { open(false); closeMobile(); } });

  // "/" focuses the search from anywhere (unless the user is already typing).
  document.addEventListener('keydown', e => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    e.preventDefault();
    openMobile();
    input.focus();
  });

  toggle.addEventListener('click', () => { openMobile(); input.focus(); });
  closeBt.addEventListener('click', () => {
    input.value = ''; results = []; open(false); closeMobile(); toggle.focus();
  });
}
