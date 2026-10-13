#!/usr/bin/env python3
"""Render site/literature.html from site/data/literature.json and site/data/text.json.

The page renders itself from literature.json with a small inline script when
served over HTTP. The same list is also written statically into a <noscript>
block, so the page reads in full without JavaScript, and the script falls back
to that static block when fetch() is unavailable (for example from file://).

Run:  python3 site/tracker/render_literature.py
Owner: Agent D. Regenerate whenever literature.json or the review text changes.
"""
from __future__ import annotations

import html
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SITE = HERE.parent
DATA = SITE / "data"
OUT = SITE / "literature.html"

PAGE_TITLE = "Literature: mirror analysis of trade statistics"
SITE_TITLE = "Import and Export Performance Tracker using Comtrade Trade-Partner Data"

# Three paragraphs from Mirror_analysis_literature_review_v5.md, rewritten for a lay reader.
WHAT_IS = [
    "Every shipment that crosses a border is written down twice: once by the customs office of the country it leaves, as an export, and once by the customs office of the country it enters, as an import. Comparing the two records is called mirror analysis, or the partner-country method. The two records differ even when both are accurate. Importers add the cost of shipping and insurance. The two sides may record a shipment in different months or under different product codes. Goods that pass through a hub such as Hong Kong or Singapore may be attributed to different partners. Fish is attributed by the flag of the vessel that caught it. A careful comparison removes these mechanical differences first and then reads what remains.",
    "The literature has used mirror analysis in three ways. The first is to check the quality of trade statistics, a practice that goes back a century. The second, and the largest, is to detect tax evasion: if the gap between two records grows when a tariff rises, some traders are probably misstating values. The third is to measure economies whose own figures arrive late, cover only part of their trade, or are not published, by reading what their partners recorded. The IMF has made this third use for decades in its Direction of Trade Statistics, filling gaps for late reporters with partner records, and IMF country teams compare the two records routinely.",
    "This tracker is a case of the third use. Kiribati is a nation of 33 islands with a small statistical office, and its monthly customs returns reach the United Nations database with delays. Its trading partners publish on steadier schedules. Reading the partner record alongside Kiribati's official statistics gives a more timely picture of the economy. The large difference in tuna is a question of attribution, of the kind the papers below isolate and resolve at the detailed product level: importers code tuna to the flag of the catching vessel, while balance-of-payments rules ask where the vessel's operator is resident. Nothing on this site treats Kiribati as a case of evasion or of poor data. The documents below are listed so that readers can see where the method comes from and how it is meant to be used.",
]


def esc(s: object) -> str:
    return html.escape(str(s or ""), quote=True)


def card(p: dict, use_tags: dict) -> str:
    link = p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else "")
    link_html = f'<a class="lit-link" href="{esc(link)}" target="_blank" rel="noopener">Open document</a>' if link else ""
    doi_html = f'<span class="lit-doi">DOI: {esc(p["doi"])}</span>' if p.get("doi") else ""
    return (
        f'<article class="lit-card" id="{esc(p["id"])}" data-use="{esc(p["use"])}">\n'
        f'  <header class="lit-head">\n'
        f'    <span class="lit-year">{esc(p["year"])}</span>\n'
        f'    <span class="lit-use lit-use-{esc(p["use"])}">{esc(use_tags.get(p["use"], p["use"]))}</span>\n'
        f'  </header>\n'
        f'  <h3 class="lit-title">{esc(p["title"])}</h3>\n'
        f'  <p class="lit-cite">{esc(p["authors"])}. <em>{esc(p["series"])}</em>. {doi_html}</p>\n'
        f'  <p class="lit-abstract">{esc(p["mini_abstract"])}</p>\n'
        f'  <p class="lit-why"><strong>Why it matters here.</strong> {esc(p["why_it_matters_here"])}</p>\n'
        f'  {link_html}\n'
        f'</article>'
    )


