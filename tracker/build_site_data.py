#!/usr/bin/env python3
"""Build the tracker's data files from the Comtrade mirror pipeline outputs.

    python tracker/build_site_data.py --inputs /path/to/KiriTrade --out site/data

Produces (owner: Agent A):

    site/data/coverage.json   percent complete per month / quarter / year
    site/data/series.json     partner-reported and Kiribati-reported series
    site/data/manifest.json   panel, lags, Kiribati's own reporting calendar
    site/tracker/panel.json   the partner panel and its weights

Everything is read relative to the ``--inputs`` root in the layout the
pipeline writes (``data/raw/<country>/raw_observations.parquet``,
``data/out/<country>/fish/*.csv`` ...), so a live refresh that rewrites those
files can call :func:`build_all` (or the individual functions) unchanged.

Public functions
----------------
load_inputs(inputs_root)                     -> dict of DataFrames
build_panel(raw, window=(2023, 2025))        -> dict (panel.json content)
coverage_from_data(raw, panel, fish_detail, kiribati_months)      -> dict  (OFFLINE)
coverage_from_availability(rows, panel, kiribati_months)          -> dict  (LIVE)
series_from_data(raw, fish_detail, coverage, kiribati_months, ...) -> dict
build_manifest(...)                          -> dict
write_all(out_dir, manifest, coverage, series, panel, panel_path) -> list[Path]
build_all(inputs_root, out_dir, ...)         -> dict of everything

Units: USD millions. ``null`` = not available / not published, never 0.
No trade balance is computed anywhere in this module, by design.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
from pathlib import Path
from typing import Iterable

import pandas as pd

# --------------------------------------------------------------------------- #
# Definitions (recorded in the JSON meta so the UI can show them)
# --------------------------------------------------------------------------- #
SUBJECT_CODE = 296            # Kiribati, M49
SUBJECT_NAME = "Kiribati"

# Follows comtrade_mirror/fish.py::TUNA exactly.
TUNA_HS6 = frozenset({"030341", "030342", "030343", "030344", "030345",
                      "030346", "030349", "030487", "160414"})
FISH_PREFIXES = ("03", "1604")            # chapter 03 + heading 1604
COPRA_OIL_HS6 = frozenset({"151311", "151319"})
SHIPS_AIRCRAFT_HS2 = frozenset({"88", "89"})
FUEL_HS2 = frozenset({"27"})
FOOD_HS2 = frozenset({f"{c:02d}" for c in range(1, 25) if c != 3})

# Kiribati-reported single lines above this value (USD) in one month are
# flagged. Kiribati's whole annual GDP is about USD 350 million, so a single
# customs line ten times that size is shown as published but also set aside
# in a separate series so chart scales stay readable. Only one line in the
# data triggers it (January 2024, HS 940690, USD 3,135 million).
FLAGGED_LINE_USD = 1.0e9

PANEL_THRESHOLD = 0.005       # 0.5 % of partner-reported exports OR imports
DEFAULT_WINDOW = (2023, 2025)
DEFAULT_MONTHLY_START = "2017-01"
DEFAULT_ANNUAL_START = 2010

# Always-include list from the shared brief: code -> (Comtrade name, ISO3, short label)
ALWAYS_INCLUDE: dict[int, tuple[str, str, str]] = {
    36:  ("Australia", "AUS", "Australia"),
    554: ("New Zealand", "NZL", "New Zealand"),
    242: ("Fiji", "FJI", "Fiji"),
    156: ("China", "CHN", "China"),
    392: ("Japan", "JPN", "Japan"),
    764: ("Thailand", "THA", "Thailand"),
    410: ("Rep. of Korea", "KOR", "Korea"),
    702: ("Singapore", "SGP", "Singapore"),
    842: ("USA", "USA", "United States"),
    490: ("Other Asia, nes", "TWN", "Taiwan Province of China"),
    608: ("Philippines", "PHL", "Philippines"),
    360: ("Indonesia", "IDN", "Indonesia"),
    458: ("Malaysia", "MYS", "Malaysia"),
    699: ("India", "IND", "India"),
    344: ("China, Hong Kong SAR", "HKG", "Hong Kong SAR"),
    170: ("Colombia", "COL", "Colombia"),
}
SHORT_LABELS = {code: v[2] for code, v in ALWAYS_INCLUDE.items()}
SHORT_LABELS.update({724: "Spain", 380: "Italy", 208: "Denmark", 124: "Canada",
                     218: "Ecuador", 251: "France", 276: "Germany", 826: "United Kingdom"})

# Publication lags stated in the shared brief / bullet points (months from the
# reference month to the month the data are usable). Others are observed.
KNOWN_LAG_MONTHS = {764: 4, 392: 2}

# Date of the pipeline pull the offline inputs come from (bullet points handout,
# 9 Oct 2026). Only used to turn "latest published month" into an observed lag.
DEFAULT_AS_OF = "2026-10-09"

SOURCE = "UN Comtrade (partner-reported and Kiribati-reported HS6 monthly data)"


# --------------------------------------------------------------------------- #
# Period helpers
# --------------------------------------------------------------------------- #
def month_key(p) -> str:
    """'201701' / 201701 / 201701.0 / '2017-01' -> '2017-01'."""
    s = str(p).strip()
    if s.endswith(".0"):
        s = s[:-2]
    if "-" in s:
        return s[:7]
    return f"{s[:4]}-{s[4:6]}"


def month_add(m: str, k: int) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    i = y * 12 + (mo - 1) + k
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def months_between(a: str, b: str) -> int:
    """Number of months from a to b (b - a)."""
    return (int(b[:4]) * 12 + int(b[5:7])) - (int(a[:4]) * 12 + int(a[5:7]))


def month_range(start: str, end: str) -> list[str]:
    out, m = [], start
    while m <= end:
        out.append(m)
        m = month_add(m, 1)
    return out


def quarter_of(m: str) -> str:
    return f"{m[:4]}Q{(int(m[5:7]) - 1) // 3 + 1}"


def quarter_months(q: str) -> list[str]:
    y, n = int(q[:4]), int(q[5])
    return [f"{y:04d}-{(n - 1) * 3 + i:02d}" for i in (1, 2, 3)]


def quarter_range(start_q: str, end_q: str) -> list[str]:
    out, y, n = [], int(start_q[:4]), int(start_q[5])
    while f"{y}Q{n}" <= end_q:
        out.append(f"{y}Q{n}")
        n += 1
        if n == 5:
            y, n = y + 1, 1
    return out


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _r(x, nd: int = 3):
    """Round for JSON; None/NaN -> None."""
    if x is None:
        return None
    try:
        if isinstance(x, float) and math.isnan(x):
            return None
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(x), nd)


def _meta(notes: list[str], **extra) -> dict:
    m = {"generated_at": _now_iso(), "source": SOURCE, "notes": list(notes)}
    m.update(extra)
    return m


# --------------------------------------------------------------------------- #
# Loading and cleaning
# --------------------------------------------------------------------------- #
def clean_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise the raw observations: HS6 leaf rows only, no World rows."""
    d = raw.copy()
    d["period"] = d["period"].map(month_key)
    d["cmdCode"] = d["cmdCode"].astype(str).str.strip().str.zfill(6)
    d = d[d["cmdCode"].str.upper() != "TOTAL"]
    if "aggrLevel" in d.columns and d["aggrLevel"].notna().any():
        d = d[pd.to_numeric(d["aggrLevel"], errors="coerce") == 6]
    else:
        d = d[d["cmdCode"].str.len() == 6]
    d = d[pd.to_numeric(d["partnerCode"], errors="coerce") != 0]
    for c in ("reporterCode", "partnerCode"):
        d[c] = pd.to_numeric(d[c], errors="coerce").astype("Int64")
    d["primaryValue"] = pd.to_numeric(d["primaryValue"], errors="coerce")
    d = d[d["primaryValue"].notna()]
    d["hs2"] = d["cmdCode"].str[:2]
    d["value_usd_m"] = d["primaryValue"] / 1e6
    return d.reset_index(drop=True)


