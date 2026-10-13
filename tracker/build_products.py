#!/usr/bin/env python3
"""build_products.py - builds national_accounts.json, peers.json and products.json
for the Kiribati Import and Export Performance Tracker (Agent E).

    python tracker/build_products.py --inputs /home/claude/kir-tracker/_inputs --out site/data

Importable functions
--------------------
    build_national_accounts(bop_xlsx, mt_xlsx, pipeline_root) -> dict
    build_peers(pipeline_root) -> dict
    build_products(pipeline_root) -> dict
    write_all(out_dir, inputs_root) -> dict[str, Path]
    write_bop_extract(bop_xlsx, mt_xlsx, csv_path) -> pd.DataFrame

`pipeline_root` is a folder with the owner's pipeline layout
(data/raw/kiribati/raw_observations.parquet, data/interim/kiribati/
mirror_metrics.parquet, data/out/...).  Files that are missing there are
looked up in `tracker/data/static_e/` (committed copies of the one-off
analysis CSVs), so the daily refresh never needs `_inputs`.

BOP and GDP come from the IMF workbooks when they are given; otherwise from
the committed extract `tracker/data/bop_extract.csv` (year,
bop_goods_exports, bop_goods_imports, bop_fishing_licence_fees, gdp_usd).

All money is USD millions.  `None` means not available, never 0.
No trade balance is computed anywhere in this module.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "data" / "static_e"          # committed copies of one-off CSVs
BOP_EXTRACT = HERE / "data" / "bop_extract.csv"

sys.path.insert(0, str(HERE))
try:
    from hs4_labels import HS4_LABELS
except ImportError:                                # pragma: no cover
    HS4_LABELS = {}

# --------------------------------------------------------------------------
# Definitions (identical to the owner's pipeline: comtrade_mirror/fish.py and
# compare_bop_2.py)
# --------------------------------------------------------------------------
TUNA = {"030341", "030342", "030343", "030344", "030345", "030346", "030349",
        "030487", "160414"}
SHIP_CHAPTERS = {"88", "89"}
COPRA_CODES = {"120300", "151311", "151319"}
METAL_CHAPTERS = {f"{c:02d}" for c in range(72, 84)}   # HS 72-83, base metals
REPORT_YEARS = [2017, 2018, 2020, 2023, 2024, 2025, 2026]
WINDOW = ("202501", "202607")                           # Table 2 window
LATEST_12M_END = "202607"
TOP_N = 15
# A single Kiribati customs line above this (USD) is more than twice the
# country's GDP; it is set aside from the Kiribati-side totals and listed in
# meta.excluded_lines so nothing is hidden.
SELF_LINE_CAP_USD = 1.0e9

BOP_SHEET = "IN_STA_USD (Analytical)"
BOP_ROWS = {"bop_goods_exports": (6, "Goods, credit (exports)"),
            "bop_goods_imports": (7, "Goods, debit (imports)"),
            "bop_fishing_licence_fees": (14, "of which: Fishing license fees")}
BOP_HEADER_ROW = 1
MT_SHEET = "OUT_MT"
MT_GDP_USD_CODE = "826NGDP_USD"          # "GDP - In US Dollars", Million
MT_LAST_ACTUAL_YEAR = 2025               # 2025 is "Est." in T4b; 2026+ are projections

PNA = {"Kiribati", "Micronesia (FS)", "Marshall Islands", "Nauru", "Palau",
       "Papua New Guinea", "Solomon Islands", "Tuvalu"}
ISO3 = {"Kiribati": "KIR", "Micronesia (FS)": "FSM", "Marshall Islands": "MHL",
        "Nauru": "NRU", "Palau": "PLW", "Papua New Guinea": "PNG",
        "Solomon Islands": "SLB", "Tuvalu": "TUV"}

# Handout values (paper_build/bullet_points_comtrade_20261009.md), kept next
# to the recomputed ones so the reader can see both.
HANDOUT_TABLE2 = {
    "Tuna": (100.8, 6.3, "16×"),
    "Other fish and seafood": (2.5, 0.6, "4×"),
    "Copra and coconut oil": (6.2, 12.7, "0.5×"),
    "Metals (scrap)": (0.5, 0.05, "10×"),
    "All other categories": (2.5, 1.6, "–"),
    "Total exports": (109.7, 21.3, "5.2×"),
}
HANDOUT_BULLET14 = {  # (direction, hs6): (label, handout value, window note)
    ("export", "030119"): ("Live ornamental fish (marine)", 0.89, None),
    ("export", "030819"): ("Dried sea cucumber", 0.35, "2026"),
    ("export", "720449"): ("Scrap iron and steel", 0.38, None),
    ("export", "840910"): ("Aircraft engine parts", 0.25, None),
    ("export", "890332"): ("Motorboats", 0.21, None),
    ("export", "880230"): ("Light aircraft (2-15 t)", 0.20, None),
    ("import", "880240"): ("Aircraft (over 15 t)", 40.2, None),
    ("import", "890120"): ("Tankers", 1.1, None),
    ("import", "840710"): ("Aircraft engines", 0.66, None),
    ("import", "340250"): ("Cleaning products (detergent powders)", 0.52, None),
    ("import", "040790"): ("Eggs (preserved or cooked)", 0.47, None),
}
HANDOUT_TABLE4 = [  # (year label, exporter, type, units, value)
    ("2022", "Taiwan", "Fishing vessels", 2, 43.9),
    ("2022", "China, Japan", "Tugs, cruise, cargo, tankers", None, 8.7),
    ("2023", "Norway, Japan, China", "Other and cargo vessels", None, 17.9),
    ("2024", "Japan", "Tankers", 2, 12.0),
    ("2024", "China", "Fishing vessels (small)", 3, 3.9),
    ("2025", "China", "Fishing vessels (purse seiners)", 5, 108.3),
    ("2025", "Japan, Australia", "Tankers, cargo vessel", 3, 4.8),
    ("Jul 2026", "Brazil", "Aircraft", 1, 40.2),
]
SHIP_TYPE = {"890200": "Fishing vessels", "890120": "Tankers", "890110": "Cruise ships",
             "890190": "Cargo vessels", "890400": "Tugs", "890690": "Other vessels",
             "880240": "Aircraft", "880230": "Aircraft", "890310": "Inflatable boats",
             "890399": "Small boats", "890332": "Motorboats", "890590": "Light vessels"}
REPORTER_NAME = {"Other Asia, nes": "Taiwan", "Rep. of Korea": "Korea",
                 "China, Hong Kong SAR": "Hong Kong SAR"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def r3(x):
    """Round to 3 decimals; NaN/None -> None."""
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(x), 3)


def r1(x):
    v = r3(x)
    return None if v is None else round(v, 1)


def usd_m(x):
    return r3(x / 1e6) if x is not None and not pd.isna(x) else None


def ym(period: str) -> str:
    p = str(period)
    return f"{p[:4]}-{p[4:6]}" if len(p) == 6 else p


def find(pipeline_root: Path | None, rel: str) -> Path | None:
    """Return the first existing file among pipeline_root/rel and static_e/rel."""
    for base in ([Path(pipeline_root)] if pipeline_root else []) + [STATIC_DIR]:
        p = base / rel
        if p.exists():
            return p
    return None


def label_for(hs4: str, desc: str | None) -> str:
    if hs4 in HS4_LABELS:
        return HS4_LABELS[hs4]
    if not desc or pd.isna(desc):
        return f"HS {hs4}"
    s = str(desc).split(";")[0].split("(")[0].strip().rstrip(",")
    return (s[:48] + "…") if len(s) > 50 else s


# --------------------------------------------------------------------------
# workbooks
# --------------------------------------------------------------------------
def read_bop(bop_xlsx: Path) -> pd.DataFrame:
    """IN_STA_USD (Analytical): rows 6, 7, 14; years across the header row."""
    import openpyxl
    wb = openpyxl.load_workbook(bop_xlsx, data_only=True, read_only=True)
    if BOP_SHEET not in wb.sheetnames:
        raise SystemExit(f"Sheet {BOP_SHEET!r} not in {bop_xlsx}")
    ws = wb[BOP_SHEET]
    grid = {}
    for ri, row in enumerate(ws.iter_rows(min_row=1, max_row=max(r for r, _ in BOP_ROWS.values()),
                                          values_only=True), start=1):
        for ci, v in enumerate(row, start=1):
            grid[(ri, ci)] = v
    years = {}
    for (rr, cc), v in grid.items():
        if rr != BOP_HEADER_ROW:
            continue
        try:
            y = int(str(v))
        except (TypeError, ValueError):
            continue
        if 1990 <= y <= 2100:
            years[y] = cc
    out = []
    for y, col in sorted(years.items()):
        rec = {"year": y}
        for key, (row, label) in BOP_ROWS.items():
            got = str(grid.get((row, 7)) or "")
            if label.lower()[:12] not in got.lower():
                raise SystemExit(f"{BOP_SHEET} row {row} is {got!r}, expected {label!r}; layout changed")
            rec[key] = pd.to_numeric(grid.get((row, col)), errors="coerce")
        out.append(rec)
    df = pd.DataFrame(out)
    return df.dropna(subset=list(BOP_ROWS), how="all").reset_index(drop=True)


def read_gdp_usd(mt_xlsx: Path) -> pd.Series:
    """KIR_MT.xlsx sheet OUT_MT, row with Save_Series_Code 826NGDP_USD
    ("GDP - In US Dollars", Million).  Years up to MT_LAST_ACTUAL_YEAR only;
    later columns are projections and are not used."""
    import openpyxl
    wb = openpyxl.load_workbook(mt_xlsx, data_only=True, read_only=True)
    ws = wb[MT_SHEET]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    hdr = list(rows[0])
    ycols = {int(v): i for i, v in enumerate(hdr) if isinstance(v, (int, float)) and 1979 <= v <= 2100}
    for r in rows[1:]:
        if len(r) > 2 and r[2] == MT_GDP_USD_CODE:
            return pd.Series({y: float(r[c]) for y, c in ycols.items()
                              if y <= MT_LAST_ACTUAL_YEAR and isinstance(r[c], (int, float))},
                             name="gdp_usd").sort_index()
    raise SystemExit(f"{MT_GDP_USD_CODE} not found on {MT_SHEET} of {mt_xlsx}")


def write_bop_extract(bop_xlsx: Path, mt_xlsx: Path | None, csv_path: Path = BOP_EXTRACT) -> pd.DataFrame:
    bop = read_bop(bop_xlsx)
    if mt_xlsx and Path(mt_xlsx).exists():
        gdp = read_gdp_usd(mt_xlsx)
        bop["gdp_usd"] = bop["year"].map(gdp)
    else:
        bop["gdp_usd"] = None
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    bop.round(6).to_csv(csv_path, index=False)
    return bop


def load_bop(bop_xlsx: Path | None, mt_xlsx: Path | None) -> tuple[pd.DataFrame, list[str]]:
    srcs = []
    if bop_xlsx and Path(bop_xlsx).exists():
        bop = read_bop(Path(bop_xlsx))
        srcs.append(f"IMF STA BOP via {Path(bop_xlsx).name} sheet '{BOP_SHEET}' rows 6 (KIR.CD_T.G.USD.*), "
                    f"7 (KIR.DB_T.G.USD.*), 14 (KIR.CD_T.D45.USD.*), USD millions")
        if mt_xlsx and Path(mt_xlsx).exists():
            bop["gdp_usd"] = bop["year"].map(read_gdp_usd(Path(mt_xlsx)))
            srcs.append(f"Nominal GDP in USD: {Path(mt_xlsx).name} sheet '{MT_SHEET}', series {MT_GDP_USD_CODE} "
                        f"('GDP - In US Dollars', Million), through {MT_LAST_ACTUAL_YEAR} (2025 = estimate)")
        else:
            bop["gdp_usd"] = None
        return bop, srcs
    if BOP_EXTRACT.exists():
        bop = pd.read_csv(BOP_EXTRACT)
        srcs.append(f"IMF STA BOP and nominal USD GDP from the committed extract tracker/data/bop_extract.csv "
                    f"(made from KIR_BOP.xlsx '{BOP_SHEET}' rows 6/7/14 and KIR_MT.xlsx '{MT_SHEET}' {MT_GDP_USD_CODE})")
        return bop, srcs
    raise SystemExit("No BOP source: pass KIR_BOP.xlsx or commit tracker/data/bop_extract.csv")


# --------------------------------------------------------------------------
# Comtrade pairs (self vs mirror), months Kiribati reported
# --------------------------------------------------------------------------
def _pairs_from_raw(raw_path: Path) -> pd.DataFrame:
    """Rebuild the paired table from raw_observations.parquet (same rules as
    comtrade_mirror/mirror.py: subject orientation, HS6, full outer join)."""
    r = pd.read_parquet(raw_path)
    r = r[r["aggrLevel"].astype(int) == 6].copy()
    r["cmd_code"] = r["cmdCode"].astype(str).str.zfill(6)
    is_self = r["side"].astype(str) == "self"
    flow = r["flowCode"].astype(str).str.upper()
    r["direction"] = None
    r.loc[is_self & (flow == "X"), "direction"] = "export"
    r.loc[is_self & (flow == "M"), "direction"] = "import"
    r.loc[~is_self & (flow == "M"), "direction"] = "export"
    r.loc[~is_self & (flow == "X"), "direction"] = "import"
    r["counterpart_code"] = pd.to_numeric(r["partnerCode"].where(is_self, r["reporterCode"]), errors="coerce")
    r["counterpart_name"] = r["partnerDesc"].where(is_self, r["reporterDesc"])
    r = r[r["direction"].notna() & (r["counterpart_code"] != 296) & (r["counterpart_code"] != 0)]
    r["period"] = r["period"].astype(str)
    keys = ["period", "direction", "counterpart_code", "cmd_code"]
    sides = {}
    for side in ("self", "mirror"):
        sub = r[r["side"] == side]
        g = sub.groupby(keys, as_index=False).agg(value=("primaryValue", "sum"),
                                                   counterpart_name=("counterpart_name", "first"),
                                                   cmd_desc=("cmdDesc", "first"))
        sides[side] = g.rename(columns={"value": f"value_{side}", "counterpart_name": f"cn_{side}",
                                        "cmd_desc": f"cd_{side}"})
    m = sides["self"].merge(sides["mirror"], on=keys, how="outer")
    m["counterpart_name"] = m["cn_self"].fillna(m["cn_mirror"])
    m["cmd_desc"] = m["cd_self"].fillna(m["cd_mirror"])
    m = m.drop(columns=["cn_self", "cn_mirror", "cd_self", "cd_mirror"])
    m["year"] = m["period"].str[:4].astype(int)
    m["hs4"] = m["cmd_code"].str[:4]
    m["hs2"] = m["cmd_code"].str[:2]
    return m


def load_pairs(pipeline_root: Path | None) -> tuple[pd.DataFrame, str]:
    p = find(pipeline_root, "data/interim/kiribati/mirror_metrics.parquet")
    if p:
        m = pd.read_parquet(p)
        src = str(p)
    else:
        p = find(pipeline_root, "data/raw/kiribati/raw_observations.parquet")
        if not p:
            raise SystemExit("Neither mirror_metrics.parquet nor raw_observations.parquet found")
        m = _pairs_from_raw(p)
        src = f"{p} (paired in build_products.py)"
    m = m.copy()
    m["cmd_code"] = m["cmd_code"].astype(str).str.zfill(6)
    m["period"] = m["period"].astype(str)
    m["year"] = m["period"].str[:4].astype(int)
    m["hs4"] = m["cmd_code"].str[:4]
    m["hs2"] = m["cmd_code"].str[:2]
    m["value_self"] = pd.to_numeric(m["value_self"], errors="coerce")
    m["value_mirror"] = pd.to_numeric(m["value_mirror"], errors="coerce")
    return m, src


def split_excluded(m: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Set aside single Kiribati-side lines above SELF_LINE_CAP_USD."""
    big = m[m["value_self"].fillna(0) > SELF_LINE_CAP_USD]
    excluded = []
    for _, r in big.iterrows():
        excluded.append({
            "period": ym(r["period"]), "direction": r["direction"], "hs6": r["cmd_code"],
            "description": label_for(r["hs4"], r["cmd_desc"]), "counterpart": r["counterpart_name"],
            "kiribati_value_usd_m": usd_m(r["value_self"]), "partner_value_usd_m": usd_m(r["value_mirror"]),
            "reason": ("One line in Kiribati's return worth more than twice the country's annual GDP. "
                       "It is kept out of the Kiribati-side totals shown here and reported in this list "
                       "(see notes); the as-published totals are given alongside."),
        })
    if excluded:
        m = m.copy()
        m.loc[big.index, "value_self_as_published"] = m.loc[big.index, "value_self"]
        m.loc[big.index, "value_self"] = 0.0
    return m, excluded


