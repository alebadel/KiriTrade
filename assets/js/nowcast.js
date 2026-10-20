/* nowcast.js — renders nowcast.html from data/nowcast.json and data/series.json. Aggregates only. */
(function () {
  'use strict';
  const KT = window.KT;
  const $ = (id) => document.getElementById(id);
  const nf1 = new Intl.NumberFormat('en', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  function el(tag, text, attrs) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (attrs) Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); return e; }
  function getJSON(n) { return fetch('data/' + n, { cache: 'no-cache' }).then((r) => { if (!r.ok) throw new Error(n + ' (' + r.status + ')'); return r.json(); }); }
  const fmt = (v) => (KT.isNum(v) ? nf1.format(v) : '—');

  function stamp(nc) {
    const m = nc.meta;
    $('nc-strip-legend').textContent = 'Run of ' + m.run_date + '. ' + nc.ensemble.n_accepted + ' agent answers accepted' + (nc.ensemble.n_rejected ? ' (' + nc.ensemble.n_rejected + ' rejected by the checks)' : '') + '. Tier: ' + m.tier_label + '.';
  }
  function stats(nc) {
    const rows = nc.ensemble.months;
    const mean = (k) => rows.slice(0, 5).reduce((s, r) => s + r[k].mean, 0) / 5;
    const tot = mean('total'), a = mean('component_a');
    const box = $('nc-stats'); box.textContent = '';
    const add = (n, t) => { const d = el('div', null, { class: 'stat' }); d.appendChild(el('p', n, { class: 'stat-n' })); d.appendChild(el('p', t, { class: 'stat-t' })); box.appendChild(d); };
    add('USD ' + nf1.format(tot) + ' m', 'average per month, June to October 2026, agents’ average (baseline: USD ' + nf1.format(nc.baseline.nowcast.slice(0, 5).reduce((s, r) => s + r.point_usd_m, 0) / 5) + ' m)');
    add(Math.round(100 * a / tot) + '% / ' + Math.round(100 * (1 - a / tot)) + '%', 'average split between ' + nc.labels.component_a + ' and ' + nc.labels.component_b);
    const sd = rows.slice(0, 5).reduce((s, r) => s + r.total.sd, 0) / 5;
    add('USD ' + nf1.format(sd) + ' m', 'typical disagreement (one standard deviation) between agents on the monthly total');
  }
  function chartMain(nc, series) {
    const tk = KT.tokens();
    const hist = series.monthly.filter((r) => r.period >= '2023-01' && r.period <= '2026-07');
    const fut = nc.ensemble.months.map((r) => r.period);
    const labels = hist.map((r) => r.period).concat(fut.filter((p) => !hist.some((h) => h.period === p)));
    const pub = labels.map((p) => { const r = hist.find((h) => h.period === p); return r && KT.isNum(r.exports_partner_tuna) && p <= '2026-05' ? r.exports_partner_tuna : null; });
    const partial = labels.map((p) => { const r = hist.find((h) => h.period === p); return r && p > '2026-05' && KT.isNum(r.exports_partner_tuna) ? r.exports_partner_tuna : null; });
    const base = labels.map((p) => { const r = nc.baseline.nowcast.find((b) => b.period === p); return r ? r.point_usd_m : null; });
    const ag = labels.map((p) => { const r = nc.ensemble.months.find((b) => b.period === p); return r ? r.total.mean : null; });
    const p10 = labels.map((p) => { const r = nc.ensemble.months.find((b) => b.period === p); return r ? r.total.p10 : null; });
    const p90 = labels.map((p) => { const r = nc.ensemble.months.find((b) => b.period === p); return r ? r.total.p90 : null; });
    const ax = KT.axes({ monthlyDense: true, dense: true });
    ax.x.ticks.callback = function (v) { const p = this.getLabelForValue(v); return /-01$/.test(p) ? p.slice(0, 4) : ''; };
    KT.make('chart-nowcast', {
      type: 'bar',
      data: { labels, datasets: [
        { type: 'bar', label: 'Published', data: pub, backgroundColor: tk.partner, order: 3 },
        { type: 'bar', label: 'Partial (still being reported)', data: partial, backgroundColor: KT.withAlpha(tk.partner, tk.prelimAlpha), order: 3 },
        { type: 'line', label: 'Agents, 90th percentile', data: p90, borderColor: 'transparent', backgroundColor: KT.withAlpha(tk.kir, 0.18), pointRadius: 0, fill: '+1', order: 2, spanGaps: false },
        { type: 'line', label: 'Agents, 10th percentile', data: p10, borderColor: 'transparent', backgroundColor: 'transparent', pointRadius: 0, fill: false, order: 2, spanGaps: false },
        { type: 'line', label: 'Baseline', data: base, borderColor: tk.copra, backgroundColor: tk.copra, borderWidth: 2, borderDash: [5, 4], pointRadius: 3, order: 1, spanGaps: false },
        { type: 'line', label: 'Agents, average', data: ag, borderColor: tk.kir, backgroundColor: tk.kir, borderWidth: 2, pointRadius: 3, order: 0, spanGaps: false }
      ] },
      options: { scales: ax, interaction: { mode: 'index', intersect: false }, plugins: { tooltip: { callbacks: { title: (it) => KT.fmtPeriod(it[0].label), label: (c) => (c.parsed.y == null ? null : ' ' + c.dataset.label + ': ' + KT.fmtM(c.parsed.y)) } } } }
    });
    KT.legend('legend-nowcast', [
      { label: 'Published partner figures', color: tk.partner },
      { label: 'Partial months (lighter)', color: tk.partner, kind: 'light' },
      { label: 'Baseline', color: tk.copra, kind: 'line' },
      { label: 'Agents: average and 10th–90th percentile', color: tk.kir, kind: 'line' }
    ]);
    const rows = nc.ensemble.months.map((r, i) => ({ period: r.period, base: nc.baseline.nowcast.find((b) => b.period === r.period), r }));
    KT.table('table-nowcast', [
      { key: 'period', label: 'Month', fmt: (v) => KT.fmtPeriod(v) },
      { key: 'base', label: 'Baseline (USD m)', num: true, fmt: (v) => fmt(v && v.point_usd_m) },
      { key: 'r', label: 'Agents, average', num: true, fmt: (v) => fmt(v.total.mean) },
      { key: 'r', label: '10th pct', num: true, fmt: (v) => fmt(v.total.p10) },
      { key: 'r', label: '90th pct', num: true, fmt: (v) => fmt(v.total.p90) },
      { key: 'r', label: 'Std. dev. across agents', num: true, fmt: (v) => fmt(v.total.sd) }
    ], rows);
  }
  function chartSplit(nc) {
    const tk = KT.tokens(); const m = nc.ensemble.months; const labels = m.map((r) => r.period);
    const ax = KT.axes({ stacked: true });
    KT.make('chart-split', { type: 'bar',
      data: { labels, datasets: [
        { label: nc.labels.component_a, data: m.map((r) => r.component_a.mean), backgroundColor: tk.kir, stack: 's' },
        { label: nc.labels.component_b, data: m.map((r) => r.component_b.mean), backgroundColor: tk.other, stack: 's' } ] },
      options: { scales: ax, plugins: { tooltip: { callbacks: { title: (it) => KT.fmtPeriod(it[0].label), label: (c) => ' ' + c.dataset.label + ': ' + KT.fmtM(c.parsed.y) } } } } });
    KT.legend('legend-split', [{ label: nc.labels.component_a, color: tk.kir }, { label: nc.labels.component_b, color: tk.other }]);
    KT.table('table-split', [
      { key: 'period', label: 'Month', fmt: (v) => KT.fmtPeriod(v) },
      { key: 'a', label: nc.labels.component_a + ' (USD m)', num: true, fmt: fmt },
      { key: 'b', label: nc.labels.component_b + ' (USD m)', num: true, fmt: fmt },
      { key: 'sh', label: 'Share A: agents 10th–90th pct', num: true }
    ], m.map((r) => ({ period: r.period, a: r.component_a.mean, b: r.component_b.mean, sh: Math.round(100 * r.share_a.p10) + '%–' + Math.round(100 * r.share_a.p90) + '%' })));
  }
  function note(nc) {
    const n = nc.note;
    $('note-meta').textContent = n.date + ' · ' + n.title;
    const body = $('note-body'); body.textContent = '';
    n.paragraphs.forEach((p) => body.appendChild(el('p', p)));
    $('note-review').textContent = 'Checked against the statistics. ' + (n.review.history || '');
    const ul = $('note-archive'); ul.textContent = '';
    if (!nc.archive.length) ul.appendChild(el('li', 'None yet. This is the first run.'));
    nc.archive.forEach((a) => { const li = el('li'); li.appendChild(el('a', a.date, { href: a.path })); ul.appendChild(li); });
  }
  function principles(nc) {
    const ol = $('principle-list'); ol.textContent = '';
    nc.ensemble.principles.slice(0, 12).forEach((p) => { const li = el('li'); li.appendChild(el('span', p.statement + ' ')); li.appendChild(el('span', '(' + p.n_agents + ' of ' + nc.ensemble.n_accepted + ' agents)', { class: 'small muted' })); ol.appendChild(li); });
  }
  function start() {
    if (location.protocol === 'file:') { $('file-notice').hidden = false; return; }
    Promise.all([getJSON('nowcast.json'), getJSON('series.json'), getJSON('text.json').catch(() => null)]).then(([nc, series, text]) => {
      KT.applyDefaults();
      if (text && text.footer) { $('footer-credit').textContent = text.footer.credit || ''; $('footer-disclaimer').textContent = text.footer.disclaimer || ''; }
      stamp(nc); stats(nc); chartMain(nc, series); chartSplit(nc); note(nc); principles(nc);
    }).catch((err) => { $('load-error-text').textContent = 'The nowcast could not be loaded (' + err.message + ').'; $('load-error').hidden = false; });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