def clean_fish_detail(fish: pd.DataFrame) -> pd.DataFrame:
    d = fish.copy()
    d["period"] = d["period"].map(month_key)
    d["cmdCode"] = d["cmdCode"].astype(str).str.strip().str.zfill(6)
    d["reporterCode"] = pd.to_numeric(d["reporterCode"], errors="coerce").astype("Int64")
    if "value_usd_m" not in d.columns:
        d["value_usd_m"] = pd.to_numeric(d["primaryValue"], errors="coerce") / 1e6
    d["value_usd_m"] = pd.to_numeric(d["value_usd_m"], errors="coerce")
    d = d[d["value_usd_m"].notna()]
    if "side" in d.columns:
        d = d[d["side"].astype(str) == "mirror"]
    if "partnerCode" in d.columns:
        d = d[pd.to_numeric(d["partnerCode"], errors="coerce") == SUBJECT_CODE]
    d["is_tuna"] = d["cmdCode"].isin(TUNA_HS6)
    return d.reset_index(drop=True)


def load_inputs(inputs_root: str | os.PathLike, country: str = "kiribati") -> dict:
    """Read every input the builder uses, relative to the pipeline root."""
    root = Path(inputs_root)

    def first(*cands: Path) -> Path:
        for c in cands:
            if c.exists():
                return c
        return cands[0]

    # Primary layout = the owner's pipeline root (_inputs/KiriTrade). Fallbacks cover the
    # live layout under site/tracker (Agent B's data/ folder and Agent E's static copies).
    paths = {
        "raw": root / "data" / "raw" / country / "raw_observations.parquet",
        "fish_detail": root / "data" / "out" / country / "fish" / "fish_mirror_monthly_detail.csv",
        "fish_annual_by_reporter": root / "data" / "out" / country / "fish" / "fish_mirror_annual_by_reporter.csv",
        "fish_annual": root / "data" / "out" / country / "fish" / "fish_mirror_annual.csv",
        "ships_annual": first(root / "data" / "out" / country / "ships_hs6_annual_2.csv",
                              root / "data" / "static_e" / "data" / "out" / country / "ships_hs6_annual_2.csv"),
        "availability_self": first(root / f"availability_{country}.csv",
                                   root / "data" / f"availability_{country}.csv"),
    }
    out: dict = {"paths": {k: str(v) for k, v in paths.items()}, "files": {}}
    for k, p in paths.items():
        if p.exists():
            st = p.stat()
            out["files"][k] = {"path": str(p.relative_to(root)), "bytes": st.st_size,
                               "modified": _dt.datetime.fromtimestamp(st.st_mtime, _dt.timezone.utc)
                               .replace(microsecond=0).isoformat().replace("+00:00", "Z")}
    out["raw"] = clean_raw(pd.read_parquet(paths["raw"]))
    out["fish_detail"] = clean_fish_detail(
        pd.read_csv(paths["fish_detail"], dtype={"cmdCode": str, "period": str}))
    out["fish_annual_by_reporter"] = (pd.read_csv(paths["fish_annual_by_reporter"])
                                      if paths["fish_annual_by_reporter"].exists() else None)
    out["fish_annual"] = pd.read_csv(paths["fish_annual"]) if paths["fish_annual"].exists() else None
    out["ships_annual"] = pd.read_csv(paths["ships_annual"]) if paths["ships_annual"].exists() else None
    out["availability_self"] = (pd.read_csv(paths["availability_self"], dtype={"period": str})
                                if paths["availability_self"].exists() else None)
    return out


def kiribati_months_from(raw: pd.DataFrame, availability_self: pd.DataFrame | None = None) -> list[str]:
    """Months for which Kiribati's own return exists (self side present)."""
    months = set(raw.loc[raw["side"] == "self", "period"].unique())
    if availability_self is not None and "period" in availability_self.columns:
        months |= {month_key(p) for p in availability_self["period"] if len(str(p)) >= 6}
    return sorted(months)


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
def _reporter_names(raw: pd.DataFrame) -> dict[int, tuple[str, str]]:
    names: dict[int, tuple[str, str]] = {}
    m = raw[raw["side"] == "mirror"]
    for code, g in m.groupby("reporterCode"):
        row = g.iloc[0]
        names[int(code)] = (str(row.get("reporterDesc", code)), str(row.get("reporterISO", "")))
    return names


def build_panel(raw: pd.DataFrame, window: tuple[int, int] = DEFAULT_WINDOW,
                threshold: float = PANEL_THRESHOLD,
                always_include: dict[int, tuple[str, str, str]] | None = None) -> dict:
    """The partner panel and its weights.

    Membership: share >= ``threshold`` of partner-reported Kiribati exports OR
    imports in the window, plus the always-include list. Weights: each
    member's share of partner-reported value in the window, separately for
    exports (reporter flow M, partner 296) and imports (reporter flow X),
    renormalised so the panel's weights sum to one per flow. The un-normalised
    share of all reporters is kept alongside.
    """
    always = ALWAYS_INCLUDE if always_include is None else always_include
    y0, y1 = window
    m = raw[(raw["side"] == "mirror") & (raw["partnerCode"] == SUBJECT_CODE)].copy()
    m["year"] = m["period"].str[:4].astype(int)
    w = m[(m["year"] >= y0) & (m["year"] <= y1)]
    ex = w[w["flowCode"] == "M"].groupby("reporterCode")["value_usd_m"].sum()
    im = w[w["flowCode"] == "X"].groupby("reporterCode")["value_usd_m"].sum()
    ex_tot, im_tot = float(ex.sum()), float(im.sum())
    ex_share = (ex / ex_tot) if ex_tot > 0 else ex * 0
    im_share = (im / im_tot) if im_tot > 0 else im * 0

    by_threshold = set(ex_share[ex_share >= threshold].index.astype(int)) | \
        set(im_share[im_share >= threshold].index.astype(int))
    codes = sorted(by_threshold | set(always))
    names = _reporter_names(raw)

    members = []
    for c in codes:
        name, iso = names.get(c, (always.get(c, (str(c), "", str(c)))[0], always.get(c, ("", "", ""))[1]))
        if c in always and (not iso or iso.startswith("S")):
            iso = always[c][1]
        members.append({
            "code": int(c), "name": name, "iso3": iso,
            "label": SHORT_LABELS.get(c, name),
            "share_exports_all_reporters": float(ex_share.get(c, 0.0)),
            "share_imports_all_reporters": float(im_share.get(c, 0.0)),
            "value_exports_window_usd_m": float(ex.get(c, 0.0)),
            "value_imports_window_usd_m": float(im.get(c, 0.0)),
            "always_include": c in always,
            "meets_threshold": c in by_threshold,
        })
    sx = sum(p["share_exports_all_reporters"] for p in members) or 1.0
    si = sum(p["share_imports_all_reporters"] for p in members) or 1.0
    for p in members:
        p["w_exports"] = p["share_exports_all_reporters"] / sx
        p["w_imports"] = p["share_imports_all_reporters"] / si
    members.sort(key=lambda p: -(p["w_exports"] + p["w_imports"]))

    return {
        "meta": _meta([
            f"Reference window {y0}-{y1}. A reporter joins the panel if it accounts for at least "
            f"{threshold:.1%} of partner-reported Kiribati exports or imports in the window, or is on the "
            "always-include list.",
            "w_exports / w_imports are the panel members' shares of partner-reported value in the window, "
            "renormalised to sum to one across the panel. share_*_all_reporters are the raw shares of all "
            "reporters, before renormalisation.",
            "Exports weights come from partners' imports from Kiribati (reporter flow M, partner 296); "
            "imports weights from partners' exports to Kiribati (reporter flow X, partner 296).",
            "Other Asia, nes (code 490, shown as Taiwan Province of China) is on the always-include list but "
            "has no monthly rows with partner Kiribati in these data; its weights are zero.",
        ]),
        "subject": {"code": SUBJECT_CODE, "name": SUBJECT_NAME},
        "reference_window": {"start": y0, "end": y1},
        "threshold_share": threshold,
        "window_totals_usd_m": {"exports": ex_tot, "imports": im_tot,
                                "panel_exports": float(sum(p["value_exports_window_usd_m"] for p in members)),
                                "panel_imports": float(sum(p["value_imports_window_usd_m"] for p in members))},
        "n_panel": len(members),
        "members": members,
    }


def _weights(panel: dict) -> tuple[dict[int, float], dict[int, float]]:
    wx = {p["code"]: float(p["w_exports"]) for p in panel["members"]}
    wi = {p["code"]: float(p["w_imports"]) for p in panel["members"]}
    return wx, wi


def _names(panel: dict) -> dict[int, str]:
    return {p["code"]: p.get("label") or p["name"] for p in panel["members"]}