def uses_block(lit: dict) -> str:
    by_id = {p["id"]: p for p in lit["imf"] + lit["academic"]}

    def names(ids):
        parts = []
        for i in ids:
            p = by_id[i]
            first = p["authors"].split(",")[0].split(" and ")[0].strip()
            parts.append(f'<a href="#{esc(i)}">{esc(first)} ({p["year"]})</a>')
        return ", ".join(parts) if parts else "none in this collection"

    out = ['<section class="lit-uses" id="three-uses"><h2>The three uses of mirror analysis</h2>']
    for u in lit["three_uses"]:
        flag = ' <span class="lit-this">this tracker</span>' if u["use"] == "measure" else ""
        out.append(
            f'<div class="lit-use-box lit-use-box-{esc(u["use"])}">'
            f'<h3>{esc(u["label"])}{flag}</h3>'
            f'<p>{esc(u["plain"])}</p>'
            f'<p class="lit-members"><strong>IMF:</strong> {names(u["imf"])}.<br>'
            f'<strong>Academic:</strong> {names(u["academic"])}.</p></div>'
        )
    m = lit.get("method_notes")
    if m:
        out.append(
            f'<div class="lit-use-box lit-use-box-method"><h3>{esc(m["label"])}</h3><p>{esc(m["plain"])}</p>'
            f'<p class="lit-members"><strong>IMF:</strong> {names(m["imf"])}.<br>'
            f'<strong>Academic:</strong> {names(m["academic"])}.</p></div>'
        )
    out.append("</section>")
    return "\n".join(out)


def static_list(lit: dict) -> str:
    tags = lit.get("use_tags", {})
    parts = [uses_block(lit)]
    parts.append('<section id="imf"><h2>(A) IMF literature</h2><p class="lit-count">'
                 f'{len(lit["imf"])} documents, oldest first.</p><div class="lit-grid">')
    parts += [card(p, tags) for p in lit["imf"]]
    parts.append("</div></section>")
    parts.append('<section id="academic"><h2>(B) Academic literature</h2><p class="lit-count">'
                 f'{len(lit["academic"])} papers, oldest first.</p><div class="lit-grid">')
    parts += [card(p, tags) for p in lit["academic"]]
    parts.append("</div></section>")
    return "\n".join(parts)


