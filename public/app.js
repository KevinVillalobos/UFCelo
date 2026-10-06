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
  hoverlabel: {
    bgcolor: '#14172b',
    bordercolor: '#5a6088',
    font: { color: '#ffffff', size: 13, family: 'Inter, system-ui, sans-serif' },
    align: 'left',
    namelength: -1,
  },
};

// Readable hover for bar charts: "<b>category</b><br>series: value" instead of Plotly's raw "x, y".
// Applies only to bar traces that carry a formatted `text` array and no custom hovertemplate.
(function patchPlotlyHover() {
  if (!window.Plotly || Plotly.__hoverPatched) return;
  const orig = Plotly.newPlot.bind(Plotly);
  Plotly.newPlot = function (gd, data, layout, config) {
    (data || []).forEach(t => {
      if (t.type === 'scatterpolar' && !t.hovertemplate) {
        t.hovertemplate = `<b>%{theta}</b><br>${t.name ? t.name + ': ' : ''}<b>%{r:.1f}</b><extra></extra>`;
        return;
      }
      if (t.type !== 'bar' || !t.text || t.hovertemplate) return;
      const cat = t.orientation === 'h' ? '%{y}' : '%{x}';
      t.hovertemplate = `<b>${cat}</b><br>${t.name ? t.name + ': ' : ''}<b>%{text}</b><extra></extra>`;
    });
    return orig(gd, data, layout, config);
  };
  Plotly.__hoverPatched = true;
})();

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
  const text = up ? `Streak: ${n} wins in a row` : `Streak: ${n} losses in a row`;
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

// The engine stores skill dimensions under Spanish keys; the UI always shows English labels.
const SKILL_NAME_EN = {
  'Striking': 'Striking', 'Grappling': 'Grappling', 'Defensa': 'Defense', 'Consistencia': 'Consistency',
  'Finish Rate': 'Finish Rate', 'Cardio/Durabilidad': 'Cardio / Durability', 'Presión': 'Pressure',
};
function skillLabel(dim) { return SKILL_NAME_EN[dim] || dim; }

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

// Style Clash notes ("Striking dominance vs poor defense (+2%)": + favours A, - favours B). They explain the
// matchup but do NOT change the win probability, so the percentage is dropped and the favoured fighter named.
function styleNotes(reasons, nameA, nameB) {
  const last = n => String(n || '').trim().split(/\s+/).slice(-1)[0];
  return (reasons || []).map(r => {
    const m = String(r).match(/^(.*?)\s*\(([+-])[\d.]+%\)$/);
    if (!m) return escapeHtml(r);
    return `${escapeHtml(m[1])} <span class="style-ctx-who">— favors ${escapeHtml(last(m[2] === '+' ? nameA : nameB))}</span>`;
  });
}

function styleContextHTML(reasons, nameA, nameB) {
  const items = styleNotes(reasons, nameA, nameB);
  if (!items.length) return '';
  return `<div class="style-ctx">
    <div class="style-ctx-title">Style context <span>(does not affect the %)</span></div>
    <ul>${items.map(i => `<li>${i}</li>`).join('')}</ul>
  </div>`;
}

// /peleador/<slug>?id=<fighter_id> — the id is exact; the slug keeps the URL readable.
function fighterUrl(f) {
  return `/peleador/${slugify(f.name)}?id=${encodeURIComponent(f.id)}`;
}

window.UFCelo = { FighterIndex, slugify, fighterUrl };

// Markup of one search field. p = id prefix, so several instances (navbar, hero) can coexist.
function searchFieldHTML(p, opts) {
  const o = opts || {};
  const close = o.close ? `<button type="button" class="nav-search-close" id="${p}-close" aria-label="Close search">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>
      </button>` : '';
  return `<svg class="nav-search-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <input id="${p}-input" type="search" placeholder="${o.placeholder || 'Search fighters…'}" autocomplete="off" spellcheck="false"
             role="combobox" aria-label="Search fighters" aria-autocomplete="list" aria-expanded="false" aria-controls="${p}-list">
      ${close}
      <div class="nav-search-panel" id="${p}-panel" hidden>
        <ul id="${p}-list" role="listbox" aria-label="Results"></ul>
        <label class="nav-search-opt"><input type="checkbox" id="${p}-retired"> Include retired</label>
      </div>`;
}

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
    <button type="button" class="nav-search-toggle" id="nav-search-toggle" aria-label="Search fighters" aria-expanded="false">
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
    </button>
    <div class="nav-search-field">
      ${searchFieldHTML('nav-search', { close: true, placeholder: 'Search fighters…  ( / )' })}
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

  initSearch('nav-search');

  // Extra search boxes anywhere on a page: <div data-search-mount="hero-search"></div>
  document.querySelectorAll('[data-search-mount]').forEach(el => {
    const p = el.getAttribute('data-search-mount');
    el.id = p;
    el.setAttribute('role', 'search');
    el.classList.add('nav-search', 'nav-search--hero');
    el.innerHTML = `<div class="nav-search-field">${searchFieldHTML(p, { placeholder: el.getAttribute('data-placeholder') || 'Search fighters…' })}</div>`;
    initSearch(p);
  });
})();

// ── Global fighter search (Fuse.js fuzzy match over the fighter index) ────
function initSearch(p) {
  const box     = document.getElementById(p);
  const input   = document.getElementById(`${p}-input`);
  const panel   = document.getElementById(`${p}-panel`);
  const list    = document.getElementById(`${p}-list`);
  const retired = document.getElementById(`${p}-retired`);
  const toggle  = document.getElementById(`${p}-toggle`);   // navbar only (mobile icon)
  const closeBt = document.getElementById(`${p}-close`);    // navbar only
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
      const hint = retired.checked ? '' : '. Try including retired fighters.';
      list.innerHTML = `<li class="sr-empty" role="presentation">No results for "${escapeHtml(q.trim())}"${hint}</li>`;
    } else {
      list.innerHTML = results.map((f, i) => `
        <li role="presentation"><a class="sr-item" role="option" id="${p}-opt-${i}" aria-selected="false" href="${fighterUrl(f)}">
          <span class="sr-main">
            <span class="sr-name">${f.champion ? champBadge() : ''}${escapeHtml(f.name)}</span>
            <span class="sr-meta">${divBadge(f.division)}<span class="sr-rec">${escapeHtml(f.record || '—')}</span>${f.active ? '' : '<span class="sr-ret">Retired</span>'}</span>
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
  function openMobile()  { if (!toggle) return; box.classList.add('search-open');    toggle.setAttribute('aria-expanded', 'true'); }
  function closeMobile() { if (!toggle) return; box.classList.remove('search-open'); toggle.setAttribute('aria-expanded', 'false'); }

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

  // "/" focuses the navbar search from anywhere (unless the user is already typing).
  if (toggle) document.addEventListener('keydown', e => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    e.preventDefault();
    openMobile();
    input.focus();
  });

  if (toggle) toggle.addEventListener('click', () => { openMobile(); input.focus(); });
  if (closeBt) closeBt.addEventListener('click', () => {
    input.value = ''; results = []; open(false); closeMobile(); toggle.focus();
  });
}
