/* =====================================================================
   home.js — renders index.html: the two headline numbers, the five input
   cards, the run log, the waterfall and the three-records chart.
   Reads data/*.json only; writes numbers into the page with textContent.
   Needs charts.js (KT) and waterfall.js (KT.waterfall).
   ===================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const FILES = ['manifest', 'series', 'fleet', 'registry', 'national_accounts', 'corpus', 'inference', 'runs', 'text'];
  const D = {};

  function getJSON(name) {
    return fetch('data/' + name + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(name + ': ' + r.status); return r.json(); });
  }
  function setText(id, text) { const e = $(id); if (e) e.textContent = text == null ? '' : String(text); }
  function fill(key, text) { document.querySelectorAll('[data-fill="' + key + '"]').forEach(n => { n.textContent = text; }); }
  function show(id, on) { const e = $(id); if (e) e.hidden = !on; }
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v); });
    (children || []).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return e;
  }

  /* ---------- header ---------- */
  function renderHeader() {
    const m = D.manifest && D.manifest.meta ? D.manifest.meta : (D.manifest || {});
    const when = m.generated_at || (D.series && D.series.meta && D.series.meta.generated_at);
    const parts = ['Partner data retrieved ' + KT.fmtDate(when)];
    if (D.fleet && D.fleet.meta && D.fleet.meta.ais_through) parts.push('ship tracking through ' + KT.fmtDate(D.fleet.meta.ais_through + 'T00:00:00Z'));
    if (D.inference && D.inference.meta) parts.push('agents run ' + KT.fmtDate(D.inference.meta.run_date + 'T00:00:00Z'));
    const txt = parts.join(' \u00b7 ');
    setText('updated-hero', txt);
    const b = $('updated-badge'); if (b) b.lastElementChild.textContent = txt;
    // two numbers: latest complete year with 12 months of partner tuna, and BOP goods exports for that year
    const ann = (D.series.annual || []).filter(r => r.months_with_fish_data === 12 && KT.isNum(r.exports_partner_tuna));
    const last = ann[ann.length - 1];
    if (last) { setText('n-mirror', nf1.format(last.exports_partner_tuna)); setText('n-mirror-year', last.period); }
    const na = (D.national_accounts.annual || []).filter(r => KT.isNum(r.bop_goods_exports));
    const lastNa = last ? na.find(r => String(r.year) === String(last.period)) || na[na.length - 1] : na[na.length - 1];
    if (lastNa) {
      setText('n-bop', nf1.format(lastNa.bop_goods_exports)); setText('n-bop-year', lastNa.year);
      setText('n-bop-est', lastNa.gdp_is_estimate || (D.national_accounts.meta && /2025 BOP/.test((D.national_accounts.meta.notes || []).join(' ')) && lastNa.year === 2025) ? ' (compiler’s estimate)' : '');
    }
    if (D.text && D.text.footer) { setText('footer-credit', D.text.footer.credit); setText('footer-disclaimer', D.text.footer.disclaimer); }
    setText('footer-release', when ? 'Data files generated ' + KT.fmtDate(when) + '.' : '');
  }

  /* ---------- question paragraph ---------- */
  function renderQuestion() {
    const r = D.registry;
    if (!r) return;
    let withAddr = 0, total = r.meta.n_vessels;
    Object.values(r.by_flag_address_hint).forEach(f => Object.entries(f).forEach(([k, v]) => { if (!/No usable/.test(k)) withAddr += v; }));
    const share = withAddr / total;
    fill('addr-share', (share < 0.5 ? 'fewer than half' : share < 0.67 ? 'about half' : 'most') + ' (' + withAddr + ' of ' + total + ')');
    fill('rfv-date', KT.fmtDate(r.meta.register_export_date + 'T00:00:00Z'));
  }

  /* ---------- card 1: Comtrade ---------- */
  function cardComtrade() {
    const t = KT.tokens();
    const rows = (D.series.annual || []).filter(r => +r.period >= 2017 && KT.isNum(r.exports_partner_tuna));
    const labels = rows.map(r => r.period + (r.months_with_fish_data < 12 ? '*' : ''));
    KT.legend('legend-card-comtrade', [
      { label: 'Partner-reported tuna (flag basis)', color: t.partner },
      { label: 'Kiribati-reported exports, all goods, months published', color: t.kir, kind: 'line' }
    ]);
    KT.make('chart-card-comtrade', { type: 'bar', data: { labels, datasets: [
      { type: 'bar', label: 'Partner-reported tuna', data: rows.map(r => r.exports_partner_tuna), backgroundColor: rows.map(r => r.months_with_fish_data < 12 ? KT.withAlpha(t.partner, t.prelimAlpha) : t.partner), maxBarThickness: 28 },
      { type: 'line', label: 'Kiribati-reported exports', data: rows.map(r => KT.isNum(r.exports_kiribati) ? r.exports_kiribati : null), borderColor: t.kir, backgroundColor: t.kir, pointRadius: 3.5, spanGaps: false }
    ] }, options: { plugins: { tooltip: { callbacks: { label: KT.moneyLabel, footer: items => rows[items[0].dataIndex].months_with_fish_data < 12 ? '* year not complete' : '' } } }, scales: KT.axes({ unit: 'USD m' }) } });
  }

  /* ---------- card 2: fleet ---------- */
  function cardFleet() {
    const t = KT.tokens();
    const ys = {};
    D.fleet.monthly.forEach(m => { const y = m.period.slice(0, 4); ys[y] = (ys[y] || 0) + m.kir_hours_total; });
    const thisY = D.fleet.monthly[D.fleet.monthly.length - 1].period.slice(0, 4);
    const years = Object.keys(ys).filter(y => +y >= 2017).sort();
    KT.legend('legend-card-fleet', [{ label: 'Hours spent fishing, Kiribati-flagged vessels (effort, not catch)', color: t.kir }]);
    KT.make('chart-card-fleet', { type: 'bar', data: { labels: years.map(y => y + (y === thisY ? '*' : '')), datasets: [{ label: 'Fishing hours', data: years.map(y => Math.round(ys[y])), backgroundColor: years.map(y => y === thisY ? KT.withAlpha(t.kir, t.prelimAlpha) : t.kir), maxBarThickness: 28 }] },
      options: { plugins: { tooltip: { callbacks: { label: ctx => ' ' + nf0.format(ctx.parsed.y) + ' hours', footer: items => years[items[0].dataIndex] === thisY ? '* year to ' + KT.fmtPeriod(D.fleet.monthly[D.fleet.monthly.length - 1].period) : '' } } },
        scales: { x: { grid: { display: false }, border: { color: t.axis } }, y: { beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 5, callback: v => nf0.format(v) }, title: { display: true, text: 'hours', color: t.muted, font: { size: 11 } } } } } });
  }

  /* ---------- card 3: registry ---------- */
  function cardRegistry() {
    const t = KT.tokens();
    const r = D.registry;
    const flags = Object.keys(r.by_flag_type_group);
    const groups = ['Purse seiners', 'Longliners', 'Carriers', 'Bunkers', 'Other fishing vessels'];
    const colors = [t.partner, t.fish, t.kir, t.copra, t.other];
    KT.legend('legend-card-registry', groups.map((g, i) => ({ label: g, color: colors[i] })));
    KT.make('chart-card-registry', { type: 'bar', data: { labels: flags, datasets: groups.map((g, i) => ({ label: g, data: flags.map(f => r.by_flag_type_group[f][g] || 0), backgroundColor: colors[i], maxBarThickness: 40 })) },
      options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: ctx => ' ' + ctx.dataset.label + ': ' + ctx.parsed.x + ' vessels' } } },
        scales: { x: { stacked: true, beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 6 }, title: { display: true, text: 'vessels on the register (export of ' + KT.fmtDate(r.meta.register_export_date + 'T00:00:00Z') + ')', color: t.muted, font: { size: 11 } } }, y: { stacked: true, grid: { display: false }, border: { color: t.axis } } } } });
  }

  /* ---------- card 4: official ---------- */
  function cardOfficial() {
    const t = KT.tokens();
    const rows = (D.national_accounts.annual || []).filter(r => r.year >= 2010 && KT.isNum(r.bop_goods_exports));
    const isEst = r => r.gdp_is_estimate === true || r.year === 2025;
    KT.legend('legend-card-official', [{ label: 'Balance of payments: goods exports, all goods', color: t.kir }, { label: 'Latest year: compiler’s estimate', color: t.kir, kind: 'hatch' }]);
    KT.make('chart-card-official', { type: 'bar', data: { labels: rows.map(r => String(r.year)), datasets: [{ label: 'BOP goods exports', data: rows.map(r => r.bop_goods_exports), backgroundColor: rows.map(r => isEst(r) ? KT.hatch(t.kir) : t.kir), borderColor: t.kir, borderWidth: rows.map(r => isEst(r) ? 1 : 0), maxBarThickness: 28 }] },
      options: { plugins: { tooltip: { callbacks: { label: KT.moneyLabel } } }, scales: KT.axes({ unit: 'USD m' }) } });
  }

  /* ---------- card 5: documents (the knowledge base growing) ---------- */
  function cardDocuments() {
    const t = KT.tokens();
    const c = D.corpus;
    const order = c.meta.type_order;
    const SHORT = { standards: 'Manuals and standards', customs: 'Customs rules', datadoc: 'Data documentation', academic: 'Academic papers', imf: 'IMF and official reports', notes: 'Project briefs', news: 'News' };
    const colors = { standards: t.kir, customs: t.partner, datadoc: t.count, academic: t.fish, imf: t.copra, notes: t.other, news: t.peer };
    fill('corpus-count', nf0.format(c.meta.n_documents) + ' documents, ' + nf1.format(c.meta.n_words / 1e6) + ' million words today.');
    const g = c.growth || [];
    if (!g.length) { KT.empty('chart-card-documents', 'No dated documents yet.'); return; }
    // extend the last point to today so the chart reads as a level that persists
    const rows = g.slice();
    const today = new Date().toISOString().slice(0, 10);
    if (rows[rows.length - 1].date < today) rows.push(Object.assign({}, rows[rows.length - 1], { date: today, extended: true }));
    const labels = rows.map(r => KT.fmtDate(r.date + 'T00:00:00Z'));
    const used = order.filter(k => rows.some(r => r[k] > 0) || k === 'news');
    KT.legend('legend-card-documents', used.map(k => ({ label: SHORT[k], color: colors[k] })));
    KT.make('chart-card-documents', { type: 'bar', data: { labels, datasets: used.map(k => ({ label: SHORT[k], data: rows.map(r => r[k]), backgroundColor: colors[k], stack: 'w', maxBarThickness: 34 })) },
      options: { plugins: { tooltip: { callbacks: { title: items => (rows[items[0].dataIndex].extended ? 'Today: ' : 'Added by ') + items[0].label, label: ctx => ' ' + ctx.dataset.label + ': ' + nf0.format(ctx.parsed.y) + ' words (' + rows[ctx.dataIndex][order.find(k => SHORT[k] === ctx.dataset.label) + '_docs'] + ' documents)' } } },
        scales: { x: { stacked: true, grid: { display: false }, border: { color: t.axis }, ticks: { maxRotation: 0, autoSkip: true, font: { size: 10 } } }, y: { stacked: true, beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 5, callback: v => v >= 1e6 ? (v / 1e6) + ' m' : v >= 1000 ? (v / 1000) + ' k' : v }, title: { display: true, text: 'words held (cumulative)', color: t.muted, font: { size: 11 } } } } } });
  }

  /* ---------- run log ---------- */
  function renderRuns() {
    const t = KT.tokens();
    const runs = (D.runs && D.runs.runs) || [];
    if (!runs.length) { KT.empty('chart-runs', 'No runs recorded yet.'); return; }
    const labels = runs.map(r => KT.fmtDate(r.date + 'T00:00:00Z') + (runs.filter(x => x.date === r.date).length > 1 ? ' (' + r.id + ')' : ''));
    KT.make('chart-runs', { type: 'bar', data: { labels, datasets: [{ label: 'Agents', data: runs.map(r => r.n_agents), backgroundColor: runs.map(r => r.superseded ? KT.withAlpha(t.count, t.prelimAlpha) : t.kir), maxBarThickness: 48 }] },
      options: { plugins: { tooltip: { callbacks: { title: items => runs[items[0].dataIndex].label, label: ctx => ' ' + ctx.parsed.y + ' agents', footer: items => { const r = runs[items[0].dataIndex]; return [r.question, 'Inputs: ' + r.inputs.join(', '), r.superseded ? 'Superseded by a later run' : 'Current'].join('\n'); } } } },
        scales: { x: { grid: { display: false }, border: { color: t.axis }, ticks: { autoSkip: false, maxRotation: 0, font: { size: 11 } } }, y: { beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 5, precision: 0 }, title: { display: true, text: 'agents', color: t.muted, font: { size: 11 } } } } } });
    setText('runs-src', 'Source: the tracker’s run log (data/runs.json). Lighter bars: runs superseded by a later run on the same question.');
    KT.table('table-runs', [{ key: 'date', label: 'Date' }, { key: 'id', label: 'Run' }, { key: 'label', label: 'What' }, { key: 'n_agents', label: 'Agents', num: true }, { key: 'inputs', label: 'Inputs', fmt: v => v.join(', ') }, { key: 'status', label: 'Status' }], runs);
  }

  /* ---------- waterfall with period selector ---------- */
  function bridgeFor(period) {
    const inf = D.inference;
    const p = inf.periods.find(x => x.period === period);
    const defs = inf.layers;
    return {
      start: { label: 'Raw partner\nfigure (CIF)', value: p.start.value },
      steps: p.layers.map(l => { const d = defs.find(x => x.id === l.id); return { label: d.short, mean: l.mean, p10: l.p10, p90: l.p90 }; }),
      end: { label: 'Estimated\ntrue exports', mean: p.end.mean, p10: p.end.p10, p90: p.end.p90, values: p.end.values }
    };
  }
  function renderWaterfall() {
    const inf = D.inference;
    if (!inf || !inf.periods || !inf.periods.length) { KT.empty('chart-waterfall', 'No agent run has been aggregated yet.'); return; }
    const t = KT.tokens();
    const sel = $('wf-period');
    sel.textContent = '';
    inf.periods.forEach(p => sel.appendChild(el('option', { value: p.period, text: p.period })));
    sel.value = inf.periods[inf.periods.length - 1].period;
    KT.legend('legend-waterfall', [{ label: 'Removed from the partner figure', color: t.partner }, { label: 'Added to it', color: t.fish }, { label: 'Start and end', color: t.kir }, { label: 'Agents, 10th to 90th percentile', color: t.ink, kind: 'line' }]);
    if (inf.meta.agent && inf.meta.agent.model) fill('agent-def', 'Each agent is one fresh session of a large language model (' + inf.meta.agent.model + ', ' + inf.meta.agent.effort + '), with no memory of the other sessions, given the evidence files and the instructions and allowed to read nothing else.');
    const draw = () => {
      const period = sel.value;
      const p = inf.periods.find(x => x.period === period);
      setText('wf-sub', 'USD millions, calendar ' + period + '; mean of ' + inf.meta.n_agents + ' agents');
      KT.waterfall('chart-waterfall', bridgeFor(period), { labelSize: 14 });
      setText('wf-src', 'Source: UN Comtrade partner returns (start value, sum of monthly returns for ' + period + '); the tracker’s agent run ' + inf.meta.run_id + ' of ' + KT.fmtDate(inf.meta.run_date + 'T00:00:00Z') + ' (data/inference.json). The agents saw the partner series, fleet aggregates, the vessel-register hints, the standards texts and Kiribati’s official statistics.');
      KT.bridgeNarrative('wf-narrative', inf, period);
    };
    sel.addEventListener('change', draw);
    draw();
  }

  /* ---------- the three records by year ---------- */
  function renderSeries() {
    const t = KT.tokens();
    const inf = D.inference;
    const years = [];
    for (let y = 2017; y <= 2025; y++) years.push(String(y));
    const mirror = years.map(y => { const r = (D.series.annual || []).find(x => x.period === y); return r && r.months_with_fish_data === 12 ? r.exports_partner_tuna : null; });
    const bop = years.map(y => { const r = (D.national_accounts.annual || []).find(x => String(x.year) === y); return r ? r.bop_goods_exports : null; });
    const est = years.map(y => { const p = inf && inf.periods.find(x => x.period === y); return p ? p.end.mean : null; });
    const lo = years.map(y => { const p = inf && inf.periods.find(x => x.period === y); return p ? p.end.p10 : null; });
    const hi = years.map(y => { const p = inf && inf.periods.find(x => x.period === y); return p ? p.end.p90 : null; });
    KT.legend('legend-series', [{ label: 'Partner-reported tuna (flag basis)', color: t.partner, kind: 'line' }, { label: 'Agents’ estimate of true tuna exports (mean)', color: t.kir, kind: 'line' }, { label: 'Agents, 10th to 90th percentile', color: KT.withAlpha(t.kir, 0.25) }, { label: 'Balance of payments: goods exports, all goods (official)', color: t.ink, kind: 'dash' }]);
    KT.make('chart-series', { type: 'line', data: { labels: years, datasets: [
      { label: 'Partner-reported tuna', data: mirror, borderColor: t.partner, backgroundColor: t.partner, spanGaps: true },
      { label: 'Agents: 90th percentile', data: hi, borderColor: 'transparent', backgroundColor: KT.withAlpha(t.kir, 0.2), pointRadius: 0, fill: '+1', spanGaps: false },
      { label: 'Agents: 10th percentile', data: lo, borderColor: 'transparent', backgroundColor: KT.withAlpha(t.kir, 0.2), pointRadius: 0, fill: false, spanGaps: false },
      { label: 'Agents’ estimate of true exports', data: est, borderColor: t.kir, backgroundColor: t.kir, spanGaps: false },
      { label: 'Balance of payments goods exports (official)', data: bop, borderColor: t.ink, backgroundColor: t.ink, borderDash: [4, 4], spanGaps: true }
    ] }, options: { plugins: { tooltip: { callbacks: { label: ctx => /percentile/.test(ctx.dataset.label) ? null : KT.moneyLabel(ctx) } } }, scales: KT.axes({ unit: 'USD m' }) } });
    KT.table('table-series', [{ key: 'year', label: 'Year' }, { key: 'mirror', label: 'Partner-reported tuna', num: true, fmt: KT.fmtNum1 }, { key: 'est', label: 'Agents’ estimate (mean)', num: true, fmt: KT.fmtNum1 }, { key: 'lo', label: '10th pct', num: true, fmt: KT.fmtNum1 }, { key: 'hi', label: '90th pct', num: true, fmt: KT.fmtNum1 }, { key: 'bop', label: 'BOP goods exports (official)', num: true, fmt: KT.fmtNum1 }],
      years.map((y, i) => ({ year: y, mirror: mirror[i], est: est[i], lo: lo[i], hi: hi[i], bop: bop[i] })).reverse());
  }

  /* ---------- validation box (empty until the panel exists) ---------- */
  function renderValidation() {
    const t = KT.tokens();
    KT.legend('legend-validation', [{ label: 'One country-year (none yet)', color: t.kir }, { label: 'Diagonal: prediction equals the published figure', color: t.muted, kind: 'dash' }]);
    KT.empty('chart-validation', 'No panel countries yet. The chart fills as hold-out cases are scored.');
  }

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.allSettled(FILES.map(n => getJSON(n).then(d => [n, d]))).then(res => {
      const failed = [];
      res.forEach((r, i) => { if (r.status === 'fulfilled') D[r.value[0]] = r.value[1]; else failed.push(FILES[i]); });
      if (failed.length) { setText('load-error-text', 'Could not load: ' + failed.join(', ') + '. Reload the page; if it persists, the data files may be mid-update.'); show('load-error', true); }
      KT.applyDefaults();
      try { renderHeader(); } catch (e) { console.warn(e); }
      try { renderQuestion(); } catch (e) { console.warn(e); }
      if (D.series) cardComtrade();
      if (D.fleet) cardFleet();
      if (D.registry) cardRegistry();
      if (D.national_accounts) cardOfficial();
      if (D.corpus) cardDocuments();
      renderRuns();
      renderWaterfall();
      if (D.series && D.national_accounts) renderSeries();
      renderValidation();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