# --------------------------------------------------------------------------- #
# Coverage: shared assembly
# --------------------------------------------------------------------------- #
def _assemble_coverage(published_by_month: dict[str, set[int]],
                       annual_published: dict[int, dict[int, str]],
                       panel: dict, kiribati_months: list[str],
                       months: list[str], years: list[int],
                       month_method: dict[str, str], method_label: str,
                       notes: list[str],
                       direct_by_month: dict[str, set[int]] | None = None,
                       partner_months_published_by_year: dict[int, int] | None = None) -> dict:
    """Turn 'who published what' into the coverage.json structure.

    published_by_month: month -> set of panel codes counted as published.
    annual_published:   year  -> {code: basis} for partners counted as published.
    """
    wx, wi = _weights(panel)
    names = _names(panel)
    codes = sorted(wx)
    n_panel = len(codes)
    kir = set(kiribati_months)
    major = {c for c in codes if max(wx[c], wi[c]) >= 0.01} | {c for c in codes if c in ALWAYS_INCLUDE}

    monthly = []
    for m in months:
        pub = sorted(published_by_month.get(m, set()) & set(codes))
        miss = [c for c in codes if c not in pub]
        row = {
            "period": m, "n_panel": n_panel, "n_published": len(pub),
            "share_count": len(pub) / n_panel if n_panel else None,
            "share_w_exports": sum(wx[c] for c in pub),
            "share_w_imports": sum(wi[c] for c in pub),
            "published": pub, "missing": miss,
            "kiribati_reported": m in kir,
            "method": month_method.get(m, method_label),
        }
        if direct_by_month is not None:
            row["n_published_direct"] = len(direct_by_month.get(m, set()) & set(codes))
        monthly.append(row)
    by_month = {r["period"]: r for r in monthly}

    quarters = quarter_range(quarter_of(months[0]), quarter_of(months[-1]))
    quarterly = []
    for q in quarters:
        qm = quarter_months(q)
        pub_months = sum(by_month[m]["n_published"] for m in qm if m in by_month)
        possible = 3 * n_panel
        miss_major = []
        for c in codes:
            mm = [m for m in qm if c not in published_by_month.get(m, set())]
            if mm and c in major:
                miss_major.append({"code": c, "name": names[c], "months_missing": mm})
        miss_major.sort(key=lambda d: -(wx[d["code"]] + wi[d["code"]]))
        quarterly.append({
            "period": q, "months": qm, "n_panel": n_panel,
            "partner_months_possible": possible, "partner_months_published": pub_months,
            "share_count": pub_months / possible if possible else None,
            "share_w_exports": sum(by_month[m]["share_w_exports"] for m in qm if m in by_month) / 3,
            "share_w_imports": sum(by_month[m]["share_w_imports"] for m in qm if m in by_month) / 3,
            "missing_major": miss_major,
            "months_with_data": sum(1 for m in qm if m in by_month),
            "kiribati_months_reported": sum(1 for m in qm if m in kir),
        })

    annual = []
    last_month = months[-1]
    for y in years:
        ap = annual_published.get(y, {})
        pub = sorted(c for c in ap if c in wx)
        bases = {ap[c] for c in pub}
        basis = "annual_dataset" if "annual_dataset" in bases else "12_monthly_datasets"
        ym = [m for m in months if m.startswith(str(y))]
        pm_pub = (partner_months_published_by_year or {}).get(
            y, sum(by_month[m]["n_published"] for m in ym if m in by_month))
        in_progress = (y == int(last_month[:4])) and not last_month.endswith("-12")
        row = {
            "period": str(y), "n_panel": n_panel, "n_published": len(pub),
            "share_count": len(pub) / n_panel if n_panel else None,
            "share_w_exports": sum(wx[c] for c in pub),
            "share_w_imports": sum(wi[c] for c in pub),
            "published": pub, "missing": [c for c in codes if c not in pub],
            "published_basis": {str(c): ap[c] for c in pub},
            "kiribati_months_reported": sum(1 for m in kir if m.startswith(str(y))),
            "basis": basis,
            "partner_months_possible": 12 * n_panel,
            "partner_months_published": pm_pub,
            "share_count_partner_months": pm_pub / (12 * n_panel) if n_panel else None,
            "months_elapsed": len(ym),
        }
        if in_progress:
            # No annual dataset can exist yet: show the year filling up, like an unfinished quarter.
            seen = sorted({c for m in ym for c in published_by_month.get(m, set()) if c in wx})
            row.update({
                "basis": "year_in_progress",
                "n_published": len(seen), "published": seen,
                "missing": [c for c in codes if c not in seen],
                "published_basis": {str(c): "at_least_one_month" for c in seen},
                "share_count": pm_pub / (12 * n_panel) if n_panel else None,
                "share_w_exports": sum(by_month[m]["share_w_exports"] for m in ym if m in by_month) / 12,
                "share_w_imports": sum(by_month[m]["share_w_imports"] for m in ym if m in by_month) / 12,
            })
        annual.append(row)

    return {
        "meta": _meta(notes, method=method_label, n_panel=n_panel,
                      panel_codes=codes,
                      definitions={
                          "share_count": "number of panel partners whose dataset for the period is published, divided by the panel size",
                          "share_w_exports": "same, weighting each partner by its share of partner-reported Kiribati exports in the reference window",
                          "share_w_imports": "same, weighting by share of partner-reported Kiribati imports",
                          "quarterly": "partner-months published / partner-months possible (3 per partner, also for an unfinished quarter)",
                          "annual": "a partner counts as published for a year if its annual dataset exists, or at least 10 of its 12 monthly datasets do; for the current, unfinished year (basis 'year_in_progress') the shares are partner-months published / (12 x panel), so the year fills up like an unfinished quarter",
                      }),
        "monthly": monthly, "quarterly": quarterly, "annual": annual,
    }


# --------------------------------------------------------------------------- #
# Coverage: OFFLINE method (inferred from the data we have)
# --------------------------------------------------------------------------- #
def _reporter_label_map(panel: dict) -> dict[str, int]:
    """Comtrade reporter names -> panel code (annual by-reporter tables carry names only)."""
    out = {}
    for p in panel["members"]:
        out[p["name"]] = p["code"]
        if p["code"] in ALWAYS_INCLUDE:
            out[ALWAYS_INCLUDE[p["code"]][0]] = p["code"]
    return out


