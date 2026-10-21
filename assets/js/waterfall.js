/* =====================================================================
   waterfall.js — a waterfall ("bridge") chart on top of Chart.js
   ---------------------------------------------------------------------
   Draws: a start bar, signed steps (floating bars) and an end bar; on each
   step a whisker for the spread of the steps across agents; on the end bar
   a whisker for the spread of the end value; one dot per agent beside the
   end bar; and the value written on every bar. Used on index.html and
   inference.html. Needs charts.js (window.KT) and Chart.js.

   KT.waterfall(canvasId, bridge, opts)
     bridge = {
       start: {label, value},
       steps: [{label, mean, p10, p90}],       // signed amounts
       end:   {label, mean, p10, p90, values}  // values: one number per agent
     }
     opts = { unit: 'USD m', labelSize: 14, compact: false }
   ===================================================================== */
(function (global) {
  'use strict';
  const KT = global.KT;

  function fmt(v, d) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d === undefined ? 1 : d); }

  /* Plugin: whiskers, agent dots and value labels drawn after the bars. */
  const whiskers = {
    id: 'ktWhiskers',
    afterDatasetsDraw(chart, args, o) {
      if (!o || !o.items) return;
      const { ctx } = chart;
      const t = KT.tokens();
      const meta = chart.getDatasetMeta(0);
      const yScale = chart.scales.y;
      const fontFamily = getComputedStyle(document.body).fontFamily;
      ctx.save();
      o.items.forEach((it, i) => {
        const bar = meta.data[i];
        if (!bar) return;
        const x = bar.x;
        const half = Math.max(5, (bar.width || 20) * 0.22);
        // whisker (10th-90th percentile across agents)
        if (KT.isNum(it.lo) && KT.isNum(it.hi)) {
          const y1 = yScale.getPixelForValue(it.lo), y2 = yScale.getPixelForValue(it.hi);
          ctx.strokeStyle = it.whiskerColor || t.ink;
          ctx.lineWidth = 2.5;
          ctx.beginPath();
          ctx.moveTo(x, y1); ctx.lineTo(x, y2);
          ctx.moveTo(x - half, y1); ctx.lineTo(x + half, y1);
          ctx.moveTo(x - half, y2); ctx.lineTo(x + half, y2);
          ctx.stroke();
        }
        // one dot per agent beside the end bar
        if (it.dots && it.dots.length) {
          const dx = x + (bar.width || 20) * 0.72;
          ctx.fillStyle = KT.withAlpha(t.ink2, 0.75);
          it.dots.forEach((v, k) => {
            const jitter = ((k * 7919) % 13 - 6) * 0.9;
            ctx.beginPath();
            ctx.arc(dx + jitter, yScale.getPixelForValue(v), o.compact ? 2.2 : 3, 0, Math.PI * 2);
            ctx.fill();
          });
          if (!o.compact) {
            ctx.fillStyle = t.muted;
            ctx.font = '13px ' + fontFamily;
            ctx.textAlign = 'center';
            ctx.textAlign = 'right';
            ctx.fillText('one dot = one agent', chart.chartArea.right, yScale.getPixelForValue(Math.max.apply(null, it.dots)) - 12);
          }
        }
        // value label
        if (KT.isNum(it.label)) {
          ctx.fillStyle = t.ink;
          ctx.font = 'bold ' + (o.labelSize || 13) + 'px ' + fontFamily;
          ctx.textAlign = 'center';
          ctx.textBaseline = 'bottom';
          const top = Math.min(yScale.getPixelForValue(it.top), KT.isNum(it.hi) ? yScale.getPixelForValue(Math.max(it.hi, it.top)) : Infinity);
          ctx.fillText(it.text, x, top - 5);
        }
      });
      ctx.restore();
    }
  };
  if (global.Chart && !global.Chart.registry.plugins.get('ktWhiskers')) global.Chart.register(whiskers);

  function waterfall(canvasId, bridge, opts) {
    const o = Object.assign({ unit: 'USD m', labelSize: 15, compact: false, decimals: 1 }, opts || {});
    const t = KT.tokens();
    const fullLabels = [bridge.start.label].concat(bridge.steps.map(s => s.label), [bridge.end.label]);
    /* On narrow screens eight multi-line labels collide: number the bars and write the key under the plot. */
    const cv = document.getElementById(canvasId);
    const narrow = !!(cv && cv.parentElement && cv.parentElement.clientWidth > 0 && cv.parentElement.clientWidth < 600);
    const labels = narrow ? fullLabels.map((l, i) => String(i + 1)) : fullLabels;
    if (cv && cv.parentElement) {
      let key = cv.parentElement.nextElementSibling;
      if (!(key && key.classList && key.classList.contains('wf-key'))) { key = document.createElement('p'); key.className = 'wf-key small muted'; cv.parentElement.after(key); }
      key.textContent = narrow ? fullLabels.map((l, i) => (i + 1) + ' ' + String(l).replace(/\n/g, ' ')).join(' · ') : '';
      key.hidden = !narrow;
    }
    const data = [], colors = [], items = [];
    let level = bridge.start.value;
    data.push([0, level]); colors.push(t.ink2);
    items.push({ label: level, text: level.toFixed(o.decimals), top: level });
    bridge.steps.forEach(s => {
      const a = level, b = level + s.mean;
      data.push([Math.min(a, b), Math.max(a, b)]);
      colors.push(s.mean < 0 ? t.partner : t.fish);
      items.push({
        lo: KT.isNum(s.p10) ? a + s.p10 : null, hi: KT.isNum(s.p90) ? a + s.p90 : null,
        label: s.mean, text: fmt(s.mean, o.decimals), top: Math.max(a, b)
      });
      level = b;
    });
    data.push([0, bridge.end.mean]); colors.push(t.ink2);
    items.push({ lo: bridge.end.p10, hi: bridge.end.p90, whiskerColor: t.ink, dots: bridge.end.values || [], label: bridge.end.mean, text: bridge.end.mean.toFixed(o.decimals), top: Math.max(bridge.end.mean, bridge.end.p90 || 0) });

    const maxY = Math.ceil(Math.max(bridge.start.value, bridge.end.mean) * 1.15 / 10) * 10;
    return KT.make(canvasId, {
      type: 'bar',
      data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0, barPercentage: 0.62, categoryPercentage: 0.9, borderSkipped: false }] },
      options: {
        plugins: {
          ktWhiskers: { items, labelSize: o.labelSize, compact: o.compact },
          tooltip: { callbacks: {
            title: (ctx) => String(fullLabels[ctx[0].dataIndex]).replace(/\n/g, ' '),
            label: (ctx) => {
              const i = ctx.dataIndex, it = items[i];
              if (i === 0) return ' ' + bridge.start.value.toFixed(2) + ' ' + o.unit;
              if (i === labels.length - 1) return ' mean ' + bridge.end.mean.toFixed(2) + ' ' + o.unit + (KT.isNum(it.lo) ? ' (agents 10th-90th: ' + it.lo.toFixed(1) + ' to ' + it.hi.toFixed(1) + ')' : '');
              const s = bridge.steps[i - 1];
              return ' mean ' + fmt(s.mean, 2) + ' ' + o.unit + (KT.isNum(s.p10) ? ' (agents 10th-90th: ' + fmt(s.p10, 1) + ' to ' + fmt(s.p90, 1) + ')' : '');
            } } }
        },
        scales: {
          x: { grid: { display: false }, border: { color: t.axis }, ticks: { autoSkip: false, maxRotation: 0, font: { size: o.compact ? 12 : 15 }, callback: function (v) { return String(labels[v]).split('\n'); } } },
          y: { beginAtZero: true, max: maxY, grid: { color: t.grid, drawTicks: false }, border: { display: false },
            ticks: { padding: 6, maxTicksLimit: 6, precision: 0, font: { size: o.compact ? 12 : 15 } }, title: { display: !o.compact, text: 'USD millions', color: t.muted, font: { size: 14 } } }
        },
        layout: { padding: { top: o.compact ? 8 : 18, right: o.compact ? 8 : 24 } }
      }
    });
  }

  KT.waterfall = waterfall;
})(window);