# --------------------------------------------------------------------------
# national_accounts.json
# --------------------------------------------------------------------------
def _comtrade_by_year(m: pd.DataFrame) -> dict[int, dict]:
    out = {}
    for y, g in m.groupby("year"):
        ex = g[g["direction"] == "export"]
        im = g[g["direction"] == "import"]
        tuna = ex["cmd_code"].isin(TUNA)
        ship = im["hs2"].isin(SHIP_CHAPTERS)
        rec = {
            "months_kiribati_reported": int(g["period"].nunique()),
            "months_list": sorted(ym(p) for p in g["period"].unique()),
            "customs_exports_kiribati": ex["value_self"].sum(),
            "customs_imports_kiribati": im["value_self"].sum(),
            "customs_imports_kiribati_as_published": im["value_self"].sum()
            + (im["value_self_as_published"].sum() if "value_self_as_published" in im else 0.0),
            "customs_exports_kiribati_tuna": ex.loc[tuna, "value_self"].sum(),
            "customs_imports_kiribati_ships_aircraft": im.loc[ship, "value_self"].sum(),
            "partner_exports": ex["value_mirror"].sum(),
            "partner_exports_tuna": ex.loc[tuna, "value_mirror"].sum(),
            "partner_exports_ex_tuna": ex.loc[~tuna, "value_mirror"].sum(),
            "partner_imports": im["value_mirror"].sum(),
            "partner_imports_ships_aircraft": im.loc[ship, "value_mirror"].sum(),
            "partner_imports_ex_ships_aircraft": im.loc[~ship, "value_mirror"].sum(),
            "n_partners_exports": int(ex.loc[ex["value_mirror"].fillna(0) > 0, "counterpart_code"].nunique()),
            "n_partners_imports": int(im.loc[im["value_mirror"].fillna(0) > 0, "counterpart_code"].nunique()),
        }
        out[int(y)] = rec
    return out