def coverage_from_data(raw: pd.DataFrame, panel: dict, fish_detail: pd.DataFrame,
                       kiribati_months: list[str], months: list[str] | None = None,
                       years: list[int] | None = None,
                       fish_annual_by_reporter: pd.DataFrame | None = None,
                       ships_annual: pd.DataFrame | None = None,
                       later_month_rule: bool = True) -> dict:
    """Infer publication status from the rows we hold (no API access).

    A panel partner counts as published for month m if it has at least one
    mirror row (either flow) in m in ``raw``, or at least one row in
    ``fish_detail`` for m (direct evidence). With ``later_month_rule`` (default)
    it also counts as published if it has direct evidence for any later month,
    since Comtrade releases are cumulative. Months without a full mirror pull
    (the months Kiribati did not report) rely on the fish rows plus the
    later-month rule and are labelled ``partial_fish_only``.

    Limitations (also written to meta.notes): a partner that published a
    dataset containing no trade with Kiribati looks unpublished here; small
    partners therefore read as missing more often than they are. The live
    method (:func:`coverage_from_availability`) replaces this.
    """
    wx, _ = _weights(panel)
    codes = set(wx)
    kir = sorted(set(kiribati_months))
    kir_set = set(kir)
    m = raw[(raw["side"] == "mirror") & (raw["partnerCode"] == SUBJECT_CODE)]
    f = fish_detail
    if months is None:
        last = max([m["period"].max(), f["period"].max()] if len(f) else [m["period"].max()])
        months = month_range(DEFAULT_MONTHLY_START, last)
    if years is None:
        years = list(range(DEFAULT_ANNUAL_START, int(months[-1][:4]) + 1))

    direct: dict[str, set[int]] = {mm: set() for mm in months}
    for code, g in m.groupby("reporterCode"):
        if int(code) in codes:
            for p in g["period"].unique():
                direct.setdefault(p, set()).add(int(code))
    for code, g in f.groupby("reporterCode"):
        if int(code) in codes:
            for p in g["period"].unique():
                direct.setdefault(p, set()).add(int(code))

    latest_direct = {c: max((p for p, s in direct.items() if c in s), default=None) for c in codes}
    published: dict[str, set[int]] = {}
    for mm in months:
        s = set(direct.get(mm, set()))
        if later_month_rule:
            s |= {c for c in codes if latest_direct[c] is not None and latest_direct[c] > mm}
        published[mm] = s

    month_method = {mm: ("inferred_from_data" if mm in kir_set else "partial_fish_only") for mm in months}

    # Annual evidence: fish annual by reporter (names), ships annual by reporter (names)
    label_to_code = _reporter_label_map(panel)
    annual_evidence: dict[int, set[int]] = {}
    if fish_annual_by_reporter is not None and len(fish_annual_by_reporter):
        t = fish_annual_by_reporter.set_index(fish_annual_by_reporter.columns[0])
        for name, row in t.iterrows():
            c = label_to_code.get(str(name))
            if c is None:
                continue
            for col, v in row.items():
                try:
                    y, val = int(str(col)[:4]), float(v)
                except (TypeError, ValueError):
                    continue
                if val > 0:
                    annual_evidence.setdefault(y, set()).add(c)
    if ships_annual is not None and len(ships_annual) and {"period", "reporter"} <= set(ships_annual.columns):
        for _, r in ships_annual.iterrows():
            c = label_to_code.get(str(r["reporter"]))
            if c is None:
                continue
            try:
                y = int(str(r["period"])[:4])
            except ValueError:
                continue
            if len(str(r["period"])) == 4:
                annual_evidence.setdefault(y, set()).add(c)

    latest_year_evidence = {
        c: max([y for y, s in annual_evidence.items() if c in s]
               + ([int(latest_direct[c][:4])] if latest_direct[c] else []), default=None)
        for c in codes}
    annual_published: dict[int, dict[int, str]] = {}
    for y in years:
        ap: dict[int, str] = {}
        for c in sorted(codes):
            n_months = sum(1 for mm in months if mm.startswith(str(y)) and c in published[mm])
            if c in annual_evidence.get(y, set()):
                ap[c] = "annual_dataset"
            elif n_months >= 10:
                ap[c] = "12_monthly_datasets"
            elif later_month_rule and latest_year_evidence[c] is not None and latest_year_evidence[c] > y:
                ap[c] = "inferred_from_later_period"
        annual_published[y] = ap

    notes = [
        "OFFLINE method (inferred_from_data). Publication status is inferred from the rows the pipeline "
        "holds: a partner counts as published for a month if it has at least one row with partner Kiribati "
        "in that month (any flow, or in the fish-only pull), or in any later month (Comtrade releases are "
        "cumulative).",
        "A partner that published a dataset recording no trade with Kiribati in a month is indistinguishable "
        "from one that has not published; small partners therefore read as 'missing' more often than they "
        "really are, and the shares shown are a lower bound on true coverage.",
        "Months Kiribati did not report (2019, 2021, 2022-01..2023-05, 2024-07, 2024-09, 2025-03, 2025-10) have "
        "no all-goods mirror pull; their status rests on the fish-only pull and the later-month rule and is "
        "labelled 'partial_fish_only'. Partners never observed (Other Asia, nes) count as not published.",
        "Annual: a partner counts as published for a year if it appears in that year's annual fish or ships "
        "by-reporter table, or if at least 10 of its 12 months are counted as published.",
        "The live refresh replaces this with Comtrade's data-availability service (coverage_method "
        "'comtrade_getDa'), which answers the question directly.",
    ]
    out = _assemble_coverage(published, annual_published, panel, kir, months, years,
                             month_method, "inferred_from_data", notes, direct_by_month=direct)
    out["partner_status"] = {
        str(c): {"latest_published_month": latest_direct[c],
                 "latest_published_year": max([y for y, ap in annual_published.items()
                                               if c in ap and ap[c] != "inferred_from_later_period"], default=None),
                 "latest_year_annual_dataset": max([y for y, s in annual_evidence.items() if c in s], default=None)}
        for c in sorted(codes)
    }
    return out


# --------------------------------------------------------------------------- #
# Coverage: LIVE method (Comtrade getDa rows)
# --------------------------------------------------------------------------- #
def coverage_from_availability(availability_rows: Iterable[dict], panel: dict,
                               kiribati_months: list[str], months: list[str] | None = None,
                               years: list[int] | None = None,
                               monthly_start: str = DEFAULT_MONTHLY_START,
                               annual_start: int = DEFAULT_ANNUAL_START) -> dict:
    """Coverage from Comtrade's data-availability (getDa) records.

    ``availability_rows``: iterable of dicts with at least ``reporterCode`` and
    ``period`` (``YYYYMM`` for monthly, ``YYYY`` for annual); ``freqCode``
    ('M'/'A') and ``lastReleased`` are used when present. Rows for reporters
    outside the panel are ignored. The month list defaults to monthly_start ..
    the latest month in ``kiribati_months`` or in the rows, whichever is later.
    """
    wx, _ = _weights(panel)
    codes = set(wx)
    kir = sorted(set(month_key(x) for x in kiribati_months))
    monthly_sets: dict[int, set[str]] = {c: set() for c in codes}
    annual_sets: dict[int, set[int]] = {c: set() for c in codes}
    last_released: dict[int, str | None] = {c: None for c in codes}
    for r in availability_rows:
        try:
            c = int(r.get("reporterCode"))
        except (TypeError, ValueError):
            continue
        if c not in codes:
            continue
        p = str(r.get("period") or r.get("refPeriodId") or "").strip()
        if p.endswith(".0"):
            p = p[:-2]
        freq = str(r.get("freqCode") or ("A" if len(p) == 4 else "M")).upper()
        if freq == "M" and len(p) >= 6:
            monthly_sets[c].add(month_key(p[:6]))
        elif freq == "A" and len(p) >= 4:
            annual_sets[c].add(int(p[:4]))
        lr = r.get("lastReleased")
        if lr:
            lr = str(lr)[:10]
            if last_released[c] is None or lr > last_released[c]:
                last_released[c] = lr

    all_m = [m for s in monthly_sets.values() for m in s]
    last = max([kir[-1] if kir else monthly_start] + all_m)
    if months is None:
        months = month_range(monthly_start, last)
    if years is None:
        years = list(range(annual_start, int(months[-1][:4]) + 1))

    published = {m: {c for c in codes if m in monthly_sets[c]} for m in months}
    annual_published: dict[int, dict[int, str]] = {}
    for y in years:
        ap = {}
        for c in sorted(codes):
            if y in annual_sets[c]:
                ap[c] = "annual_dataset"
            elif sum(1 for m in months if m.startswith(str(y)) and m in monthly_sets[c]) >= 10:
                ap[c] = "12_monthly_datasets"
        annual_published[y] = ap

    notes = [
        "LIVE method (comtrade_getDa). A partner counts as published for a month when Comtrade's "
        "data-availability service lists that reporter-month dataset; for a year when the annual dataset is "
        "listed or at least 10 of the 12 monthly datasets are.",
        "This answers 'has the partner published?' directly, whether or not the dataset contains trade with "
        "Kiribati.",
    ]
    out = _assemble_coverage(published, annual_published, panel, kir, months, years,
                             {m: "comtrade_getDa" for m in months}, "comtrade_getDa", notes)
    out["partner_status"] = {
        str(c): {"latest_published_month": max(monthly_sets[c]) if monthly_sets[c] else None,
                 "latest_published_year": max(annual_sets[c]) if annual_sets[c] else None,
                 "last_released": last_released[c],
                 "n_monthly_datasets": len(monthly_sets[c])}
        for c in sorted(codes)
    }
    return out


