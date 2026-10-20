/* =====================================================================
   fleet.js — renders fleet.html from data/fleet.json (and data/series.json)
   ---------------------------------------------------------------------
   Aggregates only: fleet.json holds monthly hours and quarterly port-call
   counts, never vessel or company names. Built by tracker/build_fleet_data.py.
   Helpers (colours, formats, chart glue) come from charts.js (window.KT).
   ===================================================================== */
(function () {
  'use strict';
  const KT = window.KT;
  const DATA = 'data/';
  const $ = (id) => document.getElementById(id);
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  const nf0 = new Intl.NumberFormat('en', { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat('en', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const DEST = [['KIR', 'Kiribati'], ['CHN', 'China'], ['KOR', 'Korea'], ['THA', 'Thailand'], ['other', 'Other countries']];

  function el(tag, text, attrs) {
    const e = document.createElement(tag);
    if (text != null) e.textContent = text;
    if (attrs) Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v));
    return e;
  }
  function fmtDay(iso) {              // "2026-10-16" -> "16 October 2026"
    const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? (+m[3]) + ' ' + MONTHS[+m[2] - 1] + ' ' + m[1] : '—';
  }
  function getJSON(name) {
    return fetch(DATA + name, { cache: 'no-cache' }).then((r) => {
      if (!r.ok) throw new Error(name + ' (' + r.status + ')');
      return r.json();
    });
  }
  function show(id, on) { const n = $(id); if (n) n.hidden = !on; }

  /* ---------- derived numbers ---------- */
  function yearSums(monthly) {
    const y = {};
    monthly.forEach((m) => { const k = m.period.slice(0, 4); y[k] = (y[k] || 0) + m.kir_hours_total; });
    return y;
  }
  function completeYears(monthly, partial) {
    // a year is "complete" when December is present and it is not the partial month's year
    const last = monthly[monthly.length - 1].period;
    return Object.keys(yearSums(monthly)).filter((k) => k < last.slice(0, 4));
  }
  function callsSince(q, firstQuarter) {
    const t = { KIR: 0, CHN: 0, KOR: 0, THA: 0, other: 0, total: 0 };
    q.filter((r) => r.quarter >= firstQuarter).forEach((r) => { DEST.forEach(([k]) => { t[k] += r[k]; t.total += r[k]; }); });
    return t;
  }

  /* ---------- 1. freshness stamp ---------- */
  function renderStamp(f) {
    const m = f.meta;
    $('fleet-strip-h').textContent = 'AIS data through ' + fmtDay(m.ais_through);
    let share = 1;
    if (m.partial_month && m.ais_through) {
      const y = +m.partial_month.slice(0, 4), mo = +m.partial_month.slice(5, 7);
      const dim = new Date(Date.UTC(y, mo, 0)).getUTCDate();
      share = Math.min(1, (+m.ais_through.slice(8, 10)) / dim);
    }
    $('fleet-meter').style.width = Math.round(share * 100) + '%';
    const lg = $('fleet-strip-legend'); lg.textContent = '';
    if (m.partial_month) {
      lg.appendChild(el('em', KT.fmtPeriod(m.partial_month)));
      lg.appendChild(document.createTextNode(' is ' + Math.round(share * 100) + '% elapsed, so its figures are partial. '));
    } else {
      lg.appendChild(document.createTextNode('The latest month is complete. '));
    }
    lg.appendChild(document.createTextNode('Vessel register exported ' + fmtDay(m.rfv_export_date) + '. This is the fleet-side counterpart of the “percent complete” score on the main tracker.'));
    document.querySelectorAll('[data-updated-badge]').forEach((b) => { b.textContent = 'AIS data through ' + fmtDay(m.ais_through); });
  }

  /* ---------- 2. three facts ---------- */
  function renderFacts(f) {
    const box = $('fleet-stats'); box.textContent = '';
    const ys = yearSums(f.monthly);
    const cy = completeYears(f.monthly, f.meta.partial_month);
    const lastY = cy[cy.length - 1], prevY = cy[cy.length - 2];
    const add = (n, t, sub) => {
      const d = el('div', null, { class: 'stat' });
      d.appendChild(el('p', n, { class: 'stat-n' }));
      d.appendChild(el('p', t, { class: 'stat-t' }));
      if (sub) d.appendChild(el('p', sub, { class: 'stat-s' }));
      box.appendChild(d);
    };
    add(nf0.format(ys[lastY]) + ' hours',
      'of observed fishing activity by Kiribati-flagged vessels in ' + lastY + ', against ' + nf0.format(ys[prevY]) + ' in ' + prevY + '.',
      'The rise came while joint-venture vessels were added to the register. Part of it can be better AIS detection.');
    const c = f.chain_facts;
    add(nf0.format(c.tha_share_pct) + '%',
      'of ' + nf0.format(c.n_encounters) + ' at-sea transfers were followed by a call at a Thai port within ' + c.tha_window_days + ' days; the median wait was ' + nf0.format(c.lag_median_days) + ' days (middle half: ' + nf0.format(c.lag_p25) + ' to ' + nf0.format(c.lag_p75) + ').',
      'Covers vessels on the Kiribati, Nauru or Tuvalu registers while registered. A call at a Thai port shows where a carrier went next, not what it carried.');
    const t = callsSince(f.port_calls_quarterly, '2025Q1');
    add(nf0.format(t.total) + ' port calls',
      'recorded by AIS for Kiribati-flagged vessels since January 2025: ' + nf0.format(t.KIR) + ' in Kiribati, ' + nf0.format(t.CHN) + ' in China, ' + nf0.format(t.KOR) + ' in Korea, ' + nf0.format(t.THA) + ' in Thailand and ' + nf0.format(t.other) + ' elsewhere.',
      'A call is not a landing, and calls say nothing about tonnage.');
  }

  /* ---------- 3. chart: monthly hours ---------- */
  function renderHours(f) {
    const tk = KT.tokens();
    const m = f.monthly;
    const partial = f.meta.partial_month;
    const labels = m.map((r) => r.period);
    const lightIf = (c) => labels.map((p) => (p === partial ? KT.withAlpha(c, tk.prelimAlpha) : c));
    const ax = KT.axes({ stacked: true, unit: 'hours', monthlyDense: true, dense: true });
    ax.y.title.text = 'fishing hours per month';
    ax.x.ticks.callback = function (v) { const p = this.getLabelForValue(v); return /-01$/.test(p) ? p.slice(0, 4) : ''; };
    KT.make('chart-hours', {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { label: 'In Kiribati’s waters', data: m.map((r) => r.kir_hours_kir_eez), backgroundColor: lightIf(tk.kir), stack: 'h' },
          { label: 'Elsewhere', data: m.map((r) => r.kir_hours_other), backgroundColor: lightIf(tk.other), stack: 'h' }
        ]
      },
      options: {
        scales: ax,
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => KT.fmtPeriod(items[0].label) + (items[0].label === partial ? ' (partial month)' : ''),
              label: (c) => ' ' + c.dataset.label + ': ' + nf0.format(c.parsed.y) + ' hours',
              footer: (items) => 'Total: ' + nf0.format(items.reduce((s, i) => s + i.parsed.y, 0)) + ' hours'
            }
          }
        }
      }
    });
    KT.legend('legend-hours', [
      { label: 'In Kiribati’s waters (Gilbert, Phoenix, Line Islands)', color: tk.kir },
      { label: 'Elsewhere', color: tk.other },
      { label: 'Lighter bar: month still in progress', color: tk.other, kind: 'light' }
    ]);
    KT.table('table-hours', [
      { key: 'period', label: 'Month', fmt: (v) => KT.fmtPeriod(v) },
      { key: 'kir_hours_kir_eez', label: 'Hours in Kiribati’s waters', num: true, fmt: (v) => nf0.format(v) },
      { key: 'kir_hours_other', label: 'Hours elsewhere', num: true, fmt: (v) => nf0.format(v) },
      { key: 'kir_hours_total', label: 'Total hours', num: true, fmt: (v) => nf0.format(v) }
    ], m.slice().reverse());
    const ys = yearSums(m), cy = completeYears(m);
    $('chart-hours').setAttribute('aria-label', 'Monthly fishing hours of Kiribati-flagged vessels, ' + KT.fmtPeriod(m[0].period) + ' to ' + KT.fmtPeriod(m[m.length - 1].period) + '. ' + cy[cy.length - 1] + ' total: ' + nf0.format(ys[cy[cy.length - 1]]) + ' hours; ' + cy[cy.length - 2] + ': ' + nf0.format(ys[cy[cy.length - 2]]) + ' hours.');
  }

  /* ---------- 4. chart: mirror tuna beside lagged hours ---------- */
  function renderMirror(f, series) {
    const tk = KT.tokens();
    const hrs = {}; f.monthly.forEach((r) => { hrs[r.period] = r.kir_hours_total; });
    const partialM = f.meta.partial_month;
    const tuna = series.monthly.filter((r) => r.period >= '2017-01');
    const tunaBy = {}; tuna.forEach((r) => { tunaBy[r.period] = r; });
    // axis: 2017-01 to the later of the last mirror month and the month after the last complete hours month
    const lastHoursComplete = f.monthly.filter((r) => r.period !== partialM).slice(-1)[0].period;
    const nextMonth = (p) => { let y = +p.slice(0, 4), mo = +p.slice(5, 7) + 1; if (mo > 12) { mo = 1; y++; } return y + '-' + String(mo).padStart(2, '0'); };
    const lastLag = nextMonth(lastHoursComplete);
    const lastMirror = tuna[tuna.length - 1].period;
    const end = lastLag > lastMirror ? lastLag : lastMirror;
    const labels = []; for (let p = '2017-01'; p <= end; p = nextMonth(p)) labels.push(p);
    const prev = (p) => { let y = +p.slice(0, 4), mo = +p.slice(5, 7) - 1; if (mo < 1) { mo = 12; y--; } return y + '-' + String(mo).padStart(2, '0'); };
    const isProv = (p) => { const r = tunaBy[p]; return !!r && KT.isNum(r.n_reporters_fish) && r.n_reporters_fish < 3; };
    const barData = labels.map((p) => (tunaBy[p] && KT.isNum(tunaBy[p].exports_partner_tuna) ? tunaBy[p].exports_partner_tuna : null));
    const lineData = labels.map((p) => { const q = prev(p); return (q in hrs && q !== partialM) ? hrs[q] / 1000 : null; });
    const ax = KT.axes({ unit: 'USD m', monthlyDense: true, dense: true });
    ax.y.title.text = 'USD millions, partner-reported tuna';
    ax.x.ticks.callback = function (v) { const p = this.getLabelForValue(v); return /-01$/.test(p) ? p.slice(0, 4) : ''; };
    ax.y1 = {
      position: 'right', beginAtZero: true, grid: { drawOnChartArea: false }, border: { display: false },
      ticks: { padding: 6, maxTicksLimit: 6, callback: (v) => nf0.format(v) },
      title: { display: true, text: 'thousand fishing hours, previous month', color: tk.muted, font: { size: 11 } }
    };
    KT.make('chart-mirror', {
      type: 'bar',
      data: {
        labels,
        datasets: [
          { type: 'bar', label: 'Partner-reported tuna', data: barData, yAxisID: 'y', order: 2,
            backgroundColor: labels.map((p) => (isProv(p) ? KT.withAlpha(tk.partner, tk.prelimAlpha) : tk.partner)) },
          { type: 'line', label: 'Fishing hours, previous month', data: lineData, yAxisID: 'y1', order: 1,
            borderColor: tk.kir, backgroundColor: tk.kir, pointRadius: 0, pointHoverRadius: 4, spanGaps: false, borderWidth: 2 }
        ]
      },
      options: {
        scales: ax,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => KT.fmtPeriod(items[0].label),
              label: (c) => {
                if (c.dataset.yAxisID === 'y1') return ' Fishing hours, previous month: ' + (KT.isNum(c.parsed.y) ? nf0.format(c.parsed.y * 1000) : 'not available');
                return ' Partner-reported tuna: ' + KT.fmtM(c.parsed.y) + (isProv(c.label) ? ' (provisional)' : '');
              }
            }
          }
        }
      }
    });
    KT.legend('legend-mirror', [
      { label: 'Partner-reported tuna (USD m, left axis)', color: tk.partner },
      { label: 'Lighter bar: provisional (fewer than 3 partners published)', color: tk.partner, kind: 'light' },
      { label: 'Fishing hours of the previous month (right axis)', color: tk.kir, kind: 'line' }
    ]);
    const rows = labels.map((p) => ({
      period: p,
      tuna: barData[labels.indexOf(p)],
      n: tunaBy[p] ? tunaBy[p].n_reporters_fish : null,
      hours: lineData[labels.indexOf(p)] == null ? null : lineData[labels.indexOf(p)] * 1000
    })).reverse();
    KT.table('table-mirror', [
      { key: 'period', label: 'Month', fmt: (v) => KT.fmtPeriod(v) },
      { key: 'tuna', label: 'Partner-reported tuna (USD m)', num: true, fmt: (v) => (KT.isNum(v) ? nf1.format(v) : 'not published') },
      { key: 'n', label: 'Partners with fish data', num: true, fmt: (v) => (KT.isNum(v) ? String(v) : '—') },
      { key: 'hours', label: 'Fishing hours, previous month', num: true, fmt: (v) => (KT.isNum(v) ? nf0.format(v) : '—') }
    ], rows);
    renderAnnual(f, series);
    const lastTuna = tuna.filter((r) => KT.isNum(r.exports_partner_tuna)).slice(-1)[0];
    $('chart-mirror').setAttribute('aria-label', 'Partner-reported tuna by month, ' + KT.fmtPeriod('2017-01') + ' to ' + KT.fmtPeriod(lastTuna.period) + ', beside the previous month\'s fishing hours. Annual figures are in the table below the chart.');
  }

  function renderAnnual(f, series) {
    const ys = yearSums(f.monthly);
    const by = {};
    series.monthly.forEach((r) => {
      if (r.period < '2017-01' || !KT.isNum(r.exports_partner_tuna)) return;
      const y = r.period.slice(0, 4); by[y] = by[y] || { v: 0, n: 0 }; by[y].v += r.exports_partner_tuna; by[y].n += 1;
    });
    const years = Object.keys(by).sort().filter((y) => y in ys);
    const last = f.monthly[f.monthly.length - 1].period.slice(0, 4);
    const t = $('annual-table'); t.textContent = '';
    const cap = el('caption', 'Year by year: observed fishing hours and partner-reported tuna'); t.appendChild(cap);
    const thead = el('thead'), tr = el('tr');
    ['Year', 'Fishing hours (Kiribati-flagged, AIS)', 'Partner-reported tuna (USD m)', 'Months of tuna data'].forEach((h, i) => { const th = el('th', h, { scope: 'col' }); if (i) th.className = 'num'; tr.appendChild(th); });
    thead.appendChild(tr); t.appendChild(thead);
    const tb = el('tbody');
    years.forEach((y) => {
      const r = el('tr');
      r.appendChild(el('td', y + (y === last ? ' (to ' + KT.fmtPeriod(f.monthly[f.monthly.length - 1].period) + ')' : '')));
      const a = el('td', nf0.format(ys[y])); a.className = 'num'; r.appendChild(a);
      const b = el('td', nf1.format(by[y].v) + (by[y].n < 12 ? ' *' : '')); b.className = 'num'; r.appendChild(b);
      const c = el('td', String(by[y].n)); c.className = 'num'; r.appendChild(c);
      tb.appendChild(r);
    });
    t.appendChild(tb);
    const foot = el('tfoot'), fr = el('tr'), fc = el('td', '* Sum of the months published so far, not a full year. The two columns are shown side by side; no relationship between them is estimated.', { colspan: '4' });
    fr.appendChild(fc); foot.appendChild(fr); t.appendChild(foot);
  }

  /* ---------- 5. chart: quarterly port calls ---------- */
  function renderPorts(f) {
    const tk = KT.tokens();
    const q = f.port_calls_quarterly;
    const labels = q.map((r) => r.quarter);
    const last = labels[labels.length - 1];
    const partialQ = f.meta.partial_month ? (f.meta.partial_month.slice(0, 4) + 'Q' + Math.ceil(+f.meta.partial_month.slice(5, 7) / 3)) : null;
    const colour = { KIR: tk.kir, CHN: tk.partner, KOR: tk.fish, THA: tk.copra, other: tk.other };
    const lightIf = (c) => labels.map((l) => (l === partialQ ? KT.withAlpha(c, tk.prelimAlpha) : c));
    const ax = KT.axes({ stacked: true, unit: 'calls', dense: true });
    ax.y.title.text = 'port calls per quarter';
    ax.x.ticks.callback = function (v) { const p = this.getLabelForValue(v); return /Q1$/.test(p) ? p.slice(0, 4) : ''; };
    KT.make('chart-ports', {
      type: 'bar',
      data: { labels, datasets: DEST.map(([k, name]) => ({ label: name, data: q.map((r) => r[k]), backgroundColor: lightIf(colour[k]), stack: 'p' })) },
      options: {
        scales: ax,
        plugins: {
          tooltip: {
            callbacks: {
              title: (items) => KT.fmtPeriod(items[0].label) + (items[0].label === partialQ ? ' (partial quarter)' : ''),
              label: (c) => ' ' + c.dataset.label + ': ' + nf0.format(c.parsed.y) + ' calls',
              footer: (items) => 'Total: ' + nf0.format(items.reduce((s, i) => s + i.parsed.y, 0)) + ' calls'
            }
          }
        }
      }
    });
    KT.legend('legend-ports', DEST.map(([k, name]) => ({ label: 'Port in ' + (k === 'other' ? 'other countries' : name), color: colour[k] })));
    KT.table('table-ports', [{ key: 'quarter', label: 'Quarter', fmt: (v) => KT.fmtPeriod(v) }]
      .concat(DEST.map(([k, name]) => ({ key: k, label: name, num: true, fmt: (v) => nf0.format(v) })))
      .concat([{ key: 'total', label: 'Total', num: true, fmt: (v) => nf0.format(v) }]), q.slice().reverse());
    const t = callsSince(q, '2025Q1');
    $('chart-ports').setAttribute('aria-label', 'Quarterly port calls of Kiribati-flagged vessels by country of port, ' + KT.fmtPeriod(labels[0]) + ' to ' + KT.fmtPeriod(last) + '. Since January 2025: ' + t.total + ' calls, of which ' + t.KIR + ' in Kiribati and ' + t.CHN + ' in China.');
  }

  /* ---------- 6. the open question ---------- */
  function renderCallout(f, series) {
    const t = callsSince(f.port_calls_quarterly, '2025Q1');
    const box = $('china-callout'); box.textContent = '';
    box.appendChild(el('p', 'Since January 2025, AIS records ' + nf0.format(t.CHN) + ' port calls by Kiribati-flagged vessels in Chinese ports. Mainland China’s own returns to UN Comtrade list no fish originating in Kiribati for 2020 to 2025.'));
    box.appendChild(el('p', 'How landings from such calls enter each country’s trade and production statistics is an open question for the compilers of those statistics. The tracker draws no conclusion from the two observations. They are shown so that compilers and readers can ask the question with the same data in front of them.'));
  }

  /* ---------- 7. footer text ---------- */
  function renderFooter(text) {
    if (text && text.footer) {
      $('footer-credit').textContent = text.footer.credit || '';
      $('footer-disclaimer').textContent = text.footer.disclaimer || '';
    }
  }

  /* ---------- start-up ---------- */
  function start() {
    if (location.protocol === 'file:') { show('file-notice', true); return; }
    Promise.all([
      getJSON('fleet.json'),
      getJSON('series.json'),
      getJSON('text.json').catch(() => null)
    ]).then(([fleet, series, text]) => {
      KT.applyDefaults();
      renderFooter(text);
      renderStamp(fleet);
      renderFacts(fleet);
      renderHours(fleet);
      renderMirror(fleet, series);
      renderPorts(fleet);
      renderCallout(fleet, series);
    }).catch((err) => {
      $('load-error-text').textContent = 'The fleet data could not be loaded (' + err.message + '). Reload the page; if it persists, the data files may be mid-update.';
      show('load-error', true);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