def _annual_basis(pipeline_root) -> dict[int, dict]:
    """Partner totals from partners' ANNUAL returns (all reporters, all 12
    months) from screen_applicability_3_by_year.csv, Kiribati rows.  In that
    file `mirror_usd_m` is already ex HS 88-89 and `mirror_excl_88_89_usd_m`
    is the HS 88-89 amount that was taken out."""
    p = find(pipeline_root, "data/out/screen_applicability_3_by_year.csv")
    out = {}
    if not p:
        return out
    d = pd.read_csv(p)
    d = d[d["country"] == "Kiribati"]
    for _, r in d.iterrows():
        y = int(r["year"])
        rec = out.setdefault(y, {})
        ex_ships = pd.to_numeric(r["mirror_excl_88_89_usd_m"], errors="coerce")
        base = pd.to_numeric(r["mirror_usd_m"], errors="coerce")
        if r["side"] == "exp":
            rec["partner_exports_annual_basis"] = r3(base + ex_ships)
            rec["partner_exports_ex_ships_aircraft_annual_basis"] = r3(base)
        else:
            rec["partner_imports_annual_basis"] = r3(base + ex_ships)
            rec["partner_imports_ex_ships_aircraft_annual_basis"] = r3(base)
            rec["partner_imports_ships_aircraft_annual_basis"] = r3(ex_ships)
    return out


def _tuna_annual_basis(pipeline_root) -> dict[int, float]:
    p = find(pipeline_root, "data/out/kiribati/fish/fish_mirror_annual.csv")
    if not p:
        return {}
    d = pd.read_csv(p)
    return {int(r["year"]): r3(r["tuna"]) for _, r in d.iterrows()}


