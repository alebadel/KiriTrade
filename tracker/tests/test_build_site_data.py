"""Tests for tracker/build_site_data.py (plain pytest).

    cd site && python -m pytest tracker/tests -q

Most tests run on a small synthetic fixture built here. The integration tests
at the end run only when the owner's pipeline inputs are present at
``_inputs/KiriTrade`` (or $KIR_TRACKER_INPUTS) and check the published numbers
against the 9 Oct 2026 bullet points.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))          # site/
from tracker import build_site_data as b             # noqa: E402

INPUTS = Path(os.environ.get("KIR_TRACKER_INPUTS", HERE.parents[2] / "_inputs" / "KiriTrade"))
SITE_DATA = HERE.parents[1] / "data"


# --------------------------------------------------------------------------- #
# Synthetic fixture
# --------------------------------------------------------------------------- #
def _row(period, reporter, flow, cmd, value, side, partner=296, rname=None, riso=None):
    return {"period": period, "refYear": int(period[:4]), "refMonth": int(period[4:]),
            "reporterCode": reporter, "reporterDesc": rname or str(reporter), "reporterISO": riso or "",
            "partnerCode": partner, "partnerDesc": "Kiribati" if partner == 296 else str(partner),
            "cmdCode": cmd, "aggrLevel": 6, "flowCode": flow, "primaryValue": value, "side": side}


KIR_MONTHS = ["2023-10", "2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04", "2024-05", "2024-06",
              "2024-08", "2024-09", "2024-10", "2024-11", "2024-12",
              "2025-01", "2025-02", "2025-04", "2025-05", "2025-06"]     # 2024-07 and 2025-03 missing
ALL_MONTHS = b.month_range("2023-10", "2025-06")


@pytest.fixture(scope="module")
def fixture():
    rows = []
    for m in KIR_MONTHS:
        p = m.replace("-", "")
        # Kiribati's own returns
        rows.append(_row(p, 296, "X", "151311", 400_000.0, "self", partner=36, rname="Kiribati", riso="KIR"))
        rows.append(_row(p, 296, "X", "030342", 100_000.0, "self", partner=392, rname="Kiribati", riso="KIR"))
        rows.append(_row(p, 296, "M", "100630", 900_000.0, "self", partner=764, rname="Kiribati", riso="KIR"))
        rows.append(_row(p, 296, "M", "271019", 2_000_000.0, "self", partner=702, rname="Kiribati", riso="KIR"))
        # Mirror: Thailand buys tuna (exports), Australia sells food and fuel (imports), Japan both
        rows.append(_row(p, 764, "M", "030343", 5_000_000.0, "mirror", rname="Thailand", riso="THA"))
        rows.append(_row(p, 764, "X", "170114", 300_000.0, "mirror", rname="Thailand", riso="THA"))
        rows.append(_row(p, 36, "X", "020130", 1_000_000.0, "mirror", rname="Australia", riso="AUS"))
        rows.append(_row(p, 36, "X", "271019", 500_000.0, "mirror", rname="Australia", riso="AUS"))
        rows.append(_row(p, 392, "M", "030342", 700_000.0, "mirror", rname="Japan", riso="JPN"))
        rows.append(_row(p, 392, "X", "890120", 2_000_000.0 if p == "202405" else 10_000.0, "mirror",
                         rname="Japan", riso="JPN"))
        rows.append(_row(p, 392, "M", "151311", 150_000.0, "mirror", rname="Japan", riso="JPN"))
        if m <= "2025-03":                     # same rows as in the fish-only pull below
            rows.append(_row(p, 608, "M", "030119", 50_000.0, "mirror", rname="Philippines", riso="PHL"))
        # a small reporter below the threshold
        rows.append(_row(p, 208, "X", "040210", 5_000.0, "mirror", rname="Denmark", riso="DNK"))
    # a World row and an HS4 row that must be dropped
    rows.append(_row("202401", 296, "M", "100630", 5_000_000.0, "self", partner=0, rname="Kiribati"))
    rows.append({**_row("202401", 764, "M", "0303", 9_000_000.0, "mirror"), "aggrLevel": 4})
    raw = pd.DataFrame(rows)

    fish = []
    for m in ALL_MONTHS:                       # fish pull covers EVERY month, incl. the two Kiribati gaps
        p = m.replace("-", "")
        fish.append({"side": "mirror", "period": p, "reporterCode": 764, "reporterDesc": "Thailand",
                     "partnerCode": 296, "cmdCode": "030343", "value_usd_m": 5.0})
        fish.append({"side": "mirror", "period": p, "reporterCode": 392, "reporterDesc": "Japan",
                     "partnerCode": 296, "cmdCode": "030342", "value_usd_m": 0.7})
        if m <= "2025-03":                     # Philippines publishes with a lag
            fish.append({"side": "mirror", "period": p, "reporterCode": 608, "reporterDesc": "Philippines",
                         "partnerCode": 296, "cmdCode": "030119", "value_usd_m": 0.05})
    fish = pd.DataFrame(fish)
    raw = b.clean_raw(raw)
    fish = b.clean_fish_detail(fish)
    kir = b.kiribati_months_from(raw)
    panel = b.build_panel(raw, window=(2023, 2025))
    cov = b.coverage_from_data(raw, panel, fish, kir, months=ALL_MONTHS, years=[2023, 2024, 2025])
    ser = b.series_from_data(raw, fish, cov, kir)
    man = b.build_manifest(panel, cov, ser, kir, as_of="2025-09-01")
    return {"raw": raw, "fish": fish, "kir": kir, "panel": panel, "cov": cov, "ser": ser, "man": man}


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def test_clean_raw_drops_world_and_non_hs6(fixture):
    raw = fixture["raw"]
    assert (raw["partnerCode"] == 0).sum() == 0
    assert (raw["cmdCode"].str.len() == 6).all()
    assert raw["period"].str.match(r"^\d{4}-\d{2}$").all()


def test_kiribati_months(fixture):
    assert fixture["kir"] == KIR_MONTHS
    assert "2024-07" not in fixture["kir"] and "2025-03" not in fixture["kir"]


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
def test_panel_weights_sum_to_one_per_flow(fixture):
    p = fixture["panel"]
    assert abs(sum(m["w_exports"] for m in p["members"]) - 1.0) < 1e-9
    assert abs(sum(m["w_imports"] for m in p["members"]) - 1.0) < 1e-9
    assert all(0.0 <= m["w_exports"] <= 1.0 and 0.0 <= m["w_imports"] <= 1.0 for m in p["members"])


def test_panel_membership_rule(fixture):
    p = fixture["panel"]
    codes = {m["code"] for m in p["members"]}
    assert set(b.ALWAYS_INCLUDE) <= codes, "always-include list must be in the panel"
    assert 208 not in codes, "Denmark is below 0.5% in the fixture and not on the always-include list"
    thai = next(m for m in p["members"] if m["code"] == 764)
    assert thai["w_exports"] > 0.8 and thai["meets_threshold"]
    tw = next(m for m in p["members"] if m["code"] == 490)
    assert tw["w_exports"] == 0.0 and tw["w_imports"] == 0.0 and tw["always_include"]
    assert p["n_panel"] == len(p["members"]) == len(codes)


def test_panel_exports_weight_uses_partner_flow_M(fixture):
    """Australia only sells to Kiribati (flow X) -> export weight 0, import weight > 0."""
    aus = next(m for m in fixture["panel"]["members"] if m["code"] == 36)
    assert aus["w_exports"] == 0.0 and aus["w_imports"] > 0.3


# --------------------------------------------------------------------------- #
# Coverage (offline)
# --------------------------------------------------------------------------- #
def _check_shares(rows):
    for r in rows:
        for k in ("share_count", "share_w_exports", "share_w_imports"):
            assert r[k] is not None and -1e-9 <= r[k] <= 1 + 1e-9, (r["period"], k, r[k])


def test_coverage_shares_in_unit_interval(fixture):
    cov = fixture["cov"]
    _check_shares(cov["monthly"]); _check_shares(cov["quarterly"]); _check_shares(cov["annual"])
    for r in cov["monthly"]:
        assert r["n_published"] == len(r["published"]) and r["n_published"] + len(r["missing"]) == r["n_panel"]
        assert abs(r["share_count"] - r["n_published"] / r["n_panel"]) < 1e-9
    for r in cov["quarterly"]:
        assert r["partner_months_possible"] == 3 * r["n_panel"]
        assert abs(r["share_count"] - r["partner_months_published"] / r["partner_months_possible"]) < 1e-9


def test_coverage_periods_ascending_and_complete(fixture):
    cov = fixture["cov"]
    ms = [r["period"] for r in cov["monthly"]]
    assert ms == sorted(ms) == ALL_MONTHS
    qs = [r["period"] for r in cov["quarterly"]]
    assert qs == sorted(qs) == b.quarter_range("2023Q4", "2025Q2")
    assert [r["period"] for r in cov["annual"]] == ["2023", "2024", "2025"]


def test_coverage_offline_methods_and_fish_months(fixture):
    cov = {r["period"]: r for r in fixture["cov"]["monthly"]}
    assert cov["2024-07"]["method"] == "partial_fish_only" and cov["2024-07"]["kiribati_reported"] is False
    assert cov["2024-06"]["method"] == "inferred_from_data" and cov["2024-06"]["kiribati_reported"] is True
    # Thailand and Japan have fish rows in 2024-07 -> published; Australia counts via the later-month rule
    assert {764, 392, 36} <= set(cov["2024-07"]["published"])
    # Taiwan (490) never observed -> never published
    assert all(490 in r["missing"] for r in fixture["cov"]["monthly"])
    # Philippines stops after 2025-03 -> missing from 2025-04
    assert 608 in cov["2025-03"]["published"] and 608 in cov["2025-04"]["missing"]
    # Last month: only direct evidence counts
    last = cov["2025-06"]
    assert set(last["published"]) == {764, 392, 36} and last["n_published_direct"] == 3
    # where both sources exist they agree in the fixture -> no discrepancy flagged
    assert fixture["ser"]["meta"]["fish_source_discrepancies"] == []


def test_coverage_annual_basis(fixture):
    ann = {r["period"]: r for r in fixture["cov"]["annual"]}
    assert ann["2024"]["basis"] == "12_monthly_datasets"      # no annual tables in the fixture
    assert 764 in ann["2024"]["published"] and 490 in ann["2024"]["missing"]
    assert ann["2024"]["kiribati_months_reported"] == 11
    assert ann["2025"]["basis"] == "year_in_progress"


# --------------------------------------------------------------------------- #
# Coverage (live, from getDa-style rows)
# --------------------------------------------------------------------------- #
def _availability_fixture():
    rows = []
    for m in b.month_range("2024-01", "2025-05"):
        rows.append({"reporterCode": 764, "period": m.replace("-", ""), "freqCode": "M", "lastReleased": "2025-09-01"})
    for m in b.month_range("2024-01", "2025-07"):
        rows.append({"reporterCode": 392, "period": int(m.replace("-", "")), "freqCode": "M", "lastReleased": "2025-09-10"})
    for m in b.month_range("2024-01", "2024-09"):
        rows.append({"reporterCode": 36, "period": m.replace("-", ""), "freqCode": "M"})
    rows.append({"reporterCode": 156, "period": "2024", "freqCode": "A", "lastReleased": "2025-06-30"})
    rows.append({"reporterCode": 764, "period": "2024", "freqCode": "A"})
    rows.append({"reporterCode": 999, "period": "202401", "freqCode": "M"})      # not in panel -> ignored
    rows.append({"reporterCode": "bad", "period": "202401"})                      # garbage -> ignored
    return rows


def test_coverage_from_availability(fixture):
    panel = fixture["panel"]
    cov = b.coverage_from_availability(_availability_fixture(), panel, fixture["kir"],
                                       months=b.month_range("2024-01", "2025-07"), years=[2024, 2025])
    assert cov["meta"]["method"] == "comtrade_getDa"
    _check_shares(cov["monthly"]); _check_shares(cov["quarterly"]); _check_shares(cov["annual"])
    m = {r["period"]: r for r in cov["monthly"]}
    assert set(m["2024-06"]["published"]) == {764, 392, 36}
    assert set(m["2025-06"]["published"]) == {392}
    assert set(m["2025-07"]["published"]) == {392}
    assert m["2024-06"]["method"] == "comtrade_getDa"
    assert m["2024-07"]["kiribati_reported"] is False and m["2024-06"]["kiribati_reported"] is True
    # weighted shares follow the panel weights
    wx = {p["code"]: p["w_exports"] for p in panel["members"]}
    assert abs(m["2025-06"]["share_w_exports"] - wx[392]) < 1e-9
    # quarterly: 2025Q2 = Thailand 2 months + Japan 3 months
    q = {r["period"]: r for r in cov["quarterly"]}
    assert q["2025Q2"]["partner_months_published"] == 5 and q["2025Q2"]["partner_months_possible"] == 3 * panel["n_panel"]
    assert any(d["code"] == 764 and d["months_missing"] == ["2025-06"] for d in q["2025Q2"]["missing_major"])
    # annual: China via annual dataset, Thailand via annual dataset, Japan via 12 months, Australia (9 months) not
    a = {r["period"]: r for r in cov["annual"]}
    assert a["2024"]["published_basis"]["156"] == "annual_dataset"
    assert a["2024"]["published_basis"]["392"] == "12_monthly_datasets"
    assert 36 in a["2024"]["missing"]
    assert a["2024"]["basis"] == "annual_dataset"
    st = cov["partner_status"]
    assert st["764"]["latest_published_month"] == "2025-05" and st["764"]["last_released"] == "2025-09-01"
    assert st["156"]["latest_published_month"] is None and st["156"]["latest_published_year"] == 2024
    assert "999" not in st


def test_live_and_offline_coverage_share_structure(fixture):
    off = fixture["cov"]
    live = b.coverage_from_availability(_availability_fixture(), fixture["panel"], fixture["kir"],
                                        months=ALL_MONTHS, years=[2023, 2024, 2025])
    for key in ("monthly", "quarterly", "annual"):
        assert set(off[key][0]) - {"n_published_direct"} == set(live[key][0]) - {"n_published_direct"}
        assert [r["period"] for r in off[key]] == [r["period"] for r in live[key]]


# --------------------------------------------------------------------------- #
# Series
# --------------------------------------------------------------------------- #
def test_no_missing_value_coded_as_zero(fixture):
    rows = {r["period"]: r for r in fixture["ser"]["monthly"]}
    for m in ("2024-07", "2025-03"):                    # Kiribati did not report
        r = rows[m]
        assert r["kiribati_reported"] is False and r["partner_all_goods_available"] is False
        for k in b.KIRIBATI_KEYS:
            assert r[k] is None, (m, k, r[k])
        for k in b.PARTNER_ALLGOODS_KEYS:
            assert r[k] is None, (m, k, r[k])
        # but the fish-only pull covers the month
        assert r["exports_partner_tuna"] == pytest.approx(5.7)
        assert r["exports_partner_fish"] is not None and r["n_reporters_fish"] >= 2
    r = rows["2024-06"]
    assert r["exports_kiribati"] == pytest.approx(0.5) and r["imports_kiribati"] == pytest.approx(2.9)
    assert r["exports_partner"] == pytest.approx(5.9) and r["exports_partner_tuna"] == pytest.approx(5.7)
    assert r["exports_partner_copra_oil"] == pytest.approx(0.15)
    assert r["imports_partner"] == pytest.approx(1.0 + 0.5 + 0.3 + 0.01 + 0.005)
    assert r["imports_partner_fuel"] == pytest.approx(0.5) and r["imports_partner_food"] == pytest.approx(1.305)
    ships = rows["2024-05"]
    assert ships["imports_partner_ships_aircraft"] == pytest.approx(2.0)
    assert ships["imports_partner_ex_ships_aircraft"] == pytest.approx(ships["imports_partner"] - 2.0)


def test_series_identities(fixture):
    for r in fixture["ser"]["monthly"]:
        if r["exports_partner"] is not None:
            assert r["exports_partner_ex_fish"] == pytest.approx(r["exports_partner"] - r["exports_partner_fish"])
            assert r["exports_partner_other_fish"] == pytest.approx(r["exports_partner_fish"] - r["exports_partner_tuna"])
            assert r["exports_partner_ex_fish_ships"] == pytest.approx(
                r["exports_partner"] - r["exports_partner_fish"] - r["exports_partner_ships_aircraft"])
        if r["imports_partner"] is not None:
            assert r["imports_partner_ex_ships_aircraft"] == pytest.approx(
                r["imports_partner"] - r["imports_partner_ships_aircraft"])


def test_quarterly_and_annual_equal_sum_of_months(fixture):
    ser = fixture["ser"]
    by_m = {r["period"]: r for r in ser["monthly"]}
    for q in ser["quarterly"]:
        months = [by_m[m] for m in b.quarter_months(q["period"]) if m in by_m]
        for k in b.MONEY_KEYS:
            vals = [r[k] for r in months if r[k] is not None]
            if vals:
                assert q[k] == pytest.approx(sum(vals)), (q["period"], k)
            else:
                assert q[k] is None, (q["period"], k)
        assert q["months_in_period"] == 3
        assert q["kiribati_months_reported"] == sum(1 for r in months if r["kiribati_reported"])
        assert q["months_with_partner_data"] == sum(1 for r in months if r["partner_all_goods_available"])
    q = {r["period"]: r for r in ser["quarterly"]}
    assert q["2024Q3"]["months_with_partner_data"] == 2 and q["2024Q3"]["kiribati_months_reported"] == 2
    assert q["2024Q3"]["exports_kiribati"] == pytest.approx(1.0)              # two months x 0.5
    assert q["2024Q3"]["exports_partner_tuna"] == pytest.approx(3 * 5.7)      # fish pull covers all 3 months
    assert q["2024Q3"]["exports_partner_tuna_same_months"] == pytest.approx(2 * 5.7)
    for a in ser["annual"]:
        months = [by_m[m] for m in b.month_range(f"{a['period']}-01", f"{a['period']}-12") if m in by_m]
        for k in b.MONEY_KEYS:
            vals = [r[k] for r in months if r[k] is not None]
            assert (a[k] == pytest.approx(sum(vals))) if vals else (a[k] is None), (a["period"], k)
        assert a["months_in_period"] == 12


def test_series_periods_ascending_and_keys_consistent(fixture):
    ser = fixture["ser"]
    for key in ("monthly", "quarterly", "annual"):
        ps = [r["period"] for r in ser[key]]
        assert ps == sorted(ps) and len(set(ps)) == len(ps)
        cols = {tuple(sorted(r)) for r in ser[key]}
        assert len(cols) == 1, f"{key}: every row must carry the same keys"
    assert [r["period"] for r in ser["monthly"]] == ALL_MONTHS
    ends = [r["end"] for r in ser["rolling_12m"]]
    assert ends == sorted(ends)
    for k in b.MONEY_KEYS:
        assert k in ser["keys"]


def test_no_trade_balance_anywhere(fixture):
    """No key in any table may be a balance; the only mentions are the notes saying none is computed."""
    for obj in (fixture["cov"], fixture["ser"], fixture["man"], fixture["panel"]):
        for key in ("monthly", "quarterly", "annual", "rolling_12m", "panel", "members", "keys"):
            rows = obj.get(key)
            if isinstance(rows, dict):
                rows = [rows]
            for r in rows or []:
                assert not any("balance" in k.lower() for k in r), (key, [k for k in r if "balance" in k.lower()])


def test_rolling_12m(fixture):
    roll = {r["end"]: r for r in fixture["ser"]["rolling_12m"]}
    r = roll["2025-06"]
    assert r["months"] == 12 and r["exports_partner_tuna"] == pytest.approx(12 * 5.7)
    assert r["exports_partner"] is None, "all-goods window has a gap (2025-03) -> null"
    assert r["months_with_all_goods_data"] == 10 and r["months_with_fish_data"] == 12   # gaps 2024-07, 2025-03
    assert roll["2024-09"]["exports_partner"] is None                        # gap 2024-07 inside the window
    assert roll["2025-06"]["growth_pct"] is None, "no window a year earlier in the fixture"
    assert roll["2024-09"]["exports_partner_fish"] == pytest.approx(roll["2024-09"]["exports_partner_tuna"] + 12 * 0.05)


def test_pct_complete_attached(fixture):
    cov = {r["period"]: r for r in fixture["cov"]["monthly"]}
    for r in fixture["ser"]["monthly"]:
        assert r["pct_complete"] == pytest.approx(cov[r["period"]]["share_count"])
        assert r["pct_complete_w_exports"] == pytest.approx(cov[r["period"]]["share_w_exports"])


# --------------------------------------------------------------------------- #
# Manifest + JSON writing
# --------------------------------------------------------------------------- #
def test_manifest(fixture):
    man = fixture["man"]
    assert man["title"] == "Import and Export Performance Tracker using Comtrade Trade-Partner Data"
    assert man["last_update_mode"] == "offline_rebuild" and man["coverage_method"] == "inferred_from_data"
    assert man["data_through"]["monthly"] == "2025-06" and man["data_through"]["quarterly"] == "2025Q2"
    assert man["kiribati_own_reporting"]["missing_recent"] == ["2024-07", "2025-03"]
    assert man["kiribati_own_reporting"]["latest"] == "2025-06"
    codes = {p["code"] for p in man["panel"]}
    assert codes == {p["code"] for p in fixture["panel"]["members"]}
    thai = next(p for p in man["panel"] if p["code"] == 764)
    assert thai["typical_lag_months"] == 4 and thai["latest_published_month"] == "2025-06"
    tw = next(p for p in man["panel"] if p["code"] == 490)
    assert tw["latest_published_month"] is None and tw["typical_lag_months"] is None
    assert "notes" in tw and "Other Asia" in tw["notes"][0]


def test_write_all_roundtrip(fixture, tmp_path):
    written = b.write_all(tmp_path / "data", fixture["man"], fixture["cov"], fixture["ser"], fixture["panel"],
                          panel_path=tmp_path / "panel.json")
    names = sorted(p.name for p in written)
    assert names == ["coverage.json", "manifest.json", "panel.json", "series.json"]
    for p in written:
        obj = json.loads(p.read_text(encoding="utf-8"))
        assert "meta" in obj and "generated_at" in obj["meta"] and "notes" in obj["meta"]
    ser = json.loads((tmp_path / "data" / "series.json").read_text())
    txt = (tmp_path / "data" / "series.json").read_text()
    assert "NaN" not in txt and "Infinity" not in txt
    r = next(x for x in ser["monthly"] if x["period"] == "2024-07")
    assert r["exports_kiribati"] is None


def test_jsonable_rounding():
    import numpy as np
    out = b._jsonable({"a": 1.23456, "b": float("nan"), "c": np.float64(2.0), "d": np.int64(3), "e": True,
                       "f": {5, 1}, "g": [None, 0.0]})
    assert out == {"a": 1.235, "b": None, "c": 2.0, "d": 3, "e": True, "f": [1, 5], "g": [None, 0.0]}


def test_period_helpers():
    assert b.month_key(201701) == "2017-01" and b.month_key("201712.0") == "2017-12" and b.month_key("2026-07") == "2026-07"
    assert b.month_add("2026-01", -1) == "2025-12" and b.month_add("2026-12", 1) == "2027-01"
    assert b.quarter_of("2026-07") == "2026Q3" and b.quarter_months("2026Q3") == ["2026-07", "2026-08", "2026-09"]
    assert b.quarter_range("2025Q4", "2026Q2") == ["2025Q4", "2026Q1", "2026Q2"]
    assert b.months_between("2026-05", "2026-10") == 5


# --------------------------------------------------------------------------- #
# Integration: real inputs (skipped when absent)
# --------------------------------------------------------------------------- #
needs_inputs = pytest.mark.skipif(not (INPUTS / "data" / "raw" / "kiribati" / "raw_observations.parquet").exists(),
                                  reason="pipeline inputs not present")


@pytest.fixture(scope="module")
def real():
    return b.build_all(INPUTS, "/nonexistent", write=False)


@needs_inputs
def test_real_panel(real):
    p = real["panel"]
    assert abs(sum(m["w_exports"] for m in p["members"]) - 1) < 1e-9
    assert abs(sum(m["w_imports"] for m in p["members"]) - 1) < 1e-9
    assert set(b.ALWAYS_INCLUDE) <= {m["code"] for m in p["members"]}
    thai = next(m for m in p["members"] if m["code"] == 764)
    assert 0.69 < thai["share_exports_all_reporters"] < 0.72        # bullet points: Thailand ~70%


@needs_inputs
def test_real_key_numbers_match_bullet_points(real):
    ann = {r["period"]: r for r in real["series"]["annual"]}
    # Partner tuna 2025: annual table 88.2, monthly-summed 86.9 (project note); 2026 Jan-Jul tuna 23.7
    assert ann["2025"]["exports_partner_tuna_annual_dataset"] == pytest.approx(88.2, abs=0.1)
    assert ann["2025"]["exports_partner_tuna"] == pytest.approx(86.9, abs=0.1)
    assert ann["2026"]["exports_partner_tuna"] == pytest.approx(23.7, abs=0.1)
    assert ann["2026"]["exports_partner_fish"] == pytest.approx(24.4, abs=0.1)
    # BOP reconciliation table: 2025 Kiribati exports 12.0 / imports 206.3; partner exports 79.2, imports 92.7
    assert ann["2025"]["exports_kiribati"] == pytest.approx(12.0, abs=0.1)
    assert ann["2025"]["imports_kiribati"] == pytest.approx(206.3, abs=0.1)
    assert ann["2025"]["exports_partner"] == pytest.approx(79.2, abs=0.1)
    assert ann["2025"]["imports_partner"] == pytest.approx(92.7, abs=0.1)
    assert ann["2025"]["kiribati_months_reported"] == 10 and ann["2025"]["months_with_partner_data"] == 10
    # Pooled Jan 2025-Jul 2026: partners 109.7 vs Kiribati 21.3 (Table 2)
    mon = [r for r in real["series"]["monthly"] if "2025-01" <= r["period"] <= "2026-07"]
    assert sum(r["exports_partner"] or 0 for r in mon) == pytest.approx(109.7, abs=0.1)
    assert sum(r["exports_kiribati"] or 0 for r in mon) == pytest.approx(21.3, abs=0.1)
    assert sum(r["exports_kiribati_tuna"] or 0 for r in mon) == pytest.approx(6.3, abs=0.1)
    # 12 months to May: 100.9 -> 96.3 -> 67.5 (bullet 20)
    roll = {r["end"]: r for r in real["series"]["rolling_12m"]}
    assert roll["2024-05"]["exports_partner_fish"] == pytest.approx(100.9, abs=0.1)
    assert roll["2025-05"]["exports_partner_fish"] == pytest.approx(96.3, abs=0.1)
    assert roll["2026-05"]["exports_partner_fish"] == pytest.approx(67.5, abs=0.1)
    assert roll["2026-05"]["growth_pct"] == pytest.approx(-29.9, abs=0.1)
    # July 2026 aircraft 40.2 in partner-reported imports
    jul = next(r for r in real["series"]["monthly"] if r["period"] == "2026-07")
    assert jul["imports_partner_ships_aircraft"] == pytest.approx(40.2, abs=0.1)


@needs_inputs
def test_real_nulls_and_coverage(real):
    kir = set(real["kiribati_months"])
    assert len(kir) == 70
    for r in real["series"]["monthly"]:
        if r["period"] not in kir:
            assert r["exports_kiribati"] is None and r["imports_kiribati"] is None and r["exports_partner"] is None
            assert r["exports_partner_tuna"] is not None       # fish pull covers every month
    ms = [r["period"] for r in real["coverage"]["monthly"]]
    assert ms[0] == "2017-01" and ms[-1] == "2026-07" and ms == sorted(ms)
    qs = [r["period"] for r in real["coverage"]["quarterly"]]
    assert qs[0] == "2017Q1" and qs[-1] == "2026Q3"
    assert [r["period"] for r in real["coverage"]["annual"]][0] == "2010"
    _check_shares(real["coverage"]["monthly"]); _check_shares(real["coverage"]["quarterly"]); _check_shares(real["coverage"]["annual"])
    st = real["coverage"]["partner_status"]
    assert st["156"]["latest_published_month"] == "2024-12"
    assert st["410"]["latest_published_month"] == "2025-12"
    assert st["702"]["latest_published_month"] == "2026-03"
    assert st["764"]["latest_published_month"] == "2026-05"
    assert st["490"]["latest_published_month"] is None


@pytest.mark.skipif(not (SITE_DATA / "series.json").exists(), reason="site/data not built")
def test_published_json_files_are_consistent():
    cov = json.loads((SITE_DATA / "coverage.json").read_text())
    ser = json.loads((SITE_DATA / "series.json").read_text())
    man = json.loads((SITE_DATA / "manifest.json").read_text())
    panel = json.loads((HERE.parents[1] / "tracker" / "panel.json").read_text())
    assert man["n_panel"] == panel["n_panel"] == cov["monthly"][0]["n_panel"]
    assert man["data_through"]["monthly"] == ser["monthly"][-1]["period"] == cov["monthly"][-1]["period"]
    by_m = {r["period"]: r for r in ser["monthly"]}
    for q in ser["quarterly"]:
        for k in ("exports_partner", "imports_partner", "exports_kiribati", "imports_kiribati", "exports_partner_tuna"):
            vals = [by_m[m][k] for m in b.quarter_months(q["period"]) if m in by_m and by_m[m][k] is not None]
            if vals:
                assert q[k] == pytest.approx(sum(vals), abs=0.002), (q["period"], k)
            else:
                assert q[k] is None
    for r in ser["monthly"]:
        if not r["kiribati_reported"]:
            assert r["exports_kiribati"] is None
    assert "balance" not in json.dumps(ser["keys"]).lower()
