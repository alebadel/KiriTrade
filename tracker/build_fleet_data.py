#!/usr/bin/env python3
"""
build_fleet_data.py -- builds data/fleet.json for the "Fleet activity (AIS)" page.

Reads the KiriTrade GPS-layer outputs (GPS/out/*.csv) and writes AGGREGATES ONLY:
no vessel names, no identifiers (IMO, MMSI, call sign, GFW ids), no company or
operator names. The register-flag tenure windows (registration_windows.csv)
trim every event to the period a vessel was on the Kiribati, Nauru or Tuvalu
register, exactly as GPS/window_events.py does.

Inputs (all under --gps-out, default GPS/out next to the site folder):
  fishing_monthly_windowed.csv   vessel x month x EEZ fishing hours, windowed
  registration_windows.csv       register-flag tenure windows per vessel
  events_port_visits.csv         GFW port visits (not windowed; trimmed here)
  shipment_chain_windowed.csv    encounter -> next port -> Thai port, windowed
  bridge_panel.csv               monthly KIR-flag hours (reconciliation only)
  vessel_master.csv              vessel flag lookup (identifiers are never copied)

Output: data/fleet.json
  monthly[]            {period, kir_hours_total, kir_hours_kir_eez, kir_hours_other}
  port_calls_quarterly[] {quarter, KIR, CHN, KOR, THA, other, total}
  chain_facts          {tha_share_pct, lag_median_days, lag_p25, lag_p75,
                        n_encounters, ...}   (register fleet: KIR, NRU, TUV)
  chain_facts_kir      same, catchers on the Kiribati flag only
  meta                 {ais_through, rfv_export_date, notes, ...}

"KIR-flag" follows GPS/bridge.py: the vessel's GFW flag if it is KIR/NRU/TUV,
otherwise the WCPFC register flag code (KI/NR/TV).

Usage:
    python tracker/build_fleet_data.py
    python tracker/build_fleet_data.py --gps-out "C:\\...\\KiriTrade\\GPS\\out" --out data/fleet.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SITE = HERE.parent
FLAGS = ("KIR", "NRU", "TUV")
RFV_CODE = {"KI": "KIR", "NR": "NRU", "TV": "TUV"}
KIR_EEZ = {"8488", "8450", "8441"}      # Gilbert, Phoenix, Line (Marine Regions ids)
DEST = ("KIR", "CHN", "KOR", "THA")     # everything else -> "other"
THA_WINDOW_DAYS = 120

NOTES = [
    "Hours and port calls are observed from ship-borne AIS transmissions received by Global Fishing Watch; "
    "they describe where Kiribati-flagged vessels were seen, not what they caught.",
    "Only the period during which a vessel was on the Kiribati, Nauru or Tuvalu register is counted "
    "(register-flag tenure); earlier and later history of the same hull is left out.",
    "Port calls are recorded by AIS; a call is not a landing, and the number of calls says nothing about tonnage.",
    "The latest month is partial and AIS coverage varies by vessel and by sea area.",
]


# ---------------------------------------------------------------- helpers
def _read(path: Path, **kw) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace", **kw)


def flag_of(gfw_flag, rfv_flag) -> str:
    """Flag used for the 'Kiribati-flag' split (same rule as GPS/bridge.py)."""
    f = str(gfw_flag if isinstance(gfw_flag, str) else "").strip().upper()
    if f in FLAGS:
        return f
    r = str(rfv_flag if isinstance(rfv_flag, str) else "").strip().upper()
    return RFV_CODE.get(r, r if r in FLAGS else "")


def vessel_flags(master: pd.DataFrame) -> dict:
    """gfw_vessel_id -> KIR/NRU/TUV (or '')."""
    c_rfv = next((c for c in master.columns if "flag" in c.lower() and "fishing" in c.lower()
                  and "vessel" in c.lower()), None)
    m = master[master["gfw_vessel_id"].notna() & (master["gfw_vessel_id"] != "")]
    m = m.drop_duplicates("gfw_vessel_id")
    return {r["gfw_vessel_id"]: flag_of(r.get("gfw_flag"), r.get(c_rfv) if c_rfv else None)
            for _, r in m.iterrows()}


def load_windows(path: Path) -> dict:
    """gfw_vessel_id -> list[(start, end)] (UTC, end NaT = open)."""
    w = _read(path, dtype=str)
    w["s"] = pd.to_datetime(w["start"], errors="coerce", utc=True)
    w["e"] = pd.to_datetime(w["end"], errors="coerce", utc=True)
    out: dict = {}
    for vid, s, e in zip(w["gfw_vessel_id"], w["s"], w["e"]):
        if pd.notna(s):
            out.setdefault(vid, []).append((s, e))
    return out


def in_window(windows: dict, vid, t) -> bool:
    if vid not in windows or pd.isna(t):
        return True          # same rule as window_events.py: no window info -> keep
    return any(t >= s and (pd.isna(e) or t <= e) for s, e in windows[vid])


def _r(x, n=1):
    return None if x is None or pd.isna(x) else round(float(x), n)


# ---------------------------------------------------------------- builders
def build_monthly(hours: pd.DataFrame, flags: dict) -> list:
    h = hours.copy()
    h["hours"] = pd.to_numeric(h["hours"], errors="coerce").fillna(0.0)
    h["flag"] = h["vessel_id"].map(flags).fillna("")
    k = h[h["flag"] == "KIR"].copy()
    k["eez"] = k["eez"].astype(str).str.replace(r"\.0$", "", regex=True)
    k["home"] = k["eez"].isin(KIR_EEZ)
    k["month"] = k["month"].astype(str)
    if k.empty:
        return []
    tot = k.groupby("month")["hours"].sum()
    home = k[k["home"]].groupby("month")["hours"].sum()
    idx = pd.period_range(tot.index.min(), tot.index.max(), freq="M").astype(str)
    rows = []
    for p in idx:
        t = float(tot.get(p, 0.0))
        hm = float(home.get(p, 0.0))
        rows.append({"period": p, "kir_hours_total": round(t, 1),
                     "kir_hours_kir_eez": round(hm, 1), "kir_hours_other": round(t - hm, 1)})
    return rows


def build_port_calls(visits: pd.DataFrame, flags: dict, windows: dict) -> list:
    v = visits.copy()
    v["flag"] = v["vessel_id"].map(flags).fillna("")
    v = v[v["flag"] == "KIR"].copy()
    v["t"] = pd.to_datetime(v["start"], errors="coerce", utc=True)
    v = v[v["t"].notna()]
    keep = [in_window(windows, vid, t) for vid, t in zip(v["vessel_id"], v["t"])]
    v = v[keep]
    if v.empty:
        return []
    v["dest"] = v["port_flag"].fillna("").str.upper().map(lambda c: c if c in DEST else "other")
    v["quarter"] = v["t"].dt.tz_localize(None).dt.to_period("Q").astype(str)
    piv = v.groupby(["quarter", "dest"]).size().unstack(fill_value=0)
    for c in (*DEST, "other"):
        if c not in piv.columns:
            piv[c] = 0
    idx = pd.period_range(piv.index.min(), piv.index.max(), freq="Q").astype(str)
    piv = piv.reindex(idx, fill_value=0)
    rows = []
    for q, r in piv.iterrows():
        d = {"quarter": q}
        for c in (*DEST, "other"):
            d[c] = int(r[c])
        d["total"] = int(sum(d[c] for c in (*DEST, "other")))
        rows.append(d)
    return rows


def chain_stats(ch: pd.DataFrame) -> dict:
    n = len(ch)
    # An encounter is followed by a Thai call when days_to_tha_port is set (carriers_pull.py sets it
    # only if a Thai call was found within the window). tha_port_name can be blank for a found call
    # (33 of 194 in the 20 Oct build), so it must not be used to count them.
    lag_all = pd.to_numeric(ch["days_to_tha_port"], errors="coerce")
    tha = lag_all.notna()
    lags = lag_all[tha]
    return {
        "n_encounters": int(n),
        "n_followed_by_tha_call": int(tha.sum()),
        "tha_share_pct": _r(100 * tha.sum() / n) if n else None,
        "lag_median_days": _r(lags.median(), 0) if len(lags) else None,
        "lag_p25": _r(lags.quantile(.25), 0) if len(lags) else None,
        "lag_p75": _r(lags.quantile(.75), 0) if len(lags) else None,
        "tha_window_days": THA_WINDOW_DAYS,
    }


def build_chain(chain: pd.DataFrame, flags: dict) -> tuple:
    c = chain.copy()
    c["flag"] = c["catcher_id"].map(flags).fillna("")
    allf = chain_stats(c)
    allf["scope"] = "Vessels on the Kiribati, Nauru or Tuvalu register, inside register tenure"
    kir = chain_stats(c[c["flag"] == "KIR"])
    kir["scope"] = "Vessels on the Kiribati register, inside register tenure"
    return allf, kir


def latest_date(*series) -> str | None:
    best = None
    for s in series:
        t = pd.to_datetime(s, errors="coerce", utc=True).max()
        if pd.notna(t) and (best is None or t > best):
            best = t
    return best.strftime("%Y-%m-%d") if best is not None else None


def rfv_date(out_dir: Path, override: str | None) -> str | None:
    if override:
        return override
    exports = sorted(out_dir.glob("Rfv_database_export_*.csv")) + sorted(out_dir.glob("rfv_database_export_*.csv"))
    for p in reversed(exports):
        m = re.search(r"_(\d{9,11})\.csv$", p.name)
        if m:
            return dt.datetime.fromtimestamp(int(m.group(1)), dt.timezone.utc).strftime("%Y-%m-%d")
    p = out_dir / "rfv_current.csv"
    if p.exists():
        return dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).strftime("%Y-%m-%d")
    return None


def build(gps_out: Path, rfv_override: str | None = None, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    flags = vessel_flags(_read(gps_out / "vessel_master.csv", dtype=str))
    windows = load_windows(gps_out / "registration_windows.csv")

    hours = _read(gps_out / "fishing_monthly_windowed.csv", dtype={"month": str, "eez": str})
    visits = _read(gps_out / "events_port_visits.csv", dtype=str)
    chain = _read(gps_out / "shipment_chain_windowed.csv", dtype=str)

    monthly = build_monthly(hours, flags)
    calls = build_port_calls(visits, flags, windows)
    chain_all, chain_kir = build_chain(chain, flags)

    fishing_raw = gps_out / "events_fishing.csv"
    ends = [visits["start"]]
    if fishing_raw.exists():
        ends.append(_read(fishing_raw, dtype=str, usecols=["end"])["end"])
    through = latest_date(*ends)
    last_month = monthly[-1]["period"] if monthly else None

    v_hours = hours.assign(flag=hours["vessel_id"].map(flags).fillna(""))
    n_fishing = int(v_hours.loc[v_hours["flag"] == "KIR", "vessel_id"].nunique())

    return {
        "meta": {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ais_through": through,
            "rfv_export_date": rfv_date(gps_out, rfv_override),
            "partial_month": last_month if through and last_month and through[:7] == last_month
                             and int(through[8:10]) < 28 else None,
            "n_kir_flag_vessels_with_fishing_hours": n_fishing,
            "ais_source": "Global Fishing Watch (Events API, Vessels API)",
            "register_source": "WCPFC Record of Fishing Vessels",
            "units": {"hours": "fishing hours detected by AIS", "port_calls": "count of port visits"},
            "notes": NOTES,
        },
        "monthly": monthly,
        "port_calls_quarterly": calls,
        "chain_facts": chain_all,
        "chain_facts_kir": chain_kir,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gps-out", default=str(SITE.parent / "GPS" / "out"),
                    help="folder with the GPS-layer CSV outputs")
    ap.add_argument("--out", default=str(SITE / "data" / "fleet.json"))
    ap.add_argument("--rfv-export-date", default=None, help="YYYY-MM-DD of the WCPFC register export")
    a = ap.parse_args(argv)
    gps = Path(a.gps_out)
    if not (gps / "fishing_monthly_windowed.csv").exists():
        print(f"GPS output folder not found or incomplete: {gps}", file=sys.stderr)
        return 2
    js = build(gps, a.rfv_export_date)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(js, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    m = js["meta"]
    print(f"wrote {out}: {len(js['monthly'])} months, {len(js['port_calls_quarterly'])} quarters, "
          f"AIS through {m['ais_through']}, register export {m['rfv_export_date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
