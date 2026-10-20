"""Tests for tracker/build_fleet_data.py and the fleet layer (data/fleet.json, fleet.html).

Run from the site root:   python -m pytest tracker/tests/test_build_fleet_data.py -q

Three groups:
  1. builder logic on a tiny synthetic GPS/out folder (always runs);
  2. schema, aggregates-only and framing checks on the committed data/fleet.json
     and the fleet page files (always runs);
  3. reconciliation against the real GPS/out CSVs (runs only where that folder exists:
     set FLEET_GPS_OUT or keep GPS/ next to the site folder).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

SITE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SITE / "tracker"))

import build_fleet_data as bf  # noqa: E402

FLEET_JSON = SITE / "data" / "fleet.json"
_env = os.environ.get("FLEET_GPS_OUT")
GPS_OUT = Path(_env) if _env else SITE.parent / "GPS" / "out"
HAVE_GPS = (GPS_OUT / "fishing_monthly_windowed.csv").exists()

ALLOWED_KEYS = {
    "meta", "generated_at", "ais_through", "rfv_export_date", "partial_month",
    "n_kir_flag_vessels_with_fishing_hours", "ais_source", "register_source", "units", "hours",
    "port_calls", "notes", "monthly", "period", "kir_hours_total", "kir_hours_kir_eez",
    "kir_hours_other", "port_calls_quarterly", "quarter", "KIR", "CHN", "KOR", "THA", "other",
    "total", "chain_facts", "chain_facts_kir", "n_encounters", "n_followed_by_tha_call",
    "tha_share_pct", "lag_median_days", "lag_p25", "lag_p75", "tha_window_days", "scope",
}
# operator / company / vessel-series words that must never reach the site
FORBIDDEN_WORDS = [
    "sajo", "silla", "hansung", "maribo", "kibena", "blue pacific", "kiribati tuna fishing",
    "kiritimati island fish", "yun run", "fengrun", "manzai", "tudo fisheries",
]
BANNED_FRAMING = ["misreport", "under-report", "underreport", "evasion", "evade", "licence fee",
                  "license fee", "licensing fee", "nowcast"]


# ----------------------------------------------------------------- synthetic fixture
def _write(df, path):
    df.to_csv(path, index=False, encoding="utf-8-sig")


@pytest.fixture()
def gps(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    master = pd.DataFrame([
        {"gfw_vessel_id": "v-kir", "gfw_flag": "KIR", "Flag of fishing vessel": "KI", "match_method": "IRCS"},
        {"gfw_vessel_id": "v-kir2", "gfw_flag": "PAN", "Flag of fishing vessel": "KI", "match_method": "IMO"},
        {"gfw_vessel_id": "v-nru", "gfw_flag": "NRU", "Flag of fishing vessel": "NR", "match_method": "IRCS"},
    ])
    _write(master, out / "vessel_master.csv")
    _write(pd.DataFrame([
        {"gfw_vessel_id": "v-kir", "vessel": "X", "source": "flag_segments",
         "start": "2025-01-01 00:00:00+00:00", "end": ""},
        {"gfw_vessel_id": "v-kir2", "vessel": "Y", "source": "flag_segments",
         "start": "2025-02-01 00:00:00+00:00", "end": "2025-05-31 00:00:00+00:00"},
    ]), out / "registration_windows.csv")
    _write(pd.DataFrame([
        {"vessel_id": "v-kir", "vessel_name": "A", "month": "2025-01", "eez": "8488", "hours": 100.0},
        {"vessel_id": "v-kir", "vessel_name": "A", "month": "2025-01", "eez": "8324", "hours": 50.0},
        {"vessel_id": "v-kir2", "vessel_name": "B", "month": "2025-03", "eez": "8450", "hours": 10.0},
        {"vessel_id": "v-nru", "vessel_name": "C", "month": "2025-02", "eez": "8488", "hours": 999.0},
    ]), out / "fishing_monthly_windowed.csv")
    _write(pd.DataFrame([
        # inside window, China
        {"vessel_id": "v-kir", "start": "2025-02-10T00:00:00.000Z", "end": "2025-02-11T00:00:00.000Z", "port_flag": "CHN"},
        # before the window -> trimmed
        {"vessel_id": "v-kir", "start": "2024-12-10T00:00:00.000Z", "end": "2024-12-11T00:00:00.000Z", "port_flag": "THA"},
        # inside window, home port
        {"vessel_id": "v-kir", "start": "2025-04-02T00:00:00.000Z", "end": "2025-04-03T00:00:00.000Z", "port_flag": "KIR"},
        # outside v-kir2 window (after end) -> trimmed
        {"vessel_id": "v-kir2", "start": "2025-09-02T00:00:00.000Z", "end": "2025-09-03T00:00:00.000Z", "port_flag": "KOR"},
        # unknown port flag -> other
        {"vessel_id": "v-kir2", "start": "2025-03-02T00:00:00.000Z", "end": "2025-03-03T00:00:00.000Z", "port_flag": ""},
        # not a KIR-flag vessel
        {"vessel_id": "v-nru", "start": "2025-03-02T00:00:00.000Z", "end": "2025-03-03T00:00:00.000Z", "port_flag": "CHN"},
    ]), out / "events_port_visits.csv")
    _write(pd.DataFrame([
        {"catcher_id": "v-kir", "tha_port_name": "BANGKOK", "days_to_tha_port": 30.0},
        {"catcher_id": "v-kir", "tha_port_name": "", "days_to_tha_port": 50.0},   # blank port name still counts
        {"catcher_id": "v-kir", "tha_port_name": "", "days_to_tha_port": ""},
        {"catcher_id": "v-nru", "tha_port_name": "", "days_to_tha_port": ""},
    ]), out / "shipment_chain_windowed.csv")
    _write(pd.DataFrame([{"end": "2025-06-15T00:00:00.000Z"}]), out / "events_fishing.csv")
    (out / "Rfv_database_export_1792367500.csv").write_text("x\n")
    return out


def test_builder_logic(gps):
    js = bf.build(gps)
    m = {r["period"]: r for r in js["monthly"]}
    # only KIR-flag vessels (v-kir, v-kir2 via the register flag), none of the NRU hours
    assert m["2025-01"]["kir_hours_total"] == 150.0
    assert m["2025-01"]["kir_hours_kir_eez"] == 100.0 and m["2025-01"]["kir_hours_other"] == 50.0
    assert m["2025-02"]["kir_hours_total"] == 0.0            # gap month filled with zero, NRU hours excluded
    assert m["2025-03"]["kir_hours_kir_eez"] == 10.0
    assert js["meta"]["n_kir_flag_vessels_with_fishing_hours"] == 2
    q = {r["quarter"]: r for r in js["port_calls_quarterly"]}
    assert q["2025Q1"]["CHN"] == 1 and q["2025Q1"]["THA"] == 0     # December THA call trimmed (before window)
    assert q["2025Q1"]["other"] == 1                               # blank port flag
    assert q["2025Q2"]["KIR"] == 1
    assert "2025Q3" not in q and "2024Q4" not in q                  # calls outside register tenure are trimmed
    assert all(r["total"] == sum(r[k] for k in ("KIR", "CHN", "KOR", "THA", "other")) for r in q.values())
    cf = js["chain_facts"]
    assert cf["n_encounters"] == 4 and cf["n_followed_by_tha_call"] == 2
    assert cf["tha_share_pct"] == 50.0 and cf["lag_median_days"] == 40.0
    assert js["chain_facts_kir"]["n_encounters"] == 3
    assert js["meta"]["rfv_export_date"] == "2026-10-18"
    assert js["meta"]["ais_through"] == "2025-09-02"   # latest event in the feed, any vessel


def test_builder_output_has_only_whitelisted_keys(gps):
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert set(keys(bf.build(gps))) <= ALLOWED_KEYS


# ----------------------------------------------------------------- committed fleet.json
@pytest.fixture(scope="module")
def fleet():
    if not FLEET_JSON.exists():
        pytest.skip("data/fleet.json not built yet")
    return json.loads(FLEET_JSON.read_text(encoding="utf-8"))


def test_schema(fleet):
    assert set(fleet) >= {"meta", "monthly", "port_calls_quarterly", "chain_facts"}
    meta = fleet["meta"]
    for k in ("ais_through", "rfv_export_date", "notes"):
        assert k in meta
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta["ais_through"])
    assert isinstance(meta["notes"], list) and meta["notes"]
    mon = fleet["monthly"]
    assert mon and all(set(r) == {"period", "kir_hours_total", "kir_hours_kir_eez", "kir_hours_other"} for r in mon)
    periods = [r["period"] for r in mon]
    assert periods == [str(p) for p in pd.period_range(periods[0], periods[-1], freq="M")], "months must be contiguous"
    for r in mon:
        assert r["kir_hours_total"] >= 0 and r["kir_hours_kir_eez"] >= 0 and r["kir_hours_other"] >= 0
        assert abs(r["kir_hours_total"] - r["kir_hours_kir_eez"] - r["kir_hours_other"]) < 0.25
    q = fleet["port_calls_quarterly"]
    assert q and all({"quarter", "KIR", "CHN", "KOR", "THA", "other"} <= set(r) for r in q)
    for r in q:
        assert r["total"] == sum(r[k] for k in ("KIR", "CHN", "KOR", "THA", "other"))
    cf = fleet["chain_facts"]
    assert {"tha_share_pct", "lag_median_days", "lag_p25", "lag_p75", "n_encounters"} <= set(cf)
    assert 0 <= cf["tha_share_pct"] <= 100 and cf["lag_p25"] <= cf["lag_median_days"] <= cf["lag_p75"]
    assert meta["ais_through"][:7] >= periods[-1]


def test_keys_are_aggregates_only(fleet):
    def keys(o):
        if isinstance(o, dict):
            for k, v in o.items():
                yield k
                yield from keys(v)
        elif isinstance(o, list):
            for v in o:
                yield from keys(v)
    assert set(keys(fleet)) <= ALLOWED_KEYS


# ----------------------------------------------------------------- no identifiers, framing
SITE_FILES = ["data/fleet.json", "fleet.html", "assets/js/fleet.js"]


def _site_text():
    texts = {}
    for rel in SITE_FILES:
        p = SITE / rel
        if p.exists():
            texts[rel] = p.read_text(encoding="utf-8")
    meth = SITE / "methods.html"
    if meth.exists():
        t = meth.read_text(encoding="utf-8")
        m = re.search(r"<!--\s*FLEET-METHODS-START\s*-->(.*?)<!--\s*FLEET-METHODS-END\s*-->", t, re.S)
        if m:
            texts["methods.html#fleet"] = m.group(1)
    return texts


def test_no_identifiers_on_site():
    texts = _site_text()
    if not texts:
        pytest.skip("no fleet files yet")
    for rel, t in texts.items():
        low = t.lower()
        for w in FORBIDDEN_WORDS:
            assert w not in low, f"{rel}: forbidden word {w!r}"
        assert not re.search(r"\b\d{9}\b", t), f"{rel}: 9-digit number (MMSI-like)"
        assert not re.search(r"\bIMO\s*\d{7}\b", t, re.I), f"{rel}: IMO number"
        assert not re.search(r"[0-9a-f]{8,9}-[0-9a-f]{4}-[0-9a-f]{4}", low), f"{rel}: GFW/uuid-like id"


def test_framing_rules():
    texts = _site_text()
    if not texts:
        pytest.skip("no fleet files yet")
    for rel, t in texts.items():
        low = t.lower()
        for w in BANNED_FRAMING:
            assert w not in low, f"{rel}: banned framing term {w!r}"


@pytest.mark.skipif(not HAVE_GPS, reason="GPS/out not available here")
def test_no_vessel_or_company_names_from_the_real_data():
    texts = _site_text()
    master = pd.read_csv(GPS_OUT / "vessel_master.csv", dtype=str, encoding_errors="replace", encoding="utf-8-sig")
    names = set()
    for c in ("gfw_shipname", "Name of fishing vessel", "Name of the owner or owners", "Name of charterer",
              "gfw_owner", "Name of the master"):
        if c in master:
            names |= {str(x).strip().lower() for x in master[c].dropna() if len(str(x).strip()) >= 6}
    # generic words that are not identifying on their own
    names -= {"kiribati", "unknown", "none", "n/a"}
    for rel, t in texts.items():
        low = re.sub(r"\s+", " ", t.lower())
        hits = [n for n in names if n in low]
        assert not hits, f"{rel}: contains vessel/company names, e.g. {hits[:3]}"


# ----------------------------------------------------------------- reconciliation with the CSVs
@pytest.mark.skipif(not HAVE_GPS, reason="GPS/out not available here")
def test_monthly_reconciles_to_csv(fleet):
    built = bf.build(GPS_OUT)
    assert [r for r in built["monthly"]] == fleet["monthly"], "fleet.json is stale: rerun build_fleet_data.py"
    assert built["port_calls_quarterly"] == fleet["port_calls_quarterly"]
    assert built["chain_facts"] == fleet["chain_facts"]


@pytest.mark.skipif(not HAVE_GPS, reason="GPS/out not available here")
def test_monthly_matches_bridge_panel(fleet):
    bp = pd.read_csv(GPS_OUT / "bridge_panel.csv", encoding="utf-8-sig", dtype={"month": str})
    bp["hours_KIR"] = pd.to_numeric(bp["hours_KIR"], errors="coerce").fillna(0.0)
    mon = {r["period"]: r["kir_hours_total"] for r in fleet["monthly"]}
    for _, r in bp.iterrows():
        assert abs(mon.get(r["month"], 0.0) - r["hours_KIR"]) < 0.2, r["month"]


@pytest.mark.skipif(not HAVE_GPS, reason="GPS/out not available here")
def test_totals_match_windowed_csv(fleet):
    h = pd.read_csv(GPS_OUT / "fishing_monthly_windowed.csv", encoding="utf-8-sig", dtype={"month": str, "eez": str})
    master = pd.read_csv(GPS_OUT / "vessel_master.csv", dtype=str, encoding_errors="replace", encoding="utf-8-sig")
    flags = bf.vessel_flags(master)
    kir = h[h["vessel_id"].map(flags) == "KIR"]
    assert abs(kir["hours"].sum() - sum(r["kir_hours_total"] for r in fleet["monthly"])) < 5.0
    home = kir[kir["eez"].isin(bf.KIR_EEZ)]["hours"].sum()
    assert abs(home - sum(r["kir_hours_kir_eez"] for r in fleet["monthly"])) < 5.0
    ch = pd.read_csv(GPS_OUT / "shipment_chain_windowed.csv", encoding="utf-8-sig", dtype=str)
    assert fleet["chain_facts"]["n_encounters"] == len(ch)
