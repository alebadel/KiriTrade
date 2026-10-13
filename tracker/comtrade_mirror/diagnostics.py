"""Discrepancy metrics and forensic flags.

A discrepancy is a question, not a finding. Every metric here is descriptive;
none of them asserts under-reporting. The legitimate causes listed in the
project note - FOB vs CIF, shipment timing, origin vs consignment,
transshipment and re-export, HS revision differences, confidentiality,
reporting thresholds, missing reporter periods - all produce the same
arithmetic signature as under-reporting on a single observation. Only
persistence and independent corroboration separate them, which is why the
flags below are built on counts of months and counts of partners.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Rough CIF/FOB wedge for Pacific island freight; used only to label whether a
# gap is inside the range plausibly explained by valuation basis.
CIF_FOB_BAND = (1.00, 1.25)


def add_metrics(pairs: pd.DataFrame) -> pd.DataFrame:
    d = pairs.copy()
    s = pd.to_numeric(d.get("value_self"), errors="coerce")
    m = pd.to_numeric(d.get("value_mirror"), errors="coerce")
    d["value_self"], d["value_mirror"] = s, m

    d["diff_abs"] = m - s
    with np.errstate(divide="ignore", invalid="ignore"):
        d["ratio_mirror_over_self"] = np.where(s > 0, m / s, np.nan)
    denom = (s.abs() + m.abs()) / 2
    d["sym_pct_diff"] = np.where(denom > 0, (m - s) / denom * 100, np.nan)

    d["self_only"] = s.notna() & (s > 0) & (m.isna() | (m == 0))
    d["mirror_only"] = m.notna() & (m > 0) & (s.isna() | (s == 0))
    d["both_report"] = (s.fillna(0) > 0) & (m.fillna(0) > 0)

    # Weight discrepancy, where both sides gave a comparable net weight.
    ws = pd.to_numeric(d.get("net_wgt_self"), errors="coerce")
    wm = pd.to_numeric(d.get("net_wgt_mirror"), errors="coerce")
    d["wgt_diff_abs"] = wm - ws
    wden = (ws.abs() + wm.abs()) / 2
    d["wgt_sym_pct_diff"] = np.where(wden > 0, (wm - ws) / wden * 100, np.nan)

    # Is the gap within what CIF-vs-FOB alone could explain?
    lo, hi = CIF_FOB_BAND
    r = d["ratio_mirror_over_self"]
    d["within_cif_fob_band"] = np.where(
        d["direction"].eq("export") & r.notna(), r.between(lo, hi), False
    )
    return d


def forensic_flags(
    metrics: pd.DataFrame,
    *,
    min_months: int = 2,
    min_partners: int = 2,
    min_value: float = 10_000.0,
) -> pd.DataFrame:
    """Products where partners report material trade the subject does not.

    Returns one row per direction x product, with the persistence and
    corroboration counts that decide whether a gap deserves investigation.
    """
    d = metrics[metrics["mirror_only"]].copy()
    if d.empty:
        return pd.DataFrame(
            columns=["direction", "cmd_code", "cmd_desc", "mirror_only_value",
                     "n_months", "n_partners", "partners", "flag"]
        )

    g = (
        d.groupby(["direction", "cmd_code"], dropna=False)
        .agg(
            cmd_desc=("cmd_desc", "first"),
            mirror_only_value=("value_mirror", "sum"),
            n_months=("period", "nunique"),
            n_partners=("counterpart_code", "nunique"),
            partners=("counterpart_name", lambda x: ", ".join(
                sorted({str(v) for v in x.dropna()})[:8]
            )),
        )
        .reset_index()
    )
    g["persistent"] = g["n_months"] >= min_months
    g["corroborated"] = g["n_partners"] >= min_partners
    g["material"] = g["mirror_only_value"] >= min_value
    g["flag"] = np.select(
        [
            g["persistent"] & g["corroborated"] & g["material"],
            g["material"] & (g["persistent"] | g["corroborated"]),
        ],
        ["investigate", "watch"],
        default="noise",
    )
    return g.sort_values(
        ["flag", "mirror_only_value"], ascending=[True, False]
    ).reset_index(drop=True)


def coverage_report(metrics: pd.DataFrame, expected_periods: list[str]) -> pd.DataFrame:
    """Which months each side actually reported. Absence is not zero."""
    rows = []
    for p in expected_periods:
        sub = metrics[metrics["period"] == p]
        rows.append(
            {
                "period": p,
                "self_rows": int(sub["value_self"].notna().sum()),
                "mirror_rows": int(sub["value_mirror"].notna().sum()),
                "self_reported": bool(sub["value_self"].notna().any()),
                "mirror_reported": bool(sub["value_mirror"].notna().any()),
                "n_partners": int(sub["counterpart_code"].nunique()),
            }
        )
    return pd.DataFrame(rows)