FALLBACK_CSS = """
/* Minimal fallback styles: assets/css/style.css (Agent C) is loaded after this and may override. */
:root{--lit-bg:#fbfaf7;--lit-fg:#1f2a30;--lit-muted:#5b6770;--lit-card:#ffffff;--lit-line:#e3e0d8;--lit-accent:#0b5d6b;
 --lit-measure:#0b5d6b;--lit-audit:#7a5c00;--lit-evasion:#7a2e2e;--lit-method:#4b4f7a;--lit-measure-bg:#e3f1f3;--lit-audit-bg:#f8efd4;--lit-evasion-bg:#f6e3e3;--lit-method-bg:#e8e8f4}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--lit-bg:#14191c;--lit-fg:#e8e6df;--lit-muted:#a9b1b7;--lit-card:#1c2327;--lit-line:#2d3539;--lit-accent:#7fc7d2;
 --lit-measure:#7fc7d2;--lit-audit:#e4c56a;--lit-evasion:#e39a9a;--lit-method:#b4b8e6;--lit-measure-bg:#15333a;--lit-audit-bg:#3a3014;--lit-evasion-bg:#3a1f1f;--lit-method-bg:#262a44}}
:root[data-theme="dark"]{--lit-bg:#14191c;--lit-fg:#e8e6df;--lit-muted:#a9b1b7;--lit-card:#1c2327;--lit-line:#2d3539;--lit-accent:#7fc7d2;
 --lit-measure:#7fc7d2;--lit-audit:#e4c56a;--lit-evasion:#e39a9a;--lit-method:#b4b8e6;--lit-measure-bg:#15333a;--lit-audit-bg:#3a3014;--lit-evasion-bg:#3a1f1f;--lit-method-bg:#262a44}
html{box-sizing:border-box}*,*:before,*:after{box-sizing:inherit}
body{margin:0;background:var(--lit-bg);color:var(--lit-fg);font:16px/1.55 Georgia,"Times New Roman",serif}
.lit-wrap{max-width:60rem;margin:0 auto;padding:1.5rem 16px 4rem}
.lit-nav{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.9rem;margin-bottom:1rem}
.lit-nav a{color:var(--lit-accent);text-decoration:none}.lit-nav a:hover{text-decoration:underline}
.lit-kicker{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;text-transform:uppercase;letter-spacing:.08em;font-size:.75rem;color:var(--lit-muted);margin:0}
h1{font-size:1.9rem;line-height:1.2;margin:.25rem 0 1rem}
h2{font-size:1.4rem;margin:2.5rem 0 .5rem;border-top:1px solid var(--lit-line);padding-top:1.25rem}
h3{font-size:1.1rem;margin:.25rem 0 .4rem;line-height:1.3}
.lit-intro p{max-width:46rem}
.lit-toc{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.9rem;color:var(--lit-muted)}
.lit-toc a{color:var(--lit-accent)}
.lit-uses .lit-use-box{border-left:4px solid var(--lit-line);padding:.5rem 1rem;margin:1rem 0;background:var(--lit-card);border-radius:0 6px 6px 0}
.lit-use-box-measure{border-left-color:var(--lit-measure)}.lit-use-box-audit{border-left-color:var(--lit-audit)}
.lit-use-box-evasion{border-left-color:var(--lit-evasion)}.lit-use-box-method{border-left-color:var(--lit-method)}
.lit-this{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;background:var(--lit-measure);color:var(--lit-bg);padding:.15rem .45rem;border-radius:999px;vertical-align:middle;margin-left:.4rem}
.lit-members{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.85rem;color:var(--lit-muted)}
.lit-members a{color:var(--lit-accent);text-decoration:none}.lit-members a:hover{text-decoration:underline}
.lit-count{color:var(--lit-muted);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.9rem;margin-top:0}
.lit-grid{display:grid;grid-template-columns:1fr;gap:1rem}
@media (min-width:800px){.lit-grid{grid-template-columns:1fr 1fr}}
.lit-card{background:var(--lit-card);border:1px solid var(--lit-line);border-radius:8px;padding:1rem 1.1rem;display:flex;flex-direction:column;gap:.35rem;scroll-margin-top:1rem}
.lit-card:target{outline:2px solid var(--lit-accent)}
.lit-head{display:flex;justify-content:space-between;align-items:center;gap:.5rem;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.78rem}
.lit-year{font-weight:700;color:var(--lit-muted)}
.lit-use{padding:.12rem .5rem;border-radius:999px;font-weight:600;letter-spacing:.02em;text-align:right}
.lit-use-measure{background:var(--lit-measure-bg);color:var(--lit-measure)}.lit-use-audit{background:var(--lit-audit-bg);color:var(--lit-audit)}
.lit-use-evasion{background:var(--lit-evasion-bg);color:var(--lit-evasion)}.lit-use-method{background:var(--lit-method-bg);color:var(--lit-method)}
.lit-cite{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.85rem;color:var(--lit-muted);margin:0}
.lit-doi{word-break:break-all}
.lit-abstract{margin:.25rem 0}
.lit-why{margin:0;font-size:.95rem}
.lit-link{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.85rem;color:var(--lit-accent);text-decoration:none;margin-top:auto;padding-top:.4rem}
.lit-link:hover{text-decoration:underline}
.lit-filter{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.85rem;display:flex;flex-wrap:wrap;gap:.4rem;margin:1rem 0}
.lit-filter button{border:1px solid var(--lit-line);background:var(--lit-card);color:var(--lit-fg);border-radius:999px;padding:.3rem .8rem;cursor:pointer;font:inherit}
.lit-filter button[aria-pressed="true"]{background:var(--lit-accent);color:var(--lit-bg);border-color:var(--lit-accent)}
.lit-card[hidden]{display:none}
.lit-note{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.85rem;color:var(--lit-muted);border:1px dashed var(--lit-line);padding:.5rem .8rem;border-radius:6px}
footer.lit-foot{margin-top:3rem;border-top:1px solid var(--lit-line);padding-top:1rem;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:.85rem;color:var(--lit-muted)}
"""

