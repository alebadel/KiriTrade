/* =====================================================================
   charts.js — small helpers on top of Chart.js used by app.js
   ---------------------------------------------------------------------
   Nothing here knows about Kiribati or the JSON files. It only:
     • reads the colour tokens from CSS so charts match the page,
     • formats numbers and period labels the way the site wants
       ("USD 12.3 m", "Jul 2026", "2026 Q3"),
     • builds hatched fills, lighter "preliminary" fills,
     • creates / replaces a Chart.js chart in a <canvas>,
     • writes the HTML legend and the "Show as a table" twin.
   A non-developer can change colours in style.css and labels in
   data/text.json without touching this file.
   ===================================================================== */
(function (global) {
  'use strict';

  /* ---------- colours from CSS custom properties ---------- */
  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback || '#888';
  }
  function tokens() {
    return {
      kir: cssVar('--kir', '#1f6fae'),
      partner: cssVar('--partner', '#b75a1c'),
      fish: cssVar('--fish', '#1a8f68'),
      copra: cssVar('--copra', '#e09a2e'),
      other: cssVar('--other', '#9fabb2'),
      count: cssVar('--count', '#7d8f99'),
      peer: cssVar('--peer', '#b9c3c8'),
      ink: cssVar('--ink', '#15232c'),
      ink2: cssVar('--ink-2', '#46555e'),
      muted: cssVar('--muted', '#74838b'),
      grid: cssVar('--grid', '#e6ecee'),
      axis: cssVar('--axis', '#c5d0d5'),
      surface: cssVar('--surface', '#ffffff'),
      prelimAlpha: parseFloat(cssVar('--prelim-alpha', '0.42')) || 0.42
    };
  }

  /* hex -> rgba string with alpha */
  function withAlpha(hex, a) {
    const h = hex.replace('#', '');
    const full = h.length === 3 ? h.split('').map(c => c + c).join('') : h;
    const n = parseInt(full, 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return `rgba(${r},${g},${b},${a})`;
  }

  /* diagonal hatch pattern (45°) in a colour; cached per colour */
  const patternCache = new Map();
  function hatch(color, alpha) {
    const key = color + '|' + (alpha || 1);
    if (patternCache.has(key)) return patternCache.get(key);
    const c = document.createElement('canvas');
    c.width = 8; c.height = 8;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, 8, 8);
    ctx.strokeStyle = alpha ? withAlpha(color, alpha) : color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-2, 10); ctx.lineTo(10, -2);
    ctx.moveTo(-2, 2); ctx.lineTo(2, -2);
    ctx.moveTo(6, 10); ctx.lineTo(10, 6);
    ctx.stroke();
    const p = ctx.createPattern(c, 'repeat');
    patternCache.set(key, p);
    return p;
  }

  /* ---------- formatting ---------- */
  const nf1 = new Intl.NumberFormat('en', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('en', { maximumFractionDigits: 0 });
  const nf2 = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  /* "USD 12.3 m"; null -> "not published" (or custom) */
  function fmtM(v, nullText) {
    if (!isNum(v)) return nullText === undefined ? 'not published' : nullText;
    return 'USD ' + nf1.format(v) + ' m';
  }
  function fmtNum1(v) { return isNum(v) ? nf1.format(v) : '—'; }
  function fmtPct(share, nullText) {   // 0.591 -> "59%"
    if (!isNum(share)) return nullText === undefined ? '—' : nullText;
    return nf0.format(share * 100) + '%';
  }
  function fmtRatio(v) { return isNum(v) ? nf2.format(v) + '×' : '—'; }
  function fmtGrowth(v) { return isNum(v) ? (v > 0 ? '+' : '') + nf1.format(v) + '%' : '—'; }

  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  /* "2026-07" -> "Jul 2026"; "2026Q3" -> "2026 Q3"; 2025 -> "2025" */
  function fmtPeriod(p) {
    if (p === null || p === undefined) return '—';
    const s = String(p);
    let m = s.match(/^(\d{4})-(\d{2})$/);
    if (m) return MONTHS[+m[2] - 1] + ' ' + m[1];
    m = s.match(/^(\d{4})Q([1-4])$/);
    if (m) return m[1] + ' Q' + m[2];
    return s;
  }
  /* short axis tick for dense monthly series: "Jan 2024" only at January, else "Apr" */
  function tickPeriod(p, dense) {
    const s = String(p);
    const m = s.match(/^(\d{4})-(\d{2})$/);
    if (m) return dense ? (+m[2] === 1 ? m[1] : '') : MONTHS[+m[2] - 1] + ' ' + m[1];
    const q = s.match(/^(\d{4})Q([1-4])$/);
    if (q) return (q[2] === '1' || !dense) ? q[1] + ' Q' + q[2] : 'Q' + q[2];
    return s;
  }
  /* ISO date-time -> "13 Oct 2026, 08:30 UTC" */
  function fmtDateTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear() + ', ' +
      String(d.getUTCHours()).padStart(2, '0') + ':' + String(d.getUTCMinutes()).padStart(2, '0') + ' UTC';
  }
  function fmtDate(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.getUTCDate() + ' ' + MONTHS[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
  }

  /* ---------- Chart.js glue ---------- */
  const registry = new Map();   // canvas id -> Chart instance
  function hasChartJs() { return typeof global.Chart !== 'undefined'; }

  function applyDefaults() {
    if (!hasChartJs()) return;
    const t = tokens();
    const C = global.Chart;
    C.defaults.font.family = getComputedStyle(document.body).fontFamily;
    C.defaults.font.size = 12;
    C.defaults.color = t.ink2;
    C.defaults.borderColor = t.grid;
    C.defaults.plugins.legend.display = false;          // legends are HTML (see legend())
    C.defaults.plugins.tooltip.backgroundColor = t.ink;
    C.defaults.plugins.tooltip.titleColor = t.surface;
    C.defaults.plugins.tooltip.bodyColor = t.surface;
    C.defaults.plugins.tooltip.footerColor = t.surface;
    C.defaults.plugins.tooltip.padding = 10;
    C.defaults.plugins.tooltip.cornerRadius = 6;
    C.defaults.plugins.tooltip.boxPadding = 4;
    C.defaults.plugins.tooltip.usePointStyle = true;
    C.defaults.animation = matchMedia('(prefers-reduced-motion: reduce)').matches ? false : { duration: 300 };
    C.defaults.responsive = true;
    C.defaults.maintainAspectRatio = false;
    C.defaults.elements.bar.borderRadius = 3;
    C.defaults.elements.bar.borderSkipped = 'bottom';
    C.defaults.elements.line.borderWidth = 2;
    C.defaults.elements.line.tension = 0;
    C.defaults.elements.point.radius = 2.5;
    C.defaults.elements.point.hoverRadius = 5;
    C.defaults.elements.point.borderWidth = 2;
    C.defaults.elements.point.borderColor = t.surface;
  }

  /* Standard axis options. unit: 'USD m' | '%' */
  function axes(opts) {
    const t = tokens();
    const o = Object.assign({ unit: 'USD m', dense: false, stacked: false, horizontal: false, max: undefined, min: 0, monthlyDense: false }, opts || {});
    const valueAxis = {
      beginAtZero: true, min: o.min, max: o.max, stacked: o.stacked,
      grid: { color: t.grid, drawTicks: false },
      border: { display: false },
      ticks: {
        padding: 6, maxTicksLimit: 6,
        callback: (v) => o.unit === '%' ? v + '%' : nf0.format(v)
      },
      title: { display: !!o.unit, text: o.unit === '%' ? 'percent of panel' : 'USD millions', color: t.muted, font: { size: 11 } }
    };
    const catAxis = {
      stacked: o.stacked,
      grid: { display: false }, border: { color: t.axis },
      ticks: { autoSkip: !o.monthlyDense, maxRotation: 0, autoSkipPadding: 12, callback: function (val) { const l = tickPeriod(this.getLabelForValue(val), o.dense); return o.monthlyDense && l === '' ? undefined : l; } }
    };
    return o.horizontal ? { x: valueAxis, y: Object.assign(catAxis, { ticks: { autoSkip: false } }) } : { x: catAxis, y: valueAxis };
  }

  /* Create (or replace) the chart in #canvasId. Returns the Chart or null. */
  function make(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;
    const plot = canvas.parentElement;
    if (!hasChartJs()) {
      showPlotMessage(plot, 'The chart library could not be loaded. The numbers are in the table below.');
      return null;
    }
    clearPlotMessage(plot);
    if (registry.has(canvasId)) { registry.get(canvasId).destroy(); registry.delete(canvasId); }
    const chart = new global.Chart(canvas, config);
    registry.set(canvasId, chart);
    return chart;
  }
  function destroyAll() { registry.forEach(c => c.destroy()); registry.clear(); }

  function showPlotMessage(plot, text) {
    clearPlotMessage(plot);
    const d = document.createElement('div');
    d.className = 'plot-msg'; d.textContent = text;
    plot.appendChild(d);
  }
  function clearPlotMessage(plot) {
    plot.querySelectorAll('.plot-msg').forEach(e => e.remove());
  }
  /* Show a friendly empty state instead of an empty chart */
  function empty(canvasId, text) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (registry.has(canvasId)) { registry.get(canvasId).destroy(); registry.delete(canvasId); }
    showPlotMessage(canvas.parentElement, text || 'No data for this view yet.');
  }

  /* ---------- HTML legend ----------
     items: [{label, color, kind: 'box'|'line'|'hatch'|'light'|'dash'}] */
  function legend(containerId, items) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.textContent = '';
    items.forEach(it => {
      const s = document.createElement('span');
      const i = document.createElement('i');
      i.className = it.kind && it.kind !== 'box' ? it.kind : '';
      i.style.setProperty('--swatch', it.color);
      if (!it.kind || it.kind === 'box' || it.kind === 'light') i.style.background = it.color;
      s.appendChild(i);
      s.appendChild(document.createTextNode(it.label));
      el.appendChild(s);
    });
  }

  /* ---------- table twin ----------
     columns: [{key, label, fmt?}], rows: array of objects */
  function table(containerId, columns, rows, opts) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.textContent = '';
    const tbl = document.createElement('table');
    const thead = document.createElement('thead'); const trh = document.createElement('tr');
    columns.forEach(c => { const th = document.createElement('th'); th.textContent = c.label; if (c.num) th.className = 'num'; trh.appendChild(th); });
    thead.appendChild(trh); tbl.appendChild(thead);
    const tbody = document.createElement('tbody');
    rows.forEach(r => {
      const tr = document.createElement('tr');
      if (opts && opts.highlight && opts.highlight(r)) tr.className = 'is-subject';
      columns.forEach(c => {
        const td = document.createElement('td');
        const v = r[c.key];
        td.textContent = c.fmt ? c.fmt(v, r) : (v === null || v === undefined ? '—' : String(v));
        if (c.num) td.className = 'num';
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    tbl.appendChild(tbody);
    el.appendChild(tbl);
  }

  /* ---------- tooltip helpers ---------- */
  /* tooltip row callback for money datasets; hides null points */
  function moneyLabel(ctx) {
    const v = ctx.parsed[ctx.chart.options.indexAxis === 'y' ? 'x' : 'y'];
    if (!isNum(v)) return null;
    return ' ' + ctx.dataset.label + ': ' + fmtM(v);
  }

  /* Plugin: write series names at the right end of line charts (used for peers).
     Labels are nudged apart so they never overlap. */
  const endLabels = {
    id: 'endLabels',
    afterDatasetsDraw(chart, args, opts) {
      if (!opts || !opts.enabled) return;
      const { ctx, chartArea } = chart;
      const t = tokens();
      const items = [];
      chart.data.datasets.forEach((ds, i) => {
        const meta = chart.getDatasetMeta(i);
        if (!meta || meta.hidden) return;
        // last non-null point
        let last = null;
        for (let k = meta.data.length - 1; k >= 0; k--) { if (isNum(ds.data[k])) { last = meta.data[k]; break; } }
        if (!last) return;
        items.push({ y: last.y, x: last.x, label: ds.shortLabel || ds.label, strong: !!ds.isSubject });
      });
      items.sort((a, b) => a.y - b.y);
      const minGap = 13;
      for (let i = 1; i < items.length; i++) { if (items[i].y - items[i - 1].y < minGap) items[i].y = items[i - 1].y + minGap; }
      for (let i = items.length - 2; i >= 0; i--) { if (items[i + 1].y - items[i].y < minGap) items[i].y = items[i + 1].y - minGap; }
      ctx.save();
      ctx.font = (opts.font || '11px') + ' ' + getComputedStyle(document.body).fontFamily;
      ctx.textBaseline = 'middle';
      items.forEach(it => {
        ctx.fillStyle = it.strong ? t.ink : t.ink2;
        ctx.font = (it.strong ? 'bold ' : '') + (opts.font || '11px') + ' ' + getComputedStyle(document.body).fontFamily;
        ctx.fillText(it.label, Math.min(it.x + 6, chartArea.right + 6), it.y);
      });
      ctx.restore();
    }
  };

  global.KT = {
    tokens, withAlpha, hatch, isNum, fmtM, fmtNum1, fmtPct, fmtRatio, fmtGrowth, fmtPeriod, tickPeriod,
    fmtDateTime, fmtDate, applyDefaults, axes, make, empty, destroyAll, legend, table, moneyLabel, endLabels, hasChartJs
  };
})(window);
