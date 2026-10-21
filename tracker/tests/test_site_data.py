"""Contracts for the data files added with the restructured site (20 Oct 2026):
corpus.json, registry.json, inference.json, runs.json; page links; framing rules.

Run from the repository root:  python -m pytest tracker/tests/test_site_data.py -q
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

BANNED_FRAMING = re.compile(r"\b(misreport\w*|under-?report\w*|evasion|fraud\w*|nowcast(?:ed|ing)? of true)\b", re.I)
# literature.html and corpus.json quote the titles of published papers (some are about tariff evasion); they are
# not the tracker's own framing and are left out of the scan.
PUBLIC_FILES = [p for p in ROOT.glob("*.html") if p.name not in ("literature.html", "documents.html")]
# documents.html carries the research list (quoting paper titles) below id="research", rendered by research.js; both are exempt there, as literature.html was
PUBLIC_FILES += [ROOT / "documents.html"] + [p for p in (ROOT / "assets" / "js").glob("*.js") if p.name != "research.js"] + \
               [DATA / n for n in ("inference.json", "runs.json", "registry.json")]


def load(name):
    p = DATA / name
    if not p.exists():
        pytest.skip(f"{name} not built")
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- corpus
def test_corpus_schema():
    c = load("corpus.json")
    assert set(c) >= {"meta", "by_country_type", "totals_by_type", "documents"}
    types = c["meta"]["type_order"]
    assert "news" in types and "standards" in types
    assert c["meta"]["n_documents"] == len(c["documents"]) > 0
    for d in c["documents"]:
        assert d["type"] in types
        assert re.fullmatch(r"[A-Z]{3}", d["country"])
        assert d["words"] is None or d["words"] >= 0
        assert len(d["title"]) > 3 and not re.search(r"[\u2500-\u257F\u00B1\u03A6]", d["title"]), d["title"]
    # totals equal the sum over documents
    for k in types:
        assert c["totals_by_type"][k]["documents"] == sum(1 for d in c["documents"] if d["type"] == k)
        assert c["totals_by_type"][k]["words"] == sum(d["words"] or 0 for d in c["documents"] if d["type"] == k)
    # by-country cells sum to totals
    for k in types:
        assert sum(v[k]["documents"] for v in c["by_country_type"].values()) == c["totals_by_type"][k]["documents"]


def test_corpus_has_no_document_text():
    c = load("corpus.json")
    big = [d for d in c["documents"] if any(isinstance(v, str) and len(v) > 400 for v in d.values())]
    assert not big, "a document row carries a long string; only titles and sources belong here"


# ---------------------------------------------------------------- registry
def test_registry_schema_and_sums():
    r = load("registry.json")
    n = r["meta"]["n_vessels"]
    assert n > 0
    assert sum(v["active"] + v["deleted"] for v in r["by_flag_status"].values()) == n
    assert sum(sum(v.values()) for v in r["by_flag_type_group"].values()) == n
    assert sum(sum(v.values()) for v in r["by_flag_address_hint"].values()) == n
    assert sum(r["by_vessel_type"].values()) == n
    assert sum(r["ais_match"].values()) == n
    assert sum(r["built_decade"].values()) == n
    assert set(r["by_flag_status"]) <= {"Kiribati", "Nauru", "Tuvalu", "Other"}


def test_registry_has_no_identifiers_or_names():
    r = load("registry.json")
    text = json.dumps(r)
    assert not re.search(r"\b\d{7}\b", text), "7-digit number (IMO-like) in registry.json"
    assert not re.search(r"\b\d{9}\b", text), "9-digit number (MMSI-like) in registry.json"
    for word in ("Ltd", "Limited", "Co.", "Corporation", "Inc", "Fishing Co", "Marine Co"):
        assert word not in text, f"operator word {word!r} in registry.json"
    master = os.environ.get("FLEET_VESSEL_MASTER")
    if master and Path(master).exists():
        low = text.lower()
        rows = [x for x in csv.DictReader(open(master, encoding="utf-8-sig")) if x.get("VID", "").strip()]
        for col in ("Name of fishing vessel", "Name of the owner or owners", "Name of the master"):
            for x in rows:
                name = (x.get(col) or "").strip().lower()
                if len(name) >= 5:
                    assert name not in low, f"{col} value appears in registry.json"


# ---------------------------------------------------------------- inference
def test_inference_schema_and_reconciliation():
    inf = load("inference.json")
    ids = [l["id"] for l in inf["layers"]]
    assert ids == ["L1_valuation", "L2_nonresident_operated", "L3_other_origin_coding", "L4_unrecorded_routes", "L5_treatment", "L6_other"]
    assert inf["meta"]["n_agents"] >= 5
    for p in inf["periods"]:
        assert [l["id"] for l in p["layers"]] == ids
        for l in p["layers"]:
            assert l["p10"] <= l["p50"] <= l["p90"]
            assert l["min"] <= l["p10"] and l["p90"] <= l["max"]
        e = p["end"]
        assert e["p10"] <= e["p50"] <= e["p90"]
        assert len(e["values"]) == inf["meta"]["n_agents"]
        # mean of layers reconciles with mean end value
        assert abs(p["start"]["value"] + sum(l["mean"] for l in p["layers"]) - e["mean"]) < 0.05
        assert abs(sum(e["values"]) / len(e["values"]) - e["mean"]) < 0.02
        assert 0 < p["share_of_start"]["mean"] < 1.5
    assert len(inf["official_use"]) == inf["meta"]["n_agents"]
    assert all(len(p["statement"]) > 10 for p in inf["principles"])


def test_inference_has_no_names():
    inf = load("inference.json")
    text = json.dumps(inf)
    for word in ("Ltd", "Limited", "Co.,", "Corporation", "Inc.", "Fishing Co", "Marine Co", "Pte"):
        assert word not in text, f"operator word {word!r} in inference.json"
    assert not re.search(r"\b\d{7}\b", text)


# ---------------------------------------------------------------- runs
def test_runs_log():
    runs = load("runs.json")["runs"]
    assert runs and all({"id", "date", "label", "n_agents", "inputs", "status", "superseded"} <= set(r) for r in runs)
    assert sum(1 for r in runs if not r["superseded"]) >= 1
    inf = load("inference.json")
    current = [r for r in runs if r["output"] == "data/inference.json"]
    assert current and current[0]["n_agents"] >= inf["meta"]["n_agents"]


# ---------------------------------------------------------------- pages
def test_no_banned_framing_in_public_files():
    for p in PUBLIC_FILES:
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8", errors="replace")
        if p.name == "documents.html":
            txt = txt.split('id="research"')[0]  # research list is exempt, as literature.html was
        m = BANNED_FRAMING.search(txt)
        assert not m, f"{p.name}: {m.group(0)!r}"


def test_local_links_resolve():
    for page in ROOT.glob("*.html"):
        html = page.read_text(encoding="utf-8", errors="replace")
        for href in re.findall(r'href="([^"#?]+)(?:[#?][^"]*)?"', html):
            if href.startswith(("http", "mailto:")) or "'" in href:   # template strings inside scripts
                continue
            assert (ROOT / href).exists(), f"{page.name} links to missing {href}"
        for src in re.findall(r'<script src="([^"]+)"', html):
            if src.startswith("http"):
                continue
            assert (ROOT / src).exists(), f"{page.name} loads missing {src}"


def test_every_page_has_the_same_nav():
    navs = {}
    for page in ROOT.glob("*.html"):
        if page.name == "literature.html":
            continue
        html = page.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'<nav class="topnav".*?</nav>', html, re.S)
        assert m, f"{page.name} has no top navigation"
        links = re.findall(r'href="([^"]+)"', m.group(0))
        navs[page.name] = links
    first = next(iter(navs.values()))
    for name, links in navs.items():
        assert links == first, f"{name} nav differs"