# --------------------------------------------------------------------------- #
# Series
# --------------------------------------------------------------------------- #
SERIES_KEYS: dict[str, str] = {
    "exports_partner": "Partner-reported exports from Kiribati, all goods (what partners say they bought from Kiribati)",
    "exports_partner_tuna": "Partner-reported exports: tuna (frozen skipjack, yellowfin, bigeye, albacore and other tunas, frozen tuna fillets, canned tuna)",
    "exports_partner_fish": "Partner-reported exports: all fish and seafood (HS chapter 03 and heading 1604)",
    "exports_partner_other_fish": "Partner-reported exports: fish and seafood other than tuna",
    "exports_partner_copra_oil": "Partner-reported exports: coconut (copra) oil",
    "exports_partner_ships_aircraft": "Partner-reported exports: ships and aircraft (HS 88-89)",
    "exports_partner_ex_fish": "Partner-reported exports excluding fish and seafood",
    "exports_partner_ex_fish_ships": "Partner-reported exports excluding fish, seafood, ships and aircraft",
    "imports_partner": "Partner-reported imports into Kiribati, all goods (what partners say they sold to Kiribati; a lower bound)",
    "imports_partner_ships_aircraft": "Partner-reported imports: ships and aircraft (HS 88-89)",
    "imports_partner_ex_ships_aircraft": "Partner-reported imports excluding ships and aircraft",
    "imports_partner_fuel": "Partner-reported imports: fuel (HS 27)",
    "imports_partner_food": "Partner-reported imports: food, drink and tobacco (HS 01-24 excluding fish)",
    "exports_kiribati": "Kiribati-reported exports, all goods (Kiribati's own customs returns)",
    "exports_kiribati_tuna": "Kiribati-reported exports: tuna",
    "exports_kiribati_fish": "Kiribati-reported exports: all fish and seafood",
    "exports_kiribati_copra_oil": "Kiribati-reported exports: coconut (copra) oil",
    "exports_kiribati_ex_fish": "Kiribati-reported exports excluding fish and seafood",
    "imports_kiribati": "Kiribati-reported imports, all goods, as published",
    "imports_kiribati_ex_flagged": "Kiribati-reported imports with one flagged line set aside (January 2024, HS 940690, USD 3,135 million)",
    "imports_kiribati_ships_aircraft": "Kiribati-reported imports: ships and aircraft (HS 88-89)",
    "imports_kiribati_ex_ships_aircraft": "Kiribati-reported imports excluding ships and aircraft (flagged line also set aside)",
    "imports_kiribati_fuel": "Kiribati-reported imports: fuel (HS 27)",
    "imports_kiribati_food": "Kiribati-reported imports: food, drink and tobacco (HS 01-24 excluding fish)",
    "n_reporters_exports": "Number of partners with at least one export line from Kiribati in the period (all goods pull)",
    "n_reporters_imports": "Number of partners with at least one import line into Kiribati in the period (all goods pull)",
    "n_reporters_fish": "Number of partners with at least one fish line from Kiribati in the period (fish pull)",
    "pct_complete": "Percent complete, count-based (share of the panel published)",
    "pct_complete_w_exports": "Percent complete, weighted by export shares",
    "pct_complete_w_imports": "Percent complete, weighted by import shares",
    "kiribati_reported": "Whether Kiribati's own monthly return for the period is published",
    "partner_all_goods_available": "Whether the all-goods partner pull exists for the period (it exists only for months Kiribati reported)",
}
MONEY_KEYS = [k for k in SERIES_KEYS if k.startswith(("exports_", "imports_"))]
PARTNER_ALLGOODS_KEYS = ["exports_partner", "exports_partner_copra_oil", "exports_partner_ships_aircraft",
                         "exports_partner_ex_fish", "exports_partner_ex_fish_ships",
                         "imports_partner", "imports_partner_ships_aircraft", "imports_partner_ex_ships_aircraft",
                         "imports_partner_fuel", "imports_partner_food"]
PARTNER_FISH_KEYS = ["exports_partner_tuna", "exports_partner_fish", "exports_partner_other_fish"]
KIRIBATI_KEYS = [k for k in MONEY_KEYS if "_kiribati" in k]


def _cat_masks(d: pd.DataFrame) -> dict[str, pd.Series]:
    code, hs2 = d["cmdCode"], d["hs2"]
    fish = code.str.startswith(FISH_PREFIXES)
    return {
        "all": pd.Series(True, index=d.index),
        "tuna": code.isin(TUNA_HS6),
        "fish": fish,
        "copra_oil": code.isin(COPRA_OIL_HS6),
        "ships_aircraft": hs2.isin(SHIPS_AIRCRAFT_HS2),
        "fuel": hs2.isin(FUEL_HS2),
        "food": hs2.isin(FOOD_HS2),
    }


def _sums_by_period(d: pd.DataFrame) -> pd.DataFrame:
    """One row per period with the category sums (USD m), 0 where the period has rows but none in the category."""
    if d.empty:
        return pd.DataFrame()
    masks = _cat_masks(d)
    periods = sorted(d["period"].unique())
    out = pd.DataFrame(index=periods)
    for k, mk in masks.items():
        out[k] = d[mk].groupby("period")["value_usd_m"].sum().reindex(periods).fillna(0.0)
    out["n_reporters"] = d.groupby("period")["reporterCode"].nunique().reindex(periods).fillna(0).astype(int)
    return out


def _monthly_rows(raw: pd.DataFrame, fish_detail: pd.DataFrame, kiribati_months: list[str],
                  months: list[str]) -> tuple[list[dict], list[str]]:
    kir = set(kiribati_months)
    mirror = raw[(raw["side"] == "mirror") & (raw["partnerCode"] == SUBJECT_CODE)]
    self_ = raw[(raw["side"] == "self") & (raw["reporterCode"] == SUBJECT_CODE)]
    mx = _sums_by_period(mirror[mirror["flowCode"] == "M"])     # partners' imports FROM Kiribati = Kiribati exports
    mi = _sums_by_period(mirror[mirror["flowCode"] == "X"])     # partners' exports TO Kiribati  = Kiribati imports
    sx = _sums_by_period(self_[self_["flowCode"] == "X"])
    sm_rows = self_[self_["flowCode"] == "M"]
    flagged = sm_rows[sm_rows["primaryValue"] >= FLAGGED_LINE_USD]
    si = _sums_by_period(sm_rows)
    si_exf = _sums_by_period(sm_rows[sm_rows["primaryValue"] < FLAGGED_LINE_USD])
    flag_notes: list[str] = []
    fish_discrepancies: list[str] = []
    for _, r in flagged.iterrows():
        flag_notes.append(
            f"{r['period']}: Kiribati-reported import line HS {r['cmdCode']} ({str(r.get('cmdDesc', ''))[:60]}) "
            f"from {r.get('partnerDesc', '?')} is published at USD {r['primaryValue']/1e6:,.0f} million; shown as "
            "published in imports_kiribati and set aside in imports_kiribati_ex_flagged.")
    mirror_months = set(mx.index) | set(mi.index)
    fd = fish_detail
    f_t = fd[fd["is_tuna"]].groupby("period")["value_usd_m"].sum()
    f_a = fd.groupby("period")["value_usd_m"].sum()
    f_n = fd.groupby("period")["reporterCode"].nunique()
    fish_months = set(f_a.index)
    # Consistency between the two sources where both exist (they agree exactly in the 9 Oct 2026 pull).
    for m in sorted(set(mx.index) & fish_months):
        gap = float(mx.loc[m, "fish"]) - float(f_a.get(m, 0.0))
        if abs(gap) > 0.01:
            fish_discrepancies.append(f"{m}: fish in the all-goods pull ({mx.loc[m, 'fish']:.3f}) differs from the "
                              f"fish-only pull ({f_a.get(m, 0.0):.3f}) by {gap:+.3f}; the all-goods pull is used "
                              "for this month. The two pulls were made at different dates.")

    rows = []
    for m in months:
        row: dict = {"period": m}
        has_mirror = m in mirror_months
        # Partner-reported exports (all goods) only where the full mirror pull exists
        if has_mirror and m in mx.index:
            x = mx.loc[m]
            row.update({
                "exports_partner": x["all"], "exports_partner_tuna": x["tuna"], "exports_partner_fish": x["fish"],
                "exports_partner_other_fish": x["fish"] - x["tuna"], "exports_partner_copra_oil": x["copra_oil"],
                "exports_partner_ships_aircraft": x["ships_aircraft"],
                "exports_partner_ex_fish": x["all"] - x["fish"],
                "exports_partner_ex_fish_ships": x["all"] - x["fish"] - x["ships_aircraft"],
                "n_reporters_exports": int(x["n_reporters"]),
            })
        elif has_mirror:   # pull exists, but no partner recorded any import from Kiribati that month
            row.update({k: 0.0 for k in ["exports_partner", "exports_partner_tuna", "exports_partner_fish",
                                         "exports_partner_other_fish", "exports_partner_copra_oil",
                                         "exports_partner_ships_aircraft", "exports_partner_ex_fish",
                                         "exports_partner_ex_fish_ships"]})
            row["n_reporters_exports"] = 0
        else:
            for k in ["exports_partner", "exports_partner_copra_oil", "exports_partner_ships_aircraft",
                      "exports_partner_ex_fish", "exports_partner_ex_fish_ships", "n_reporters_exports"]:
                row[k] = None
            if m in fish_months:
                t = float(f_t.get(m, 0.0)); a = float(f_a.get(m, 0.0))
                row.update({"exports_partner_tuna": t, "exports_partner_fish": a, "exports_partner_other_fish": a - t})
            else:
                row.update({"exports_partner_tuna": None, "exports_partner_fish": None, "exports_partner_other_fish": None})
        row["n_reporters_fish"] = int(f_n.get(m, 0)) if m in fish_months else None
        # Partner-reported imports
        if has_mirror and m in mi.index:
            x = mi.loc[m]
            row.update({"imports_partner": x["all"], "imports_partner_ships_aircraft": x["ships_aircraft"],
                        "imports_partner_ex_ships_aircraft": x["all"] - x["ships_aircraft"],
                        "imports_partner_fuel": x["fuel"], "imports_partner_food": x["food"],
                        "n_reporters_imports": int(x["n_reporters"])})
        elif has_mirror:
            row.update({"imports_partner": 0.0, "imports_partner_ships_aircraft": 0.0,
                        "imports_partner_ex_ships_aircraft": 0.0, "imports_partner_fuel": 0.0,
                        "imports_partner_food": 0.0, "n_reporters_imports": 0})
        else:
            row.update({k: None for k in ["imports_partner", "imports_partner_ships_aircraft",
                                          "imports_partner_ex_ships_aircraft", "imports_partner_fuel",
                                          "imports_partner_food", "n_reporters_imports"]})
        # Kiribati-reported
        if m in kir and (m in sx.index or m in si.index):
            if m in sx.index:
                x = sx.loc[m]
                row.update({"exports_kiribati": x["all"], "exports_kiribati_tuna": x["tuna"],
                            "exports_kiribati_fish": x["fish"], "exports_kiribati_copra_oil": x["copra_oil"],
                            "exports_kiribati_ex_fish": x["all"] - x["fish"]})
            else:
                row.update({k: 0.0 for k in ["exports_kiribati", "exports_kiribati_tuna", "exports_kiribati_fish",
                                             "exports_kiribati_copra_oil", "exports_kiribati_ex_fish"]})
            if m in si.index:
                x = si.loc[m]
                xe = si_exf.loc[m] if m in si_exf.index else None
                exf_all = float(xe["all"]) if xe is not None else 0.0
                exf_ships = float(xe["ships_aircraft"]) if xe is not None else 0.0
                row.update({"imports_kiribati": x["all"], "imports_kiribati_ex_flagged": exf_all,
                            "imports_kiribati_ships_aircraft": x["ships_aircraft"],
                            "imports_kiribati_ex_ships_aircraft": exf_all - exf_ships,
                            "imports_kiribati_fuel": x["fuel"], "imports_kiribati_food": x["food"]})
            else:
                row.update({k: 0.0 for k in ["imports_kiribati", "imports_kiribati_ex_flagged",
                                             "imports_kiribati_ships_aircraft", "imports_kiribati_ex_ships_aircraft",
                                             "imports_kiribati_fuel", "imports_kiribati_food"]})
        else:
            row.update({k: None for k in KIRIBATI_KEYS})
        row["kiribati_reported"] = m in kir
        row["partner_all_goods_available"] = has_mirror
        rows.append(row)
    return rows, flag_notes, fish_discrepancies