def build_national_accounts(bop_xlsx=None, mt_xlsx=None, pipeline_root=None) -> dict:
    bop, sources = load_bop(bop_xlsx, mt_xlsx)
    bop = bop.set_index("year")
    m, pairs_src = load_pairs(pipeline_root)
    m, excluded = split_excluded(m)
    ct = _comtrade_by_year(m)
    ann_basis = _annual_basis(pipeline_root)
    tuna_ann = _tuna_annual_basis(pipeline_root)
    sources.append(f"UN Comtrade monthly HS6, both sides, months Kiribati reported: {pairs_src}")
    sources.append("Partner annual-return totals (all reporters): data/out/screen_applicability_3_by_year.csv "
                   "(Kiribati rows) and data/out/kiribati/fish/fish_mirror_annual.csv")

    years = sorted(set(bop.index.tolist()) | set(ct) | {y for y in ann_basis if y >= 2017})
    years = [y for y in years if y >= 2006]
    pct_keys = ["bop_goods_exports", "bop_goods_imports", "bop_fishing_licence_fees",
                "customs_exports_kiribati_scaled12", "customs_imports_kiribati_scaled12",
                "partner_exports", "partner_exports_tuna", "partner_exports_ex_tuna",
                "partner_imports", "partner_imports_ex_ships_aircraft",
                "partner_exports_annual_basis", "partner_imports_annual_basis",
                "partner_exports_tuna_annual_basis"]
    rows = []
    for y in years:
        b = bop.loc[y] if y in bop.index else None
        c = ct.get(y)
        rec = {"year": int(y)}
        if c:
            rec["months_kiribati_reported"] = c["months_kiribati_reported"]
        elif y in (2019, 2021, 2022):
            rec["months_kiribati_reported"] = 0
        else:
            rec["months_kiribati_reported"] = None if y < 2017 else 0
        for k in ("bop_goods_exports", "bop_goods_imports", "bop_fishing_licence_fees"):
            rec[k] = r3(b[k]) if b is not None else None
        cov = (c["months_kiribati_reported"] / 12) if c else None
        rec["customs_exports_kiribati"] = usd_m(c["customs_exports_kiribati"]) if c else None
        rec["customs_imports_kiribati"] = usd_m(c["customs_imports_kiribati"]) if c else None
        rec["customs_exports_kiribati_scaled12"] = usd_m(c["customs_exports_kiribati"] / cov) if c else None
        rec["customs_imports_kiribati_scaled12"] = usd_m(c["customs_imports_kiribati"] / cov) if c else None
        if c and abs(c["customs_imports_kiribati_as_published"] - c["customs_imports_kiribati"]) > 1:
            rec["customs_imports_kiribati_as_published"] = usd_m(c["customs_imports_kiribati_as_published"])
        rec["customs_exports_kiribati_tuna"] = usd_m(c["customs_exports_kiribati_tuna"]) if c else None
        rec["customs_imports_kiribati_ships_aircraft"] = usd_m(c["customs_imports_kiribati_ships_aircraft"]) if c else None
        for k in ("partner_exports", "partner_exports_tuna", "partner_exports_ex_tuna", "partner_imports",
                  "partner_imports_ships_aircraft", "partner_imports_ex_ships_aircraft"):
            rec[k] = usd_m(c[k]) if c else None
        rec["partner_exports_scaled12"] = usd_m(c["partner_exports"] / cov) if c else None
        rec["partner_exports_ex_tuna_scaled12"] = usd_m(c["partner_exports_ex_tuna"] / cov) if c else None
        rec["n_partners_exports"] = c["n_partners_exports"] if c else None
        rec["n_partners_imports"] = c["n_partners_imports"] if c else None
        ab = ann_basis.get(y, {})
        for k in ("partner_exports_annual_basis", "partner_exports_ex_ships_aircraft_annual_basis",
                  "partner_imports_annual_basis", "partner_imports_ex_ships_aircraft_annual_basis",
                  "partner_imports_ships_aircraft_annual_basis"):
            rec[k] = ab.get(k)
        rec["partner_exports_tuna_annual_basis"] = tuna_ann.get(y)
        gdp = r3(b["gdp_usd"]) if (b is not None and "gdp_usd" in b and not pd.isna(b["gdp_usd"])) else None
        rec["gdp_usd"] = gdp
        rec["gdp_is_estimate"] = (y == MT_LAST_ACTUAL_YEAR) if gdp is not None else None
        rec["pct_gdp"] = {k: r1(rec[k] / gdp * 100) for k in pct_keys
                          if gdp and rec.get(k) is not None} if gdp else {}
        rec["ratio_partner_to_kiribati_exports"] = (r1(c["partner_exports"] / c["customs_exports_kiribati"])
                                                    if c and c["customs_exports_kiribati"] > 0 else None)
        rec["ratio_partner_to_bop_exports"] = (r1(rec["partner_exports_scaled12"] / rec["bop_goods_exports"])
                                               if c and rec["bop_goods_exports"] else None)
        rows.append(rec)

    notes = [
        "Kiribati's balance of payments (BOP) goods lines and Kiribati's own customs returns agree once the "
        "months Kiribati has not yet published are allowed for. The difference between Kiribati's figures and "
        "partner-reported exports is tuna that importing countries code to Kiribati because the catching "
        "vessel flies the Kiribati flag; under balance-of-payments rules much of it may correctly sit outside "
        "Kiribati's goods exports.",
        "Partner-reported imports are a lower bound (only partners that publish on time appear; China's monthly "
        "data stop at 2024-12). No trade balance is shown or should be computed from these columns.",
        "customs_*_scaled12 and partner_exports_scaled12 = value × 12 / months Kiribati reported. This is an "
        "order-of-magnitude device, not an estimate: it assumes the missing months look like the reported ones.",
        "Comtrade columns cover only the months Kiribati published a return (2017, 2018, 2020: 12 months; 2023: "
        "7, Jun-Dec; 2024: 10; 2025: 10; 2026: 7, Jan-Jul). The partner side of the monthly dataset was pulled "
        "for those months only. Rows for 2019, 2021 and 2022 have no Kiribati monthly return (months = 0).",
        "*_annual_basis columns come from partners' ANNUAL returns to Comtrade (all 12 months, all reporters, "
        "including those that only publish annually). They are a different basis from the monthly columns and "
        "are shown so a full-year partner figure exists for every year; partner_exports_tuna_annual_basis is "
        "the fish-only annual pull (HS 03 + 1604, tuna codes).",
        "BOP goods imports for 2025 read 270.4 in the workbook copy used here (IN_STA_USD row 7); the 8 Oct "
        "pipeline run and earlier notes quoted 270.6 from a previous vintage of the same cell.",
        "2025 BOP and GDP values are estimates (marked 'Est.' in the workbook). GDP in USD is the macro "
        "framework's 826NGDP_USD series; 2026 is a projection and is not used, so pct_gdp is empty for 2026.",
        "Percent-of-GDP figures are computed here from IN_STA_USD rows and 826NGDP_USD; the Board table "
        "T4b in KIR_BOP.xlsx uses a slightly different vintage (e.g. fishing licence fees 2025: 36.1 percent "
        "there against 37.4 percent here).",
        "Tuna = HS6 030341-030349 (frozen tunas), 030487 (frozen tuna fillets) and 160414 (prepared tuna), the "
        "definition in comtrade_mirror/fish.py. Ships and aircraft = HS chapters 88 and 89.",
        "Fishing licence fees are a separate flow (BOP primary income) from the tuna series and must not be "
        "compared with it as if one explained the other.",
    ]
    if excluded:
        notes.append(
            "Kiribati's January 2024 import return contains one line (HS 940690 prefabricated buildings from "
            "Viet Nam, USD 3,135 million) worth about nine times Kiribati's annual GDP. It is a difference of "
            "scale, not of coverage, so it is set aside from customs_imports_kiribati (listed in "
            "meta.excluded_lines) and the as-published total is given in customs_imports_kiribati_as_published. "
            "With it set aside, 2024 customs imports scaled to 12 months (about 215) sit close to the BOP figure "
            "(226.6), as in every other year.")
    return {
        "meta": {"generated_at": now_iso(), "source": "IMF STA BOP; IMF macro framework; UN Comtrade",
                 "sources": sources, "unit": "USD millions", "excluded_lines": excluded, "notes": notes},
        "annual": rows,
        "quarterly": [],
        "notes": notes[:2],
    }


