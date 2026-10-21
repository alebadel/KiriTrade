(function(){
  var app = document.getElementById('lit-app');
  var fallback = document.getElementById('lit-fallback');
  var status = document.getElementById('lit-status');
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; }); }
  function useStatic(msg){
    if (fallback) { app.innerHTML = fallback.textContent; foldEvasion(); }
    if (status && msg) { status.textContent = msg; status.hidden = false; }
    wireFilters();
  }
  function card(p, tags){
    var link = p.url || (p.doi ? 'https://doi.org/' + p.doi : '');
    return '<article class="lit-card" id="' + esc(p.id) + '" data-use="' + esc(p.use) + '">' +
      '<header class="lit-head"><span class="lit-year">' + esc(p.year) + '</span>' +
      '<span class="lit-use lit-use-' + esc(p.use) + '">' + esc(tags[p.use] || p.use) + '</span></header>' +
      '<h3 class="lit-title">' + esc(p.title) + '</h3>' +
      '<p class="lit-cite">' + esc(p.authors) + '. <em>' + esc(p.series) + '</em>. ' + (p.doi ? '<span class="lit-doi">DOI: ' + esc(p.doi) + '</span>' : '') + '</p>' +
      '<p class="lit-abstract">' + esc(p.mini_abstract) + '</p>' +
      '<p class="lit-why"><strong>Why it matters here.</strong> ' + esc(p.why_it_matters_here) + '</p>' +
      (link ? '<a class="lit-link" href="' + esc(link) + '" target="_blank" rel="noopener">Open document</a>' : '') +
      '</article>';
  }
  function names(ids, byId){
    if (!ids || !ids.length) return 'none in this collection';
    return ids.map(function(i){ var p = byId[i]; if (!p) return esc(i);
      var first = p.authors.split(',')[0].split(' and ')[0];
      return '<a href="#' + esc(i) + '">' + esc(first) + ' (' + esc(p.year) + ')</a>'; }).join(', ');
  }
  function render(lit){
    var tags = lit.use_tags || {};
    var byId = {}; (lit.imf || []).concat(lit.academic || []).forEach(function(p){ byId[p.id] = p; });
    var h = '<section class="lit-uses" id="three-uses"><h2>The three uses of mirror analysis</h2>';
    (lit.three_uses || []).forEach(function(u){
      h += '<div class="lit-use-box lit-use-box-' + esc(u.use) + '"><h3>' + esc(u.label) + (u.use === 'measure' ? ' <span class="lit-this">this tracker</span>' : '') + '</h3><p>' + esc(u.plain) + '</p>' +
           '<p class="lit-members"><strong>IMF:</strong> ' + names(u.imf, byId) + '.<br><strong>Academic:</strong> ' + names(u.academic, byId) + '.</p></div>';
    });
    if (lit.method_notes) { var m = lit.method_notes;
      h += '<div class="lit-use-box lit-use-box-method"><h3>' + esc(m.label) + '</h3><p>' + esc(m.plain) + '</p>' +
           '<p class="lit-members"><strong>IMF:</strong> ' + names(m.imf, byId) + '.<br><strong>Academic:</strong> ' + names(m.academic, byId) + '.</p></div>'; }
    h += '</section>';
    h += '<section id="imf"><h2>(A) IMF literature</h2><p class="lit-count">' + (lit.imf || []).length + ' documents, oldest first.</p><div class="lit-grid">' + (lit.imf || []).map(function(p){ return card(p, tags); }).join('') + '</div></section>';
    h += '<section id="academic"><h2>(B) Academic literature</h2><p class="lit-count">' + (lit.academic || []).length + ' papers, oldest first.</p><div class="lit-grid">' + (lit.academic || []).map(function(p){ return card(p, tags); }).join('') + '</div></section>';
    app.innerHTML = h;
    foldEvasion();
    var gen = lit.meta && lit.meta.generated_at;
    var g = document.getElementById('lit-generated'); if (g && gen) { g.textContent = 'List generated ' + gen.slice(0, 10) + '.'; }
    wireFilters();
  }
  /* The evasion papers are not the use made here: fold them into one block per section so the page reads shorter. */
  function foldEvasion(){
    ['imf', 'academic'].forEach(function(sec){
      var s = document.getElementById(sec); if (!s) return;
      var grid = s.querySelector('.lit-grid'); if (!grid) return;
      var cards = Array.prototype.slice.call(grid.querySelectorAll('.lit-card[data-use="evasion"]'));
      if (!cards.length) return;
      var d = document.createElement('details'); d.className = 'lit-fold';
      var sm = document.createElement('summary'); sm.textContent = 'Detecting evasion: ' + cards.length + ' document' + (cards.length > 1 ? 's' : '') + ' (not the use made here)';
      d.appendChild(sm);
      var g2 = document.createElement('div'); g2.className = 'lit-grid';
      cards.forEach(function(c){ g2.appendChild(c); });
      d.appendChild(g2); grid.after(d);
    });
  }
  function wireFilters(){
    var bar = document.getElementById('lit-filter'); if (!bar) return;
    bar.hidden = false;
    var buttons = bar.querySelectorAll('button');
    buttons.forEach(function(b){ b.onclick = function(){
      buttons.forEach(function(x){ x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      var u = b.getAttribute('data-filter');
      document.querySelectorAll('.lit-card').forEach(function(c){ c.hidden = (u !== 'all' && c.getAttribute('data-use') !== u); });
      document.querySelectorAll('details.lit-fold').forEach(function(d){ d.open = (u === 'evasion'); d.hidden = (u !== 'all' && u !== 'evasion'); });
    }; });
  }
  if (!window.fetch || location.protocol === 'file:') { useStatic('Showing the built-in copy of the list. Open the published site for the live version.'); return; }
  fetch('data/literature.json', {cache: 'no-cache'}).then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(function(){ useStatic('Could not load data/literature.json; showing the built-in copy of the list.'); });
})();
