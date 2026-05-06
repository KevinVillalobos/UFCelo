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
  font: { color: '#F0F2F6', family: 'system-ui, sans-serif' },
  margin: { l: 50, r: 20, t: 40, b: 50 },
};

async function apiFetch(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`API ${r.status}: ${path}`);
  return r.json();
}

function streakBadge(streak) {
  if (streak >= 3)  return `<span class="streak-w">+${streak}W</span>`;
  if (streak <= -3) return `<span class="streak-l">${streak}L</span>`;
  return '';
}

function champBadge() {
  return '<span class="badge-champ">C</span>';
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

// ── Inject nav ────────────────────────────────────────────────────────────
(function () {
  const page = window.location.pathname.split('/').pop() || 'index.html';
  const links = [
    ['index.html',      'Home',        '/'],
    ['rankings.html',   'Rankings',    '/rankings.html'],
    ['fighter.html',    'Fighter',     '/fighter.html'],
    ['predict.html',    'Predict',     '/predict.html'],
    ['simulate.html',   'Simulate',    '/simulate.html'],
    ['matchmaking.html','Matchmaking', '/matchmaking.html'],
    ['p4p.html',        'P4P',         '/p4p.html'],
  ];
  const isActive = f => (page === '' || page === '/') ? f === 'index.html' : page === f;
  const html = `<nav class="navbar">
  <a href="/" class="nav-brand">UFC<span>elo</span>.gg</a>
  <div class="nav-links">
    ${links.map(([f,l,h]) => `<a href="${h}"${isActive(f)?' class="active"':''}>${l}</a>`).join('')}
    <span id="visit-counter" style="color:var(--muted);font-size:0.78rem;padding:4px 8px;opacity:0.7;" title="Total page visits"></span>
  </div>
</nav>`;
  document.body.insertAdjacentHTML('afterbegin', html);

  // Count this visit once per browser session, then display total everywhere
  const isFirstVisit = !sessionStorage.getItem('_v');
  fetch(API + '/visits', { method: isFirstVisit ? 'POST' : 'GET' })
    .then(r => r.json())
    .then(d => {
      sessionStorage.setItem('_v', '1');
      const n = (d.total || 0).toLocaleString();
      // Navbar counter (all pages)
      const navEl = document.getElementById('visit-counter');
      if (navEl) navEl.textContent = `👁 ${n}`;
      // Home page prominent counter
      const homeEl = document.getElementById('home-visit-num');
      if (homeEl) homeEl.textContent = n;
    })
    .catch(() => {
      const homeEl = document.getElementById('home-visit-num');
      if (homeEl) homeEl.textContent = '—';
    });
})();