# --------------------------------------------------------------------------
# peers.json
# --------------------------------------------------------------------------
def build_peers(pipeline_root=None) -> dict:
    p_pna = find(pipeline_root, "data/out/pna_crosscheck_tuna_by_origin.csv")
    p_scr = find(pipeline_root, "data/out/screen_applicability_3.csv")
    p_by = find(pipeline_root, "data/out/screen_applicability_3_by_year.csv")
    if not p_pna or not p_scr:
        raise SystemExit("peer CSVs not found")

    pna = pd.read_csv(p_pna, index_col=0)
    years = [int(c) for c in pna.columns]
    order = ["Papua New Guinea", "Micronesia (FS)", "Nauru", "Solomon Islands", "Kiribati",
             "Marshall Islands", "Tuvalu"]
    label_map = {"Papua New Guinea": "+70%", "Micronesia (FS)": "×10", "Nauru": "from zero",
                 "Solomon Islands": "+30%", "Kiribati": "−26%", "Marshall Islands": "−12%", "Tuvalu": "×8"}
    countries = []
    for name in order + [n for n in pna.index if n not in order]:
        if name not in pna.index:
            continue
        vals = [r1(v) for v in pna.loc[name].tolist()]
        v15, v25 = pna.loc[name, "2015"], pna.loc[name, "2025"]
        chg = r1((v25 / v15 - 1) * 100) if v15 and v15 > 0.5 else None
        rec = {"name": name, "iso3": ISO3.get(name, ""), "values": vals,
               "is_subject": name == "Kiribati", "pna": name in PNA,
               "change_2015_2025_pct": chg,
               "change_2015_2025_label": label_map.get(name)}
        if name == "Micronesia (FS)":
            avg = r1(pna.loc[name, ["2023", "2024", "2025"]].mean())
            rec["note"] = (f"The 2024 figure ({vals[years.index(2024)]:.0f}) is a one-year spike; the 2023-2025 "
                           f"average is about {avg:.0f}.")
        if name == "Nauru":
            rec["note"] = ("Zero until 2018, then USD 23m in 2019 and 109-181m a year since: vessels were "
                           "reflagged to Nauru. Importers code tuna by the vessel's flag, so this measures the "
                           "flagged fleet's landings, not catch in Nauru's waters.")
        if name == "Kiribati":
            rec["note"] = "The only PNA flag state with a clear decline (2015 to 2025: −26 percent)."
        countries.append(rec)

    scr = pd.read_csv(p_scr)
    by_year = pd.read_csv(p_by) if p_by else None
    app = []
    for _, r in scr.iterrows():
        def num(k):
            v = pd.to_numeric(r.get(k), errors="coerce")
            return None if pd.isna(v) else float(v)
        lat = r.get("c1_latest_month")
        lat = ym(str(int(lat))) if pd.notna(lat) else None
        rec = {
            "country": r["country"], "iso3": r["iso3"], "is_subject": r["country"] == "Kiribati",
            "pna": r["country"] in PNA,
            "own_monthly_lag_months": int(r["c1_lag_months"]) if pd.notna(r["c1_lag_months"]) else None,
            "own_months_of_24": int(r["c1_months_of_24"]) if pd.notna(r["c1_months_of_24"]) else 0,
            "own_latest_month": lat,
            "exp_cov_12m": num("c2_exp_cov_12m"), "exp_cov_6m": num("c2_exp_cov_6m"),
            "imp_cov_12m": num("c2_imp_cov_12m"), "imp_cov_6m": num("c2_imp_cov_6m"),
            "exp_n_partners": int(r["c2_exp_n_partners"]), "imp_n_partners": int(r["c2_imp_n_partners"]),
            "coverage_weights": r.get("c2_exp_weights"),
            "exp_ratio": num("c3_exp_ratio"), "imp_ratio": num("c3_imp_ratio"),
            "ratio_year": int(r["c3_exp_year"]) if pd.notna(r["c3_exp_year"]) else None,
            "ratio_year_imp": int(r["c3_imp_year"]) if pd.notna(r["c3_imp_year"]) else None,
            "own_source": _own_source_latest(r.get("c3_exp_own_source"), r.get("c3_exp_year")),
            "own_source_history": r.get("c3_exp_own_source"),
            "exp_mirror_usd_m": num("c3_exp_mirror_usd_m"), "exp_own_usd_m": num("c3_exp_own_usd_m"),
            "imp_mirror_usd_m": num("c3_imp_mirror_usd_m"), "imp_own_usd_m": num("c3_imp_own_usd_m"),
            "exp_mirror_ships_aircraft_usd_m": num("c3_exp_mirror_excl_88_89_usd_m"),
            "exp_own_ships_aircraft_usd_m": num("c3_exp_own_excl_88_89_usd_m"),
            "imp_mirror_ships_aircraft_usd_m": num("c3_imp_mirror_excl_88_89_usd_m"),
            "imp_own_ships_aircraft_usd_m": num("c3_imp_own_excl_88_89_usd_m"),
        }
        if rec["exp_mirror_usd_m"] is not None and rec["exp_own_usd_m"]:
            with_ships = ((rec["exp_mirror_usd_m"] + (rec["exp_mirror_ships_aircraft_usd_m"] or 0))
                          / (rec["exp_own_usd_m"] + (rec["exp_own_ships_aircraft_usd_m"] or 0)))
            rec["exp_ratio_incl_ships_aircraft"] = r1(with_ships) if with_ships else None
        else:
            rec["exp_ratio_incl_ships_aircraft"] = None
        if by_year is not None:
            sub = by_year[by_year["country"] == r["country"]]
            rec["ratios_by_year"] = {
                side: {str(int(rr["year"])): (None if pd.isna(pd.to_numeric(rr["ratio"], errors="coerce"))
                                               else float(rr["ratio"]))
                       for _, rr in sub[sub["side"] == side].iterrows()}
                for side in ("exp", "imp")}
        if r["country"] == "Kiribati":
            rec["note"] = ("Export ratio 6.6× in 2025 (partners 95.1 vs Kiribati 14.5, both excluding ships and "
                           "aircraft; Kiribati's figure is 10 months scaled to 12), against 1.4-2.1× for Papua New "
                           "Guinea, Maldives and Comoros.")
        if r["country"] == "Maldives":
            rec["note"] = ("Removing ships and aircraft (HS 88-89) lowers the export ratio from 2.65 to 1.62: "
                           "vessel transactions distort the comparison.")
        app.append(rec)
    app.sort(key=lambda d: (not d["is_subject"], d["country"]))

    notes = [
        "tuna_by_origin: tuna (HS 030341-030349, 030487, 160414) that importing countries record as "
        "originating in each country, from partners' annual returns to UN Comtrade (all reporters). Importers "
        "assign origin by the catching vessel's flag, so this is each flag's fleet landing abroad, not catch in "
        "the country's own waters and not a measure of licence fees.",
        "PNA = Parties to the Nauru Agreement: Kiribati, Micronesia (FS), Marshall Islands, Nauru, Palau, Papua "
        "New Guinea, Solomon Islands, Tuvalu. The tuna cross-check uses seven of them (not Palau). The "
        "applicability screen covers 15 small island states; Marshall Islands is not among them because its "
        "partner data are unusable: trade booked to its ship registry swamps the figures.",
        "applicability: exp_cov_12m / imp_cov_12m = share of the country's trade (excluding ships and aircraft) "
        "with partners whose latest monthly Comtrade data are within 12 months (6m variants alongside). "
        "exp_ratio / imp_ratio = partner-reported total ÷ the country's own total, both excluding HS 88-89, for "
        "the latest year both exist (ratio_year). own_source says whether the own total is the annual return "
        "or monthly returns scaled to 12.",
        "exp/imp_mirror_usd_m and exp/imp_own_usd_m exclude ships and aircraft; the HS 88-89 amounts taken out "
        "are in *_ships_aircraft_usd_m. In the source CSV the column named 'mirror_excl_88_89_usd_m' holds that "
        "excluded amount, not a total.",
        "Kiribati's export ratio (6.6×) is the largest among peers with their own data, against 1.4-2.1× for "
        "Papua New Guinea, Maldives and Comoros. Ships and aircraft removal lowers Maldives' export ratio from "
        "2.65 to 1.62. Marshall Islands: partner data unusable (ship registry).",
        "Import coverage is weaker everywhere (about 40-85 percent of trade with prompt reporters); partner "
        "data are a usable export record for the tuna exporters (95 percent or more with prompt reporters).",
        "Ratios are read annually only; the Kiribati 2024 import ratio (0.04) is dominated by one outsized line "
        "in Kiribati's January 2024 return and should not be quoted (see national_accounts.json).",
    ]
    return {
        "meta": {"generated_at": now_iso(), "source": "UN Comtrade (annual partner returns; getDa availability)",
                 "sources": [str(p_pna), str(p_scr)] + ([str(p_by)] if p_by else []),
                 "screen_date": "2026-10-07", "notes": notes},
        "tuna_by_origin": {"unit": "USD millions", "years": years, "countries": countries,
                           "handout_table": "Table 1 of bullet_points_comtrade_20261009.md"},
        "applicability": app,
        "notes": notes,
    }


def _own_source_latest(hist, year):
    if hist is None or pd.isna(hist) or hist == "none":
        return "none"
    try:
        y = str(int(year))
    except (TypeError, ValueError):
        return str(hist)
    for part in str(hist).split(";"):
        part = part.strip()
        if part.startswith(y + ":"):
            return part.split(":", 1)[1]
    return str(hist)


# --------------------------------------------------------------------------
# products.json
# --------------------------------------------------------------------------
def _category(code: str) -> str:
    if code in TUNA:
        return "Tuna"
    if code[:2] == "03" or code[:4] in ("1604", "1605"):
        return "Other fish and seafood"
    if code in COPRA_CODES:
        return "Copra and coconut oil"
    if code[:2] in METAL_CHAPTERS:
        return "Metals (scrap)"
    return "All other categories"