SCRIPT = r"""
(function(){
  var app = document.getElementById('lit-app');
  var fallback = document.getElementById('lit-fallback');
  var status = document.getElementById('lit-status');
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]; }); }
  function useStatic(msg){
    if (fallback) { app.innerHTML = fallback.textContent; }
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
    var gen = lit.meta && lit.meta.generated_at;
    var g = document.getElementById('lit-generated'); if (g && gen) { g.textContent = 'List generated ' + gen.slice(0, 10) + '.'; }
    wireFilters();
  }
  function wireFilters(){
    var bar = document.getElementById('lit-filter'); if (!bar) return;
    bar.hidden = false;
    var buttons = bar.querySelectorAll('button');
    buttons.forEach(function(b){ b.onclick = function(){
      buttons.forEach(function(x){ x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
      var u = b.getAttribute('data-filter');
      document.querySelectorAll('.lit-card').forEach(function(c){ c.hidden = (u !== 'all' && c.getAttribute('data-use') !== u); });
    }; });
  }
  if (!window.fetch || location.protocol === 'file:') { useStatic('Showing the built-in copy of the list. Open the published site for the live version.'); return; }
  fetch('data/literature.json', {cache: 'no-cache'}).then(function(r){ if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(render)
    .catch(function(){ useStatic('Could not load data/literature.json; showing the built-in copy of the list.'); });
})();
"""


def build() -> str:
    lit = json.loads((DATA / "literature.json").read_text(encoding="utf-8"))
    text = {}
    tp = DATA / "text.json"
    if tp.exists():
        text = json.loads(tp.read_text(encoding="utf-8"))
    blurb = text.get("literature_blurb", "")
    footer = text.get("footer", {})
    static = static_list(lit)
    intro = "\n".join(f"<p>{esc(p)}</p>" for p in WHAT_IS)
    gen = (lit.get("meta") or {}).get("generated_at", "")[:10]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(PAGE_TITLE)}</title>
<meta name="description" content="Plain-language summaries of the IMF and academic literature on mirror analysis of trade statistics, and why it matters for the Kiribati tracker.">
<style>{FALLBACK_CSS}</style>
<link rel="stylesheet" href="assets/css/style.css">
</head>
<body>
<div class="lit-wrap">
  <nav class="lit-nav" aria-label="Site"><a href="index.html">&larr; Back to tracker</a> &nbsp;|&nbsp; <a href="methods.html">Methods</a></nav>
  <p class="lit-kicker">{esc(SITE_TITLE)}</p>
  <h1>{esc(PAGE_TITLE)}</h1>

  <section class="lit-intro" id="what-is">
    <h2 style="border-top:0;padding-top:0;margin-top:1rem">What is mirror analysis, and why it matters for Kiribati</h2>
    {intro}
    {f'<p class="lit-note">{esc(blurb)}</p>' if blurb else ''}
    <p class="lit-toc">On this page: <a href="#three-uses">the three uses</a> &middot; <a href="#imf">(A) IMF literature</a> &middot; <a href="#academic">(B) Academic literature</a></p>
  </section>

  <div class="lit-filter" id="lit-filter" hidden role="group" aria-label="Filter by use">
    <button type="button" data-filter="all" aria-pressed="true">All</button>
    <button type="button" data-filter="measure">Measuring an economy (this tracker)</button>
    <button type="button" data-filter="audit">Checking statistics</button>
    <button type="button" data-filter="method">Why records differ</button>
    <button type="button" data-filter="evasion">Detecting evasion (not used here)</button>
  </div>
  <p class="lit-note" id="lit-status" hidden></p>

  <div id="lit-app">
    <noscript id="lit-fallback">
{static}
    </noscript>
  </div>

  <footer class="lit-foot">
    <p id="lit-generated">List generated {esc(gen)}.</p>
    <p>Source: <em>Mirror analysis of trade statistics: literature review</em>, draft 5 (7 October 2026), and the project's paper knowledge base. Summaries are paraphrases written for a general reader, not the documents' own abstracts.</p>
    {f'<p>{esc(footer.get("credit", ""))}</p>' if footer.get("credit") else ''}
    {f'<p>{esc(footer.get("disclaimer", ""))}</p>' if footer.get("disclaimer") else ''}
    <p><a href="index.html">&larr; Back to tracker</a></p>
  </footer>
</div>
<script>{SCRIPT}</script>
</body>
</html>
"""


def main() -> int:
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
