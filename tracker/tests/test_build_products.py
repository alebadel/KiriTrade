"""Tests for tracker/build_products.py (Agent E).

Run from site/:   python -m pytest tracker/tests/test_build_products.py -q

The tests run against the committed inputs (tracker/data/raw parquet,
tracker/data/static_e CSVs, tracker/data/bop_extract.csv) so they work in
GitHub Actions without `_inputs`.  When `_inputs` is present the BOP tests
also read the workbook directly.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[2]
TRACKER = SITE / "tracker"
sys.path.insert(0, str(TRACKER))

import build_products as bp  # noqa: E402

INPUTS = Path("/home/claude/kir-tracker/_inputs")
PIPELINE = INPUTS / "KiriTrade" if (INPUTS / "KiriTrade").exists() else TRACKER
BOP_XLSX = INPUTS / "KIR_BOP.xlsx" if (INPUTS / "KIR_BOP.xlsx").exists() else None
MT_XLSX = INPUTS / "KIR_MT.xlsx" if (INPUTS / "KIR_MT.xlsx").exists() else None


@pytest.fixture(scope="module")
def na():
    return bp.build_national_accounts(BOP_XLSX, MT_XLSX, PIPELINE)


@pytest.fixture(scope="module")
def peers():
    return bp.build_peers(PIPELINE)


@pytest.fixture(scope="module")
def products():
    return bp.build_products(PIPELINE)


def row(na, year):
    return next(r for r in na["annual"] if r["year"] == year)


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, o


# ---------------------------------------------------------------- BOP 2025
def test_bop_2025_values(na):
    r = row(na, 2025)
    assert r["bop_goods_exports"] == pytest.approx(17.3, abs=0.05)
    assert r["bop_goods_imports"] == pytest.approx(270.4, abs=0.3)      # 270.6 in the earlier vintage
    assert r["bop_fishing_licence_fees"] == pytest.approx(130.6, abs=0.05)
    assert r["months_kiribati_reported"] == 10
    assert r["customs_exports_kiribati"] == pytest.approx(12.0, abs=0.06)
    assert r["customs_imports_kiribati"] == pytest.approx(206.3, abs=0.05)
    assert r["customs_exports_kiribati_scaled12"] == pytest.approx(14.5, abs=0.05)
    assert r["customs_imports_kiribati_scaled12"] == pytest.approx(247.5, abs=0.05)
    assert r["partner_exports"] == pytest.approx(79.2, abs=0.05)
    assert r["partner_exports_ex_tuna"] == pytest.approx(5.5, abs=0.06)
    assert r["partner_imports"] == pytest.approx(92.7, abs=0.05)
    assert r["partner_imports_ex_ships_aircraft"] == pytest.approx(90.3, abs=0.05)
    assert r["gdp_usd"] == pytest.approx(349.3, abs=0.05)


def test_bop_2024_values(na):
    r = row(na, 2024)
    assert r["bop_goods_exports"] == pytest.approx(8.5, abs=0.05)
    assert r["bop_goods_imports"] == pytest.approx(226.6, abs=0.05)
    assert r["months_kiribati_reported"] == 10
    # the USD 3.1bn prefabricated-buildings line is set aside, not hidden
    assert r["customs_imports_kiribati_as_published"] > 3000
    assert r["customs_imports_kiribati"] < 200
    assert na["meta"]["excluded_lines"][0]["hs6"] == "940690"


def test_bop_series_covers_2006_2025(na):
    years = [r["year"] for r in na["annual"] if r["bop_goods_exports"] is not None]
    assert years[0] == 2006 and years[-1] == 2025 and len(years) == 20


def test_scaled12_identity(na):
    for r in na["annual"]:
        if r["months_kiribati_reported"] and r["customs_exports_kiribati"] is not None:
            assert r["customs_exports_kiribati_scaled12"] == pytest.approx(
                r["customs_exports_kiribati"] * 12 / r["months_kiribati_reported"], abs=0.002)


def test_pct_gdp_only_where_gdp(na):
    for r in na["annual"]:
        if r["gdp_usd"] is None:
            assert r["pct_gdp"] == {}
        else:
            assert r["pct_gdp"]["bop_goods_exports"] == pytest.approx(
                r["bop_goods_exports"] / r["gdp_usd"] * 100, abs=0.06)


def test_bop_extract_csv_matches_workbook():
    csv_path = TRACKER / "data" / "bop_extract.csv"
    assert csv_path.exists()
    import pandas as pd
    d = pd.read_csv(csv_path).set_index("year")
    assert set(d.columns) == {"bop_goods_exports", "bop_goods_imports", "bop_fishing_licence_fees", "gdp_usd"}
    assert d.loc[2025, "bop_goods_exports"] == pytest.approx(17.342, abs=0.001)
    if BOP_XLSX:
        wb = bp.read_bop(BOP_XLSX).set_index("year")
        assert wb.loc[2024, "bop_goods_imports"] == pytest.approx(d.loc[2024, "bop_goods_imports"], abs=1e-4)


# ---------------------------------------------------------------- products
def test_categories_sum_to_total(products):
    cats = products["categories"]
    parts = [c for c in cats if not c["is_total"]]
    total = next(c for c in cats if c["is_total"])
    assert len(parts) == 5
    assert sum(c["partners"] for c in parts) == pytest.approx(total["partners"], abs=0.01)
    assert sum(c["kiribati"] for c in parts) == pytest.approx(total["kiribati"], abs=0.01)
    assert total["partners"] == pytest.approx(109.7, abs=0.1)
    assert total["kiribati"] == pytest.approx(21.3, abs=0.1)
    tuna = next(c for c in parts if c["category"] == "Tuna")
    assert tuna["kiribati"] == pytest.approx(6.3, abs=0.05)
    assert tuna["handout_partners"] == 100.8          # the handout value is kept alongside
    copra = next(c for c in parts if c["category"] == "Copra and coconut oil")
    assert copra["kiribati"] > copra["partners"]      # runs the other way


def test_hs4_tables_have_top15_other_total(products):
    for direction in ("exports", "imports"):
        ann = products[direction]["annual"]
        assert set(ann) == {"2017", "2018", "2020", "2023", "2024", "2025", "2026"}
        for y, rows in ann.items():
            assert rows[-1]["hs4"] == "total" and rows[-2]["hs4"] == "other"
            detail = [r for r in rows if not r["is_summary"]]
            assert len(detail) == 15
            tot = rows[-1]
            assert sum((r["partner"] or 0) for r in rows[:-1]) == pytest.approx(tot["partner"], abs=0.01)
            assert sum((r["kiribati"] or 0) for r in rows[:-1]) == pytest.approx(tot["kiribati"], abs=0.01)
            for r in detail:
                assert r["label"] and not r["label"].startswith("HS ")
        l12 = products[direction]["latest_12m"]
        assert l12["end"] == "2026-07" and l12["months_in_window"] == 11
        assert l12["months_without_kiribati_return"] == ["2025-10"]


def test_table4_and_bullet14_match_handout(products):
    assert all(r["matches_handout"] for r in products["ships_aircraft"])
    seiners = next(r for r in products["ships_aircraft"] if r["type"].startswith("Fishing vessels (purse"))
    assert seiners["value"] == pytest.approx(108.3, abs=0.05) and seiners["units"] == 5
    mo = {(r["direction"], r["hs6"]): r for r in products["mirror_only_notable"]}
    assert mo[("import", "880240")]["partners"] == pytest.approx(40.2, abs=0.05)
    assert mo[("export", "030119")]["partners"] == pytest.approx(0.89, abs=0.01)
    assert mo[("export", "030819")]["window"].startswith("2026")
    assert sum(1 for r in products["mirror_only_notable"] if r["matches_handout"]) >= 10


def test_staples_present(products):
    s = products["staples"]
    assert set(s) == {"rice", "sugar"}
    rice25 = next(r for r in s["rice"]["annual"] if r["year"] == 2025)
    assert rice25["kiribati_monthly"] > 10 and rice25["partner_monthly"] < 1
    sugar24 = next(r for r in s["sugar"]["annual"] if r["year"] == 2024)
    assert 5 <= sugar24["partner_monthly"] <= 6.5


# ---------------------------------------------------------------- peers
def test_peers_15_rows_7_pna(peers):
    app = peers["applicability"]
    assert len(app) == 15
    assert sum(1 for a in app if a["pna"]) == 7
    assert {a["country"] for a in app if a["pna"]} == {
        "Kiribati", "Micronesia (FS)", "Nauru", "Palau", "Papua New Guinea", "Solomon Islands", "Tuvalu"}
    k = next(a for a in app if a["is_subject"])
    assert k["exp_ratio"] == pytest.approx(6.58) and k["ratio_year"] == 2025
    assert k["exp_mirror_usd_m"] == 95.1 and k["exp_own_usd_m"] == 14.5
    assert k["own_source"] == "monthly x12/10"
    mdv = next(a for a in app if a["iso3"] == "MDV")
    assert mdv["exp_ratio"] == pytest.approx(1.62) and mdv["exp_ratio_incl_ships_aircraft"] == pytest.approx(2.6, abs=0.1)


def test_tuna_by_origin(peers):
    t = peers["tuna_by_origin"]
    assert t["years"] == list(range(2010, 2026))
    assert len(t["countries"]) == 7
    k = next(c for c in t["countries"] if c["is_subject"])
    assert k["name"] == "Kiribati" and k["change_2015_2025_pct"] == pytest.approx(-26, abs=0.5)
    assert all(len(c["values"]) == 16 for c in t["countries"])
    fsm = next(c for c in t["countries"] if c["iso3"] == "FSM")
    assert "240" in fsm["note"] or "239" in fsm["note"]
    nru = next(c for c in t["countries"] if c["iso3"] == "NRU")
    assert nru["change_2015_2025_pct"] is None and "reflag" in nru["note"]


# ---------------------------------------------------------------- hygiene
def test_no_negative_values_and_no_balance(na, peers, products):
    for name, d in (("na", na), ("peers", peers), ("products", products)):
        for path, v in walk(d):
            assert "balance" not in path.lower(), path
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if "change_2015_2025" in path:
                continue
            assert v >= 0, (name, path, v)
            assert not math.isnan(v), (name, path)


def test_json_files_validate(tmp_path):
    paths = bp.write_all(tmp_path, INPUTS if INPUTS.exists() else None,
                         None if INPUTS.exists() else TRACKER)
    for key in ("national_accounts", "peers", "products"):
        d = json.loads(paths[key].read_text(encoding="utf-8"))
        assert "meta" in d and "generated_at" in d["meta"] and isinstance(d["meta"]["notes"], list)
    na = json.loads(paths["national_accounts"].read_text())
    assert {"annual", "quarterly", "notes"} <= set(na)
    pe = json.loads(paths["peers"].read_text())
    assert {"tuna_by_origin", "applicability", "notes"} <= set(pe)
    pr = json.loads(paths["products"].read_text())
    assert {"categories", "exports", "imports", "mirror_only_notable", "ships_aircraft", "staples", "notes"} <= set(pr)
    for d in (pr["exports"], pr["imports"]):
        assert {"annual", "latest_12m"} <= set(d)