def _agg_rows(monthly: list[dict], groups: list[tuple[str, list[str]]], raw: pd.DataFrame,
              fish_detail: pd.DataFrame, kiribati_months: list[str], months_in_period: int) -> list[dict]:
    """Sum monthly rows into quarterly/annual rows. A key is the sum of its non-null months, null if none."""
    by_m = {r["period"]: r for r in monthly}
    kir = set(kiribati_months)
    mirror = raw[(raw["side"] == "mirror") & (raw["partnerCode"] == SUBJECT_CODE)]
    out = []
    for label, pm in groups:
        rows = [by_m[m] for m in pm if m in by_m]
        agg: dict = {"period": label}
        for k in MONEY_KEYS:
            vals = [r[k] for r in rows if r.get(k) is not None]
            agg[k] = float(sum(vals)) if vals else None
        # Fish summed over the same months as the all-goods total, so that
        # exports_partner == exports_partner_fish_same_months + exports_partner_ex_fish holds.
        ag_rows = [r for r in rows if r["partner_all_goods_available"]]
        agg["exports_partner_fish_same_months"] = float(sum(r["exports_partner_fish"] for r in ag_rows)) if ag_rows else None
        agg["exports_partner_tuna_same_months"] = float(sum(r["exports_partner_tuna"] for r in ag_rows)) if ag_rows else None
        sub = mirror[mirror["period"].isin(pm)]
        nx = int(sub.loc[sub["flowCode"] == "M", "reporterCode"].nunique())
        ni = int(sub.loc[sub["flowCode"] == "X", "reporterCode"].nunique())
        any_mirror = any(r["partner_all_goods_available"] for r in rows)
        agg["n_reporters_exports"] = nx if any_mirror else None
        agg["n_reporters_imports"] = ni if any_mirror else None
        fsub = fish_detail[fish_detail["period"].isin(pm)]
        agg["n_reporters_fish"] = int(fsub["reporterCode"].nunique()) if len(fsub) else None
        agg["months_in_period"] = months_in_period
        agg["months_with_partner_data"] = sum(1 for r in rows if r["partner_all_goods_available"])
        agg["months_with_fish_data"] = sum(1 for r in rows if r.get("exports_partner_fish") is not None)
        agg["kiribati_months_reported"] = sum(1 for m in pm if m in kir)
        agg["kiribati_reported"] = agg["kiribati_months_reported"] == months_in_period
        agg["partner_all_goods_available"] = agg["months_with_partner_data"] == months_in_period
        out.append(agg)
    return out


def _attach_coverage(rows: list[dict], cov_rows: list[dict]) -> None:
    by_p = {c["period"]: c for c in cov_rows}
    for r in rows:
        c = by_p.get(r["period"])
        r["pct_complete"] = c["share_count"] if c else None
        r["pct_complete_w_exports"] = c["share_w_exports"] if c else None
        r["pct_complete_w_imports"] = c["share_w_imports"] if c else None


def _rolling_12m(monthly: list[dict]) -> list[dict]:
    out = []
    n = len(monthly)
    fish_by_end: dict[str, float | None] = {}
    tuna_by_end: dict[str, float | None] = {}
    for i in range(11, n):
        win = monthly[i - 11:i + 1]
        end = win[-1]["period"]
        fish = [r["exports_partner_fish"] for r in win]
        tuna = [r["exports_partner_tuna"] for r in win]
        allg = [r["exports_partner"] for r in win]
        f_ok = all(v is not None for v in fish)
        a_ok = all(v is not None for v in allg)
        fish_v = float(sum(fish)) if f_ok else None
        tuna_v = float(sum(tuna)) if f_ok else None
        fish_by_end[end], tuna_by_end[end] = fish_v, tuna_v
        prev = month_add(end, -12)
        pf, pt = fish_by_end.get(prev), tuna_by_end.get(prev)
        row = {
            "end": end, "months": 12,
            "exports_partner": float(sum(allg)) if a_ok else None,
            "exports_partner_tuna": tuna_v, "exports_partner_fish": fish_v,
            "exports_partner_ex_fish": (float(sum(allg)) - fish_v) if (a_ok and f_ok) else None,
            "months_with_all_goods_data": sum(1 for v in allg if v is not None),
            "months_with_fish_data": sum(1 for v in fish if v is not None),
            "growth_pct": ((fish_v / pf - 1) * 100) if (fish_v is not None and pf) else None,
            "growth_pct_tuna": ((tuna_v / pt - 1) * 100) if (tuna_v is not None and pt) else None,
            "n_reporters_fish_max": max((r["n_reporters_fish"] or 0) for r in win),
        }
        out.append(row)
    return out


