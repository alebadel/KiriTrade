/* inference.js — renders inference.html from data/inference.json, data/nowcast.json and data/series.json. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const nf1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function setText(id, t) { const e = $(id); if (e) e.textContent = t == null ? '' : String(t); }
  function show(id, on) { const e = $(id); if (e) e.hidden = !on; }
  function getJSON(n) { return fetch('data/' + n + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(n + ': ' + r.status); return r.json(); }); }
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v); });
    (children || []).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return e;
  }
  const sgn = v => (v > 0 ? '+' : v < 0 ? '−' : '') + nf1.format(Math.abs(v));

  function renderMethod(inf) {
    const m = inf.meta;
    setText('in-strip', 'Run ' + m.run_id + ' of ' + KT.fmtDate(m.run_date + 'T00:00:00Z') + ': ' + m.n_agents + ' agent answers accepted' + (m.n_rejected ? ', ' + m.n_rejected + ' rejected by the checks' : '') + '. Years: ' + inf.periods.map(p => p.period).join(', ') + '. Evidence: ' + m.evidence.join('; ') + '.');
    const ol = $('layer-list'); ol.textContent = '';
    inf.layers.forEach(l => ol.appendChild(el('li', null, [el('strong', { text: l.label + '. ' }), l.description])));
  }

  function renderBridges(inf) {
    const t = KT.tokens();
    const box = $('bridge-figures'); box.textContent = '';
    inf.periods.slice().reverse().forEach(p => {
      const id = 'chart-bridge-' + p.period;
      const fig = el('figure', { class: 'fig' }, [
        el('div', { class: 'fig-head' }, [el('div', null, [el('h3', { text: 'Calendar ' + p.period }), el('p', { class: 'sub', text: 'From ' + nf2.format(p.start.value) + ' recorded by importers to an estimated ' + nf2.format(p.end.mean) + ' (agents’ 10th to 90th percentile ' + nf1.format(p.end.p10) + ' to ' + nf1.format(p.end.p90) + '), USD millions' })])]),
        el('div', { class: 'legend', id: 'legend-' + id }),
        el('div', { class: 'plot tall' }, [el('canvas', { id, role: 'img', 'aria-label': 'Waterfall from the raw partner figure to the agents’ estimate for ' + p.period })]),
        el('figcaption', null, [el('p', { class: 'src', text: 'Source: UN Comtrade partner returns (start value); the tracker’s agent run ' + inf.meta.run_id + '. ' + (p.official && KT.isNum(p.official.bop_goods_exports) ? 'For reference, the official balance-of-payments goods exports (all goods) for ' + p.period + ' were USD ' + nf1.format(p.official.bop_goods_exports) + ' m.' : '') })]),
        el('details', { class: 'narr' }, [el('summary', { text: 'The experts\u2019 narrative for ' + p.period + ': five points, then the arguments layer by layer' }), el('div', { class: 'narr-body', id: 'narr-' + p.period })])
      ]);
      box.appendChild(fig);
      KT.legend('legend-' + id, [{ label: 'Removed', color: t.partner }, { label: 'Added', color: t.fish }, { label: 'Start and end', color: t.kir }, { label: 'Agents, 10th to 90th percentile', color: t.ink, kind: 'line' }]);
      KT.waterfall(id, {
        start: { label: 'Raw partner\nfigure (CIF)', value: p.start.value },
        steps: p.layers.map(l => { const d = inf.layers.find(x => x.id === l.id); return { label: d.short, mean: l.mean, p10: l.p10, p90: l.p90 }; }),
        end: { label: 'Estimated\ntrue exports', mean: p.end.mean, p10: p.end.p10, p90: p.end.p90, values: p.end.values }
      }, { labelSize: 14 });
      KT.bridgeNarrative('narr-' + p.period, inf, p.period);
    });
    // table
    const cols = [{ key: 'label', label: 'Step' }];
    inf.periods.forEach(p => { cols.push({ key: 'm' + p.period, label: p.period + ' mean', num: true, fmt: v => KT.isNum(v) ? nf2.format(v) : '—' }); cols.push({ key: 'r' + p.period, label: p.period + ' 10th–90th', num: true }); });
    const rows = [];
    const row = (label, get, signed, dec) => { const f = v => signed ? sgn(v) : (dec === 2 ? nf2.format(v) : nf1.format(v)); const r = { label }; inf.periods.forEach(p => { const x = get(p); r['m' + p.period] = x.mean; r['r' + p.period] = KT.isNum(x.p10) ? f(x.p10) + ' to ' + f(x.p90) : ''; }); rows.push(r); };
    row('Raw partner figure (CIF)', p => ({ mean: p.start.value }), false, 1);
    inf.layers.forEach((l, i) => row(l.label, p => p.layers[i], true));
    row('Estimated true exports', p => p.end, false, 1);
    row('Estimate as a share of the partner figure', p => ({ mean: p.share_of_start.mean, p10: p.share_of_start.p10, p90: p.share_of_start.p90 }), false, 2);
    KT.table('table-layers', cols, rows);
    setText('src-layers', 'Source: data/inference.json, run ' + inf.meta.run_id + '. Layer ranges are the 10th and 90th percentiles of the signed layer across agents.');
  }

  function renderNotes(inf) {
    const ol = $('official-use-list'); ol.textContent = '';
    inf.official_use.forEach(o => ol.appendChild(el('li', null, [o.text + ' ', el('span', { class: 'meta', text: '(' + o.agent.replace('draw_', 'agent ') + ')' })])));
    const tl = $('theme-list'); tl.textContent = '';
    if (inf.principle_themes && inf.principle_themes.length) {
      inf.principle_themes.forEach(th => tl.appendChild(el('li', null, [th.statement + ' ', el('span', { class: 'meta', text: '(' + th.n_agents + ' of ' + inf.meta.n_agents + ' agents)' })])));
    } else {
      tl.appendChild(el('li', { text: 'Themes have not been summarised for this run; the full list is below.' }));
    }
    const pl = $('principle-list'); pl.textContent = '';
    inf.principles.forEach(p => pl.appendChild(el('li', null, [el('strong', { text: p.agent.replace('draw_', 'Agent ') + ', ' + p.id + '. ' }), p.statement + ' ', el('span', { class: 'meta', text: 'Source: ' + (p.source || '') + '. Uncertainty: ' + (p.uncertainty || '') })])));
  }

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
    KT.legend('legend-nowcast', [{ label: 'Published partner figures', color: tk.partner }, { label: 'Partial months', color: tk.partner, kind: 'light' }, { label: 'Baseline', color: tk.copra, kind: 'dash' }, { label: 'Agents: average and 10th–90th percentile', color: tk.kir, kind: 'line' }]);
    setText('src-nowcast', 'Source: UN Comtrade partner returns; the tracker’s baseline (tracker/README.md) and agent run of ' + nc.meta.run_date + ' (' + nc.ensemble.n_accepted + ' agents, flag-basis total only).');
    KT.table('table-nowcast', [{ key: 'period', label: 'Month', fmt: v => KT.fmtPeriod(v) }, { key: 'base', label: 'Baseline', num: true, fmt: v => KT.isNum(v) ? nf1.format(v) : '—' }, { key: 'mean', label: 'Agents, average', num: true, fmt: nf1.format }, { key: 'p10', label: '10th pct', num: true, fmt: nf1.format }, { key: 'p90', label: '90th pct', num: true, fmt: nf1.format }],
      nc.ensemble.months.map(r => ({ period: r.period, base: (nc.baseline.nowcast.find(b => b.period === r.period) || {}).point_usd_m, mean: r.total.mean, p10: r.total.p10, p90: r.total.p90 })));
  }

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([getJSON('inference'), getJSON('nowcast').catch(() => null), getJSON('series'), getJSON('text').catch(() => null)]).then(([inf, nc, series, text]) => {
      KT.applyDefaults();
      if (text && text.footer) { setText('footer-credit', text.footer.credit); setText('footer-disclaimer', text.footer.disclaimer); }
      renderMethod(inf); renderBridges(inf); renderNotes(inf);
      if (nc) renderNowcast(nc, series); else { KT.empty('chart-nowcast', 'No early estimate has been published for this run.'); }
    }).catch(err => { setText('load-error-text', 'The inference data could not be loaded (' + err.message + ').'); show('load-error', true); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
