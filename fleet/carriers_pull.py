#!/usr/bin/env python3
"""
carriers_pull.py -- KiriTrade GPS layer, stage 3: the carrier leg to port.

Takes the encounter partners found by events_pull.py (out\\encounter_partners.csv),
pulls THEIR port visits from the GFW Events API, and links the chain:

    catcher --(encounter at sea)--> carrier --(next port visit)--> country

The key output is out\\shipment_chain.csv: one row per catcher-carrier
encounter, with the carrier's next port call after the encounter and the
first Thailand call within --tha-window days (default 120). The lag from
encounter to Thai port is the physical half of the catch-to-customs lag.

Resilience: the GFW gateway occasionally answers a page with a spurious
422 "dataset deprecated". Each carrier is pulled on its own; a 422 is
retried, then retried with a smaller page, and only that carrier is
skipped (and reported) if it persists.

By default only partners typed 'carrier' are pulled (--all-partners for
bunkers and the rest).

Outputs (in .\\out\\):
    events_port_visits_carriers.csv   carrier port calls
    events_raw_carrier_visits.jsonl   raw API pages (appended)
    shipment_chain.csv                encounter -> next port linkage

Usage (from the GPS folder, where KEY.txt lives):
    python carriers_pull.py
    python carriers_pull.py --all-partners --start 2018-01-01
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
DS_PORT = "public-global-port-visits-events:latest"
PAGE = 500


class Gfw422(Exception):
    pass


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
        if r.status_code == 422:
            if attempt < 2:
                time.sleep(5)
                continue
            raise Gfw422(r.text[:300])
        if r.status_code == 401:
            sys.exit("GFW returned 401 -- token rejected. Check KEY.txt.")
        if r.status_code >= 400:
            print(f"GFW {r.status_code} on {url}\n  response: {r.text[:400]}")
            r.raise_for_status()
        return r.json()
    r.raise_for_status()


def flat_visit(e):
    v = e.get("vessel") or {}
    pv = e.get("port_visit") or {}
    anch = (pv.get("intermediateAnchorage") or pv.get("startAnchorage")
            or pv.get("endAnchorage") or {})
    return {
        "event_id": e.get("id"), "start": e.get("start"), "end": e.get("end"),
        "carrier_id": v.get("id"), "carrier_name": v.get("name"),
        "carrier_flag": v.get("flag"),
        "port_name": anch.get("name"), "port_flag": anch.get("flag"),
        "port_confidence": pv.get("confidence"),
        "port_duration_hrs": pv.get("durationHrs"),
    }


def pull_vessel_visits(session, vid, start, end, raw):
    """All port visits for one vessel; shrinks the page on spurious 422s.
    Returns (rows, ok)."""
    rows, offset, page = [], 0, PAGE
    body = {"datasets": [DS_PORT], "vessels": [vid],
            "startDate": start, "endDate": end}
    while True:
        try:
            js = gfw_post(session, body, offset, page)
        except Gfw422:
            if page > 100:
                page = 100
                continue
            return rows, False
        entries = js.get("entries", [])
        for e in entries:
            raw.write(json.dumps(e) + "\n")
            rows.append(flat_visit(e))
        total = js.get("total", 0)
        nxt = js.get("nextOffset")
        if not entries or nxt is None or (total and nxt >= total):
            return rows, True
        offset = nxt
        time.sleep(0.3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--all-partners", action="store_true",
                    help="pull all encounter partners, not only type 'carrier'")
    ap.add_argument("--tha-window", type=int, default=120,
                    help="days after encounter to look for a Thailand call")
    args = ap.parse_args()
    out_dir = Path("out")

    partners = pd.read_csv(out_dir / "encounter_partners.csv", dtype=str,
                           encoding_errors="replace")
    partners = partners[partners["partner_id"].notna()
                        & (partners["partner_id"].str.lower() != "nan")]
    if not args.all_partners:
        partners = partners[partners["partner_type"].str.lower() == "carrier"]
    ids = sorted(set(partners["partner_id"]))
    print(f"partners to pull: {len(ids)} "
          f"({'all types' if args.all_partners else 'carriers only'})")
    if not ids:
        sys.exit("No partner ids -- run events_pull.py first.")

    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {gfw_token()}",
                      "Content-Type": "application/json", **UA})

    rows, skipped = [], []
    raw = (out_dir / "events_raw_carrier_visits.jsonl").open("a", encoding="utf-8")
    for i, vid in enumerate(ids, 1):
        vrows, ok = pull_vessel_visits(s, vid, args.start, args.end, raw)
        rows += vrows
        tag = "" if ok else "  [partial: 422, skipped remainder]"
        print(f"  {i:3d}/{len(ids)}  {vid[:14]}...  {len(vrows)} visits{tag}",
              flush=True)
        if not ok:
            skipped.append(vid)
        time.sleep(0.2)
    raw.close()
    if skipped:
        print(f"carriers with incomplete pulls (spurious 422): {len(skipped)}")

    visits = pd.DataFrame(rows)
    if len(visits):
        visits = visits.drop_duplicates(subset="event_id")
    visits.to_csv(out_dir / "events_port_visits_carriers.csv", index=False,
                  encoding="utf-8-sig")
    print(f"-> events_port_visits_carriers.csv: {len(visits)} port calls")
    if len(visits):
        cnt = Counter(visits["port_flag"].fillna("?"))
        print("  carrier port calls by country:",
              ", ".join(f"{k}:{n}" for k, n in cnt.most_common(12)))

    # ---- link: encounter -> carrier's next port ---------------------------
    enc = pd.read_csv(out_dir / "events_encounters.csv", dtype=str,
                      encoding_errors="replace")
    enc = enc[enc["partner_id"].isin(set(ids))].copy()
    enc["enc_end"] = pd.to_datetime(enc["end"], errors="coerce", utc=True)
    visits["arr"] = pd.to_datetime(visits["start"], errors="coerce", utc=True)
    visits_sorted = visits.sort_values("arr")

    chain = []
    for _, r in enc.iterrows():
        after = visits_sorted[(visits_sorted["carrier_id"] == r["partner_id"])
                              & (visits_sorted["arr"] > r["enc_end"])]
        nxt = after.iloc[0] if len(after) else None
        win = after[after["arr"] <= r["enc_end"] + pd.Timedelta(days=args.tha_window)]
        tha = win[win["port_flag"] == "THA"]
        tha0 = tha.iloc[0] if len(tha) else None
        chain.append({
            "catcher_id": r["vessel_id"], "catcher_name": r["vessel_name"],
            "enc_start": r["start"], "enc_end": r["end"],
            "carrier_id": r["partner_id"], "carrier_name": r["partner_name"],
            "carrier_flag": r["partner_flag"],
            "next_port_name": None if nxt is None else nxt["port_name"],
            "next_port_flag": None if nxt is None else nxt["port_flag"],
            "days_to_next_port": None if nxt is None else
                round((nxt["arr"] - r["enc_end"]).total_seconds() / 86400, 1),
            "tha_port_name": None if tha0 is None else tha0["port_name"],
            "days_to_tha_port": None if tha0 is None else
                round((tha0["arr"] - r["enc_end"]).total_seconds() / 86400, 1),
        })
    ch = pd.DataFrame(chain)
    ch.to_csv(out_dir / "shipment_chain.csv", index=False, encoding="utf-8-sig")
    print(f"-> shipment_chain.csv: {len(ch)} encounters linked")
    if len(ch):
        linked = ch[ch["next_port_flag"].notna()]
        print("  next-port country after encounter:",
              ", ".join(f"{k}:{n}" for k, n in
                        Counter(linked["next_port_flag"]).most_common(10)))
        tha_n = ch["tha_port_name"].notna().sum()
        print(f"  encounters with a Thailand call within {args.tha_window} days: "
              f"{tha_n} ({100 * tha_n / len(ch):.0f}%)")
        lags = pd.to_numeric(ch["days_to_tha_port"], errors="coerce").dropna()
        if len(lags):
            print(f"  encounter -> Thai port lag: median {lags.median():.0f} days, "
                  f"p25 {lags.quantile(.25):.0f}, p75 {lags.quantile(.75):.0f}")

    print("\ndone.")


if __name__ == "__main__":
    main()