def series_from_data(raw: pd.DataFrame, fish_detail: pd.DataFrame, coverage: dict,
                     kiribati_months: list[str], months: list[str] | None = None,
                     years: list[int] | None = None, quarters: list[str] | None = None,
                     fish_annual: pd.DataFrame | None = None,
                     fish_annual_by_reporter: pd.DataFrame | None = None) -> dict:
    """series.json content: monthly, quarterly, annual and rolling 12-month tables."""
    kir = sorted(set(kiribati_months))
    if months is None:
        months = [r["period"] for r in coverage["monthly"]]
    if quarters is None:
        quarters = [r["period"] for r in coverage["quarterly"]]
    if years is None:
        years = [int(r["period"]) for r in coverage["annual"]]

    monthly, flag_notes, fish_discrepancies = _monthly_rows(raw, fish_detail, kir, months)
    _attach_coverage(monthly, coverage["monthly"])

    quarterly = _agg_rows(monthly, [(q, quarter_months(q)) for q in quarters], raw, fish_detail, kir, 3)
    _attach_coverage(quarterly, coverage["quarterly"])

    annual = _agg_rows(monthly, [(str(y), [f"{y}-{i:02d}" for i in range(1, 13)]) for y in years],
                       raw, fish_detail, kir, 12)
    _attach_coverage(annual, coverage["annual"])

    # Annual fish dataset (Comtrade annual returns, 2010-2025): separate keys, never mixed with monthly sums.
    ann_fish: dict[int, dict] = {}
    if fish_annual is not None and len(fish_annual) and "year" in fish_annual.columns:
        for _, r in fish_annual.iterrows():
            ann_fish[int(r["year"])] = {
                "exports_partner_tuna_annual_dataset": float(r.get("tuna", float("nan"))),
                "exports_partner_fish_annual_dataset": float(r.get("all_fish", float("nan"))),
                "n_reporters_fish_annual_dataset": int(r["n_reporters"]) if "n_reporters" in r and pd.notna(r["n_reporters"]) else None,
            }
    elif fish_annual_by_reporter is not None and len(fish_annual_by_reporter):
        t = fish_annual_by_reporter.set_index(fish_annual_by_reporter.columns[0])
        for col in t.columns:
            try:
                y = int(str(col)[:4])
            except ValueError:
                continue
            v = pd.to_numeric(t[col], errors="coerce")
            ann_fish[y] = {"exports_partner_tuna_annual_dataset": None,
                           "exports_partner_fish_annual_dataset": float(v.sum()),
                           "n_reporters_fish_annual_dataset": int((v > 0).sum())}
    for r in annual:
        extra = ann_fish.get(int(r["period"]), {})
        r["exports_partner_tuna_annual_dataset"] = _r(extra.get("exports_partner_tuna_annual_dataset"))
        r["exports_partner_fish_annual_dataset"] = _r(extra.get("exports_partner_fish_annual_dataset"))
        r["n_reporters_fish_annual_dataset"] = extra.get("n_reporters_fish_annual_dataset")

    rolling = _rolling_12m(monthly)

    keys = dict(SERIES_KEYS)
    keys.update({
        "exports_partner_tuna_annual_dataset": "Partner-reported tuna from Comtrade's ANNUAL returns (available 2010 onwards; differs slightly from the sum of monthly returns)",
        "exports_partner_fish_annual_dataset": "Partner-reported fish and seafood from Comtrade's ANNUAL returns",
        "n_reporters_fish_annual_dataset": "Number of partners in the annual fish returns",
        "exports_partner_fish_same_months": "Partner-reported fish summed over only the months that have the all-goods pull (so it is comparable with exports_partner)",
        "exports_partner_tuna_same_months": "Partner-reported tuna summed over only the months that have the all-goods pull",
        "months_in_period": "Months in the period (3 or 12)",
        "months_with_partner_data": "Months in the period with the all-goods partner pull",
        "months_with_fish_data": "Months in the period with partner fish data",
        "kiribati_months_reported": "Months in the period with Kiribati's own return published",
        "rolling_12m.growth_pct": "Change of the 12-month fish total against the 12 months a year earlier, percent",
    })
    notes = [
        "Values in USD millions. null = not available (the dataset is not published or was not pulled); it is never 0.",
        "Partner-reported exports = what Kiribati's partners record as imports from Kiribati (partner flow M); "
        "partner-reported imports = what partners record as exports to Kiribati (partner flow X). "
        "Kiribati-reported = Kiribati's own customs returns on Comtrade (flows X and M).",
        "All-goods partner series exist only for the months Kiribati itself reported (the pipeline pulled the "
        "mirror side for those 70 months). For the other months only the fish series (tuna, all fish, other fish) "
        "are available, from a separate fish-only pull that covers every month 2017-01 onward.",
        f"Tuna = HS6 {sorted(TUNA_HS6)} (frozen albacore, yellowfin, skipjack, bigeye, bluefin and other tunas, "
        "frozen tuna fillets, prepared or preserved tuna), as in comtrade_mirror/fish.py. Fish = HS chapter 03 + "
        "heading 1604. Copra oil = HS 151311 + 151319. Ships and aircraft = HS chapters 88-89. Fuel = HS 27. "
        "Food = HS 01-24 excluding chapter 03.",
        "Quarterly and annual rows are sums of the available months; months_with_partner_data, "
        "months_with_fish_data and kiribati_months_reported say how many months are in each sum. Quarters and "
        "years with fewer months are not comparable with complete ones.",
        "In quarterly and annual rows the fish series (exports_partner_tuna, _fish, _other_fish) can cover more "
        "months than the all-goods series, so exports_partner_tuna may exceed exports_partner (e.g. 2024: tuna "
        "over 12 months, all goods over the 10 months Kiribati reported). Use exports_partner_fish_same_months / "
        "exports_partner_tuna_same_months when comparing with exports_partner.",
        "Annual rows also carry exports_partner_*_annual_dataset from Comtrade's annual returns (2010-2025), "
        "which cover years before 2017 and partners that report annually only; they are kept separate from "
        "the monthly sums.",
        "rolling_12m: 12-month totals of partner-reported fish and tuna for every end month; the all-goods "
        "total is given only when all 12 months have the all-goods pull. growth_pct compares the fish total "
        "with the 12 months a year earlier. Read growth only off this window; single months are noise.",
        "Partner-reported imports are a lower bound (about a third to a half of what Kiribati records). "
        "No trade balance is computed from these data.",
        "Partner-reported exports are valued CIF (including freight and insurance) by most reporters; "
        "Kiribati-reported exports are FOB.",
    ] + flag_notes + fish_discrepancies
    return {
        "meta": _meta(notes, units="USD millions", coverage_method=coverage["meta"].get("method"),
                      flagged_lines=flag_notes, flagged_line_threshold_usd=FLAGGED_LINE_USD,
                      fish_source_discrepancies=fish_discrepancies),
        "keys": keys,
        "monthly": monthly, "quarterly": quarterly, "annual": annual, "rolling_12m": rolling,
    }


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
def build_manifest(panel: dict, coverage: dict, series: dict, kiribati_months: list[str],
                   last_update_mode: str = "offline_rebuild", as_of: str = DEFAULT_AS_OF,
                   inputs_info: dict | None = None, extra_notes: list[str] | None = None) -> dict:
    kir = sorted(set(kiribati_months))
    months = [r["period"] for r in series["monthly"]]
    last_m = months[-1]
    all_since = month_range(months[0], kir[-1] if kir else last_m)
    missing_all = [m for m in all_since if m not in set(kir)]
    missing_recent = [m for m in missing_all if m >= "2023-06"]
    status = coverage.get("partner_status", {})
    ref_month = month_key(as_of[:7])          # the pull month: lag = pull month - latest published month
    panel_rows = []
    for p in panel["members"]:
        st = status.get(str(p["code"]), {})
        latest = st.get("latest_published_month")
        if p["code"] in KNOWN_LAG_MONTHS:
            lag, basis = KNOWN_LAG_MONTHS[p["code"]], "shared brief / bullet points"
        elif latest:
            lag, basis = max(1, months_between(latest, ref_month) - 1), f"observed: pull {as_of}, latest month {latest}"
        else:
            lag, basis = None, "never observed with partner Kiribati in these data"
        row = {"code": p["code"], "name": p["name"], "label": p["label"], "iso3": p["iso3"],
               "w_exports": p["w_exports"], "w_imports": p["w_imports"],
               "latest_published_month": latest,
               "latest_published_year": st.get("latest_published_year"),
               "typical_lag_months": lag, "lag_basis": basis,
               "always_include": p["always_include"], "meets_threshold": p["meets_threshold"]}
        if st.get("last_released"):
            row["last_released"] = st["last_released"]
        notes = []
        if p["code"] == 156:
            notes.append("No monthly data after 2024-12 on this API; 2025 onward is available annually only. "
                         "China supplied 27-28% of partner-reported imports in 2023-2024 (about a fifth of the "
                         "2023-2025 window because its 2025 months are absent). Its 2025 vessel deliveries "
                         "(USD 108 million) appear only in the annual data.")
        if p["code"] == 490:
            notes.append("Comtrade reporter 'Other Asia, nes' (code 490). Reports nothing monthly with partner "
                         "Kiribati on this API; included with zero weight because it is a known supplier "
                         "(fishing vessels in 2022, rice).")
        if p["code"] == 764:
            notes.append("Main tuna buyer; about 70% of partner-reported exports. June-July 2026 not yet published at the pull date.")
        if p["code"] == 410:
            notes.append("Latest monthly dataset 2025-12.")
        if p["code"] == 702:
            notes.append("Latest monthly dataset 2026-03.")
        if notes:
            row["notes"] = notes
        panel_rows.append(row)

    last_q = series["quarterly"][-1]["period"] if series["quarterly"] else quarter_of(last_m)
    annual_years = [int(r["period"]) for r in series["annual"]
                    if r.get("exports_partner_fish_annual_dataset") is not None]
    data_through = {"monthly": last_m, "quarterly": last_q,
                    "annual": max(annual_years) if annual_years else int(last_m[:4]) - 1,
                    "annual_ytd": int(last_m[:4])}
    notes = [
        "Partner-reported data complement Kiribati's own customs figures (the official source); they fill gaps "
        "in timing and coverage, they do not replace them.",
        "Partner data are usable about four months after the reference month for the fish series (Thailand, "
        "Japan, Philippines publish within about four months); other partners take longer.",
        "The last four months of any series are provisional and change as late reporters publish.",
        f"Offline inputs were produced by the owner's pipeline pull of {as_of}.",
    ] + (extra_notes or [])
    return {
        "meta": _meta(notes, as_of=as_of, inputs=(inputs_info or {})),
        "title": "Import and Export Performance Tracker using Comtrade Trade-Partner Data",
        "purpose": "Summarize and share trading-partner data to track the performance of the Kiribati economy.",
        "subject": {"code": SUBJECT_CODE, "name": SUBJECT_NAME},
        "last_update_mode": last_update_mode,
        "data_through": data_through,
        "reference_window": panel["reference_window"],
        "n_panel": panel["n_panel"],
        "panel": panel_rows,
        "kiribati_own_reporting": {
            "months_published": kir, "n_months_published": len(kir),
            "latest": kir[-1] if kir else None,
            "missing_recent": missing_recent, "missing_since_2017": missing_all,
        },
        "coverage_method": coverage["meta"].get("method"),
        "definitions": {
            "tuna_hs6": sorted(TUNA_HS6), "fish": "HS chapter 03 + heading 1604",
            "copra_oil_hs6": sorted(COPRA_OIL_HS6), "ships_aircraft_hs2": sorted(SHIPS_AIRCRAFT_HS2),
            "fuel_hs2": sorted(FUEL_HS2), "food_hs2": "01-24 excluding 03",
            "units": "USD millions", "null": "not available / not published; never 0",
        },
        "files": {"coverage": "data/coverage.json", "series": "data/series.json",
                  "panel": "tracker/panel.json"},
    }


