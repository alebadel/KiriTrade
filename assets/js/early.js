/* early.js — the early estimate of the partner series, on the Partner data page.
   Reads data/nowcast.json, data/nowcast_baseline.json (via nowcast) and data/series.json. */
(function () {
  'use strict';
  const nf1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  function getJSON(n) { return fetch('data/' + n + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(n + ': ' + r.status); return r.json(); }); }
  function renderNowcast(nc, series) {
    const tk = KT.tokens();
    const lastPub = series.monthly.filter(r => KT.isNum(r.exports_partner_tuna) && r.pct_complete_w_exports >= 0.85).slice(-1)[0];
    const cut = lastPub ? lastPub.period : '2026-05';
    const hist = series.monthly.filter(r => r.period >= '2023-01');
    const fut = nc.ensemble.months.map(r => r.period);
    const labels = hist.map(r => r.period).concat(fut.filter(p => !hist.some(h => h.period === p)));
    const pub = labels.map(p => { const r = hist.find(h => h.period === p); return r && KT.isNum(r.exports_partner_tuna) && p <= cut ? r.exports_partner_tuna : null; });
    const partial = labels.map(p => { const r = hist.find(h => h.period === p); return r && p > cut && KT.isNum(r.exports_partner_tuna) ? r.exports_partner_tuna : null; });
    const base = labels.map(p => { const r = nc.baseline.nowcast.find(b => b.period === p); return r ? r.point_usd_m : null; });
    const ag = labels.map(p => { const r = nc.ensemble.months.find(b => b.period === p); return r ? r.total.mean : null; });
    const p10 = labels.map(p => { const r = nc.ensemble.months.find(b => b.period === p); return r ? r.total.p10 : null; });
    const p90 = labels.map(p => { const r = nc.ensemble.months.find(b => b.period === p); return r ? r.total.p90 : null; });
    const ax = KT.axes({ monthlyDense: true, dense: true });
    ax.x.ticks.callback = function (v) { const p = this.getLabelForValue(v); return /-01$/.test(p) ? p.slice(0, 4) : ''; };
    KT.make('chart-nowcast', { type: 'bar', data: { labels, datasets: [
      { type: 'bar', label: 'Published', data: pub, backgroundColor: tk.partner, order: 3 },
      { type: 'bar', label: 'Partial (still being reported)', data: partial, backgroundColor: KT.withAlpha(tk.partner, tk.prelimAlpha), order: 3 },
      { type: 'line', label: 'Agents, 90th percentile', data: p90, borderColor: 'transparent', backgroundColor: KT.withAlpha(tk.kir, 0.18), pointRadius: 0, fill: '+1', order: 2, spanGaps: false },
      { type: 'line', label: 'Agents, 10th percentile', data: p10, borderColor: 'transparent', backgroundColor: 'transparent', pointRadius: 0, fill: false, order: 2, spanGaps: false },
      { type: 'line', label: 'Baseline', data: base, borderColor: tk.copra, backgroundColor: tk.copra, borderWidth: 2, borderDash: [5, 4], pointRadius: 3, order: 1, spanGaps: false },
      { type: 'line', label: 'Agents, average', data: ag, borderColor: tk.kir, backgroundColor: tk.kir, borderWidth: 2, pointRadius: 3, order: 0, spanGaps: false }
    ] }, options: { scales: ax, interaction: { mode: 'index', intersect: false }, plugins: { tooltip: { callbacks: { title: it => KT.fmtPeriod(it[0].label), label: c => (c.parsed.y == null ? null : ' ' + c.dataset.label + ': ' + KT.fmtM(c.parsed.y)) } } } } });
    KT.legend('legend-nowcast', [{ label: 'Published partner figures', color: tk.partner }, { label: 'Partial months', color: tk.partner, kind: 'light' }, { label: 'Baseline', color: tk.copra, kind: 'dash' }, { label: 'Agents, average', color: tk.kir, kind: 'line' }, { label: 'Agents, 10th to 90th percentile (band)', color: KT.withAlpha(tk.kir, 0.25) }]);
    setText('src-nowcast', 'Source: UN Comtrade partner returns; the tracker’s baseline (tracker/README.md) and agent run of ' + nc.meta.run_date + ' (' + nc.ensemble.n_accepted + ' agents, flag-basis total only).');
    KT.table('table-nowcast', [{ key: 'period', label: 'Month', fmt: v => KT.fmtPeriod(v) }, { key: 'base', label: 'Baseline', num: true, fmt: v => KT.isNum(v) ? nf1.format(v) : '—' }, { key: 'mean', label: 'Agents, average', num: true, fmt: nf1.format }, { key: 'p10', label: '10th pct', num: true, fmt: nf1.format }, { key: 'p90', label: '90th pct', num: true, fmt: nf1.format }],
      nc.ensemble.months.map(r => ({ period: r.period, base: (nc.baseline.nowcast.find(b => b.period === r.period) || {}).point_usd_m, mean: r.total.mean, p10: r.total.p10, p90: r.total.p90 })));
  }

  function start() {
    if (location.protocol === 'file:') return;
    Promise.all([getJSON('nowcast').catch(() => null), getJSON('series')]).then(([nc, series]) => {
      if (nc) renderNowcast(nc, series); else KT.empty('chart-nowcast', 'No early estimate has been published for this run.');
    }).catch(err => console.warn(err));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