def _categories(m: pd.DataFrame) -> list[dict]:
    w = m[(m["period"] >= WINDOW[0]) & (m["period"] <= WINDOW[1]) & (m["direction"] == "export")].copy()
    w["cat"] = w["cmd_code"].map(_category)
    g = w.groupby("cat")[["value_mirror", "value_self"]].sum() / 1e6
    window = f"{ym(WINDOW[0])}..{ym(WINDOW[1])}"
    months = int(w["period"].nunique())
    notes = {
        "Tuna": "Coded to Kiribati by the catching vessel's flag; under balance-of-payments rules much of it may "
                "correctly sit outside Kiribati's goods exports. Handout partner figure (100.8) traces to the "
                "8 Sept run (tuna fillets then 19.5, now 16.3 after a partner revision); current data give 97.4.",
        "Other fish and seafood": "Mainly sea cucumber and live ornamental fish on the partner side.",
        "Copra and coconut oil": "Kiribati records more than partners: the method is symmetric. Crude coconut "
                                 "oil (HS 151311): partners 5.7 vs Kiribati 11.9 (handout: 5.4 vs 11.9, "
                                 "8 Sept run).",
        "Metals (scrap)": "HS chapters 72-83; on the partner side almost all scrap iron, aluminium and "
                          "lead-acid batteries.",
        "All other categories": "Everything else; mostly goods not specified by kind (HS 9999), engine parts, "
                                "cars and small aircraft on the partner side; cranes on Kiribati's side.",
    }
    rows = []
    for cat in ["Tuna", "Other fish and seafood", "Copra and coconut oil", "Metals (scrap)",
                "All other categories"]:
        pv = float(g.loc[cat, "value_mirror"]) if cat in g.index else 0.0
        kv = float(g.loc[cat, "value_self"]) if cat in g.index else 0.0
        h = HANDOUT_TABLE2[cat]
        rows.append({"category": cat, "window": window, "months_in_window": months, "direction": "export",
                     "partners": r3(pv), "kiribati": r3(kv),
                     "ratio": r1(pv / kv) if kv > 0.005 else None,
                     "handout_partners": h[0], "handout_kiribati": h[1], "handout_ratio": h[2],
                     "is_total": False, "note": notes[cat]})
    pv, kv = float(g["value_mirror"].sum()), float(g["value_self"].sum())
    h = HANDOUT_TABLE2["Total exports"]
    rows.append({"category": "Total exports", "window": window, "months_in_window": months,
                 "direction": "export", "partners": r3(pv), "kiribati": r3(kv),
                 "ratio": r1(pv / kv) if kv else None,
                 "handout_partners": h[0], "handout_kiribati": h[1], "handout_ratio": h[2], "is_total": True,
                 "note": "Sum of the five categories above (all goods, including ships and aircraft, which "
                         "are small on the export side in this window)."})
    return rows


def _hs4_table(sub: pd.DataFrame) -> list[dict]:
    """Top-15 HS4 rows (ranked by the larger of the two sides) + All other + Total."""
    if sub.empty:
        return []
    g = sub.groupby("hs4").agg(partner=("value_mirror", "sum"), kiribati=("value_self", "sum"),
                               desc=("cmd_desc", "first"))
    npart = sub[sub["value_mirror"].fillna(0) > 0].groupby("hs4")["counterpart_code"].nunique()
    g["n_partners"] = npart.reindex(g.index).fillna(0).astype(int)
    g["rank_key"] = g[["partner", "kiribati"]].max(axis=1)
    g = g.sort_values("rank_key", ascending=False)
    top = g.head(TOP_N)
    rest = g.iloc[TOP_N:]
    rows = []
    for i, (hs4, r) in enumerate(top.iterrows(), 1):
        rows.append({"rank": i, "hs4": hs4, "label": label_for(hs4, r["desc"]),
                     "partner": usd_m(r["partner"]), "kiribati": usd_m(r["kiribati"]),
                     "n_partners": int(r["n_partners"]), "is_summary": False})
    rows.append({"rank": None, "hs4": "other", "label": f"All other ({len(rest)} headings)",
                 "partner": usd_m(rest["partner"].sum()), "kiribati": usd_m(rest["kiribati"].sum()),
                 "n_partners": int(sub[(sub["value_mirror"].fillna(0) > 0) & sub["hs4"].isin(rest.index)]
                                   ["counterpart_code"].nunique()),
                 "is_summary": True})
    rows.append({"rank": None, "hs4": "total", "label": "Total, all goods",
                 "partner": usd_m(g["partner"].sum()), "kiribati": usd_m(g["kiribati"].sum()),
                 "n_partners": int(sub[sub["value_mirror"].fillna(0) > 0]["counterpart_code"].nunique()),
                 "is_summary": True})
    return rows


def _mirror_only(m: pd.DataFrame) -> list[dict]:
    w = m[(m["period"] >= WINDOW[0]) & (m["period"] <= WINDOW[1])]
    out = []
    for (direction, hs6), (label, hv, win_note) in HANDOUT_BULLET14.items():
        x = w[(w["direction"] == direction) & (w["cmd_code"] == hs6)]
        window = f"{ym(WINDOW[0])}..{ym(WINDOW[1])}"
        if win_note == "2026":
            x = x[x["year"] == 2026]
            window = "2026-01..2026-07"
        pv = x["value_mirror"].sum()
        kv = x["value_self"].sum()
        out.append({"direction": direction, "hs6": hs6, "hs4": hs6[:4], "label": label,
                    "partners": usd_m(pv), "kiribati": usd_m(kv) if kv else 0.0,
                    "n_partners": int(x.loc[x["value_mirror"].fillna(0) > 0, "counterpart_code"].nunique()),
                    "n_months": int(x.loc[x["value_mirror"].fillna(0) > 0, "period"].nunique()),
                    "window": window, "handout_value": hv,
                    "matches_handout": abs(round(pv / 1e6, 2) - hv) <= 0.05})
    # sea cucumber: full-window context
    for row in out:
        if row["hs6"] == "030819":
            x = w[(w["direction"] == "export") & (w["cmd_code"] == "030819")]
            row["note"] = (f"Over {ym(WINDOW[0])}..{ym(WINDOW[1])} partners report {x['value_mirror'].sum()/1e6:.2f} "
                           f"and Kiribati {x['value_self'].sum()/1e6:.2f} (one month, 2025-11); in 2026 Kiribati "
                           f"has recorded none so far.")
        if row["hs6"] == "040790":
            row["note"] = ("Handout gives 0.47; current data give 0.50 (Fiji, 10 months). Kiribati records eggs "
                           "under other HS6 lines of heading 0407, so this is a difference of classification "
                           "within the heading as much as of coverage.")
    return out


