/* inference.js — renders inference.html from data/inference.json, data/nowcast.json and data/series.json. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
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
    const ans = $('in-answer');
    if (ans && inf.periods.length) {
      const parts = inf.periods.map(p => p.period + ': about USD ' + Math.round(p.end.mean) + ' million (middle 80% of agents ' + Math.round(p.end.p10) + ' to ' + Math.round(p.end.p90) + ')');
      ans.textContent = 'Tuna sold abroad by Kiribati residents, as ' + m.n_agents + ' AI agents estimate it from the five inputs. ' + parts.join('; ') + '. Importers recorded ' + inf.periods.map(p => Math.round(p.start.value)).join(', ') + ' for the same years on the flag basis.';
    }
    setText('in-strip', 'Run ' + m.run_id + ' of ' + KT.fmtDate(m.run_date + 'T00:00:00Z') + ': ' + m.n_agents + ' agent answers accepted' + (m.n_rejected ? ', ' + m.n_rejected + ' rejected by the checks' : '') + '. Years: ' + inf.periods.map(p => p.period).join(', ') + '. Evidence: partner returns, ship-tracking summaries, vessel-register hints, statistical standards and Kiribati official statistics.');
    const ol = $('layer-list'); ol.textContent = '';
    inf.layers.forEach(l => ol.appendChild(el('li', null, [el('strong', { text: l.label + '. ' }), l.description])));
  }

  function thinNote(p) {
    const thin = p.layers.filter(l => Math.abs(l.mean) < 0.01 * p.start.value).map(l => inf_layer_short(l.id));
    return thin.length ? (thin.length === 1 ? 'One layer (' + thin[0] + ') is under 1% of the start and too thin to see; read its label.' : thin.length + ' layers (' + thin.join('; ') + ') are under 1% of the start and too thin to see; read their labels.') : '';
  }
  let inf_layer_short = id => id;
  function renderBridges(inf) {
    const t = KT.tokens();
    inf_layer_short = id => { const d = inf.layers.find(x => x.id === id); return d ? d.label.replace(/^(Less|Add|Adjust|Other):\s*/, '') : id; };
    const box = $('bridge-figures'); box.textContent = '';
    inf.periods.slice().forEach(p => {
      const id = 'chart-bridge-' + p.period;
      const fig = el('figure', { class: 'fig' }, [
        el('div', { class: 'fig-head' }, [el('div', null, [el('h3', { text: 'Calendar ' + p.period }), el('p', { class: 'sub', text: 'From ' + nf2.format(p.start.value) + ' recorded by importers to an estimated ' + nf2.format(p.end.mean) + ' (agents’ 10th to 90th percentile ' + nf1.format(p.end.p10) + ' to ' + nf1.format(p.end.p90) + '), USD millions' })])]),
        el('div', { class: 'legend', id: 'legend-' + id }),
        el('div', { class: 'plot tall' }, [el('canvas', { id, role: 'img', 'aria-label': 'Waterfall from the raw partner figure to the agents’ estimate for ' + p.period })]),
        el('figcaption', null, [
          el('p', { class: 'how', text: 'Each bar is the average step across the ' + inf.meta.n_agents + ' agents; the whisker is where the middle 80% of agents fall; each dot beside the last bar is one agent’s total. ' + thinNote(p) }),
          el('p', { class: 'src', text: 'Source: UN Comtrade partner returns (start value); the tracker’s agent run ' + inf.meta.run_id + '. ' + (p.official && KT.isNum(p.official.bop_goods_exports) ? 'For reference, the official balance-of-payments goods exports (all goods) for ' + p.period + ' were USD ' + nf1.format(p.official.bop_goods_exports) + ' m.' : '') })]),
        el('details', { class: 'tbl' }, [el('summary', { text: 'Show this year as a table' }), el('div', { class: 'scroll', id: 'table-bridge-' + p.period })]),
        el('details', { class: 'narr' }, [el('summary', { text: 'The experts\u2019 narrative for ' + p.period + ': five points, then the arguments layer by layer' }), el('div', { class: 'narr-body', id: 'narr-' + p.period })])
      ]);
      box.appendChild(fig);
      KT.legend('legend-' + id, [{ label: 'Removed', color: t.partner }, { label: 'Added', color: t.fish }, { label: 'Start and end', color: t.ink2 }, { label: 'Whisker: 10th to 90th percentile across agents', color: t.ink, kind: 'line' }, { label: 'Dot: one agent’s estimate', color: t.ink2 }]);
      KT.waterfall(id, {
        start: { label: 'Raw partner\nfigure (CIF)', value: p.start.value },
        steps: p.layers.map(l => { const d = inf.layers.find(x => x.id === l.id); return { label: d.short, mean: l.mean, p10: l.p10, p90: l.p90 }; }),
        end: { label: 'Estimated\ntrue exports', mean: p.end.mean, p10: p.end.p10, p90: p.end.p90, values: p.end.values }
      }, { labelSize: 14 });
      KT.bridgeNarrative('narr-' + p.period, inf, p.period);
      KT.table('table-bridge-' + p.period, [{ key: 'label', label: 'Step' }, { key: 'mean', label: 'Mean', num: true, fmt: v => KT.isNum(v) ? nf1.format(v) : '—' }, { key: 'range', label: '10th to 90th percentile', num: true }],
        [{ label: 'Raw partner figure (CIF)', mean: p.start.value, range: '' }]
          .concat(p.layers.map(l => ({ label: inf.layers.find(x => x.id === l.id).label, mean: l.mean, range: sgn(l.p10) + ' to ' + sgn(l.p90) })))
          .concat([{ label: 'Estimated true exports', mean: p.end.mean, range: nf1.format(p.end.p10) + ' to ' + nf1.format(p.end.p90) }]));
    });
    // table
    const cols = [{ key: 'label', label: 'Step' }];
    inf.periods.forEach(p => { cols.push({ key: 'm' + p.period, label: p.period + ' mean', num: true, fmt: v => KT.isNum(v) ? nf2.format(v) : '—' }); cols.push({ key: 'r' + p.period, label: p.period + ' 10th–90th', num: true }); });
    const rows = [];
    const row = (label, get, signed, dec) => { const f = v => signed ? sgn(v) : (dec === 2 ? nf2.format(v) : nf1.format(v)); const r = { label }; inf.periods.forEach(p => { const x = get(p); r['m' + p.period] = x.mean; r['r' + p.period] = KT.isNum(x.p10) ? f(x.p10) + ' to ' + f(x.p90) : ''; }); rows.push(r); };
    row('Raw partner figure (CIF)', p => ({ mean: p.start.value }), false, 1);
    inf.layers.forEach((l, i) => row(l.label, p => p.layers[i], true));
    row('Estimated true exports', p => p.end, false, 1);
    row('Estimate as a share of the partner figure (%)', p => ({ mean: 100 * p.share_of_start.mean, p10: 100 * p.share_of_start.p10, p90: 100 * p.share_of_start.p90 }), false, 1);
    KT.table('table-layers', cols, rows);
    setText('src-layers', 'Source: data/inference.json, run ' + inf.meta.run_id + '. Layer ranges are the 10th and 90th percentiles of the signed layer across agents.');
  }

  /* ---------- run log ---------- */
  function renderRuns(runsData) {
    const t = KT.tokens();
    const runs = (runsData && runsData.runs) || [];
    if (!runs.length) { KT.empty('chart-runs', 'No runs recorded yet.'); return; }
    const labels = runs.map(r => KT.fmtDate(r.date + 'T00:00:00Z') + (runs.filter(x => x.date === r.date).length > 1 ? ' (' + r.id + ')' : ''));
    KT.make('chart-runs', { type: 'bar', data: { labels, datasets: [{ label: 'Agents', data: runs.map(r => r.n_agents), backgroundColor: runs.map(r => r.superseded ? KT.withAlpha(t.count, t.prelimAlpha) : t.kir), maxBarThickness: 48 }] },
      options: { plugins: { tooltip: { callbacks: { title: items => runs[items[0].dataIndex].label, label: ctx => ' ' + ctx.parsed.y + ' agents', footer: items => { const r = runs[items[0].dataIndex]; return [r.question, 'Inputs: ' + r.inputs.join(', '), r.superseded ? 'Superseded by a later run' : 'Current'].join('\n'); } } } },
        scales: { x: { grid: { display: false }, border: { color: t.axis }, ticks: { autoSkip: false, maxRotation: 0, font: { size: 11 } } }, y: { beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 5, precision: 0 }, title: { display: true, text: 'agents', color: t.muted, font: { size: 11 } } } } } });
    setText('runs-src', 'Source: the tracker’s run log (data/runs.json). Lighter bars: runs superseded by a later run on the same question.');
    KT.table('table-runs', [{ key: 'date', label: 'Date' }, { key: 'id', label: 'Run' }, { key: 'label', label: 'What' }, { key: 'n_agents', label: 'Agents', num: true }, { key: 'inputs', label: 'Inputs', fmt: v => v.join(', ') }, { key: 'status', label: 'Status' }], runs);
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

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([getJSON('inference'), getJSON('text').catch(() => null), getJSON('runs').catch(() => null)]).then(([inf, text, runs]) => {
      KT.applyDefaults();
      if (text && text.footer) { setText('footer-credit', text.footer.credit); setText('footer-disclaimer', text.footer.disclaimer); }
      renderMethod(inf); renderBridges(inf); renderRuns(runs); renderNotes(inf);
    }).catch(err => { setText('load-error-text', 'The inference data could not be loaded (' + err.message + ').'); show('load-error', true); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