# --------------------------------------------------------------------------- #
# JSON output
# --------------------------------------------------------------------------- #
def _jsonable(o):
    """Round floats to 3 decimals, NaN -> null, numpy scalars -> python."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in (sorted(o) if isinstance(o, (set, frozenset)) else o)]
    if isinstance(o, bool):
        return o
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):   # numpy scalar
        o = o.item()
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 3)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def write_json(path: str | os.PathLike, obj: dict) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(_jsonable(obj), fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return p


def write_all(out_dir: str | os.PathLike, manifest: dict, coverage: dict, series: dict,
              panel: dict, panel_path: str | os.PathLike | None = None) -> list[Path]:
    out = Path(out_dir)
    written = [write_json(out / "coverage.json", coverage),
               write_json(out / "series.json", series),
               write_json(out / "manifest.json", manifest)]
    if panel_path is None:
        panel_path = Path(__file__).resolve().parent / "panel.json"
    written.append(write_json(panel_path, panel))
    return written


def build_all(inputs_root: str | os.PathLike, out_dir: str | os.PathLike,
              panel_path: str | os.PathLike | None = None, window: tuple[int, int] = DEFAULT_WINDOW,
              as_of: str = DEFAULT_AS_OF, availability_rows: Iterable[dict] | None = None,
              last_update_mode: str | None = None, write: bool = True) -> dict:
    """Load inputs, build everything, write the four files. Returns all objects.

    ``availability_rows`` (Comtrade getDa records) switches coverage to the live
    method; without it the offline inference is used.
    """
    inp = load_inputs(inputs_root)
    raw, fish = inp["raw"], inp["fish_detail"]
    kir = kiribati_months_from(raw, inp["availability_self"])
    panel = build_panel(raw, window=window)
    last_month = max(raw["period"].max(), fish["period"].max() if len(fish) else raw["period"].max())
    months = month_range(DEFAULT_MONTHLY_START, last_month)
    years = list(range(DEFAULT_ANNUAL_START, int(last_month[:4]) + 1))
    if availability_rows is not None:
        coverage = coverage_from_availability(list(availability_rows), panel, kir, months=months, years=years)
        mode = last_update_mode or "live_comtrade"
    else:
        coverage = coverage_from_data(raw, panel, fish, kir, months=months, years=years,
                                      fish_annual_by_reporter=inp["fish_annual_by_reporter"],
                                      ships_annual=inp["ships_annual"])
        mode = last_update_mode or "offline_rebuild"
    series = series_from_data(raw, fish, coverage, kir, fish_annual=inp["fish_annual"],
                              fish_annual_by_reporter=inp["fish_annual_by_reporter"])
    manifest = build_manifest(panel, coverage, series, kir, last_update_mode=mode, as_of=as_of,
                              inputs_info=inp["files"])
    written = write_all(out_dir, manifest, coverage, series, panel, panel_path) if write else []
    return {"panel": panel, "coverage": coverage, "series": series, "manifest": manifest,
            "kiribati_months": kir, "written": written, "inputs": inp}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _summary(res: dict) -> str:
    s = res["series"]
    ann = {r["period"]: r for r in s["annual"]}
    roll = {r["end"]: r for r in s["rolling_12m"]}
    lines = ["Key numbers (USD millions):"]
    for y in ("2024", "2025", "2026"):
        r = ann.get(y)
        if r:
            lines.append(f"  {y}: partner exports {_r(r['exports_partner'])} (tuna {_r(r['exports_partner_tuna'])}, "
                         f"fish {_r(r['exports_partner_fish'])}, copra oil {_r(r['exports_partner_copra_oil'])}); "
                         f"Kiribati exports {_r(r['exports_kiribati'])} (tuna {_r(r['exports_kiribati_tuna'])}); "
                         f"partner imports {_r(r['imports_partner'])} (ships/aircraft {_r(r['imports_partner_ships_aircraft'])}); "
                         f"Kiribati imports {_r(r['imports_kiribati'])}; months partner {r['months_with_partner_data']}, "
                         f"Kiribati {r['kiribati_months_reported']}; annual-dataset tuna {r['exports_partner_tuna_annual_dataset']}")
    for e in ("2024-05", "2025-05", "2026-05", "2026-07"):
        r = roll.get(e)
        if r:
            lines.append(f"  12m to {e}: fish {_r(r['exports_partner_fish'])} tuna {_r(r['exports_partner_tuna'])} "
                         f"all goods {_r(r['exports_partner'])} growth {_r(r['growth_pct'], 1)}%")
    cov = {r["period"]: r for r in res["coverage"]["monthly"]}
    for m in ("2026-03", "2026-05", "2026-07"):
        r = cov.get(m)
        if r:
            lines.append(f"  coverage {m}: {r['n_published']}/{r['n_panel']} = {r['share_count']:.0%}, "
                         f"w_exp {r['share_w_exports']:.0%}, w_imp {r['share_w_imports']:.0%}, missing {r['missing']}")
    lines.append(f"  panel: {[(p['label'], round(p['w_exports'], 3), round(p['w_imports'], 3)) for p in res['panel']['members']]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", required=True, help="pipeline root (contains data/raw, data/out)")
    ap.add_argument("--out", required=True, help="output folder for coverage/series/manifest JSON (site/data)")
    ap.add_argument("--panel-out", default=None, help="where to write panel.json (default: next to this script)")
    ap.add_argument("--as-of", default=DEFAULT_AS_OF, help="date of the pipeline pull the inputs come from")
    ap.add_argument("--window", nargs=2, type=int, default=list(DEFAULT_WINDOW), metavar=("START", "END"))
    ap.add_argument("--availability-json", default=None,
                    help="optional JSON file with Comtrade getDa rows; switches coverage to the live method")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    avail = None
    if a.availability_json:
        with open(a.availability_json, encoding="utf-8") as fh:
            avail = json.load(fh)
            if isinstance(avail, dict):
                avail = avail.get("data") or avail.get("rows") or []
    res = build_all(a.inputs, a.out, panel_path=a.panel_out, window=tuple(a.window), as_of=a.as_of,
                    availability_rows=avail)
    if not a.quiet:
        for p in res["written"]:
            print("wrote", p)
        print(_summary(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