def _ships_aircraft(pipeline_root) -> dict:
    p_ann = find(pipeline_root, "data/out/kiribati/ships_hs6_annual_2.csv")
    p_mon = find(pipeline_root, "data/out/kiribati/ships_monthly_partners.csv")
    p_year = find(pipeline_root, "data/out/kiribati/ships_by_year.csv")
    lines, table, by_year = [], [], []
    if p_ann:
        a = pd.read_csv(p_ann)
        a["hs6"] = a["hs6"].astype(str).str.zfill(6)
        big = a[a["value_usd_m"] >= 1.0].sort_values(["period", "value_usd_m"], ascending=[True, False])
        for _, r in big.iterrows():
            lines.append({"year": int(r["period"]), "period": str(int(r["period"])), "basis": "annual return",
                          "exporter": REPORTER_NAME.get(r["reporter"], r["reporter"]), "hs6": r["hs6"],
                          "type": SHIP_TYPE.get(r["hs6"], label_for(r["hs6"][:4], r["description"])),
                          "units": (int(r["qty"]) if pd.notna(r["qty"]) and r["qty_unit"] == "u" and r["qty"] > 0
                                    else None),
                          "value": r3(r["value_usd_m"])})
    if p_mon:
        mo = pd.read_csv(p_mon)
        mo["hs6"] = mo["hs6"].astype(str).str.zfill(6)
        big = mo[(mo["value_usd_m"] >= 1.0) & (mo["period"].astype(str).str.startswith("2026"))]
        for _, r in big.iterrows():
            lines.append({"year": 2026, "period": ym(str(int(r["period"]))), "basis": "monthly return",
                          "exporter": REPORTER_NAME.get(r["reporter"], r["reporter"]), "hs6": r["hs6"],
                          "type": SHIP_TYPE.get(r["hs6"], label_for(r["hs6"][:4], r["description"])),
                          "units": (int(r["qty"]) if pd.notna(r["qty"]) and r["qty_unit"] == "u" and r["qty"] > 0
                                    else None),
                          "value": r3(r["value_usd_m"])})
    # Table 4 rows, recomputed from the lines
    groups = {
        ("2022", "Taiwan", "Fishing vessels"): lambda l: l["year"] == 2022 and l["hs6"] == "890200",
        ("2022", "China, Japan", "Tugs, cruise, cargo, tankers"): lambda l: l["year"] == 2022 and l["hs6"] != "890200",
        ("2023", "Norway, Japan, China", "Other and cargo vessels"): lambda l: l["year"] == 2023,
        ("2024", "Japan", "Tankers"): lambda l: l["year"] == 2024 and l["hs6"] == "890120",
        ("2024", "China", "Fishing vessels (small)"): lambda l: l["year"] == 2024 and l["hs6"] == "890200",
        ("2025", "China", "Fishing vessels (purse seiners)"): lambda l: l["year"] == 2025 and l["hs6"] == "890200",
        ("2025", "Japan, Australia", "Tankers, cargo vessel"): lambda l: l["year"] == 2025 and l["hs6"] != "890200",
        ("Jul 2026", "Brazil", "Aircraft"): lambda l: l["year"] == 2026 and l["hs6"] == "880240",
    }
    hand = {(y, e, t): (u, v) for y, e, t, u, v in HANDOUT_TABLE4}
    for (ylab, exp, typ), pred in groups.items():
        sel = [l for l in lines if pred(l)]
        units = sum(l["units"] for l in sel if l["units"]) or None
        val = sum(l["value"] for l in sel)
        hu, hv = hand[(ylab, exp, typ)]
        table.append({"year": int(ylab[-4:]), "year_label": ylab, "exporter": exp, "type": typ,
                      "units": units if hu is not None else None, "value": r1(val),
                      "handout_units": hu, "handout_value": hv, "matches_handout": abs(round(val, 1) - hv) <= 0.1,
                      "hs6": sorted({l["hs6"] for l in sel})})
    if p_year:
        y = pd.read_csv(p_year)
        for _, r in y.iterrows():
            by_year.append({"year": int(r["year"]), "partner_reported": r3(r["partner_reported_usd_m"]),
                            "kiribati_recorded": r3(r["kiribati_recorded_usd_m"]),
                            "kiribati_months_published": int(r["kiribati_months_published"]),
                            "basis": "partner annual returns 2017-2025; 2026 = monthly reporters Jan-Aug"})
    return {"table4": table, "lines_1m_plus": lines, "by_year": by_year,
            "note": ("Partner-reported HS 88-89 exported to Kiribati, lines of USD 1m or more. Under BPM6 a "
                     "vessel or aircraft is a goods import when a resident acquires it, however it is financed. "
                     "China publishes no monthly data after 2024-12, so its 2025 deliveries cannot be dated by "
                     "month. Lines before 2022 (e.g. an aircraft from Brazil in 2020, a fishing vessel from "
                     "Taiwan in 2021) are in lines_1m_plus but not in the handout's Table 4.")}


def _staples(pipeline_root) -> dict:
    out = {}
    meta = {"rice": ("HS 1006", "Viet Nam and Australia do not report rice to Comtrade at HS6 monthly on time, "
                     "and China and Taiwan have not yet published 2025, so partner data cannot measure rice. "
                     "Kiribati's own data show rice imports up 40-50 percent in the last year, with suppliers "
                     "shifting from Australia to Viet Nam, Taiwan and China."),
            "sugar": ("HS 1701", "Both sources agree: USD 5-6.5m a year, mostly from Thailand.")}
    for prod, (hs, note) in meta.items():
        d = f"data/out/kiribati/{prod}"
        p_mm = find(pipeline_root, f"{d}/fish_mirror_monthly.csv")
        p_ma = find(pipeline_root, f"{d}/fish_mirror_annual.csv")
        p_mr = find(pipeline_root, f"{d}/fish_mirror_annual_by_reporter.csv")
        p_sm = find(pipeline_root, f"{d}/fish_self_monthly_detail.csv")
        p_sa = find(pipeline_root, f"{d}/fish_self_annual_detail.csv")
        if not (p_mm and p_sm):
            continue
        mm = pd.read_csv(p_mm); mm["year"] = mm["period"].astype(str).str[:4].astype(int)
        sm = pd.read_csv(p_sm); sm["year"] = sm["period"].astype(str).str[:4].astype(int)
        ma = pd.read_csv(p_ma).set_index("year") if p_ma else None
        sa = pd.read_csv(p_sa) if p_sa else None
        years = sorted(set(mm["year"]) | set(sm["year"]))
        rows = []
        for y in years:
            if y < 2017:
                continue
            a = mm[mm["year"] == y]
            s = sm[sm["year"] == y]
            rec = {"year": int(y),
                   "partner_monthly": r3(a["all_fish"].sum()) if len(a) else None,
                   "partner_months": int(a["period"].nunique()),
                   "partner_annual_return": r3(ma.loc[y, "all_fish"]) if ma is not None and y in ma.index else None,
                   "partner_n_reporters_annual": int(ma.loc[y, "n_reporters"]) if ma is not None and y in ma.index else None,
                   "kiribati_monthly": r3(s["value_usd_m"].sum()) if len(s) else None,
                   "kiribati_months": int(s["period"].nunique()),
                   "kiribati_annual_return": (r3(sa.loc[sa["year"] == y, "value_usd_m"].sum())
                                              if sa is not None and (sa["year"] == y).any() else None)}
            if rec["kiribati_months"] and 0 < rec["kiribati_months"] < 12:
                rec["kiribati_monthly_scaled12"] = r3(rec["kiribati_monthly"] * 12 / rec["kiribati_months"])
            else:
                rec["kiribati_monthly_scaled12"] = rec["kiribati_monthly"] if rec["kiribati_months"] == 12 else None
            top = (s.groupby("partnerDesc")["value_usd_m"].sum().sort_values(ascending=False).head(4))
            rec["kiribati_top_suppliers"] = [{"name": n, "value": r3(v)} for n, v in top.items() if v > 0.05]
            rows.append(rec)
        reporters = None
        if p_mr:
            rp = pd.read_csv(p_mr).set_index(pd.read_csv(p_mr).columns[0])
            cols = [c for c in rp.columns if c in ("2022", "2023", "2024", "2025")]
            rp = rp[cols]
            rp = rp[rp.sum(axis=1) > 0.05].sort_values("2024", ascending=False)
            reporters = [{"name": n, **{c: r3(v) for c, v in row.items()}} for n, row in rp.iterrows()]
        out[prod] = {"hs": hs, "unit": "USD millions", "annual": rows, "partner_reporters_recent": reporters,
                     "note": note,
                     "basis": ("partner_monthly sums every month partners published (all months, not only the "
                               "months Kiribati reported); kiribati_monthly sums Kiribati's own monthly returns "
                               "(kiribati_months of 12); *_annual_return are the annual datasets where one exists. "
                               "Pipeline files are named fish_* but hold this product.")}
    return out


