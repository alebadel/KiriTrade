/* registry.js — renders registry.html from data/registry.json (counts only). */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  function setText(id, t) { const e = $(id); if (e) e.textContent = t == null ? '' : String(t); }
  function show(id, on) { const e = $(id); if (e) e.hidden = !on; }
  function getJSON(n) { return fetch('data/' + n + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error(n + ': ' + r.status); return r.json(); }); }

  function barAxes(t, unit, horizontal) {
    const val = { stacked: true, beginAtZero: true, grid: { color: t.grid, drawTicks: false }, border: { display: false }, ticks: { maxTicksLimit: 6, precision: 0 }, title: { display: true, text: unit, color: t.muted, font: { size: 11 } } };
    const cat = { stacked: true, grid: { display: false }, border: { color: t.axis }, ticks: { autoSkip: false, maxRotation: 0 } };
    return horizontal ? { x: val, y: cat } : { x: cat, y: val };
  }
  const countLabel = (ctx) => ' ' + ctx.dataset.label + ': ' + (ctx.parsed.y !== undefined && ctx.chart.options.indexAxis !== 'y' ? ctx.parsed.y : ctx.parsed.x) + ' vessels';

  function render(r, text) {
    const t = KT.tokens();
    const src = 'Source: ' + r.meta.source + '. Counts of ' + r.meta.n_vessels + ' register entries.';
    setText('src-1', src); ['src-2', 'src-3', 'src-4', 'src-5', 'src-6'].forEach(id => setText(id, 'Same source and counts as the first chart.'));
    setText('rg-strip', r.meta.n_vessels + ' entries for the Kiribati, Nauru and Tuvalu flags, exported ' + KT.fmtDate(r.meta.register_export_date + 'T00:00:00Z') + '.');
    const flags = Object.keys(r.by_flag_status);

    // status
    KT.legend('legend-status', [{ label: 'On the register', color: t.kir }, { label: 'Deleted by the flag state', color: t.other }]);
    KT.make('chart-status', { type: 'bar', data: { labels: flags, datasets: [
      { label: 'On the register', data: flags.map(f => r.by_flag_status[f].active), backgroundColor: t.kir, maxBarThickness: 40 },
      { label: 'Deleted by the flag state', data: flags.map(f => r.by_flag_status[f].deleted), backgroundColor: t.other, maxBarThickness: 40 }] },
      options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: countLabel } } }, scales: barAxes(t, 'vessels', true) } });

    // type
    const groups = ['Purse seiners', 'Longliners', 'Carriers', 'Bunkers', 'Other fishing vessels'];
    const colors = [t.partner, t.fish, t.kir, t.copra, t.other];
    KT.legend('legend-type', groups.map((g, i) => ({ label: g, color: colors[i] })));
    KT.make('chart-type', { type: 'bar', data: { labels: flags, datasets: groups.map((g, i) => ({ label: g, data: flags.map(f => r.by_flag_type_group[f][g] || 0), backgroundColor: colors[i], maxBarThickness: 40 })) },
      options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: countLabel } } }, scales: barAxes(t, 'vessels', true) } });
    KT.table('table-type', [{ key: 'type', label: 'Register type code and name' }, { key: 'n', label: 'Vessels', num: true }], Object.entries(r.by_vessel_type).map(([k, v]) => ({ type: k, n: v })));

    // address hint
    const hints = ['Owner or operator address in Kiribati, Nauru or Tuvalu', 'Owner or operator address abroad', 'Addresses both at home and abroad', 'No usable address on the register'];
    const hcol = [t.kir, t.partner, t.copra, t.other];
    KT.legend('legend-hint', hints.map((h, i) => ({ label: h, color: hcol[i] })));
    KT.make('chart-hint', { type: 'bar', data: { labels: flags, datasets: hints.map((h, i) => ({ label: h, data: flags.map(f => (r.by_flag_address_hint[f] || {})[h] || 0), backgroundColor: hcol[i], maxBarThickness: 40 })) },
      options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: countLabel } } }, scales: barAxes(t, 'vessels', true) } });

    // previous flag
    const isNonFlag = k => /^(No previous flag|Other countr|Not stated|Not recorded|Unknown)/i.test(k);
    const flagName = k => k === 'Korea' ? 'South Korea' : k;
    const pf = Object.entries(r.previous_flag).filter(x => !isNonFlag(x[0])).sort((a, b) => b[1] - a[1]).concat(Object.entries(r.previous_flag).filter(x => isNonFlag(x[0])));
    KT.legend('legend-prev', [{ label: 'Previous flag', color: t.count }, { label: 'No previous flag, or other', color: t.other }]);
    KT.make('chart-prev', { type: 'bar', data: { labels: pf.map(x => flagName(x[0])), datasets: [{ label: 'Vessels', data: pf.map(x => x[1]), backgroundColor: pf.map(x => isNonFlag(x[0]) ? t.other : t.count), maxBarThickness: 22 }] },
      options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: countLabel } } }, scales: barAxes(t, 'vessels', true) } });

    // built decade
    const bd = Object.entries(r.built_decade);
    KT.make('chart-built', { type: 'bar', data: { labels: bd.map(x => x[0]), datasets: [{ label: 'Vessels', data: bd.map(x => x[1]), backgroundColor: t.count, maxBarThickness: 36 }] },
      options: { plugins: { tooltip: { callbacks: { label: countLabel } } }, scales: barAxes(t, 'vessels', false) } });

    // AIS match
    const am = Object.entries(r.ais_match);
    const matched = am.filter(x => /^Matched/i.test(x[0])).reduce((s, x) => s + x[1], 0), unmatched = am.filter(x => !/^Matched/i.test(x[0])).reduce((s, x) => s + x[1], 0);
    KT.make('chart-ais', { type: 'bar', data: { labels: ['Register entries'], datasets: [
      { label: 'Matched to a ship-tracking identity', data: [matched], backgroundColor: t.kir, stack: 'a', maxBarThickness: 60 },
      { label: 'Not matched', data: [unmatched], backgroundColor: t.other, stack: 'a', maxBarThickness: 60 }] },
      options: { indexAxis: 'y', plugins: { tooltip: { callbacks: { label: countLabel, footer: () => matched + ' of ' + (matched + unmatched) + ' matched' } } }, scales: (() => { const s = barAxes(t, 'vessels', true); s.x.stacked = true; s.y.stacked = true; return s; })() } });

    // facts
    const dl = $('rg-facts'); dl.textContent = '';
    const add = (k, v) => { const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = v; dl.appendChild(dt); dl.appendChild(dd); };
    add('Authorised to tranship on the high seas', Object.entries(r.authorized_to_tranship_high_seas).map(([k, v]) => k + ': ' + v).join('; '));
    add('Entries with a charterer recorded', String(r.n_with_charterer_recorded));
    add('Deletion reasons', Object.entries(r.deletion_reasons).filter(([k]) => !/On the register/.test(k)).map(([k, v]) => k + ': ' + v).join('; '));

    if (text && text.footer) { setText('footer-credit', text.footer.credit); setText('footer-disclaimer', text.footer.disclaimer); }
  }

  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([getJSON('registry'), getJSON('text').catch(() => null)]).then(([r, text]) => { KT.applyDefaults(); render(r, text); })
      .catch(err => { setText('load-error-text', 'The register data could not be loaded (' + err.message + ').'); show('load-error', true); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
