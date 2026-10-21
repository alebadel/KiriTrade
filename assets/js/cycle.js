/* Fills the figures in the fish-cycle diagram from data/fleet.json. Used on index.html. */
(function () {
  'use strict';
  const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  function set(key, text) { document.querySelectorAll('[data-fill="' + key + '"]').forEach(function (n) { n.textContent = text; }); }
  function start() {
    if (location.protocol === 'file:' || !document.getElementById('cycle')) return;
    fetch('data/fleet.json', { cache: 'no-cache' }).then(function (r) { return r.json(); }).then(function (f) {
      const c = f.chain_facts, ys = {};
      f.monthly.forEach(function (m) { const y = m.period.slice(0, 4); ys[y] = (ys[y] || 0) + m.kir_hours_total; });
      const thisY = f.monthly[f.monthly.length - 1].period.slice(0, 4);
      const full = Object.keys(ys).filter(function (y) { return y < thisY; }).sort();
      const last = full[full.length - 1];
      set('hours', nf0.format(ys[last]) + ' hours spent fishing in ' + last);
      set('encounters', nf0.format(c.n_encounters) + ' vessel pairs seen together at sea');
      set('lag', nf0.format(c.tha_share_pct) + '% of hand-overs were followed by a carrier call at a Thai port within ' + c.tha_window_days + ' days (median ' + nf0.format(c.lag_median_days) + ' days)');
    }).catch(function () {});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
