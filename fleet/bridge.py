#!/usr/bin/env python3
"""
bridge.py -- KiriTrade GPS layer, stage 5: effort -> mirror bridge.

Origin in the mirror follows the catching vessel's FLAG, so the regressor
is flag-specific: Kiribati-origin tuna against KIR-FLAG fishing hours
(--flag to switch). Two known confounders are handled explicitly:

  * opposing trends -- KIR-flag hours trend up (fleet additions, AIS
    detection improving) while KIR-origin value trends down; a levels
    regression is dominated by that. The script therefore ALSO estimates
    in 12-month differences, which removes trend and seasonality.
  * effort vs CPUE -- hours measure searching, not landing; in poor
    months boats fish longer for less. If the 12m-difference relation is
    still weak/negative, the bridge needs CPUE and price controls, and the
    nowcast should ride on rolling value-per-hour ratios instead of OLS.

Prints: annual hours-vs-tuna table, lag correlations (levels and 12m
diffs), both OLS variants, actual-vs-fitted, the nowcast (from the 12m-
difference model: last year's tuna + b * change in hours), and the class
split when ownership_class (or --use-hints) is available.

Reads:  ..\\site_publish\\data\\series.json (or --series PATH)
        out\\fishing_monthly_windowed.csv, out\\vessel_master.csv
Writes: out\\bridge_panel.csv, out\\bridge_fit.csv

Usage (from the GPS folder):
    python bridge.py
    python bridge.py --flag NRU --min-reporters 2
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("out")
FLAGS = ("KIR", "NRU", "TUV")


def load_mirror(series_path):
    js = json.loads(Path(series_path).read_text(encoding="utf-8"))
    rows = [(m["period"], m.get("exports_partner_tuna"),
             m.get("n_reporters_fish"))
            for m in js.get("monthly", [])]
    return pd.DataFrame(rows, columns=["month", "tuna_usdm", "n_reporters_fish"])


def find_col(df, *keywords):
    for c in df.columns:
        lc = c.lower()
        if all(k in lc for k in keywords):
            return c
    return None


def load_hours(use_hints):
    h = pd.read_csv(OUT / "fishing_monthly_windowed.csv", dtype={"month": str})
    h["hours"] = pd.to_numeric(h["hours"], errors="coerce")
    master = pd.read_csv(OUT / "vessel_master.csv", dtype=str,
                         encoding_errors="replace")
    c_rflag = find_col(master, "flag", "fishing", "vessel")
    keep = ["gfw_vessel_id", "gfw_flag", "ownership_class", "class_hint"]
    if c_rflag:
        keep.append(c_rflag)
    m = (master[master["gfw_vessel_id"].notna()][keep]
         .drop_duplicates("gfw_vessel_id"))
    h = h.merge(m, left_on="vessel_id", right_on="gfw_vessel_id", how="left")

    rf_map = {"KI": "KIR", "NR": "NRU", "TV": "TUV"}

    def flag_of(row):
        f = str(row.get("gfw_flag") or "").strip().upper()
        if f in FLAGS:
            return f
        rf = str(row.get(c_rflag) or "").strip().upper() if c_rflag else ""
        return rf_map.get(rf, rf if rf in FLAGS else "")

    h["flag"] = h.apply(flag_of, axis=1)

    def cls(row):
        oc = str(row.get("ownership_class") or "").strip().upper()
        if oc.startswith("K"):
            return oc[:2]
        if use_hints:
            ch = str(row.get("class_hint") or "")
            if ch.startswith("K1"):
                return "K1h"
            if ch.startswith("K2"):
                return "K2h"
        return ""

    h["cls"] = h.apply(cls, axis=1)

    panel = h.groupby("month")["hours"].sum().rename("hours_total").to_frame()
    for f in FLAGS:
        s = h[h["flag"] == f].groupby("month")["hours"].sum()
        panel = panel.join(s.rename(f"hours_{f}"), how="left")
    hc = h[h["cls"] != ""]
    if len(hc):
        by_cls = hc.pivot_table(index="month", columns="cls",
                                values="hours", aggfunc="sum").add_prefix("hours_")
        panel = panel.join(by_cls, how="left")
    return panel.reset_index()


def ols(y, X):
    Xc = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    fit = Xc @ beta
    ss_res = ((y - fit) ** 2).sum()
    ss_tot = ((y - y.mean()) ** 2).sum()
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return beta, r2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default=r"..\site_publish\data\series.json")
    ap.add_argument("--flag", default="KIR", choices=list(FLAGS))
    ap.add_argument("--min-reporters", type=int, default=3)
    ap.add_argument("--use-hints", action="store_true")
    ap.add_argument("--start", default="2017-01")
    args = ap.parse_args()

    sp = Path(args.series)
    if not sp.exists():
        sys.exit(f"series.json not found at {sp} -- pass --series PATH.")

    mirror = load_mirror(sp)
    hours = load_hours(args.use_hints)
    df = mirror.merge(hours, on="month", how="outer").sort_values("month")
    df = df[df["month"] >= args.start].reset_index(drop=True)
    hcol = f"hours_{args.flag}"
    for c in ("hours_total", hcol):
        df[c] = pd.to_numeric(df.get(c), errors="coerce").fillna(0.0)
    df["h_l1"] = df[hcol].shift(1)
    df["h_l2"] = df[hcol].shift(2)
    df["d12_tuna"] = df["tuna_usdm"] - df["tuna_usdm"].shift(12)
    df["d12_h_l1"] = df["h_l1"] - df["h_l1"].shift(12)
    df["d12_h_l2"] = df["h_l2"] - df["h_l2"].shift(12)
    df.to_csv(OUT / "bridge_panel.csv", index=False, encoding="utf-8-sig")

    # ---- annual table -------------------------------------------------------
    ann = df.copy()
    ann["year"] = ann["month"].str[:4]
    at = ann.groupby("year").agg(
        tuna=("tuna_usdm", "sum"), months=("tuna_usdm", "count"),
        kir_hours=(hcol, "sum")).reset_index()
    print(f"annual: Kiribati-origin tuna (USDm, sum of published months) vs "
          f"{args.flag}-flag hours")
    for _, r in at.iterrows():
        print(f"    {r['year']}  tuna {r['tuna']:7.1f} ({int(r['months']):2d}m)   "
              f"hours {r['kir_hours']:9.0f}")

    solid = (df["tuna_usdm"].notna()
             & (pd.to_numeric(df["n_reporters_fish"], errors="coerce")
                .fillna(0) >= args.min_reporters))
    est = df[solid].copy()
    print(f"\nregressor: {hcol}; estimation months: {len(est)} "
          f"({int((df['tuna_usdm'].notna() & ~solid).sum())} provisional excluded)")

    print("corr, LEVELS  tuna_t ~ h_(t-k):        ", end="")
    print("  ".join(f"k={k}: {est['tuna_usdm'].corr(df[hcol].shift(k).loc[est.index]):+.3f}"
                    for k in range(0, 3)))
    d = df[solid & df["d12_tuna"].notna()]
    print("corr, 12M-DIFF d12tuna ~ d12h_(t-k):   ", end="")
    print("  ".join(f"k={k}: {d['d12_tuna'].corr((df[hcol].shift(k) - df[hcol].shift(k + 12)).loc[d.index]):+.3f}"
                    for k in range(0, 3)))

    # ---- OLS in levels ------------------------------------------------------
    reg = est.dropna(subset=["h_l1", "h_l2"])
    bL, r2L = ols(reg["tuna_usdm"].to_numpy(float),
                  reg[["h_l1", "h_l2"]].to_numpy(float))
    print(f"\nOLS levels:   N={len(reg)}, R2={r2L:.3f}; "
          f"b1={bL[1] * 1000:+.2f}, b2={bL[2] * 1000:+.2f} USDm per 1000 h")

    # ---- OLS in 12m differences --------------------------------------------
    regd = df[solid].dropna(subset=["d12_tuna", "d12_h_l1", "d12_h_l2"])
    bD, r2D = ols(regd["d12_tuna"].to_numpy(float),
                  regd[["d12_h_l1", "d12_h_l2"]].to_numpy(float))
    print(f"OLS 12m-diff: N={len(regd)}, R2={r2D:.3f}; "
          f"b1={bD[1] * 1000:+.2f}, b2={bD[2] * 1000:+.2f} USDm per 1000 h "
          f"(trend/seasonality removed)")

    # ---- fitted / nowcast from the 12m-difference model ---------------------
    full = df.dropna(subset=["d12_h_l1", "d12_h_l2"]).copy()
    base = full["tuna_usdm"].shift(12)
    full["fitted_usdm"] = (base + bD[0] + bD[1] * full["d12_h_l1"]
                           + bD[2] * full["d12_h_l2"])
    full["nowcast"] = full["tuna_usdm"].isna() & full["fitted_usdm"].notna()
    full["provisional"] = full["tuna_usdm"].notna() & ~solid.loc[full.index]
    fit = full[["month", "tuna_usdm", "fitted_usdm", "nowcast",
                "provisional", hcol]]
    fit.to_csv(OUT / "bridge_fit.csv", index=False, encoding="utf-8-sig")

    print("\nlast 6 solid months, actual vs fitted (12m-diff model, USDm):")
    for _, r in full[~full["nowcast"] & ~full["provisional"]
                     & full["fitted_usdm"].notna()].tail(6).iterrows():
        print(f"    {r['month']}  actual {r['tuna_usdm']:6.1f}   "
              f"fitted {r['fitted_usdm']:6.1f}")
    now = full[full["nowcast"] & (full[hcol] > 0)]
    if len(now):
        print("nowcast (= same month last year + effect of hours change):")
        for _, r in now.iterrows():
            print(f"    {r['month']}  fitted {r['fitted_usdm']:6.1f}")

    # ---- class split (conditional) ------------------------------------------
    cls_cols = [c for c in df.columns
                if c.startswith("hours_K") and c != "hours_KIR"]
    if cls_cols:
        tail = df[df[hcol] > 0].tail(12)
        tot = tail[hcol].sum()
        label = ("provisional, from class_hint" if args.use_hints
                 else "from manual ownership_class")
        print(f"\nhours share by ownership class, last 12 active months "
              f"({label}; residence stated as a condition, not a fact):")
        for c in sorted(cls_cols):
            share = tail[c].fillna(0).sum() / tot if tot else np.nan
            print(f"    {c.replace('hours_', '')}: {100 * share:5.1f}%")
    else:
        print("\nownership_class empty and --use-hints not set: no class split.")

    print("\nNote: tuna = partner-reported Kiribati-origin, all partners, CIF, "
          "USDm; hours = flagged fleet inside registration windows. If the "
          "12m-diff relation is weak, the next control is CPUE and the "
          "Bangkok skipjack price (value = effort x CPUE x price).")


if __name__ == "__main__":
    main()
