"""Quarterly output layers. Monthly data is stored; quarterly is reported.

Every table here aggregates upward from the HS6 rows. Nothing is ever computed
from a broader download, and the HS6 layer is never destroyed.
"""
from __future__ import annotations

import pandas as pd

# HS2 chapter -> broad economic sector. Edit freely; the mapping is a reporting
# convenience layer and never replaces the HS6 detail underneath it.
SECTOR_BY_CHAPTER: dict[str, str] = {
    **{f"{c:02d}": "Agriculture & food" for c in range(1, 25) if c != 3},
    "03": "Fish & seafood",
    **{f"{c:02d}": "Minerals & fuels" for c in range(25, 28)},
    "27": "Fuels",
    **{f"{c:02d}": "Chemicals & plastics" for c in range(28, 41)},
    **{f"{c:02d}": "Hides, wood, paper" for c in range(41, 50)},
    **{f"{c:02d}": "Textiles & apparel" for c in range(50, 64)},
    **{f"{c:02d}": "Other manufactures" for c in range(64, 72)},
    **{f"{c:02d}": "Metals" for c in range(72, 84)},
    **{f"{c:02d}": "Machinery & electrical" for c in range(84, 86)},
    **{f"{c:02d}": "Transport equipment" for c in range(86, 90)},
    **{f"{c:02d}": "Precision & misc." for c in range(90, 100)},
}

VALUE_COLS = ["value_self", "value_mirror", "diff_abs"]


def add_sector(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    out["hs2"] = out["cmd_code"].str[:2]
    out["hs4"] = out["cmd_code"].str[:4]
    out["sector"] = out["hs2"].map(SECTOR_BY_CHAPTER).fillna("Unclassified")
    return out


def _agg(d: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    g = (
        d.groupby(keys, dropna=False)
        .agg(
            value_self=("value_self", "sum"),
            value_mirror=("value_mirror", "sum"),
            mirror_only_value=("value_mirror", lambda x: x[d.loc[x.index, "mirror_only"]].sum()),
            self_only_value=("value_self", lambda x: x[d.loc[x.index, "self_only"]].sum()),
            n_products=("cmd_code", "nunique"),
            n_months=("period", "nunique"),
        )
        .reset_index()
    )
    g["diff_abs"] = g["value_mirror"] - g["value_self"]
    denom = (g["value_self"].abs() + g["value_mirror"].abs()) / 2
    g["sym_pct_diff"] = (g["diff_abs"] / denom * 100).where(denom > 0)
    return g


def quarterly_tables(metrics: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The five reporting tables: total, by partner, by product, by sector, flags."""
    d = add_sector(metrics)

    totals = _agg(d, ["quarter", "direction"])
    # Trade balance on each basis, from the subject's point of view.
    wide = totals.pivot_table(
        index="quarter", columns="direction",
        values=["value_self", "value_mirror"], aggfunc="sum",
    )
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    for basis in ("self", "mirror"):
        x, m = f"value_{basis}_export", f"value_{basis}_import"
        if x in wide.columns and m in wide.columns:
            wide[f"balance_{basis}"] = wide[x] - wide[m]
    balance = wide.reset_index()

    return {
        "quarterly_total": totals,
        "quarterly_balance": balance,
        "quarterly_by_partner": _agg(
            d, ["quarter", "direction", "counterpart_code", "counterpart_name"]
        ).sort_values(["quarter", "direction", "value_mirror"], ascending=[True, True, False]),
        "quarterly_by_product_hs6": _agg(
            d, ["quarter", "direction", "cmd_code", "cmd_desc"]
        ).sort_values(["quarter", "direction", "value_mirror"], ascending=[True, True, False]),
        "quarterly_by_product_hs4": _agg(d, ["quarter", "direction", "hs4"]),
        "quarterly_by_sector": _agg(d, ["quarter", "direction", "sector"]),
    }


def check_month_to_quarter(metrics: pd.DataFrame, quarterly: pd.DataFrame) -> pd.DataFrame:
    """Validation 4: monthly values must sum exactly to the quarterly totals."""
    monthly = (
        metrics.groupby(["quarter", "direction"], dropna=False)[["value_self", "value_mirror"]]
        .sum()
        .reset_index()
    )
    merged = monthly.merge(
        quarterly, on=["quarter", "direction"], suffixes=("_monthly", "_quarterly")
    )
    for c in ("value_self", "value_mirror"):
        merged[f"{c}_gap"] = (
            merged[f"{c}_monthly"] - merged[f"{c}_quarterly"]
        ).abs()
    merged["ok"] = (
        (merged["value_self_gap"] < 1e-6) & (merged["value_mirror_gap"] < 1e-6)
    )
    return merged