/* =====================================================================
   KT.bridgeNarrative(container, inf, period)
   Fills a container with the experts' narrative for one year: four
   summary points computed from the aggregates, then one block per layer
   with the layer's definition, its mean and spread, and the words of the
   agents at the low end, the middle and the high end of that layer.
   Everything is read from data/inference.json; nothing is typed in.
   ===================================================================== */
(function (global) {
  'use strict';
  const KT = global.KT;
  const nf1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
  const sg = v => (v > 0 ? '+' : v < 0 ? '−' : '') + nf1.format(Math.abs(v));
  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v); });
    (children || []).forEach(c => e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return e;
  }
  function bridgeNarrative(container, inf, period) {
    const box = typeof container === 'string' ? document.getElementById(container) : container;
    if (!box) return;
    box.textContent = '';
    const p = inf.periods.find(x => x.period === period);
    if (!p) return;
    const n = inf.meta.n_agents;
    const L = id => p.layers.find(l => l.id === id);
    const big = p.layers.slice().sort((a, b) => Math.abs(b.mean) - Math.abs(a.mean))[0];
    const bigDef = inf.layers.find(x => x.id === big.id);
    const adds = p.layers.filter(l => l.mean > 0);
    const widths = p.layers.map(l => ({ id: l.id, w: l.p90 - l.p10 }));
    const widest = widths.slice().sort((a, b) => b.w - a.w)[0];
    const others = widths.filter(w => w.id !== widest.id).map(w => w.w);
    const widestDef = inf.layers.find(x => x.id === widest.id);
    const sum = el('ol', { class: 'narrative' }, [
      el('li', null, [el('strong', { text: 'Start. ' }), 'Importers recorded USD ' + nf1.format(p.start.value) + ' million of tuna as Kiribati-origin in ' + period + ', credited by the flag of the catching vessel and valued at their own border (CIF).']),
      el('li', null, [el('strong', { text: 'One layer does the work. ' }), bigDef.label + ': mean ' + sg(big.mean) + ', agents’ 10th to 90th percentile ' + sg(big.p10) + ' to ' + sg(big.p90) + '. The agents judge that about ' + nf0.format(100 * Math.abs(big.mean) / p.start.value) + ' percent of the flag-basis figure is ' + (big.id === 'L2_nonresident_operated' ? 'catch of vessels run by non-resident operators, which is not a Kiribati export under the residence rule.' : bigDef.label.toLowerCase() + '.')]),
      el('li', null, [el('strong', { text: 'The additions are small. ' }), adds.length ? adds.map(l => inf.layers.find(x => x.id === l.id).label + ' ' + sg(l.mean)).join('; ') + '. The partner series misses some resident sales, but the agents do not find much of it.' : 'No layer adds to the figure.']),
      el('li', null, [el('strong', { text: 'End. ' }), 'Estimated true exports USD ' + nf1.format(p.end.mean) + ' million, ' + nf0.format(100 * p.share_of_start.mean) + ' percent of the partner figure; the thirty agents run from ' + nf1.format(p.end.min) + ' to ' + nf1.format(p.end.max) + '. ' + (p.official && KT.isNum(p.official.bop_goods_exports) ? 'For reference, the balance of payments records USD ' + nf1.format(p.official.bop_goods_exports) + ' million of goods exports, all goods, for ' + period + '.' : '')]),
      el('li', null, [el('strong', { text: 'Where the disagreement sits. ' }), widestDef.label + ': the 10th to 90th percentile spans ' + nf1.format(widest.w) + '; the other five layers span ' + nf1.format(Math.min.apply(null, others)) + ' to ' + nf1.format(Math.max.apply(null, others)) + '. No public source measures who operates each vessel, so this layer rests on register address hints and the agents’ knowledge of Pacific fleets.'])
    ]);
    box.appendChild(el('h4', { text: 'In five points' }));
    box.appendChild(sum);
    box.appendChild(el('h4', { text: 'Layer by layer, in the agents’ own words' }));
    box.appendChild(el('p', { class: 'small muted', text: 'For each layer: what it is, the mean and spread across the ' + n + ' agents, and the reasons given by the agent at the low end, the agent in the middle and the agent at the high end of that layer. Agents are numbered, not named; "P" cites the agent’s own principles and two-digit numbers cite evidence files.' }));
    inf.layers.forEach(def => {
      const l = L(def.id);
      const rs = (p.rationales || []).filter(r => r.layer === def.id).slice().sort((a, b) => a.value - b.value);
      const pick = rs.length ? [rs[0], rs[Math.floor(rs.length / 2)], rs[rs.length - 1]] : [];
      const block = el('div', { class: 'layer-block' }, [
        el('h5', { text: def.label }),
        el('p', { class: 'small' }, [el('span', { class: 'muted', text: def.description + ' ' }), el('strong', { text: 'Mean ' + sg(l.mean) + '; agents’ 10th to 90th percentile ' + sg(l.p10) + ' to ' + sg(l.p90) + '.' })]),
        el('ul', { class: 'quotes' }, pick.map((r, i) => el('li', null, [
          el('span', { class: 'who', text: ['Low end', 'Middle', 'High end'][i] + ' (agent ' + r.agent.replace('draw_', '') + ', ' + sg(r.value) + '): ' }),
          el('q', { text: r.text })
        ])))
      ]);
      box.appendChild(block);
    });
  }
  KT.bridgeNarrative = bridgeNarrative;
})(window);