def build_products(pipeline_root=None) -> dict:
    m, pairs_src = load_pairs(pipeline_root)
    m, excluded = split_excluded(m)
    months_by_year = {int(y): sorted(ym(p) for p in g["period"].unique()) for y, g in m.groupby("year")}

    def annual_tables(direction):
        tabs = {}
        for y in REPORT_YEARS:
            sub = m[(m["direction"] == direction) & (m["year"] == y)]
            if not sub.empty:
                tabs[str(y)] = _hs4_table(sub)
        return tabs

    end12 = max(m["period"].max(), LATEST_12M_END)      # moves forward on a live refresh
    start = (pd.Period(ym(end12), "M") - 11).strftime("%Y%m")
    w12 = m[(m["period"] >= start) & (m["period"] <= end12)]
    months12 = sorted(ym(p) for p in w12["period"].unique())
    all12 = [p.strftime("%Y-%m") for p in pd.period_range(ym(start), ym(end12), freq="M")]
    missing12 = [p for p in all12 if p not in months12]

    def latest(direction):
        sub = w12[w12["direction"] == direction]
        return {"end": ym(end12), "start": ym(start), "months_in_window": len(months12),
                "months_with_kiribati_return": months12, "months_without_kiribati_return": missing12,
                "rows": _hs4_table(sub),
                "note": (f"Window {ym(start)}..{ym(end12)}: {len(months12)} of 12 months. Months with no "
                         f"Kiribati return ({', '.join(missing12) or 'none'}) are null on the Kiribati side and are "
                         "also absent from the partner side of this dataset, which was pulled only for the months "
                         "Kiribati reported. Partner data are usable about 4 months after the reference month; "
                         "Thailand's June-July 2026 data were still missing at build time.")}

    products = {
        "meta": {"generated_at": now_iso(), "source": "UN Comtrade monthly HS6 (partner and Kiribati returns)",
                 "sources": [pairs_src, "data/out/kiribati/ships_hs6_annual_2.csv", "ships_monthly_partners.csv",
                             "ships_by_year.csv", "data/out/kiribati/rice/*", "data/out/kiribati/sugar/*"],
                 "unit": "USD millions", "excluded_lines": excluded,
                 "definitions": {"tuna_hs6": sorted(TUNA), "ships_aircraft": "HS chapters 88 and 89",
                                 "copra_and_coconut_oil": sorted(COPRA_CODES), "metals": "HS chapters 72-83",
                                 "other_fish": "HS chapter 03 and headings 1604-1605, excluding the tuna codes"},
                 "notes": []},
        "categories": _categories(m),
        "exports": {"annual": annual_tables("export"), "annual_months": {str(k): v for k, v in months_by_year.items()},
                    "latest_12m": latest("export")},
        "imports": {"annual": annual_tables("import"), "annual_months": {str(k): v for k, v in months_by_year.items()},
                    "latest_12m": latest("import")},
        "mirror_only_notable": _mirror_only(m),
        "ships_aircraft": _ships_aircraft(pipeline_root)["table4"],
        "ships_aircraft_detail": _ships_aircraft(pipeline_root),
        "staples": _staples(pipeline_root),
        "notes": [],
    }
    products["ships_aircraft_detail"].pop("table4", None)
    notes = [
        "categories (Table 2 of the handout, Jan 2025-Jul 2026, 17 months with a Kiribati return): both the "
        "recomputed value (partners, kiribati) and the handout value (handout_*) are given. They differ for tuna "
        "(97.4 here vs 100.8) and copra (6.5 vs 6.2) because the handout's partner-side category figures came "
        "from the 8 Sept data run, before a partner revision to frozen tuna fillets (19.5 -> 16.3); the total "
        "(109.7 vs 21.3) is the same in both. Kiribati-side figures agree throughout.",
        "The tuna gap is tuna coded to Kiribati by vessel flag; under balance-of-payments rules much of it may "
        "correctly sit outside Kiribati's goods exports. Copra and coconut oil runs the other way: Kiribati "
        "records more than partners.",
        "exports/imports.annual: top 15 HS4 headings per year ranked by the larger of the two sides, plus an "
        "'All other' row and a 'Total, all goods' row (is_summary = true). n_partners = number of partner "
        "countries that reported the heading that year. annual_months lists the months Kiribati reported; "
        "partner values cover those months only.",
        "Partner-reported imports are a lower bound; never compute a trade balance from these tables.",
        "mirror_only_notable: products partners report that Kiribati's own records do not show in the window; "
        "hs6 code, number of partners and months given; handout_value is bullet 14 of the handout.",
        "ships_aircraft: Table 4 of the handout recomputed from partners' annual returns (2026: monthly); "
        "ships_aircraft_detail has every line of USD 1m or more and the yearly totals with and without "
        "Kiribati's own record.",
        "Labels are plain-English shortenings of the HS headings (tracker/hs4_labels.py); where no label is "
        "listed the Comtrade description is shortened.",
    ]
    if excluded:
        notes.append("Kiribati's January 2024 import return has one line (HS 940690, prefabricated buildings, "
                     "USD 3,135m) worth about nine times GDP. It is set aside from the Kiribati-side figures in "
                     "these tables and listed in meta.excluded_lines; the 9406 row for 2024 shows the remaining "
                     "value of that heading.")
    products["meta"]["notes"] = notes
    products["notes"] = notes
    return products


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------
def _clean(o):
    """Turn numpy/pandas scalars into plain JSON types; NaN -> None."""
    import numpy as np
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if pd.isna(o) else float(o)
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def _dump(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_clean(obj), f, ensure_ascii=False, indent=1, allow_nan=False)


def write_all(out_dir, inputs_root=None, pipeline_root=None) -> dict[str, Path]:
    """Build the three JSON files.  `inputs_root` is the folder holding
    KIR_BOP.xlsx, KIR_MT.xlsx and KiriTrade/ (offline rebuild); `pipeline_root`
    overrides the pipeline folder (live run: the vendored tracker folder).
    When the workbooks exist the committed bop_extract.csv is refreshed."""
    out_dir = Path(out_dir)
    inputs_root = Path(inputs_root) if inputs_root else None
    bop_xlsx = inputs_root / "KIR_BOP.xlsx" if inputs_root else None
    mt_xlsx = inputs_root / "KIR_MT.xlsx" if inputs_root else None
    if pipeline_root is None and inputs_root is not None and (inputs_root / "KiriTrade").exists():
        pipeline_root = inputs_root / "KiriTrade"
    if bop_xlsx and bop_xlsx.exists():
        write_bop_extract(bop_xlsx, mt_xlsx, BOP_EXTRACT)
    else:
        bop_xlsx = mt_xlsx = None
    paths = {}
    na = build_national_accounts(bop_xlsx, mt_xlsx, pipeline_root)
    _dump(na, out_dir / "national_accounts.json"); paths["national_accounts"] = out_dir / "national_accounts.json"
    pe = build_peers(pipeline_root)
    _dump(pe, out_dir / "peers.json"); paths["peers"] = out_dir / "peers.json"
    pr = build_products(pipeline_root)
    _dump(pr, out_dir / "products.json"); paths["products"] = out_dir / "products.json"
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", default=None, help="folder with KIR_BOP.xlsx, KIR_MT.xlsx, KiriTrade/")
    ap.add_argument("--pipeline-root", default=None, help="pipeline folder (default: <inputs>/KiriTrade)")
    ap.add_argument("--out", default=str(HERE.parent / "data"), help="site/data")
    a = ap.parse_args(argv)
    paths = write_all(a.out, a.inputs, a.pipeline_root)
    for k, p in paths.items():
        print(f"wrote {k:18} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
