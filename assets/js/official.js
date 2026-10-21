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
    const lastY = Math.max.apply(null, bop.map(r => r.year));
    const isEst = r => r.year === lastY;   // the latest BOP year is the compiler's estimate (see national_accounts.json notes)
    const last = bop.find(r => r.year === lastY);
    setText('of-strip', lastY + ': goods exports ' + KT.fmtM(last.bop_goods_exports) + ', goods imports ' + KT.fmtM(last.bop_goods_imports) + ' (compiler’s estimates). Source: IMF balance of payments for Kiribati.');
    const src = 'Source: ' + (na.meta.sources ? na.meta.sources[0] : na.meta.source) + '.';
    setText('src-bop-x', src); setText('src-bop-m', src);
    setText('src-customs', 'Source: UN Comtrade, Kiribati-reported monthly returns (' + (na.meta.sources ? na.meta.sources[2] : '') + ').');

    const labels = bop.map(r => String(r.year));
    const mk = (id, key, label) => KT.make(id, { type: 'bar', data: { labels, datasets: [{ label, data: bop.map(r => r[key]), backgroundColor: bop.map(r => isEst(r) ? KT.hatch(t.kir) : t.kir), borderColor: t.kir, borderWidth: bop.map(r => isEst(r) ? 1 : 0), maxBarThickness: 26 }] },
      options: { plugins: { tooltip: { callbacks: { label: KT.moneyLabel, footer: items => isEst(bop[items[0].dataIndex]) ? 'compiler’s estimate' : '' } } }, scales: KT.axes({ unit: 'USD m' }) } });
    KT.legend('legend-bop-x', [{ label: 'Goods exports (balance of payments)', color: t.kir }, { label: 'Latest year: estimate', color: t.kir, kind: 'hatch' }]);
    KT.legend('legend-bop-m', [{ label: 'Goods imports (balance of payments)', color: t.kir }, { label: 'Latest year: estimate', color: t.kir, kind: 'hatch' }]);
    mk('chart-bop-x', 'bop_goods_exports', 'Goods exports');
    mk('chart-bop-m', 'bop_goods_imports', 'Goods imports');

    const cu = rows.filter(r => r.year >= 2017);
    KT.legend('legend-customs', [{ label: 'Kiribati-reported exports, all goods (months published)', color: t.kir }, { label: 'of which tuna', color: t.fish }]);
    KT.make('chart-customs', { type: 'bar', data: { labels: cu.map(r => String(r.year) + (r.months_kiribati_reported ? ' (' + r.months_kiribati_reported + ' mo)' : ' (none)')), datasets: [
      { label: 'All goods', data: cu.map(r => KT.isNum(r.customs_exports_kiribati) ? r.customs_exports_kiribati : null), backgroundColor: t.kir, maxBarThickness: 30 },
      { label: 'Tuna', data: cu.map(r => KT.isNum(r.customs_exports_kiribati_tuna) ? r.customs_exports_kiribati_tuna : null), backgroundColor: t.fish, maxBarThickness: 30 }] },
      options: { plugins: { tooltip: { callbacks: { label: KT.moneyLabel, footer: items => 'months published: ' + (cu[items[0].dataIndex].months_kiribati_reported || 0) } } }, scales: KT.axes({ unit: 'USD m' }) } });

    KT.table('table-official', [{ key: 'year', label: 'Year' }, { key: 'bop_goods_exports', label: 'BOP goods exports', num: true, fmt: KT.fmtNum1 }, { key: 'bop_goods_imports', label: 'BOP goods imports', num: true, fmt: KT.fmtNum1 }, { key: 'months_kiribati_reported', label: 'Months published', num: true }, { key: 'customs_exports_kiribati', label: 'Customs exports (months published)', num: true, fmt: KT.fmtNum1 }, { key: 'customs_exports_kiribati_tuna', label: 'of which tuna', num: true, fmt: KT.fmtNum1 }, { key: 'customs_imports_kiribati', label: 'Customs imports (months published)', num: true, fmt: KT.fmtNum1 }], rows.slice().reverse());

    if (text && text.footer) { setText('footer-credit', text.footer.credit); setText('footer-disclaimer', text.footer.disclaimer); }
  }

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([getJSON('national_accounts'), getJSON('text').catch(() => null)]).then(([na, text]) => { KT.applyDefaults(); render(na, text); })
      .catch(err => { setText('load-error-text', 'The official data could not be loaded (' + err.message + ').'); show('load-error', true); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
