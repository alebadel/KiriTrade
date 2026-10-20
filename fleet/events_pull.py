#!/usr/bin/env python3
"""
events_pull.py -- KiriTrade GPS layer, stage 2: events for the register fleet.

Reads out\\vessel_master.csv, takes the register vessels that have a GFW
identity (match_method != GFW_ONLY, gfw_vessel_id present), and pulls from
the GFW Events API, 2015-01-01 to today:

    fishing      fishing events with positions and EEZ/RFMO region tags
    port_visits  port visits with anchorage name + flag (THA = Thailand leg)
    encounters   at-sea encounters (catcher <-> carrier transshipment signal)
    loitering    loitering events (only with --types ...,loitering)

API shape (per GFW v3 docs): POST /v3/events?offset=N&limit=M with the
filters (datasets, vessels, startDate, endDate) in the JSON body --
offset/limit are QUERY parameters, not body fields.

Outputs (in .\\out\\):
    events_fishing.csv, events_port_visits.csv, events_encounters.csv [...]
    events_raw_<type>.jsonl      raw API pages, appended (schema may drift)
    fishing_monthly.csv          vessel x month x EEZ fishing-hours panel
    encounter_partners.csv       unique partner vessels (input for carrier pull)

EEZ/RFMO tags come as Marine Regions ids; they are written raw, and the run
prints the top EEZ ids by fishing hours so the Kiribati ids are easy to pin.

Usage (from the GPS folder, where KEY.txt lives):
    python events_pull.py                        # fishing + port_visits + encounters
    python events_pull.py --types port_visits    # one type only
    python events_pull.py --start 2020-01-01
Never prints the API token.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

GFW_BASE = "https://gateway.api.globalfishingwatch.org/v3"
UA = {"User-Agent": "KiriTrade-research/0.1 (IMF Kiribati desk; contact via GFW account)"}

DATASETS = {
    "fishing": "public-global-fishing-events:latest",
    "port_visits": "public-global-port-visits-events:latest",
    "encounters": "public-global-encounters-events:latest",
    "loitering": "public-global-loitering-events:latest",
}
PAGE = 500          # events per page (offset/limit are query params)


def gfw_token():
    txt = Path("KEY.txt").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'API_TOKEN\s*=\s*"([^"]+)"', txt)
    if not m:
        sys.exit("KEY.txt found but no API_TOKEN=\"...\" line in it.")
    return m.group(1).strip()


def gfw_post(session, body, offset, limit):
    url = f"{GFW_BASE}/events?offset={offset}&limit={limit}"
    for attempt in range(4):
        r = session.post(url, json=body, timeout=180)
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 401:
            sys.exit("GFW returned 401 -- token rejected. Check KEY.txt.")
        if r.status_code >= 400:
            print(f"GFW {r.status_code} on {url}\n  body: "
                  f"{json.dumps({k: (v if k != 'vessels' else f'[{len(v)} ids]') for k, v in body.items()})}"
                  f"\n  response: {r.text[:400]}")
            r.raise_for_status()
        return r.json()
    r.raise_for_status()


def flat_event(e):
    pos = e.get("position") or {}
    reg = e.get("regions") or {}
    v = e.get("vessel") or {}
    row = {
        "event_id": e.get("id"), "type": e.get("type"),
        "start": e.get("start"), "end": e.get("end"),
        "lat": pos.get("lat"), "lon": pos.get("lon"),
        "eez": ";".join(map(str, reg.get("eez") or [])),
        "rfmo": ";".join(map(str, reg.get("rfmo") or [])),
        "vessel_id": v.get("id"), "vessel_name": v.get("name"),
        "vessel_flag": v.get("flag"), "mmsi": v.get("ssvid"),
    }
    f = e.get("fishing") or {}
    if f:
        row["avg_speed_kn"] = f.get("averageSpeedKnots")
        row["distance_km"] = f.get("totalDistanceKm")
    enc = e.get("encounter") or {}
    if enc:
        ev = enc.get("vessel") or {}
        row["partner_id"] = ev.get("id")
        row["partner_name"] = ev.get("name")
        row["partner_flag"] = ev.get("flag")
        row["partner_type"] = enc.get("vesselType") or ev.get("type")
        row["median_distance_km"] = enc.get("medianDistanceKilometers")
    pv = e.get("port_visit") or {}
    if pv:
        anch = (pv.get("intermediateAnchorage") or pv.get("startAnchorage")
                or pv.get("endAnchorage") or {})
        row["port_name"] = anch.get("name")
        row["port_flag"] = anch.get("flag")
        row["port_confidence"] = pv.get("confidence")
        row["port_duration_hrs"] = pv.get("durationHrs")
    return row


def pull_type(session, etype, vessel_ids, start, end, out_dir, chunk):
    ds = DATASETS[etype]
    rows = []
    raw_path = out_dir / f"events_raw_{etype}.jsonl"
    raw = raw_path.open("a", encoding="utf-8")
    for c0 in range(0, len(vessel_ids), chunk):
        ids = vessel_ids[c0:c0 + chunk]
        body = {"datasets": [ds], "vessels": ids,
                "startDate": start, "endDate": end}
        offset = 0
        while True:
            js = gfw_post(session, body, offset, PAGE)
            entries = js.get("entries", [])
            for e in entries:
                raw.write(json.dumps(e) + "\n")
                rows.append(flat_event(e))
            total = js.get("total", 0)
            print(f"  {etype}: vessels {c0 + 1}-{c0 + len(ids)}, "
                  f"{min(offset + len(entries), total)}/{total}", flush=True)
            nxt = js.get("nextOffset")
            if not entries or nxt is None or (total and nxt >= total):
                break
            offset = nxt
            time.sleep(0.4)
        time.sleep(0.4)
    raw.close()
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="fishing,port_visits,encounters",
                    help="comma list from fishing,port_visits,encounters,loitering")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--master", default="out/vessel_master.csv")
    ap.add_argument("--chunk", type=int, default=15,
                    help="vessels per API request")
    args = ap.parse_args()
    types = [t.strip() for t in args.types.split(",") if t.strip()]
    out_dir = Path("out"); out_dir.mkdir(exist_ok=True)

    master = pd.read_csv(args.master, dtype=str, encoding_errors="replace")
    fleet = master[(master["match_method"] != "GFW_ONLY")
                   & master["gfw_vessel_id"].notna()
                   & (master["gfw_vessel_id"] != "")]
    vessel_ids = sorted(set(fleet["gfw_vessel_id"]))
    print(f"register fleet with GFW identity: {len(vessel_ids)} vessels")
    if not vessel_ids:
        sys.exit("No vessel ids found in the master -- run vessel_master.py first.")

    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {gfw_token()}",
                      "Content-Type": "application/json", **UA})

    for etype in types:
        if etype not in DATASETS:
            print(f"unknown type '{etype}' -- skipped"); continue
        print(f"{etype}: dataset {DATASETS[etype]}")
        df = pull_type(s, etype, vessel_ids, args.start, args.end,
                       out_dir, args.chunk)
        path = out_dir / f"events_{etype}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print(f"  -> {path.name}: {len(df)} events")

        if etype == "fishing" and len(df):
            d = df.copy()
            d["start_dt"] = pd.to_datetime(d["start"], errors="coerce", utc=True)
            d["end_dt"] = pd.to_datetime(d["end"], errors="coerce", utc=True)
            d["hours"] = (d["end_dt"] - d["start_dt"]).dt.total_seconds() / 3600
            d["month"] = d["start_dt"].dt.to_period("M").astype(str)
            panel = (d.groupby(["vessel_id", "vessel_name", "month", "eez"],
                               dropna=False)["hours"].sum().reset_index())
            panel.to_csv(out_dir / "fishing_monthly.csv", index=False,
                         encoding="utf-8-sig")
            print(f"  -> fishing_monthly.csv: {len(panel)} vessel-month-EEZ rows")
            top = (d.groupby("eez")["hours"].sum()
                   .sort_values(ascending=False).head(8))
            print("  top EEZ ids by fishing hours (map these to countries):")
            for k, v in top.items():
                print(f"    {v:10.0f} h  eez={k or '(high seas)'}")

        if etype == "port_visits" and len(df) and "port_flag" in df:
            cnt = Counter(df["port_flag"].fillna("?"))
            print("  port visits by country:",
                  ", ".join(f"{k}:{n}" for k, n in cnt.most_common(10)))
            tha = df[df["port_flag"] == "THA"]
            print(f"  Thailand port visits: {len(tha)}")

        if etype == "encounters" and len(df) and "partner_id" in df:
            partners = (df.groupby(["partner_id", "partner_name", "partner_flag",
                                    "partner_type"], dropna=False)
                        .size().reset_index(name="n_encounters")
                        .sort_values("n_encounters", ascending=False))
            partners.to_csv(out_dir / "encounter_partners.csv", index=False,
                            encoding="utf-8-sig")
            print(f"  -> encounter_partners.csv: {len(partners)} unique partners; top:")
            for _, p in partners.head(6).iterrows():
                print(f"    {int(p.n_encounters):4d}x  {p.partner_name} "
                      f"({p.partner_flag}, {p.partner_type})")

    print("\ndone.")


if __name__ == "__main__":
    main()
