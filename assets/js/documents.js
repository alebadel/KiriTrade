/* documents.js — renders documents.html from data/corpus.json (counts and titles only). */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  function setText(id, t) { const e = $(id); if (e) e.textContent = t == null ? '' : String(t); }
  function show(id, on) { const e = $(id); if (e) e.hidden = !on; }
  function getJSON(n) { return fetch('data/' + n + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(n + ': ' + r.status); return r.json(); }); }
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v); });
    (children || []).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return e;
  }

  function render(c, text) {
    const t = KT.tokens();
    const m = c.meta;
    const names = m.country_names || {};
    const cname = iso => iso === 'ALL' ? 'All countries' : iso === 'GEN' ? 'General (not about one country)' : (names[iso] || iso);
    setText('dc-strip', nf0.format(m.n_documents) + ' documents and ' + nf1.format(m.n_words / 1e6) + ' million words, inventoried ' + KT.fmtDate(m.generated_at) + '.');
    setText('src-corpus', 'Source: the tracker’s document inventory (tracker/build_corpus_data.py), ' + KT.fmtDate(m.generated_at) + '.');

    const sel = $('corpus-country');
    const countries = ['ALL'].concat(Object.keys(c.by_country_type));
    countries.forEach(iso => sel.appendChild(el('option', { value: iso, text: cname(iso) })));
    sel.value = 'ALL';
    KT.legend('legend-corpus', [{ label: 'Words of text held', color: t.other }, { label: 'Number of documents (in the tooltip)', color: t.count, kind: 'line' }]);

    const draw = () => {
      const iso = sel.value;
      const order = m.type_order;
      const cell = k => iso === 'ALL' ? c.totals_by_type[k] : (c.by_country_type[iso] || {})[k] || { documents: 0, words: 0 };
      const words = order.map(k => cell(k).words);
      const docs = order.map(k => cell(k).documents);
      setText('corpus-sub', cname(iso) + ': ' + nf0.format(docs.reduce((a, b) => a + b, 0)) + ' documents, ' + nf0.format(words.reduce((a, b) => a + b, 0)) + ' words');
      KT.make('chart-corpus', { type: 'bar', data: { labels: order.map(k => m.types[k]), datasets: [{ label: 'Words', data: words, backgroundColor: t.other, maxBarThickness: 26 }] },
        options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: ctx => ' ' + nf0.format(ctx.parsed.x) + ' words in ' + docs[ctx.dataIndex] + ' document' + (docs[ctx.dataIndex] === 1 ? '' : 's') } } },
          scales: { x: { beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 6, callback: v => v >= 1e6 ? (v / 1e6) + ' m' : v >= 1000 ? (v / 1000) + ' k' : v }, title: { display: true, text: 'words', color: t.muted, font: { size: 11 } } }, y: { grid: { display: false }, border: { color: t.axis }, ticks: { autoSkip: false } } } } });
      const rows = c.documents.filter(d => iso === 'ALL' || d.country === iso).slice().sort((a, b) => (m.type_order.indexOf(a.type) - m.type_order.indexOf(b.type)) || ((a.year || 0) - (b.year || 0)));
      setText('docs-lede', rows.length + ' document' + (rows.length === 1 ? '' : 's') + ' for ' + cname(iso).toLowerCase() + '. Titles are as given in the knowledge base; sources are the publishing bodies.');
      const tbl = $('docs-table'); tbl.textContent = '';
      const head = el('thead', null, [el('tr', null, ['Title', 'Type', 'Country', 'Year', 'Pages', 'Words', 'Source'].map((h, i) => el('th', { text: h, class: i >= 3 && i <= 5 ? 'num' : '' })))]);
      tbl.appendChild(head);
      const body = el('tbody');
      rows.forEach(d => body.appendChild(el('tr', null, [
        el('td', { text: d.title }), el('td', { text: m.types[d.type] }), el('td', { text: cname(d.country) }),
        el('td', { text: d.year || '—', class: 'num' }), el('td', { text: d.pages ? nf0.format(d.pages) : '—', class: 'num' }), el('td', { text: KT.isNum(d.words) ? nf0.format(d.words) : '—', class: 'num' }), el('td', { text: d.source || '' })
      ])));
      tbl.appendChild(body);
    };
    sel.addEventListener('change', draw);
    draw();
    if (text && text.footer) { setText('footer-credit', text.footer.credit); setText('footer-disclaimer', text.footer.disclaimer); }
  }

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([getJSON('corpus'), getJSON('text').catch(() => null)]).then(([c, text]) => { KT.applyDefaults(); render(c, text); })
      .catch(err => { setText('load-error-text', 'The inventory could not be loaded (' + err.message + ').'); show('load-error', true); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
