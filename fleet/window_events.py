#!/usr/bin/env python3
"""
window_events.py -- KiriTrade GPS layer, stage 4: registration windows.

GFW vessel identities span a hull's whole AIS history, including years
before it flagged into KIR/NRU/TUV (which is why Russian-EEZ fishing hours
showed up for the register fleet). This script trims every event to the
vessel's register-flag tenure.

Window sources, in order of preference per vessel:
  1. FLAG SEGMENTS (precise): each GFW identity's selfReportedInfo is a
     list of AIS segments with their own flag and transmission dates.
     The window is the union of segments whose flag is KIR/NRU/TUV --
     read from the cached out\\gfw_raw_<FLAG>.json, no new downloads.
  2. AUTHORIZATION DATES (fallback, conservative): the RFV export's
     'Start/End of period of validity of authorization' (plus charter
     dates), for register vessels with no KIR/NRU/TUV AIS segment
     (e.g. chartered carriers currently under KOR/PAN/etc. flags).
  3. No window info at all -> events kept.

Reads:  out\\gfw_raw_*.json, out\\vessel_master.csv, out\\events_fishing.csv,
        out\\shipment_chain.csv, out\\rfv_current.csv [, rfv_with_deleted.csv]
Writes: out\\registration_windows.csv
        out\\fishing_monthly_windowed.csv
        out\\shipment_chain_windowed.csv

Usage (from the GPS folder):
    python window_events.py
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

OUT = Path("out")
REG_FLAGS = {"KIR", "NRU", "TUV"}
KIR_EEZ = {"8488", "8450", "8441"}
EEZ_NAMES = {"5690": "Russia", "8488": "KIR-Gilbert", "8450": "KIR-Phoenix",
             "8441": "KIR-Line", "8317": "Nauru", "8324": "PNG",
             "8326": "Tuvalu", "8316": "FSM", "8318": "eez=8318",
             "": "(high seas)"}


def col(df, *keywords):
    for c in df.columns:
        lc = c.lower()
        if all(k in lc for k in keywords):
            return c
    return None


def load_flag_segments():
    """vid -> list of (start, end) where the self-reported flag is a
    register flag. end may be NaT (still transmitting)."""
    ivals = {}
    for f in sorted(REG_FLAGS):
        p = OUT / f"gfw_raw_{f}.json"
        if not p.exists():
            continue
        for e in json.loads(p.read_text(encoding="utf-8")):
            srep = e.get("selfReportedInfo") or []
            comb = (e.get("combinedSourcesInfo") or [{}])[0]
            vid = (srep[0].get("id") if srep else None) or comb.get("vesselId")
            if not vid:
                continue
            for seg in srep:
                if str(seg.get("flag", "")).upper() in REG_FLAGS:
                    s = pd.to_datetime(seg.get("transmissionDateFrom"),
                                       errors="coerce", utc=True)
                    t = pd.to_datetime(seg.get("transmissionDateTo"),
                                       errors="coerce", utc=True)
                    if pd.notna(s):
                        ivals.setdefault(vid, []).append((s, t))
    return ivals


def load_auth_windows():
    """win -> (start, end) from RFV authorization + charter dates."""
    frames = []
    for name in ("rfv_current.csv", "rfv_with_deleted.csv"):
        p = OUT / name
        if not p.exists():
            continue
        df = pd.read_csv(p, dtype=str, encoding_errors="replace")
        c_win = col(df, "win") or col(df, "identification")
        c_a0, c_a1 = col(df, "start", "validity"), col(df, "end", "validity")
        c_c0, c_c1 = col(df, "start", "charter"), col(df, "expiration", "charter")
        if not (c_win and c_a0 and c_a1):
            continue
        frames.append(pd.DataFrame({
            "win": df[c_win].str.strip().str.upper(),
            "a0": pd.to_datetime(df[c_a0], errors="coerce", utc=True),
            "a1": pd.to_datetime(df[c_a1], errors="coerce", utc=True),
            "c0": pd.to_datetime(df[c_c0], errors="coerce", utc=True) if c_c0 else pd.NaT,
            "c1": pd.to_datetime(df[c_c1], errors="coerce", utc=True) if c_c1 else pd.NaT,
        }))
    if not frames:
        return {}
    rfv = pd.concat(frames, ignore_index=True)
    rfv["s"] = rfv[["a0", "c0"]].min(axis=1)
    rfv["e"] = rfv[["a1", "c1"]].max(axis=1)
    g = rfv.groupby("win").agg(s=("s", "min"), e=("e", "max"))
    return {w: (r["s"], r["e"]) for w, r in g.iterrows() if pd.notna(r["s"])}


def main():
    segs = load_flag_segments()
    auth = load_auth_windows()

    master = pd.read_csv(OUT / "vessel_master.csv", dtype=str,
                         encoding_errors="replace")
    c_mwin = col(master, "win") or col(master, "identification")
    fleet = master[(master["match_method"] != "GFW_ONLY")
                   & master["gfw_vessel_id"].notna()
                   & (master["gfw_vessel_id"] != "")].copy()

    rows, n_seg, n_auth, n_none = [], 0, 0, 0
    for _, r in fleet.iterrows():
        vid = r["gfw_vessel_id"]
        w = str(r.get(c_mwin) or "").strip().upper() if c_mwin else ""
        if vid in segs:
            src = "flag_segments"; n_seg += 1
            for s, e in segs[vid]:
                rows.append({"gfw_vessel_id": vid, "vessel": r.get("gfw_shipname"),
                             "source": src, "start": s, "end": e})
        elif w and w in auth:
            src = "auth_dates"; n_auth += 1
            s, e = auth[w]
            rows.append({"gfw_vessel_id": vid, "vessel": r.get("gfw_shipname"),
                         "source": src, "start": s, "end": e})
        else:
            n_none += 1
    pd.DataFrame(rows).to_csv(OUT / "registration_windows.csv", index=False,
                              encoding="utf-8-sig")
    print(f"windows: {n_seg} vessels from flag segments, {n_auth} from "
          f"authorization dates, {n_none} without (events kept)")

    ivals = {}
    for r in rows:
        ivals.setdefault(r["gfw_vessel_id"], []).append((r["start"], r["end"]))

    def in_window(vid, t):
        if vid not in ivals or pd.isna(t):
            return True
        for s, e in ivals[vid]:
            if t >= s and (pd.isna(e) or t <= e):
                return True
        return False

    # ---- fishing events ---------------------------------------------------
    ev = pd.read_csv(OUT / "events_fishing.csv", dtype=str,
                     encoding_errors="replace")
    ev["t"] = pd.to_datetime(ev["start"], errors="coerce", utc=True)
    ev["t_end"] = pd.to_datetime(ev["end"], errors="coerce", utc=True)
    ev["hours"] = (ev["t_end"] - ev["t"]).dt.total_seconds() / 3600
    keep = ev.apply(lambda r: in_window(r["vessel_id"], r["t"]), axis=1)
    cut, evw = ev[~keep], ev[keep].copy()
    print(f"fishing events: {len(evw)} kept, {len(cut)} outside register-flag "
          f"tenure ({cut['hours'].sum():.0f} h removed)")
    if len(cut):
        gone = (cut.groupby("eez")["hours"].sum()
                .sort_values(ascending=False).head(5))
        print("  removed hours by EEZ:",
              ", ".join(f"{EEZ_NAMES.get(k, k)}:{v:.0f}" for k, v in gone.items()))

    evw["month"] = evw["t"].dt.tz_localize(None).dt.to_period("M").astype(str)
    panel = (evw.groupby(["vessel_id", "vessel_name", "month", "eez"],
                         dropna=False)["hours"].sum().reset_index())
    panel.to_csv(OUT / "fishing_monthly_windowed.csv", index=False,
                 encoding="utf-8-sig")
    print(f"-> fishing_monthly_windowed.csv: {len(panel)} vessel-month-EEZ rows")
    top = evw.groupby("eez")["hours"].sum().sort_values(ascending=False).head(8)
    print("  top EEZ by fishing hours, windowed:")
    for k, v in top.items():
        print(f"    {v:10.0f} h  {EEZ_NAMES.get(k, 'eez=' + str(k))}")
    kir = evw[evw["eez"].isin(KIR_EEZ)]["hours"].sum()
    print(f"  Kiribati EEZ total (Gilbert+Phoenix+Line): {kir:.0f} h")

    # ---- shipment chain ---------------------------------------------------
    chp = OUT / "shipment_chain.csv"
    if chp.exists():
        ch = pd.read_csv(chp, dtype=str, encoding_errors="replace")
        ch["t"] = pd.to_datetime(ch["enc_end"], errors="coerce", utc=True)
        keep = ch.apply(lambda r: in_window(r["catcher_id"], r["t"]), axis=1)
        chw = ch[keep].copy()
        chw.to_csv(OUT / "shipment_chain_windowed.csv", index=False,
                   encoding="utf-8-sig")
        print(f"-> shipment_chain_windowed.csv: {len(chw)} of {len(ch)} "
              f"encounters inside register-flag tenure")
        if len(chw):
            nx = chw[chw["next_port_flag"].notna()]
            print("  next-port country, windowed:",
                  ", ".join(f"{k}:{n}" for k, n in
                            Counter(nx["next_port_flag"]).most_common(8)))
            tha = chw["tha_port_name"].notna().sum()
            print(f"  encounters -> Thailand: {tha} ({100 * tha / len(chw):.0f}%)")
            lags = pd.to_numeric(chw["days_to_tha_port"], errors="coerce").dropna()
            if len(lags):
                print(f"  encounter -> Thai port lag: median {lags.median():.0f} d, "
                      f"p25 {lags.quantile(.25):.0f}, p75 {lags.quantile(.75):.0f}")

    print("\ndone.")


if __name__ == "__main__":
    main()
