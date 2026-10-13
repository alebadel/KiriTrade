"""Mirror pairing: put the subject's own report next to the partner's report.

Both sides are first normalised onto one orientation - always from the subject
country's point of view - so that the join key is symmetric:

    direction "export"  = subject -> counterpart
        self side   : reporter=subject, flow X
        mirror side : reporter=counterpart, partner=subject, flow M

    direction "import"  = counterpart -> subject
        self side   : reporter=subject, flow M
        mirror side : reporter=counterpart, partner=subject, flow X
"""
from __future__ import annotations

import logging

import pandas as pd

from .config import Config

log = logging.getLogger(__name__)

CANON = [
    "period", "year", "quarter", "direction", "counterpart_code",
    "counterpart_name", "classification", "cmd_code", "cmd_desc",
    "value", "fob", "cif", "net_wgt", "qty", "qty_unit",
]


def _num(s):
    return pd.to_numeric(s, errors="coerce")


def normalise(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Map either side onto the subject's orientation."""
    if df.empty:
        return pd.DataFrame(columns=CANON + ["side"])

    d = df.copy()
    d["side"] = d["side"].astype(str)
    is_self = d["side"] == "self"
    flow = d["flowCode"].astype(str).str.upper()

    # Direction from the subject's point of view.
    d["direction"] = pd.Series(
        pd.NA, index=d.index, dtype="object"
    )
    d.loc[is_self & (flow == "X"), "direction"] = "export"
    d.loc[is_self & (flow == "M"), "direction"] = "import"
    d.loc[~is_self & (flow == "M"), "direction"] = "export"
    d.loc[~is_self & (flow == "X"), "direction"] = "import"

    # Counterpart: the country that is not the subject.
    d["counterpart_code"] = _num(
        d["partnerCode"].where(is_self, d["reporterCode"])
    ).astype("Int64")
    src_name = d.get("partnerDesc", pd.Series(index=d.index, dtype=object))
    rep_name = d.get("reporterDesc", pd.Series(index=d.index, dtype=object))
    d["counterpart_name"] = src_name.where(is_self, rep_name)

    d["period"] = d["period"].astype(str)
    d["year"] = d["period"].str[:4].astype(int)
    month = d["period"].str[4:6].astype(int)
    d["quarter"] = d["year"].astype(str) + "Q" + ((month - 1) // 3 + 1).astype(str)

    d["classification"] = d.get("classificationCode", pd.NA)
    d["cmd_code"] = d["cmdCode"].astype(str).str.zfill(6)
    d["cmd_desc"] = d.get("cmdDesc", pd.NA)

    d["fob"] = _num(d.get("fobvalue"))
    d["cif"] = _num(d.get("cifvalue"))
    d["value"] = _num(d.get("primaryValue"))
    d["net_wgt"] = _num(d.get("netWgt"))
    d["qty"] = _num(d.get("qty"))
    d["qty_unit"] = d.get("qtyUnitAbbr", pd.NA)

    d = d[d["direction"].notna() & d["counterpart_code"].notna()]
    d = d[d["counterpart_code"] != cfg.code]
    return d[CANON + ["side"]].reset_index(drop=True)


def _collapse(d: pd.DataFrame, side: str) -> pd.DataFrame:
    """One row per period x direction x counterpart x product, per side."""
    sub = d[d["side"] == side]
    if sub.empty:
        return pd.DataFrame()
    keys = ["period", "year", "quarter", "direction", "counterpart_code", "cmd_code"]
    agg = (
        sub.groupby(keys, dropna=False)
        .agg(
            value=("value", "sum"),
            fob=("fob", "sum"),
            cif=("cif", "sum"),
            net_wgt=("net_wgt", "sum"),
            qty=("qty", "sum"),
            counterpart_name=("counterpart_name", "first"),
            cmd_desc=("cmd_desc", "first"),
            classification=("classification", "first"),
            qty_unit=("qty_unit", "first"),
            n_rows=("value", "size"),
        )
        .reset_index()
    )
    suffix = "_self" if side == "self" else "_mirror"
    rename = {
        c: c + suffix
        for c in ("value", "fob", "cif", "net_wgt", "qty", "n_rows",
                  "classification", "qty_unit", "cmd_desc", "counterpart_name")
    }
    return agg.rename(columns=rename)


def build_pairs(normalised: pd.DataFrame) -> pd.DataFrame:
    """Full outer join of the two sides. Unmatched rows are kept, not dropped."""
    keys = ["period", "year", "quarter", "direction", "counterpart_code", "cmd_code"]
    left = _collapse(normalised, "self")
    right = _collapse(normalised, "mirror")

    if left.empty and right.empty:
        return pd.DataFrame(columns=keys)
    if left.empty:
        pairs = right.copy()
        for c in ("value_self", "net_wgt_self", "qty_self"):
            pairs[c] = pd.NA
    elif right.empty:
        pairs = left.copy()
        for c in ("value_mirror", "net_wgt_mirror", "qty_mirror"):
            pairs[c] = pd.NA
    else:
        pairs = left.merge(right, on=keys, how="outer")

    # Descriptive fields: take whichever side supplied one.
    for base in ("counterpart_name", "cmd_desc", "classification", "qty_unit"):
        s, m = f"{base}_self", f"{base}_mirror"
        if s in pairs.columns or m in pairs.columns:
            pairs[base] = pairs.get(s, pd.Series(index=pairs.index, dtype=object))
            if m in pairs.columns:
                pairs[base] = pairs[base].fillna(pairs[m])
            pairs = pairs.drop(columns=[c for c in (s, m) if c in pairs.columns])

    pairs["hs4"] = pairs["cmd_code"].str[:4]
    pairs["hs2"] = pairs["cmd_code"].str[:2]
    return pairs.sort_values(keys).reset_index(drop=True)
