import json, re, subprocess, sys
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tracker"))
import ensemble_tools as et

NC = json.load(open(ROOT / "data/nowcast.json"))

def _draw(**over):
    d = {"principles":[{"id":"P1","statement":"s","source":"x","uncertainty":"u"}]*3,
         "months":[{"period":p,"total":5.0,"component_a":1.0,"component_b":4.0,"lo80":3.0,"hi80":7.0,"rationale":"r","principles_used":["P1"],"evidence_refs":["01"]} for p in et.TARGETS],
         "audit":"ok"}
    d["principles"] = [{"id":f"P{i+1}","statement":"s","source":"x","uncertainty":"u"} for i in range(3)]
    d.update(over); return d

def test_a_plus_b_equals_total_published():
    for r in NC["ensemble"]["months"]:
        assert abs(r["component_a"]["mean"] + r["component_b"]["mean"] - r["total"]["mean"]) < 0.01

def test_interval_ordering_published():
    for r in NC["ensemble"]["months"]:
        t = r["total"]; assert t["p10"] <= t["p50"] <= t["p90"]
    for b in NC["baseline"]["nowcast"]: assert b["lo80_usd_m"] <= b["point_usd_m"] <= b["hi80_usd_m"]

def test_no_names_or_official_figures_in_public_files():
    blob = json.dumps(NC) + open(ROOT/"notes/2026-10-20.md").read()
    assert not et.BANNED.search(blob)
    assert "exports_kiribati" not in blob

def test_valid_draw_accepted(): assert et.check(_draw()) == []
def test_validator_rejects_sum_mismatch():
    d = _draw(); d["months"][0]["component_a"] = 2.0; assert any("A+B" in e for e in et.check(d))
def test_validator_rejects_bad_interval():
    d = _draw(); d["months"][1]["lo80"] = 6.0; assert any("interval" in e for e in et.check(d))
def test_validator_rejects_unknown_principle_ref():
    d = _draw(); d["months"][2]["principles_used"] = ["P9"]; assert any("principle refs" in e for e in et.check(d))
def test_validator_rejects_name_pattern():
    d = _draw(); d["months"][0]["rationale"] = "MV Something sold fish"; assert "name pattern" in et.check(d)
def test_validator_rejects_wrong_months():
    d = _draw(); d["months"] = d["months"][:5]; assert et.check(d)

def test_tier0_empty_pack_draw_still_validates():
    # a run with no evidence cites only principle ids and evidence file 00; validator must accept it
    d = _draw()
    for m in d["months"]: m["evidence_refs"] = ["00"]
    assert et.check(d) == []

def test_pack_has_no_kiribati_own_series():
    for f in (ROOT / "GPS/ensemble/evidence_20261020").glob("0[1-4]*.json") if (ROOT/"GPS/ensemble/evidence_20261020").exists() else []:
        assert "exports_kiribati" not in f.read_text()
