/* official.js — renders official.html from data/national_accounts.json. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const nf1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  function setText(id, t) { const e = $(id); if (e) e.textContent = t == null ? '' : String(t); }
  function show(id, on) { const e = $(id); if (e) e.hidden = !on; }
  function getJSON(n) { return fetch('data/' + n + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(n + ': ' + r.status); return r.json(); }); }

  function render(na, text) {
    const t = KT.tokens();
    const rows = (na.annual || []).filter(r => KT.isNum(r.bop_goods_exports) || KT.isNum(r.customs_exports_kiribati));
    const bop = rows.filter(r => KT.isNum(r.bop_goods_exports));
    const lastY = bop.length ? Math.max.apply(null, bop.map(r => r.year)) : null;
    const isEst = r => r.gdp_is_estimate === true;   // flagged by the builder from the workbook's 'Est.' marks
    const last = bop.find(r => r.year === lastY);
    if (last) setText('of-strip', lastY + ': goods exports ' + KT.fmtM(last.bop_goods_exports) + ', goods imports ' + KT.fmtM(last.bop_goods_imports) + (isEst(last) ? ' (compiler’s estimates)' : '') + '. Source: IMF balance of payments for Kiribati.');
    const srcs = Array.isArray(na.meta.sources) ? na.meta.sources : [na.meta.source || ''];
    const pick = (re, fallback) => { const s = srcs.find(x => re.test(x)); return s ? s.replace(/:\s*\/\S+/g, '') : fallback; };
    setText('src-bop-x', 'Source: IMF Statistics Department, balance of payments for Kiribati (' + pick(/BOP/i, 'balance of payments') + ').');
    setText('src-bop-m', 'Same source as goods exports.');
    setText('src-customs', 'Source: UN Comtrade, Kiribati-reported monthly returns, months Kiribati published; scaled to 12 months here.');

    const labels = bop.map(r => String(r.year));
    const mk = (id, key, label) => KT.make(id, { type: 'bar', data: { labels, datasets: [{ label, data: bop.map(r => r[key]), backgroundColor: bop.map(r => isEst(r) ? KT.hatch(t.kir) : t.kir), borderColor: t.kir, borderWidth: bop.map(r => isEst(r) ? 1 : 0), maxBarThickness: 26 }] },
      options: { plugins: { tooltip: { callbacks: { label: KT.moneyLabel, footer: items => isEst(bop[items[0].dataIndex]) ? 'compiler’s estimate' : '' } } }, scales: KT.axes({ unit: 'USD m' }) } });
    KT.legend('legend-bop-x', [{ label: 'Goods exports (balance of payments)', color: t.kir }, { label: 'Latest year: estimate', color: t.kir, kind: 'hatch' }]);
    KT.legend('legend-bop-m', [{ label: 'Goods imports (balance of payments)', color: t.kir }, { label: 'Latest year: estimate', color: t.kir, kind: 'hatch' }]);
    mk('chart-bop-x', 'bop_goods_exports', 'Goods exports');
    mk('chart-bop-m', 'bop_goods_imports', 'Goods imports');

    const cu = rows.filter(r => r.year >= 2017);
    const scale = r => (r.months_kiribati_reported ? 12 / r.months_kiribati_reported : null);
    const s12 = (r, v) => (KT.isNum(v) && scale(r)) ? v * scale(r) : null;
    const ax = KT.axes({ unit: 'USD m' }); ax.x.stacked = true; ax.y.stacked = true;
    KT.legend('legend-customs', [{ label: 'Tuna', color: t.fish }, { label: 'Other goods', color: t.kir }, { label: 'Fewer than 12 months published, scaled to 12', color: t.kir, kind: 'light' }]);
    KT.make('chart-customs', { type: 'bar', data: { labels: cu.map(r => String(r.year) + (r.months_kiribati_reported ? (r.months_kiribati_reported < 12 ? '*' : '') : ' (none)')), datasets: [
      { label: 'Tuna', data: cu.map(r => s12(r, r.customs_exports_kiribati_tuna)), backgroundColor: cu.map(r => r.months_kiribati_reported < 12 ? KT.withAlpha(t.fish, t.prelimAlpha) : t.fish), stack: 'c', maxBarThickness: 30 },
      { label: 'Other goods', data: cu.map(r => KT.isNum(r.customs_exports_kiribati) ? s12(r, Math.max(0, r.customs_exports_kiribati - (r.customs_exports_kiribati_tuna || 0))) : null), backgroundColor: cu.map(r => r.months_kiribati_reported < 12 ? KT.withAlpha(t.kir, t.prelimAlpha) : t.kir), stack: 'c', maxBarThickness: 30 }] },
      options: { plugins: { tooltip: { callbacks: { label: KT.moneyLabel, footer: items => { const r = cu[items[0].dataIndex]; return ['All goods, 12-month basis: ' + (KT.isNum(r.customs_exports_kiribati_scaled12) ? KT.fmtM(r.customs_exports_kiribati_scaled12) : KT.fmtM(s12(r, r.customs_exports_kiribati))), 'As published (' + (r.months_kiribati_reported || 0) + ' months): ' + (KT.isNum(r.customs_exports_kiribati) ? KT.fmtM(r.customs_exports_kiribati) : '—')]; } } } }, scales: ax } });

    KT.table('table-official', [{ key: 'year', label: 'Year' }, { key: 'bop_goods_exports', label: 'BOP goods exports', num: true, fmt: KT.fmtNum1 }, { key: 'bop_goods_imports', label: 'BOP goods imports', num: true, fmt: KT.fmtNum1 }, { key: 'customs_exports_kiribati', label: 'Customs exports, as published', num: true, fmt: (v, r) => KT.isNum(v) ? KT.fmtNum1(v) + ' (' + (r.months_kiribati_reported || 0) + ' mo)' : '—' }, { key: 'customs_exports_kiribati_tuna', label: 'of which tuna', num: true, fmt: KT.fmtNum1 }, { key: 'customs_exports_kiribati_scaled12', label: 'Customs exports, 12-month basis', num: true, fmt: KT.fmtNum1 }], rows.slice().reverse());

    if (text && text.footer) { setText('footer-credit', text.footer.credit); setText('footer-disclaimer', text.footer.disclaimer); }
  }

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([getJSON('national_accounts'), getJSON('text').catch(() => null)]).then(([na, text]) => { KT.applyDefaults(); render(na, text); })
      .catch(err => { setText('load-error-text', 'The official data could not be loaded (' + err.message + ').'); show('load-error', true); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
