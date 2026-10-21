/* =====================================================================
   app.js — loads data/*.json and renders every section of index.html
   ---------------------------------------------------------------------
   Reading guide for a non-developer maintainer
   • Section 1  SETTINGS   — file names, defaults, fallback text.
   • Section 2  LOADING    — fetches the JSON files, shows notices.
   • Section 3  STATE      — the Annual | Quarterly switch.
   • Section 4  RENDERERS  — one function per component on the page,
                              in the same order as the page.
   • Section 5  START-UP   — wires buttons and runs everything.
   All helpers for charts/formatting live in charts.js (window.KT).
   The wording on the page comes from data/text.json; the strings in
   DEFAULT_TEXT below are used only when a key is missing there.
   ===================================================================== */
(function () {
  'use strict';
  const KT = window.KT;

  /* ============================ 1. SETTINGS ============================ */
  const DATA_DIR = 'data/';                 // relative: works under /<repo>/ on GitHub Pages
  const FILES = ['manifest', 'coverage', 'series', 'national_accounts', 'peers', 'products', 'text'];
  const PRELIM_THRESHOLD = 0.6;             // below this "percent complete" a period is preliminary
  const GITHUB_URL = 'https://github.com/alebadel/KiriTrade';                    // set to the repository URL once known, e.g. 'https://github.com/<owner>/<repo>'

  /* Fallback wording. Agent D's text.json overrides any key present there. */
  const DEFAULT_TEXT = {
    site_title: 'KiriTrade: Tuna Exports Now with AI',
    purpose: 'Summarize and share trading-partner data to track the performance of the Kiribati economy.',
    intro: [
      'Kiribati is a Pacific island nation. Like every country it records the goods it sells abroad (exports) and buys from abroad (imports). This page adds a second view of the same trade: what Kiribati\'s trading partners recorded on their side.',
      'Partner records arrive on a steady schedule and often cover months that Kiribati has not yet published. They complement the official figures; they do not replace them.',
      'Because partners publish at different speeds, every period comes with a "percent complete" score: the share of the partners we watch whose figures for that period are already published.'
    ],
    how_to_use: [
      'Choose Annual or Quarterly at the top. Every chart and table follows.',
      'Hover over or tap a bar to see the numbers and how complete that period is.',
      'Lighter bars are preliminary: fewer than 60% of partners have published for that period.'
    ],
    glossary: [
      { term: 'Partner-reported data', definition: 'What Kiribati\'s trading partners declared to UN Comtrade about their trade with Kiribati.' },
      { term: 'Kiribati-reported data', definition: 'Kiribati\'s own customs returns, published on UN Comtrade.' },
      { term: 'Percent complete', definition: 'The share of the partner panel whose data for a period have been published. A trade-weighted version counts big partners more.' },
      { term: 'Partner panel', definition: 'The fixed list of trading partners this tracker watches.' },
      { term: 'UN Comtrade', definition: 'The United Nations database where countries publish their trade statistics.' },
      { term: 'HS code', definition: 'The Harmonized System, an international numbering of goods. The first four digits (HS4) name a product group.' },
      { term: 'Balance of payments', definition: 'The official summary of all economic transactions between a country and the rest of the world.' }
    ],
    charts: {
      coverage: { title: 'How much of the picture is in yet?', subtitle: 'Share of the partner panel that has published, by period', how_to_read: 'Each bar is one period. A bar at 100% means every partner on the panel has published its figures for that period. The two lines weight partners by how much they trade with Kiribati.', caveat: 'A low bar does not mean trade was low; it means figures are still to come.' },
      exports: { title: 'Exports: what partners record buying from Kiribati', subtitle: 'Partner-reported exports by product group, with Kiribati\'s own total as a line', how_to_read: 'Stacked bars add up the partner records by product group. The line is Kiribati\'s own customs total, drawn only where it has been published.', caveat: 'Tuna is recorded by the buyer\'s customs by vessel flag. Under balance-of-payments rules most of it may correctly sit outside Kiribati\'s goods exports.' },
      imports: { title: 'Imports: what partners record selling to Kiribati', subtitle: 'Partner-reported imports, with ships and aircraft shown separately', how_to_read: 'Solid bars exclude ships and aircraft; hatched bars add them. The line is Kiribati\'s own import total.', caveat: 'Partner data cover only part of Kiribati\'s imports, so no trade balance is shown.' },
      rolling: { title: 'Fish exports over the last 12 months', subtitle: 'Partner-reported fish and seafood, rolling 12-month total', how_to_read: 'Each point adds up the previous 12 months, which smooths seasonal swings. The tooltip shows the change against the same 12 months a year earlier.', caveat: 'The latest points are provisional until all buyers have published.' },
      national_accounts: { title: 'Comparison with the official figures', subtitle: 'Balance of payments, Kiribati customs and partner records, by year', how_to_read: 'The first two bars are Kiribati\'s official figures. The last two are the partner records, shown with and without tuna (exports) or ships and aircraft (imports).', caveat: 'Customs totals for years with missing months are scaled to 12 months. Official balance-of-payments figures are annual, so this chart stays annual in both views.' },
      peers_tuna: { title: 'Tuna recorded by importers as originating in each country', subtitle: 'Seven Pacific tuna states, annual', how_to_read: 'Each line is the value of tuna that importers attributed to that country\'s flag. Kiribati is the dark line.', caveat: 'Origin follows the vessel flag, so a fleet moving onto a new flag moves the line. Micronesia\'s 2024 figure is a one-year spike.' },
      peers_applicability: { title: 'Could this tracker be built for other small island states?', subtitle: 'Three checks for 15 countries', how_to_read: 'Click a column heading to sort. Coverage is the share of a country\'s trade with partners that publish promptly. The ratio compares partner records with the country\'s own total.', caveat: 'Ratios are read annually and exclude ships and aircraft. Blank cells mean the country has not published that figure.' },
      products: { title: 'Top product groups', subtitle: 'Partner-reported next to Kiribati-reported, for one year', how_to_read: 'Each pair of bars is one product group (HS4). Longer is larger.', caveat: 'Product labels are shortened from the official descriptions.' },
      copra: { title: 'Copra oil runs the other way', subtitle: '', how_to_read: '', caveat: '' },
      ships: { title: 'Ships and aircraft', subtitle: 'Large one-off deliveries partners recorded as sold to Kiribati', how_to_read: 'Each row is one delivery or group of deliveries of USD 1 million or more.', caveat: 'Ships and aircraft are lumpy one-offs, which is why totals are always shown with and without them.' }
    },
    findings: [],
    sensitivity_statement: 'Kiribati\'s own customs figures are the official source. Partner data fill gaps in timing and coverage. Where the two differ, the difference reflects coverage and definitions, not errors.',
    literature_blurb: 'Why economists compare one country\'s trade records with its partners\', and what they have found. In plain words.',
    footer: { credit: 'Prepared by the IMF Kiribati desk.', disclaimer: 'The views expressed are those of the author and do not necessarily represent the views of the IMF, its Executive Board, or IMF management.' },
    notes: {
      exports: 'The tuna bar is catch landed abroad by Kiribati-flagged vessels. The buyer\'s customs records it by vessel flag. Under balance-of-payments rules most of it may correctly sit outside Kiribati\'s goods exports.',
      imports: 'Partner data cover only part of Kiribati\'s imports (roughly a third to a half of Kiribati\'s own total). For that reason no trade balance is shown anywhere on this page.',
      coverage_legend: 'A bar at 100% means every partner on the panel has published its figures for that period.',
      panel: 'The panel is every partner with at least 0.5% of partner-reported trade with Kiribati in the reference window, plus a fixed list of major partners. Weights are each partner\'s share of partner-reported exports or imports in that window.',
      notable: 'Products where one side records a value and the other records little or nothing.',
      ships: 'Deliveries of USD 1 million or more that partners recorded.'
    }
  };

  /* ============================ 2. LOADING ============================= */
  const D = {};          // loaded JSON by name: D.manifest, D.coverage, ...
  const failed = [];     // names of files that did not load

  function isFileProtocol() { return location.protocol === 'file:'; }

  async function loadAll() {
    const results = await Promise.allSettled(FILES.map(async name => {
      const r = await fetch(DATA_DIR + name + '.json', { cache: 'no-cache' });
      if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
      return [name, await r.json()];
    }));
    results.forEach((res, i) => {
      if (res.status === 'fulfilled') D[res.value[0]] = res.value[1];
      else { failed.push(FILES[i]); console.warn('Could not load', FILES[i], res.reason); }
    });
  }

  /* text lookup with fallback: T('charts.exports.title') */
  function T(path) {
    const parts = path.split('.');
    let a = D.text, b = DEFAULT_TEXT;
    for (const p of parts) { a = a && a[p] !== undefined ? a[p] : undefined; b = b && b[p] !== undefined ? b[p] : undefined; }
    return a !== undefined && a !== null && a !== '' ? a : b;
  }

  /* ============================== 3. STATE ============================= */
  const state = { view: 'quarterly', productsDir: 'exports', productsYear: null, peersSort: { key: null, dir: 1 } };

  function readInitialView() {
    const q = new URLSearchParams(location.search).get('view');
    if (q === 'annual' || q === 'quarterly') return q;
    try { const s = localStorage.getItem('kt-view'); if (s === 'annual' || s === 'quarterly') return s; } catch (e) { /* private mode etc. */ }
    return 'quarterly';
  }
  function setView(view) {
    state.view = view;
    document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
    try { localStorage.setItem('kt-view', view); } catch (e) { /* ignore */ }
    try { const u = new URL(location.href); u.searchParams.set('view', view); history.replaceState(null, '', u); } catch (e) { /* ignore */ }
    renderViewDependent();
  }
  const VIEW_LABEL = { annual: 'year', quarterly: 'quarter', monthly: 'month' };

  /* per-chart "Monthly" option (small chips inside coverage / exports / imports) */
  const monthlyOn = { coverage: false, exports: false, imports: false };
  function viewFor(chart) { return monthlyOn[chart] ? 'monthly' : state.view; }

  /* ============================ 4. RENDERERS =========================== */
  /* small DOM helpers (always textContent, never innerHTML with data) */
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v); });
    (children || []).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return e;
  }
  function setText(id, text) { const e = document.getElementById(id); if (e) e.textContent = text == null ? '' : String(text); }
  function clear(id) { const e = document.getElementById(id); if (e) e.textContent = ''; return e; }

  /* Fill the standard figure chrome: title, subtitle, how-to-read, caveat, source line */
  function figChrome(figId, textKey, srcInfo, overrides) {
    const fig = document.getElementById(figId);
    if (!fig) return;
    const alias = { rolling: 'rolling_fish' };             // text.json may name a chart differently
    const fromFile = D.text && D.text.charts ? (D.text.charts[textKey] || D.text.charts[alias[textKey]]) : null;
    const t = Object.assign({}, DEFAULT_TEXT.charts[textKey] || {}, fromFile || {}, overrides || {});
    fig.querySelector('h3').textContent = t.title || '';
    fig.querySelector('.sub').textContent = t.subtitle || '';
    const how = fig.querySelector('.how'); if (how) { how.textContent = t.how_to_read || ''; how.hidden = !t.how_to_read; }
    const cav = fig.querySelector('.caveat'); if (cav) { cav.textContent = t.caveat || ''; cav.hidden = !t.caveat; }
    const src = fig.querySelector('.src');
    if (src) {
      const rel = D.manifest && D.manifest.meta ? KT.fmtDate(D.manifest.meta.generated_at) : '—';
      let s = 'Source: UN Comtrade, data as of ' + rel + '.';
      if (srcInfo && KT.isNum(srcInfo.pct)) s += ' Percent complete' + (srcInfo.period ? ' for ' + srcInfo.period : '') + ': ' + KT.fmtPct(srcInfo.pct) + '.';
      if (srcInfo && srcInfo.extra) s += ' ' + srcInfo.extra;
      src.textContent = s;
    }
  }

  /* names for partner codes (from manifest.panel) */
  function partnerName(code) {
    const p = D.manifest && D.manifest.panel ? D.manifest.panel.find(x => x.code === code) : null;
    return p ? p.name : String(code);
  }
  function missingNames(row) {
    if (Array.isArray(row.missing_major)) return row.missing_major.map(m => m.name + (m.months_missing && m.months_missing.length < 3 && m.months_missing.length ? ' (' + m.months_missing.map(KT.fmtPeriod).join(', ') + ')' : ''));
    if (Array.isArray(row.missing)) return row.missing.map(partnerName);
    return [];
  }
  /* The share to display for a coverage row. A year still in progress has no
     annual dataset from anyone, so share_count is 0; the builder then also gives
     the share of partner-months published, which is the honest number to show. */
  function effShare(row) {
    if (KT.isNum(row.share_count_partner_months) && (!KT.isNum(row.share_count) || row.share_count === 0)) return row.share_count_partner_months;
    return row.share_count;
  }
  function isPrelim(row) { const p = row.pct_complete !== undefined ? row.pct_complete : row.share_count; return KT.isNum(p) && p < PRELIM_THRESHOLD; }
  function latestRow(rows) { return rows && rows.length ? rows[rows.length - 1] : null; }

  /* ---- 0. header: badge, strip ---- */
  function renderHeader() {
    const m = D.manifest;
    /* The page's own <title> and <h1> are kept; text.json site_title/purpose are no longer applied here (the home page is index.html). */
    document.querySelectorAll('[data-updated-badge]').forEach(badge => {
      badge.textContent = '';
      badge.appendChild(el('span', { class: 'dot', 'aria-hidden': 'true' }));
      if (m && m.meta) {
        const through = m.data_through ? m.data_through[state.view] : null;
        badge.appendChild(el('span', { text: 'Last updated: ' + KT.fmtDateTime(m.meta.generated_at) + ' · data through ' + KT.fmtPeriod(through) }));
        badge.title = m.last_update_mode === 'live_comtrade' ? 'Refreshed from UN Comtrade automatically' : 'Built from the offline pipeline outputs';
      } else {
        badge.appendChild(el('span', { text: 'Last updated: unknown' }));
      }
    });
    if (GITHUB_URL) { const g = document.getElementById('github-link'); if (g) g.href = GITHUB_URL; }
    renderStrip();
  }

  /* The strip in the hero: one dot per partner for the latest month */
  function renderStrip() {
    const cov = D.coverage && D.coverage.monthly ? latestRow(D.coverage.monthly) : null;
    const panel = D.manifest && D.manifest.panel ? D.manifest.panel : [];
    const dots = clear('strip-dots');
    if (!cov || !panel.length) { setText('strip-h', 'Latest month: no coverage data'); return; }
    setText('strip-h', 'Latest month on record: ' + KT.fmtPeriod(cov.period));
    const published = new Set(cov.published || []);
    const sorted = panel.slice().sort((a, b) => Math.max(b.w_exports, b.w_imports) - Math.max(a.w_exports, a.w_imports));
    sorted.forEach(p => {
      const i = el('i', { title: (p.label || p.name) + (published.has(p.code) ? ': published' : ': not yet published') });
      if (published.has(p.code)) i.classList.add('on');
      if (Math.max(p.w_exports, p.w_imports) >= 0.1) i.classList.add('big');
      dots.appendChild(i);
    });
    const meter = document.getElementById('strip-meter'); if (meter) meter.style.width = Math.round((cov.share_count || 0) * 100) + '%';
    const lg = clear('strip-legend');
    lg.appendChild(el('em', { text: cov.n_published + ' of ' + cov.n_panel + ' partners' }));
    lg.appendChild(document.createTextNode(' have published for this month (' + KT.fmtPct(cov.share_count) + ' by count; ' + KT.fmtPct(cov.share_w_exports) + ' of export value, ' + KT.fmtPct(cov.share_w_imports) + ' of import value). Bigger dots are bigger partners.'));
  }

  /* ---- 1. intro ---- */
  function renderIntro() {
    const ip = clear('intro-paragraphs');
    (T('intro') || []).forEach(p => ip.appendChild(el('p', { text: p })));
    const how = clear('how-to-use');
    (T('how_to_use') || []).forEach(p => how.appendChild(el('li', { text: p })));
    setText('lit-blurb', T('literature_blurb'));
    const sens = clear('sensitivity');
    sens.appendChild(el('p', { text: T('sensitivity_statement') }));
    const gl = clear('glossary-list');
    (T('glossary') || []).forEach(g => { gl.appendChild(el('dt', { text: g.term })); gl.appendChild(el('dd', { text: g.definition })); });
  }

  /* ---- 2. coverage chart + panel table ---- */
  function addMonthlyChip(figId, chartKey) {
    const fig = document.getElementById(figId); if (!fig) return;
    let tools = fig.querySelector('.fig-tools');
    if (!tools) { tools = el('div', { class: 'fig-tools' }); fig.querySelector('.fig-head').appendChild(tools); }
    if (tools.querySelector('[data-monthly]')) return;
    const b = el('button', { type: 'button', class: 'chip', 'data-monthly': chartKey, 'aria-pressed': 'false', text: 'Monthly' });
    b.addEventListener('click', () => { monthlyOn[chartKey] = !monthlyOn[chartKey]; b.setAttribute('aria-pressed', String(monthlyOn[chartKey])); renderViewDependent(); });
    tools.appendChild(b);
  }
  function viewLabelFor(chartKey) { return monthlyOn[chartKey] ? 'monthly' : state.view; }

  function renderCoverage() {
    const t = KT.tokens();
    addMonthlyChip('fig-coverage', 'coverage');
    const view = viewFor('coverage');
    const rows = coverageRows(view);
    const last = latestRow(rows);
    figChrome('fig-coverage', 'coverage', last ? { pct: effShare(last), period: KT.fmtPeriod(last.period) } : null,
      { subtitle: (T('charts.coverage.subtitle') || '') + ' — by ' + VIEW_LABEL[view] });
    KT.legend('legend-coverage', [
      { label: 'Share of partners published (count)', color: t.count, kind: 'box' },
      { label: 'Weighted by export value', color: t.partner, kind: 'line' },
      { label: 'Weighted by import value', color: t.kir, kind: 'dash' }
    ]);
    const fig = document.getElementById('fig-coverage');
    let note = fig.querySelector('.note'); if (!note) { note = el('p', { class: 'note' }); fig.querySelector('figcaption').before(note); }
    note.textContent = T('notes.coverage_legend');
    if (!rows.length) { KT.empty('chart-coverage', 'No coverage data for this view.'); clear('table-coverage'); return; }
    const labels = rows.map(r => r.period);
    KT.make('chart-coverage', {
      type: 'bar',
      data: { labels, datasets: [
        { type: 'line', label: 'Weighted by export value', data: rows.map(r => KT.isNum(r.share_w_exports) ? r.share_w_exports * 100 : null), borderColor: t.partner, backgroundColor: t.partner, pointRadius: rows.length > 60 ? 0 : 2.5, order: 0 },
        { type: 'line', label: 'Weighted by import value', data: rows.map(r => KT.isNum(r.share_w_imports) ? r.share_w_imports * 100 : null), borderColor: t.kir, backgroundColor: t.kir, borderDash: [3, 3], pointRadius: rows.length > 60 ? 0 : 2.5, order: 0 },
        { type: 'bar', label: 'Share of partners published', data: rows.map(r => KT.isNum(effShare(r)) ? effShare(r) * 100 : null), backgroundColor: KT.withAlpha(t.count, 0.55), hoverBackgroundColor: t.count, maxBarThickness: 24, order: 1 }
      ] },
      options: {
        scales: KT.axes({ unit: '%', max: 100, dense: rows.length > 24, monthlyDense: view === 'monthly' }),
        interaction: { mode: 'index', intersect: false },
        plugins: { tooltip: { callbacks: {
          title: items => KT.fmtPeriod(items[0].label),
          label: ctx => ' ' + ctx.dataset.label + ': ' + Math.round(ctx.parsed.y) + '%',
          afterBody: items => {
            const r = rows[items[0].dataIndex]; const out = [];
            if (KT.isNum(r.n_published) && !(r.n_published === 0 && KT.isNum(r.share_count_partner_months))) out.push(r.n_published + ' of ' + r.n_panel + ' partners published' + (r.basis === 'annual_dataset' ? ' (annual returns)' : ''));
            if (KT.isNum(r.partner_months_published)) out.push(r.partner_months_published + ' of ' + r.partner_months_possible + ' partner-months published' + (r.basis === '12_monthly_datasets' ? ' (year still filling in)' : ''));
            if (KT.isNum(r.kiribati_months_reported)) out.push('Kiribati published ' + r.kiribati_months_reported + ' month' + (r.kiribati_months_reported === 1 ? '' : 's'));
            else if (r.kiribati_reported !== undefined) out.push('Kiribati\'s own return: ' + (r.kiribati_reported ? 'published' : 'not yet published'));
            const miss = missingNames(r);
            if (miss.length) out.push('Still missing: ' + miss.slice(0, 8).join(', ') + (miss.length > 8 ? ', …' : ''));
            else out.push('No partner missing');
            return out;
          }
        } } }
      }
    });
    KT.table('table-coverage', [
      { key: 'period', label: 'Period', fmt: KT.fmtPeriod },
      { key: 'share_count', label: 'By count', num: true, fmt: (v, r) => KT.fmtPct(effShare(r)) },
      { key: 'share_w_exports', label: 'Export-weighted', num: true, fmt: KT.fmtPct },
      { key: 'share_w_imports', label: 'Import-weighted', num: true, fmt: KT.fmtPct },
      { key: '_missing', label: 'Still missing', fmt: (v, r) => { const m = missingNames(r); return m.length ? m.join(', ') : 'none'; } }
    ], rows.slice().reverse());
  }

  function renderPanel() {
    const panel = D.manifest && D.manifest.panel ? D.manifest.panel.slice() : [];
    setText('panel-lede', T('notes.panel') + (D.manifest && D.manifest.reference_window ? ' Reference window: ' + D.manifest.reference_window.start + '–' + D.manifest.reference_window.end + '.' : ''));
    const tbl = clear('panel-table'); if (!tbl) return;
    if (!panel.length) { tbl.appendChild(el('caption', { class: 'empty', text: 'Panel not available.' })); return; }
    panel.sort((a, b) => Math.max(b.w_exports, b.w_imports) - Math.max(a.w_exports, a.w_imports));
    const thead = el('thead', null, [el('tr', null, ['Partner', 'Weight in exports', 'Weight in imports', 'Latest month published', 'Typical lag'].map((h, i) => el('th', { text: h, class: i === 1 || i === 2 ? 'num' : '' })))]);
    tbl.appendChild(thead);
    const tb = el('tbody');
    const barCell = (w) => { const td = el('td', { class: 'num' }); const bar = el('span', { class: 'bar' }); bar.style.width = Math.max(2, Math.round((w || 0) * 120)) + 'px'; td.appendChild(bar); td.appendChild(document.createTextNode(KT.fmtPct(w))); return td; };
    panel.forEach(p => {
      const tr = el('tr', null, [el('td', { text: p.label || p.name })]);
      tr.appendChild(barCell(p.w_exports)); tr.appendChild(barCell(p.w_imports));
      tr.appendChild(el('td', { text: p.latest_published_month ? KT.fmtPeriod(p.latest_published_month) : 'nothing yet' }));
      tr.appendChild(el('td', { text: KT.isNum(p.typical_lag_months) ? 'about ' + p.typical_lag_months + ' months' : '—' }));
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
  }

  /* ---- 3. observed series ---- */
  /* Rows for a view, trimmed of leading periods where none of the plotted keys has a value
     (the annual file may reach back to 2010 with only the separate annual-dataset tuna series). */
  const PLOT_KEYS = ['exports_partner', 'exports_partner_tuna', 'exports_kiribati', 'imports_partner', 'imports_kiribati'];
  function seriesRows(view) {
    const rows = D.series && Array.isArray(D.series[view]) ? D.series[view] : [];
    const first = rows.findIndex(r => PLOT_KEYS.some(k => KT.isNum(r[k])));
    return first > 0 ? rows.slice(first) : rows;
  }
  /* coverage rows aligned to the same start as the series (so the two charts line up) */
  function coverageRows(view) {
    const rows = D.coverage && Array.isArray(D.coverage[view]) ? D.coverage[view] : [];
    const sr = seriesRows(view); if (!sr.length) return rows;
    const i = rows.findIndex(r => String(r.period) >= String(sr[0].period));
    return i > 0 ? rows.slice(i) : rows;
  }
  function fishOnly(r) { return !KT.isNum(r.exports_partner) && KT.isNum(r.exports_partner_tuna); }
  function prelimTick(rows, dense, monthly) { return function (val) { const r = rows[val]; const l = KT.tickPeriod(this.getLabelForValue(val), dense); if (monthly && l === '') return undefined; return l + (r && isPrelim(r) ? '*' : ''); }; }
  function pctFooter(rows) {
    return items => { const r = rows[items[0].dataIndex]; if (!r) return '';
      const parts = ['Percent complete: ' + KT.fmtPct(r.pct_complete) + (KT.isNum(r.pct_complete_w_exports) ? ' (export-weighted ' + KT.fmtPct(r.pct_complete_w_exports) + ', import-weighted ' + KT.fmtPct(r.pct_complete_w_imports) + ')' : '')];
      if (isPrelim(r)) parts.push('Preliminary: under ' + Math.round(PRELIM_THRESHOLD * 100) + '% complete');
      if (fishOnly(r)) parts.push('Only the fish series are available for this period (see note)');
      if (r.kiribati_reported === false) parts.push('Kiribati\'s own return: not yet published');
      else if (KT.isNum(r.kiribati_months_reported) && KT.isNum(r.months_in_period) && r.kiribati_months_reported < r.months_in_period) parts.push('Kiribati published ' + r.kiribati_months_reported + ' of ' + r.months_in_period + ' months');
      return parts; };
  }
  /* colours per bar: lighter when preliminary */
  function fills(rows, color) { const a = KT.tokens().prelimAlpha; return rows.map(r => isPrelim(r) ? KT.withAlpha(color, a) : color); }
  function nz(v) { return KT.isNum(v) ? v : null; }

  function renderExports() {
    const t = KT.tokens();
    addMonthlyChip('fig-exports', 'exports');
    const view = viewFor('exports'); const rows = seriesRows(view); const last = latestRow(rows);
    figChrome('fig-exports', 'exports', last ? { pct: last.pct_complete, period: KT.fmtPeriod(last.period) } : null, { subtitle: (T('charts.exports.subtitle') || '') + ' — by ' + VIEW_LABEL[view] });
    KT.legend('legend-exports', [
      { label: 'Tuna (by vessel flag)', color: t.partner }, { label: 'Other fish and seafood', color: t.fish }, { label: 'Copra oil', color: t.copra }, { label: 'Other goods (excluding ships and aircraft)', color: t.other },
      { label: 'Kiribati-reported exports', color: t.kir, kind: 'line' }, { label: 'Preliminary (* on the axis)', color: t.partner, kind: 'light' }
    ]);
    setText('note-exports', T('notes.exports') + (rows.some(fishOnly) ? ' Where Kiribati\'s own return is not published, partner data were collected for fish only, so those bars show tuna and other fish but not copra oil or other goods.' : '') + (rows.some(r => KT.isNum(r.months_with_partner_data) && KT.isNum(r.months_with_fish_data) && r.months_with_partner_data < r.months_with_fish_data) ? ' Fish bars cover every month; copra oil and other goods cover only the months Kiribati published, so the stack is not an all-goods total for those years (hover a bar for both figures).' : ''));
    if (!rows.length) { KT.empty('chart-exports'); clear('table-exports'); return; }
    const other = rows.map(r => {
      const copra = r.exports_partner_copra_oil || 0;
      if (KT.isNum(r.exports_partner_ex_fish_ships)) return Math.max(0, r.exports_partner_ex_fish_ships - copra);
      if (KT.isNum(r.exports_partner)) return Math.max(0, r.exports_partner - (r.exports_partner_tuna || 0) - (r.exports_partner_other_fish || 0) - copra);
      return null;
    });
    const dense = rows.length > 24;
    KT.make('chart-exports', {
      type: 'bar',
      data: { labels: rows.map(r => r.period), datasets: [
        { label: 'Tuna', data: rows.map(r => nz(r.exports_partner_tuna)), backgroundColor: fills(rows, t.partner), stack: 'p', maxBarThickness: 24 },
        { label: 'Other fish and seafood', data: rows.map(r => nz(r.exports_partner_other_fish)), backgroundColor: fills(rows, t.fish), stack: 'p', maxBarThickness: 24 },
        { label: 'Copra oil', data: rows.map(r => nz(r.exports_partner_copra_oil)), backgroundColor: fills(rows, t.copra), stack: 'p', maxBarThickness: 24 },
        { label: 'Other goods (ex ships and aircraft)', data: other, backgroundColor: fills(rows, t.other), stack: 'p', maxBarThickness: 24 },
        { type: 'line', label: 'Kiribati-reported exports', data: rows.map(r => nz(r.exports_kiribati)), borderColor: t.kir, backgroundColor: t.kir, spanGaps: false, pointRadius: dense ? 1.5 : 3, order: -1 }
      ] },
      options: {
        scales: (() => { const s = KT.axes({ stacked: true, dense, monthlyDense: view === 'monthly' }); s.x.ticks.callback = prelimTick(rows, dense, view === 'monthly'); return s; })(),
        interaction: { mode: 'index', intersect: false },
        plugins: { tooltip: { callbacks: { title: items => KT.fmtPeriod(items[0].label), label: KT.moneyLabel, footer: pctFooter(rows),
          afterBody: items => { const r = rows[items[0].dataIndex]; if (!KT.isNum(r.exports_partner)) return [];
            const mixed = KT.isNum(r.months_with_partner_data) && KT.isNum(r.months_with_fish_data) && r.months_with_partner_data < r.months_with_fish_data;
            return mixed ? ['Fish bars: all ' + r.months_with_fish_data + ' months. Other bars and this total: the ' + r.months_with_partner_data + ' months Kiribati published.', 'All goods, ' + r.months_with_partner_data + ' months: ' + KT.fmtM(r.exports_partner)] : ['Partner-reported total: ' + KT.fmtM(r.exports_partner)]; } } } }
      }
    });
    KT.table('table-exports', [
      { key: 'period', label: 'Period', fmt: KT.fmtPeriod }, { key: 'exports_partner_tuna', label: 'Tuna', num: true, fmt: KT.fmtNum1 }, { key: 'exports_partner_other_fish', label: 'Other fish', num: true, fmt: KT.fmtNum1 },
      { key: 'exports_partner_copra_oil', label: 'Copra oil', num: true, fmt: KT.fmtNum1 }, { key: 'exports_partner', label: 'Partner total', num: true, fmt: KT.fmtNum1 },
      { key: 'exports_kiribati', label: 'Kiribati-reported', num: true, fmt: KT.fmtNum1 }, { key: 'pct_complete', label: 'Complete', num: true, fmt: KT.fmtPct }
    ], rows.slice().reverse());
  }

  /* Kiribati's own import total. The builder may supply imports_kiribati_ex_flagged,
     the same series with one implausible published line set aside; use it when present. */
  function kirImports(r) { return KT.isNum(r.imports_kiribati_ex_flagged) ? r.imports_kiribati_ex_flagged : r.imports_kiribati; }
  function renderImports() {
    const t = KT.tokens();
    addMonthlyChip('fig-imports', 'imports');
    const view = viewFor('imports'); const rows = seriesRows(view); const last = latestRow(rows);
    figChrome('fig-imports', 'imports', last ? { pct: last.pct_complete, period: KT.fmtPeriod(last.period) } : null, { subtitle: (T('charts.imports.subtitle') || '') + ' — by ' + VIEW_LABEL[view] });
    KT.legend('legend-imports', [
      { label: 'Partner-reported, excluding ships and aircraft', color: t.partner }, { label: 'Ships and aircraft (HS 88–89)', color: t.partner, kind: 'hatch' },
      { label: 'Kiribati-reported imports', color: t.kir, kind: 'line' }, { label: 'Preliminary (* on the axis)', color: t.partner, kind: 'light' }
    ]);
    setText('note-imports', T('notes.imports'));
    if (!rows.length) { KT.empty('chart-imports'); clear('table-imports'); return; }
    const dense = rows.length > 24; const a = t.prelimAlpha;
    KT.make('chart-imports', {
      type: 'bar',
      data: { labels: rows.map(r => r.period), datasets: [
        { label: 'Excluding ships and aircraft', data: rows.map(r => nz(r.imports_partner_ex_ships_aircraft)), backgroundColor: fills(rows, t.partner), stack: 'p', maxBarThickness: 24 },
        { label: 'Ships and aircraft', data: rows.map(r => nz(r.imports_partner_ships_aircraft)), backgroundColor: rows.map(r => KT.hatch(t.partner, isPrelim(r) ? a : 1)), borderColor: rows.map(r => isPrelim(r) ? KT.withAlpha(t.partner, a) : t.partner), borderWidth: 1, stack: 'p', maxBarThickness: 24 },
        { type: 'line', label: 'Kiribati-reported imports', data: rows.map(r => nz(kirImports(r))), borderColor: t.kir, backgroundColor: t.kir, spanGaps: false, pointRadius: dense ? 1.5 : 3, order: -1 }
      ] },
      options: {
        scales: (() => { const s = KT.axes({ stacked: true, dense, monthlyDense: view === 'monthly' }); s.x.ticks.callback = prelimTick(rows, dense, view === 'monthly'); return s; })(),
        interaction: { mode: 'index', intersect: false },
        plugins: { tooltip: { callbacks: { title: items => KT.fmtPeriod(items[0].label), label: KT.moneyLabel, footer: pctFooter(rows),
          afterBody: items => { const r = rows[items[0].dataIndex]; return KT.isNum(r.imports_partner) ? ['Partner-reported total: ' + KT.fmtM(r.imports_partner)] : []; } } } }
      }
    });
    KT.table('table-imports', [
      { key: 'period', label: 'Period', fmt: KT.fmtPeriod }, { key: 'imports_partner_ex_ships_aircraft', label: 'Partner ex ships & aircraft', num: true, fmt: KT.fmtNum1 },
      { key: 'imports_partner_ships_aircraft', label: 'Ships & aircraft', num: true, fmt: KT.fmtNum1 }, { key: 'imports_partner', label: 'Partner total', num: true, fmt: KT.fmtNum1 },
      { key: 'imports_kiribati', label: 'Kiribati-reported', num: true, fmt: (v, r) => KT.fmtNum1(kirImports(r)) }, { key: 'pct_complete', label: 'Complete', num: true, fmt: KT.fmtPct }
    ], rows.slice().reverse());
    const hasFlag = rows.some(r => KT.isNum(r.imports_kiribati_ex_flagged) && KT.isNum(r.imports_kiribati) && Math.abs(r.imports_kiribati_ex_flagged - r.imports_kiribati) > 0.001);
    if (hasFlag) setText('note-imports', T('notes.imports') + ' One published Kiribati import line (January 2024, prefabricated buildings, USD 3,135 million) is set aside in the line shown here; the data file keeps it as published.');
  }

  function rollFish(r) { return KT.isNum(r.exports_partner_fish) ? r.exports_partner_fish : r.exports_partner; }
  function renderRolling() {
    const t = KT.tokens();
    const rows = D.series && Array.isArray(D.series.rolling_12m) ? D.series.rolling_12m : [];
    const last = latestRow(rows);
    const lastM = latestRow(seriesRows('monthly'));
    figChrome('fig-rolling', 'rolling', lastM ? { pct: lastM.pct_complete, period: KT.fmtPeriod(lastM.period) } : null, last ? { subtitle: (T('charts.rolling.subtitle') || '') + ' — latest: ' + KT.fmtM(rollFish(last)) + ' in the 12 months to ' + KT.fmtPeriod(last.end) + (KT.isNum(last.growth_pct) ? ' (' + KT.fmtGrowth(last.growth_pct) + ' on a year earlier)' : '') } : null);
    KT.legend('legend-rolling', [{ label: 'All fish and seafood', color: t.fish, kind: 'line' }, { label: 'Of which tuna', color: t.partner, kind: 'dash' }]);
    if (!rows.length) { KT.empty('chart-rolling'); clear('table-rolling'); return; }
    KT.make('chart-rolling', {
      type: 'line',
      data: { labels: rows.map(r => r.end), datasets: [
        { label: 'All fish and seafood', data: rows.map(r => nz(rollFish(r))), borderColor: t.fish, backgroundColor: KT.withAlpha(t.fish, 0.1), fill: true, pointRadius: 0, pointHitRadius: 12 },
        { label: 'Of which tuna', data: rows.map(r => nz(r.exports_partner_tuna)), borderColor: t.partner, backgroundColor: t.partner, borderDash: [3, 3], pointRadius: 0, pointHitRadius: 12 }
      ] },
      options: {
        scales: KT.axes({ dense: true, monthlyDense: true }),
        interaction: { mode: 'index', intersect: false },
        plugins: { tooltip: { callbacks: { title: items => '12 months to ' + KT.fmtPeriod(items[0].label), label: KT.moneyLabel,
          footer: items => { const r = rows[items[0].dataIndex]; return [KT.isNum(r.growth_pct) ? 'Change on a year earlier: ' + KT.fmtGrowth(r.growth_pct) : 'Change on a year earlier: not available', (KT.isNum(r.months_with_fish_data) && r.months_with_fish_data < 12) ? 'Only ' + r.months_with_fish_data + ' of 12 months have partner data' : ((r.months && r.months < 12) ? 'Only ' + r.months + ' months available' : '')].filter(Boolean); } } } }
      }
    });
    KT.table('table-rolling', [
      { key: 'end', label: '12 months to', fmt: KT.fmtPeriod }, { key: 'exports_partner_fish', label: 'All fish (USD m)', num: true, fmt: (v, r) => KT.fmtNum1(rollFish(r)) },
      { key: 'exports_partner_tuna', label: 'Tuna (USD m)', num: true, fmt: KT.fmtNum1 }, { key: 'growth_pct', label: 'Change on a year earlier', num: true, fmt: KT.fmtGrowth }
    ], rows.slice().reverse());
  }

  /* ---- 4. national accounts ---- */
  function renderNationalAccounts() {
    const t = KT.tokens(); const NA = D.national_accounts;
    const allRows = NA && Array.isArray(NA.annual) ? NA.annual : [];
    /* The chart shows the years for which partner records exist (2017 onwards); earlier
       balance-of-payments years stay in the table twin. */
    const firstPartner = allRows.findIndex(r => KT.isNum(r.partner_exports) || KT.isNum(r.partner_imports));
    const rows = firstPartner > 0 ? allRows.slice(firstPartner) : allRows;
    const side = clear('na-side');
    const txt = Object.assign({}, DEFAULT_TEXT.charts.national_accounts, (D.text && D.text.charts && D.text.charts.national_accounts) || {});
    if (txt.side_text) (Array.isArray(txt.side_text) ? txt.side_text : [txt.side_text]).forEach(p => side.appendChild(el('p', { text: p })));
    (NA && Array.isArray(NA.notes) ? NA.notes : []).forEach(n => side.appendChild(el('p', { text: n })));
    if (state.view === 'quarterly') side.appendChild(el('p', { class: 'small muted', text: 'Official balance-of-payments figures are published once a year, so this comparison stays annual even in the quarterly view.' }));
    const covA = D.coverage && D.coverage.annual ? D.coverage.annual : [];
    const lastY = latestRow(rows); const covLast = lastY ? covA.find(c => String(c.period) === String(lastY.year)) : null;
    const src = covLast ? { pct: covLast.share_count, period: String(lastY.year) } : null;
    figChrome('fig-na-exports', 'national_accounts', src, { title: 'Exports: official figures next to partner records' });
    figChrome('fig-na-imports', 'national_accounts', src, { title: 'Imports: official figures next to partner records', how_to_read: '', caveat: txt.caveat });
    KT.legend('legend-na-exports', [{ label: 'Balance of payments, goods exports (official)', color: t.kir }, { label: 'Kiribati customs, scaled to 12 months', color: t.kir, kind: 'hatch' }, { label: 'Partner-reported, full year: tuna (by vessel flag)', color: t.partner }, { label: 'Partner-reported, full year: other goods', color: t.partner, kind: 'hatch' }]);
    KT.legend('legend-na-imports', [{ label: 'Balance of payments, goods imports (official)', color: t.kir }, { label: 'Kiribati customs, scaled to 12 months', color: t.kir, kind: 'hatch' }, { label: 'Partner-reported, full year: excluding ships and aircraft', color: t.partner }, { label: 'Partner-reported, full year: ships and aircraft', color: t.partner, kind: 'hatch' }]);
    if (!rows.length) { KT.empty('chart-na-exports'); KT.empty('chart-na-imports'); return; }
    const partial = r => KT.isNum(r.months_kiribati_reported) && r.months_kiribati_reported < 12;
    const labels = rows.map(r => String(r.year) + (partial(r) ? '*' : ''));
    ['fig-na-exports', 'fig-na-imports'].forEach(id => { const fig = document.getElementById(id); let n = fig.querySelector('.note'); if (!n) { n = el('p', { class: 'note' }); fig.querySelector('figcaption').before(n); }
      const some = rows.filter(r => partial(r) && r.months_kiribati_reported > 0).map(r => r.year + ' (' + r.months_kiribati_reported + ' months)'); const none = rows.filter(r => KT.isNum(r.months_kiribati_reported) && r.months_kiribati_reported === 0).map(r => String(r.year));
      n.textContent = (some.length ? '* Kiribati published fewer than 12 months: ' + some.join(', ') + '; for these years the customs bar is scaled to 12 months. ' : '') + (none.length ? 'No Kiribati return for ' + none.join(', ') + '. ' : '') + 'Partner bars are full-year figures from partners\u2019 annual returns (all reporters); the months-published figures are in the table.'; });
    const gdpLine = (key) => (ctx) => { const r = rows[ctx.dataIndex]; const v = ctx.parsed.y; if (!KT.isNum(v)) return null;
      const pg = r.pct_gdp && KT.isNum(r.pct_gdp[key]) ? r.pct_gdp[key] : (KT.isNum(r.gdp_usd) && r.gdp_usd > 0 ? v / r.gdp_usd * 100 : null);
      return ' ' + ctx.dataset.label + ': ' + KT.fmtM(v) + (KT.isNum(pg) ? ' (' + KT.fmtNum1(pg) + '% of GDP)' : ''); };
    const common = (keys) => ({
      scales: KT.axes({}), interaction: { mode: 'index', intersect: false },
      plugins: { tooltip: { callbacks: { title: items => String(rows[items[0].dataIndex].year),
        label: ctx => gdpLine(keys[ctx.datasetIndex])(ctx),
        footer: items => { const r = rows[items[0].dataIndex]; const out = []; if (KT.isNum(r.months_kiribati_reported) && r.months_kiribati_reported < 12) out.push('Kiribati published ' + r.months_kiribati_reported + ' of 12 months'); const c = covA.find(x => String(x.period) === String(r.year)); if (c) out.push('Percent complete: ' + KT.fmtPct(c.share_count)); return out; } } } }
    });
    const bar = (label, data, color, hatched, stack) => ({ label, data, backgroundColor: hatched ? KT.hatch(color) : color, borderColor: color, borderWidth: hatched ? 1 : 0, maxBarThickness: 22, stack: stack || label });
    const diff = (a, b) => (KT.isNum(a) && KT.isNum(b)) ? Math.max(0, a - b) : null;
    const ek = ['bop_goods_exports', 'customs_exports_kiribati_scaled12', 'partner_exports_tuna_annual_basis', 'partner_exports_annual_basis'];
    const stackTotal = (totalKey, label) => items => { const r = rows[items[0].dataIndex]; return KT.isNum(r[totalKey]) ? [label + ': ' + KT.fmtM(r[totalKey])] : []; };
    const optsE = common(ek); optsE.scales = KT.axes({ stacked: true }); optsE.plugins.tooltip.callbacks.afterBody = stackTotal('partner_exports_annual_basis', 'Partner-reported, all goods, full year');
    KT.make('chart-na-exports', { type: 'bar', data: { labels, datasets: [
      bar('Balance of payments (official)', rows.map(r => nz(r.bop_goods_exports)), t.kir, false),
      bar('Kiribati customs, scaled to 12 months', rows.map(r => nz(r.customs_exports_kiribati_scaled12)), t.kir, true),
      bar('Partner-reported: tuna, full year', rows.map(r => nz(r.partner_exports_tuna_annual_basis)), t.partner, false, 'partner'),
      bar('Partner-reported: other goods, full year', rows.map(r => diff(r.partner_exports_annual_basis, r.partner_exports_tuna_annual_basis)), t.partner, true, 'partner')
    ] }, options: optsE });
    const ik = ['bop_goods_imports', 'customs_imports_kiribati_scaled12', 'partner_imports_ex_ships_aircraft_annual_basis', 'partner_imports_ships_aircraft_annual_basis'];
    const optsI = common(ik); optsI.scales = KT.axes({ stacked: true }); optsI.plugins.tooltip.callbacks.afterBody = stackTotal('partner_imports_annual_basis', 'Partner-reported, all goods, full year');
    KT.make('chart-na-imports', { type: 'bar', data: { labels, datasets: [
      bar('Balance of payments (official)', rows.map(r => nz(r.bop_goods_imports)), t.kir, false),
      bar('Kiribati customs, scaled to 12 months', rows.map(r => nz(r.customs_imports_kiribati_scaled12)), t.kir, true),
      bar('Partner-reported: excluding ships and aircraft, full year', rows.map(r => nz(r.partner_imports_ex_ships_aircraft_annual_basis)), t.partner, false, 'partner'),
      bar('Partner-reported: ships and aircraft, full year', rows.map(r => nz(r.partner_imports_ships_aircraft_annual_basis)), t.partner, true, 'partner')
    ] }, options: optsI });
    KT.table('table-na-exports', [{ key: 'year', label: 'Year' }, { key: 'months_kiribati_reported', label: 'Months Kiribati published', num: true }, { key: 'bop_goods_exports', label: 'BOP exports', num: true, fmt: KT.fmtNum1 }, { key: 'customs_exports_kiribati', label: 'Customs (as published)', num: true, fmt: KT.fmtNum1 }, { key: 'customs_exports_kiribati_scaled12', label: 'Customs, 12-month basis', num: true, fmt: KT.fmtNum1 }, { key: 'partner_exports_tuna_annual_basis', label: 'Partner tuna, full year', num: true, fmt: KT.fmtNum1 }, { key: 'partner_exports_annual_basis', label: 'Partner all goods, full year', num: true, fmt: KT.fmtNum1 }, { key: 'partner_exports', label: 'Partner all goods, months published', num: true, fmt: KT.fmtNum1 }, { key: 'gdp_usd', label: 'GDP', num: true, fmt: KT.fmtNum1 }], allRows.slice().reverse());
    KT.table('table-na-imports', [{ key: 'year', label: 'Year' }, { key: 'months_kiribati_reported', label: 'Months Kiribati published', num: true }, { key: 'bop_goods_imports', label: 'BOP imports', num: true, fmt: KT.fmtNum1 }, { key: 'customs_imports_kiribati', label: 'Customs (as published)', num: true, fmt: KT.fmtNum1 }, { key: 'customs_imports_kiribati_scaled12', label: 'Customs, 12-month basis', num: true, fmt: KT.fmtNum1 }, { key: 'partner_imports_ex_ships_aircraft_annual_basis', label: 'Partner ex ships & aircraft, full year', num: true, fmt: KT.fmtNum1 }, { key: 'partner_imports_annual_basis', label: 'Partner all goods, full year', num: true, fmt: KT.fmtNum1 }, { key: 'partner_imports', label: 'Partner all goods, months published', num: true, fmt: KT.fmtNum1 }, { key: 'customs_imports_kiribati_as_published', label: 'Customs, as published', num: true, fmt: (v, r) => KT.isNum(v) ? KT.fmtNum1(v) : KT.fmtNum1(r.customs_imports_kiribati) }], allRows.slice().reverse());
    const excl = NA && NA.meta && Array.isArray(NA.meta.excluded_lines) ? NA.meta.excluded_lines : [];
    if (excl.length) { const fig = document.getElementById('fig-na-imports'); const n = fig.querySelector('.note'); if (n) n.textContent = (n.textContent ? n.textContent + ' ' : '') + 'Set aside from the customs bars: ' + excl.map(e => KT.fmtPeriod(e.period) + ', ' + e.description + ' (USD ' + KT.fmtNum1(e.kiribati_value_usd_m) + ' m)').join('; ') + '. The as-published total is in the table.'; }
  }

  /* ---- 5. peers ---- */
  const PEER_GREYS_LIGHT = ['#6b7a84', '#8a98a1', '#a3afb6', '#7d8b94', '#95a2a9', '#b0bbc1'];
  function renderPeersTuna() {
    const t = KT.tokens(); const P = D.peers && D.peers.tuna_by_origin;
    const covA = D.coverage && D.coverage.annual ? D.coverage.annual : [];
    const countries = P && Array.isArray(P.countries) ? P.countries : [];
    const years = P && Array.isArray(P.years) ? P.years : [];
    const lastY = years.length ? years[years.length - 1] : null; const c = covA.find(x => String(x.period) === String(lastY));
    figChrome('fig-peers-tuna', 'peers_tuna', c ? { pct: c.share_count, period: String(lastY) } : null, { subtitle: (T('charts.peers_tuna.subtitle') || '') + (P && P.unit ? ' · ' + P.unit : '') });
    const kir = countries.find(x => x.is_subject); const others = countries.filter(x => !x.is_subject);
    KT.legend('legend-peers-tuna', [{ label: 'Kiribati', color: t.kir, kind: 'line' }].concat(others.map((o, i) => ({ label: o.name, color: PEER_GREYS_LIGHT[i % PEER_GREYS_LIGHT.length], kind: 'line' }))));
    if (!countries.length) { KT.empty('chart-peers-tuna'); return; }
    /* Basis note: this chart uses partners' annual returns (all reporters), the rest of the site the monthly returns. */
    (function () { const fig = document.getElementById('fig-peers-tuna'); if (!fig || !kir) return; let n = fig.querySelector('.note'); if (!n) { n = el('p', { class: 'note' }); const fc = fig.querySelector('figcaption'); if (fc) fc.before(n); }
      const i = years.indexOf(lastY); const here = kir.values[i]; const ann = D.series && D.series.annual ? D.series.annual.find(r => String(r.period) === String(lastY) && r.months_with_fish_data === 12) : null;
      n.textContent = 'Basis: partners\u2019 annual returns to UN Comtrade, all reporters, so every country is on the same footing. The rest of this site uses monthly returns, which exclude annual-only reporters' + (ann && KT.isNum(here) && KT.isNum(ann.exports_partner_tuna) ? ' (Kiribati ' + lastY + ': ' + KT.fmtM(here) + ' here, ' + KT.fmtM(ann.exports_partner_tuna) + ' in the monthly series).' : '.'); })();
    const ds = others.map((o, i) => ({ label: o.name, shortLabel: o.name.replace('Papua New Guinea', 'PNG').replace('Micronesia (FS)', 'Micronesia').replace('Solomon Islands', 'Solomon Is.').replace('Marshall Islands', 'Marshall Is.'), data: o.values.map(nz), borderColor: PEER_GREYS_LIGHT[i % PEER_GREYS_LIGHT.length], backgroundColor: PEER_GREYS_LIGHT[i % PEER_GREYS_LIGHT.length], borderWidth: 1.5, pointRadius: 0, pointHitRadius: 10 }));
    if (kir) ds.push({ label: kir.name, shortLabel: 'Kiribati', isSubject: true, data: kir.values.map(nz), borderColor: t.kir, backgroundColor: t.kir, borderWidth: 3, pointRadius: 3, pointHitRadius: 10 });
    KT.make('chart-peers-tuna', {
      type: 'line', data: { labels: years.map(String), datasets: ds },
      options: { layout: { padding: { right: 84 } }, scales: KT.axes({}), interaction: { mode: 'index', intersect: false },
        plugins: { endLabels: { enabled: true }, tooltip: { itemSort: (a, b) => b.parsed.y - a.parsed.y, callbacks: { title: items => items[0].label, label: KT.moneyLabel } } } },
      plugins: [KT.endLabels]
    });
    const cols = [{ key: 'name', label: 'Country' }].concat(years.map((y, i) => ({ key: 'v' + i, label: String(y), num: true, fmt: KT.fmtNum1 }))).concat([{ key: 'change_2015_2025_pct', label: '2015→2025', num: true, fmt: v => KT.isNum(v) ? (v > 0 ? '+' : '') + Math.round(v) + '%' : '—' }]);
    KT.table('table-peers-tuna', cols, countries.map(cn => { const r = { name: cn.name, change_2015_2025_pct: cn.change_2015_2025_pct, is_subject: cn.is_subject }; cn.values.forEach((v, i) => r['v' + i] = v); return r; }), { highlight: r => r.is_subject });
  }

  function renderPeersTable() {
    const rows = D.peers && Array.isArray(D.peers.applicability) ? D.peers.applicability.slice() : [];
    figChrome('fig-peers-app', 'peers_applicability', null, { subtitle: (T('charts.peers_applicability.subtitle') || '') + (rows.length ? ' · ratio year ' + (rows.find(r => r.is_subject) || rows[0]).ratio_year : '') });
    const tbl = clear('peers-table'); if (!tbl) return;
    if (!rows.length) { tbl.appendChild(el('caption', { class: 'empty', text: 'Peer comparison not available.' })); return; }
    const cols = [
      { key: 'country', label: 'Country', fmt: (v, r) => v },
      { key: 'own_monthly_lag_months', label: 'Own monthly data: lag', num: true, fmt: v => KT.isNum(v) ? v + ' mo' : 'none', na: v => !KT.isNum(v) },
      { key: 'own_months_of_24', label: 'Months published of last 24', num: true, fmt: v => KT.isNum(v) ? String(v) : '0' },
      { key: 'exp_cov_12m', label: 'Export coverage', num: true, bar: true, fmt: KT.fmtPct },
      { key: 'imp_cov_12m', label: 'Import coverage', num: true, bar: true, fmt: KT.fmtPct },
      { key: 'exp_ratio', label: 'Export ratio (partners ÷ own)', num: true, fmt: KT.fmtRatio, na: v => !KT.isNum(v) },
      { key: 'imp_ratio', label: 'Import ratio (partners ÷ own)', num: true, fmt: KT.fmtRatio, na: v => !KT.isNum(v) }
    ];
    const sort = state.peersSort;
    if (sort.key) rows.sort((a, b) => { const x = a[sort.key], y = b[sort.key]; if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1; return (typeof x === 'string' ? x.localeCompare(y) : x - y) * sort.dir; });
    const trh = el('tr');
    cols.forEach(c => { const b = el('button', { type: 'button', text: c.label }); if (sort.key === c.key) b.setAttribute('aria-sort', sort.dir === 1 ? 'ascending' : 'descending');
      b.addEventListener('click', () => { state.peersSort = { key: c.key, dir: sort.key === c.key ? -sort.dir : (c.key === 'country' ? 1 : -1) }; renderPeersTable(); });
      trh.appendChild(el('th', { class: c.num ? 'num' : '' }, [b])); });
    tbl.appendChild(el('thead', null, [trh]));
    const tb = el('tbody');
    rows.forEach(r => {
      const tr = el('tr', { class: r.is_subject ? 'is-subject' : '' });
      cols.forEach(c => {
        const td = el('td', { class: (c.num ? 'num' : '') + (c.na && c.na(r[c.key]) ? ' na' : '') + (c.bar ? ' bar-cell' : '') });
        if (c.bar && KT.isNum(r[c.key])) { const b = el('span', { class: 'dbar' }); b.style.width = Math.round(r[c.key] * 60) + 'px'; td.appendChild(b); }
        td.appendChild(document.createTextNode(c.fmt(r[c.key], r)));
        if (c.key === 'country' && r.pna) td.appendChild(el('span', { class: 'pna-tag', text: 'PNA', title: 'Party to the Nauru Agreement' }));
        tr.appendChild(td);
      });
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    /* peers.json "notes" are technical (they name JSON fields), so the page keeps its own plain line. */
    const fig = document.getElementById('fig-peers-app'); let n = fig.querySelector('.note'); if (!n) { n = el('p', { class: 'note' }); fig.querySelector('figcaption').before(n); }
    n.textContent = 'A blank ratio means the country has not published its own total for a recent year. PNA = Parties to the Nauru Agreement, the group of Pacific states that run the Vessel Day Scheme for tuna fishing. The Marshall Islands is not in this table because trade booked to its ship registry swamps its partner data.';
  }

  /* ---- 6. products ---- */
  function productsYears() {
    const P = D.products; const dir = state.productsDir; if (!P || !P[dir]) return [];
    const ys = Object.keys(P[dir].annual || {}).sort().reverse();
    const out = ys.map(y => ({ value: y, label: y }));
    if (P[dir].latest_12m && Array.isArray(P[dir].latest_12m.rows) && P[dir].latest_12m.rows.length) out.unshift({ value: 'latest_12m', label: '12 months to ' + KT.fmtPeriod(P[dir].latest_12m.end) });
    return out;
  }
  function renderProducts() {
    const t = KT.tokens(); const P = D.products; const dir = state.productsDir;
    const sel = document.getElementById('products-year');
    const years = productsYears();
    if (sel) {
      const cur = state.productsYear; sel.textContent = '';
      years.forEach(y => sel.appendChild(el('option', { value: y.value, text: y.label })));
      if (!years.some(y => y.value === cur)) { const annualThrough = D.manifest && D.manifest.data_through ? String(D.manifest.data_through.annual) : null; state.productsYear = years.some(y => y.value === annualThrough) ? annualThrough : (years.find(y => y.value !== 'latest_12m') || years[0] || {}).value; }
      sel.value = state.productsYear;
    }
    const y = state.productsYear;
    const rowsAll = P && P[dir] ? (y === 'latest_12m' ? P[dir].latest_12m.rows : (P[dir].annual || {})[y]) || [] : [];
    const isSummary = r => r.is_summary === true || r.hs4 === 'other' || r.hs4 === 'total';
    const rows = rowsAll.filter(r => !isSummary(r)); const otherRow = rowsAll.find(r => r.hs4 === 'other'); const totalRow = rowsAll.find(r => r.hs4 === 'total');
    const covA = D.coverage && D.coverage.annual ? D.coverage.annual : []; const c = covA.find(x => String(x.period) === String(y));
    const dirWord = dir === 'exports' ? 'Exports' : 'Imports';
    figChrome('fig-products', 'products', c ? { pct: c.share_count, period: String(y) } : null, { title: (T('charts.products.title') || 'Top product groups') + ': ' + dirWord.toLowerCase() + ', ' + (y === 'latest_12m' ? 'latest 12 months' : y) });
    KT.legend('legend-products', [{ label: 'Partner-reported', color: t.partner }, { label: 'Kiribati-reported', color: t.kir }]);
    if (!rows.length) { KT.empty('chart-products', 'No product detail for this year.'); clear('table-products'); return; }
    const plot = document.querySelector('#fig-products .plot'); if (plot) plot.style.height = Math.max(260, 40 + rows.length * 34) + 'px';
    KT.make('chart-products', {
      type: 'bar', data: { labels: rows.map(r => r.label), datasets: [
        { label: 'Partner-reported', data: rows.map(r => nz(r.partner)), backgroundColor: t.partner, maxBarThickness: 14 },
        { label: 'Kiribati-reported', data: rows.map(r => nz(r.kiribati)), backgroundColor: t.kir, maxBarThickness: 14 }
      ] },
      options: { indexAxis: 'y', scales: (() => { const s = KT.axes({ horizontal: true }); const maxChars = (document.getElementById('chart-products').parentElement.clientWidth || 600) > 700 ? 40 : 24;
        s.y.ticks.callback = function (v) { const l = this.getLabelForValue(v); return l.length > maxChars ? l.slice(0, maxChars - 1) + '…' : l; }; s.y.ticks.font = { size: 11 }; s.y.ticks.crossAlign = 'far'; return s; })(),
        interaction: { mode: 'index', intersect: false, axis: 'y' },
        plugins: { tooltip: { callbacks: { title: items => { const r = rows[items[0].dataIndex]; return r.label + ' (HS ' + r.hs4 + ')'; }, label: KT.moneyLabel,
          footer: items => { const r = rows[items[0].dataIndex]; const out = []; if (KT.isNum(r.n_partners)) out.push(r.n_partners + ' partner' + (r.n_partners === 1 ? '' : 's') + ' reported this line'); if (KT.isNum(r.partner) && KT.isNum(r.kiribati)) out.push('Difference: ' + KT.fmtM(r.partner - r.kiribati) + ' (partners minus Kiribati)'); return out; } } } } }
    });
    const fig = document.getElementById('fig-products'); let n = fig.querySelector('.note'); if (!n) { n = el('p', { class: 'note' }); fig.querySelector('figcaption').before(n); }
    n.textContent = (otherRow ? (otherRow.label || 'All other product groups') + ': partner-reported ' + KT.fmtM(otherRow.partner) + ', Kiribati-reported ' + KT.fmtM(otherRow.kiribati) + '. ' : '') + (totalRow ? 'Total, all goods: partner-reported ' + KT.fmtM(totalRow.partner) + ', Kiribati-reported ' + KT.fmtM(totalRow.kiribati) + '.' : '');
    KT.table('table-products', [{ key: 'hs4', label: 'HS4', fmt: v => (v === 'other' || v === 'total') ? '' : v }, { key: 'label', label: 'Product group' }, { key: 'partner', label: 'Partner-reported', num: true, fmt: KT.fmtNum1 }, { key: 'kiribati', label: 'Kiribati-reported', num: true, fmt: KT.fmtNum1 }, { key: 'n_partners', label: 'Partners reporting', num: true, fmt: v => KT.isNum(v) ? String(v) : '' }], rowsAll, { highlight: isSummary });
  }

  /* "2025-01..2026-07" -> "Jan 2025 to Jul 2026" */
  function fmtWindow(w) { const m = String(w).match(/^(\d{4}-\d{2})\.\.(\d{4}-\d{2})$/); return m ? KT.fmtPeriod(m[1]) + ' to ' + KT.fmtPeriod(m[2]) : String(w); }
  function renderNotable() {
    const P = D.products; const ul = clear('notable-list'); setText('notable-lede', T('notes.notable'));
    if (!P) { ul.appendChild(el('li', { class: 'empty', text: 'Not available.' })); return; }
    const items = [];
    (P.categories || []).filter(c => !c.is_total && KT.isNum(c.ratio) && c.ratio < 1).forEach(c => items.push({ what: c.category + ': Kiribati records more than partners', nums: 'Partners ' + KT.fmtM(c.partners) + ' · Kiribati ' + KT.fmtM(c.kiribati) + (c.window ? ' · ' + fmtWindow(c.window) : ''), why: 'This runs the other way from fish, which shows the comparison is symmetric: either side can record more. Most likely buyers record the oil under a different code or partner after processing or transit.' }));
    (P.mirror_only_notable || []).forEach(m => items.push({ what: m.label + ' (' + (m.direction === 'export' ? 'export' : 'import') + ', HS ' + m.hs6 + ')', nums: 'Partners ' + KT.fmtM(m.partners) + ' · Kiribati ' + KT.fmtM(m.kiribati) + (m.window ? ' · ' + fmtWindow(m.window) : ''), why: (KT.isNum(m.n_partners) ? m.n_partners + ' partner' + (m.n_partners === 1 ? '' : 's') + ' recorded this line' + (KT.isNum(m.n_months) ? ' in ' + m.n_months + ' month' + (m.n_months === 1 ? '' : 's') : '') + '; ' : '') + 'Kiribati\'s records show little or none of it.' + (m.note ? ' ' + m.note : '') }));
    if (!items.length) { ul.appendChild(el('li', { class: 'empty', text: 'No notable differences listed.' })); return; }
    items.forEach(it => ul.appendChild(el('li', null, [el('span', { class: 'what', text: it.what }), el('span', { class: 'nums', text: it.nums }), el('span', { class: 'why', text: it.why })])));
  }

  function renderShips() {
    const P = D.products; const tbl = clear('ships-table'); const txt = Object.assign({}, DEFAULT_TEXT.charts.ships, (D.text && D.text.charts && D.text.charts.ships) || {});
    setText('ships-title', txt.title); setText('ships-lede', (txt.subtitle ? txt.subtitle + '. ' : '') + (txt.how_to_read || '')); setText('ships-caveat', txt.caveat);
    const rows = P && Array.isArray(P.ships_aircraft) ? P.ships_aircraft : [];
    if (!rows.length) { tbl.appendChild(el('caption', { class: 'empty', text: 'Not available.' })); return; }
    tbl.appendChild(el('thead', null, [el('tr', null, [el('th', { text: 'Year' }), el('th', { text: 'Sold by' }), el('th', { text: 'What' }), el('th', { text: 'Units', class: 'num' }), el('th', { text: 'USD m', class: 'num' })])]));
    const tb = el('tbody');
    rows.forEach(r => tb.appendChild(el('tr', null, [el('td', { text: String(r.year_label || r.year) }), el('td', { text: r.exporter }), el('td', { text: r.type }), el('td', { class: 'num', text: KT.isNum(r.units) ? String(r.units) : '—' }), el('td', { class: 'num', text: KT.fmtNum1(r.value) })])));
    tbl.appendChild(tb);
  }

  /* ---- 7. findings ---- */
  function renderFindings() {
    const wrap = clear('findings-cards'); const list = T('findings') || [];
    if (!list.length) { wrap.appendChild(el('p', { class: 'empty', text: 'Findings will appear here once the text file includes them.' })); return; }
    list.forEach(f => {
      const card = el('article', { class: 'finding', id: f.id ? 'finding-' + f.id : null }, [el('h3', { text: f.headline || '' }), el('p', { text: f.plain || '' })]);
      if (f.sensitivity) card.appendChild(el('p', { class: 'sens', text: f.sensitivity }));
      if (f.evidence) card.appendChild(el('p', { class: 'ev', text: 'Evidence: ' + f.evidence }));
      wrap.appendChild(card);
    });
  }

  /* ---- 8. footer ---- */
  function renderFooter() {
    const f = T('footer') || {};
    setText('footer-credit', f.credit || ''); setText('footer-disclaimer', f.disclaimer || '');
    if (D.manifest && D.manifest.meta) setText('footer-release', 'Comtrade data as retrieved on ' + KT.fmtDate(D.manifest.meta.generated_at) + '.');
  }

  /* everything that changes with Annual | Quarterly (or a Monthly chip) */
  function renderViewDependent() {
    renderHeader();
    renderCoverage();
    renderExports();
    renderImports();
    renderNationalAccounts();
  }
  function renderStatic() {
    renderIntro(); renderPanel(); renderRolling(); renderPeersTuna(); renderPeersTable(); renderProducts(); renderNotable(); renderShips(); renderFindings(); renderFooter();
  }

  /* ============================= 5. START-UP =========================== */
  function wireControls() {
    document.querySelectorAll('[data-view]').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
    document.querySelectorAll('[data-dir]').forEach(b => b.addEventListener('click', () => { state.productsDir = b.dataset.dir; document.querySelectorAll('[data-dir]').forEach(x => x.setAttribute('aria-pressed', String(x === b))); renderProducts(); }));
    const sel = document.getElementById('products-year'); if (sel) sel.addEventListener('change', () => { state.productsYear = sel.value; renderProducts(); });
    // re-render charts when the colour scheme flips so they pick up the new tokens
    try { matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { KT.applyDefaults(); renderViewDependent(); renderStatic(); }); } catch (e) { /* old browsers */ }
  }

  async function main() {
    KT.applyDefaults();
    wireControls();
    state.view = readInitialView();
    document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === state.view)));
    if (isFileProtocol()) {
      document.getElementById('file-notice').hidden = false;
      renderIntro(); renderFooter();
      ['chart-coverage', 'chart-exports', 'chart-imports', 'chart-rolling', 'chart-na-exports', 'chart-na-imports', 'chart-peers-tuna', 'chart-products'].forEach(id => KT.empty(id, 'Open the page from its web address to see this chart.'));
      return;
    }
    await loadAll();
    if (failed.length) {
      const box = document.getElementById('load-error'); box.hidden = false;
      setText('load-error-text', 'Missing or unreadable: ' + failed.map(f => f + '.json').join(', ') + '. The rest of the page is shown; the affected charts say so in place.');
    }
    renderViewDependent();
    renderStatic();
    if (!KT.hasChartJs()) {
      const box = document.getElementById('load-error'); box.hidden = false;
      setText('load-error-text', (document.getElementById('load-error-text').textContent + ' ').trim() + ' The chart library did not load (no internet or blocked CDN); every chart has a "Show as a table" twin with the same numbers.');
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', main); else main();
})();
