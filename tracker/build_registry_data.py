#!/usr/bin/env python3
"""Build data/registry.json: aggregates from the WCPFC Record of Fishing Vessels (RFV) export.

Input: GPS/out/vessel_master.csv (the RFV export for the Kiribati, Nauru and Tuvalu flags, joined to
AIS identities by fleet/vessel_master.py). That file holds vessel, owner and master names and is never
published. This script writes counts only: by flag, vessel type, register status, owner-address hint,
build decade, previous flag and AIS match. No names, registration numbers or identifiers.

Usage:  python tracker/build_registry_data.py --master GPS/out/vessel_master.csv --out data/registry.json --export-date 2026-10-18
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

FLAGS = {"KI": "Kiribati", "NR": "Nauru", "TV": "Tuvalu"}
# Vessel-type codes as used in the WCPFC register (FAO ISSCFV classification).
VESSEL_TYPES = {
    "SP": "Purse seiner", "SPT": "Tuna purse seiner", "LL": "Longliner", "LLT": "Tuna longliner",
    "LP": "Pole-and-line vessel", "FO": "Fish carrier", "VOB": "Bunker (fuel supply) vessel", "FX": "Other fishing vessel",
}
TYPE_GROUPS = {
    "SP": "Purse seiners", "SPT": "Purse seiners", "LL": "Longliners", "LLT": "Longliners",
    "LP": "Other fishing vessels", "FX": "Other fishing vessels", "FO": "Carriers", "VOB": "Bunkers",
}
HINTS = {
    "K1?": "Owner or operator address in Kiribati, Nauru or Tuvalu",
    "K2?": "Owner or operator address abroad",
    "K1/": "Addresses both at home and abroad",
    "": "No usable address on the register",
}
PREV_FLAG_GROUPS = {
    "NONE": "No previous flag", "": "Not stated", "PANAMA": "Panama", "KOREA": "Korea", "REPUBLIC OF KOREA": "Korea",
    "PAPUA NEW GUINEA": "Papua New Guinea", "BELIZE": "Belize", "UNITED STATES OF AMERICA": "United States",
    "USA": "United States", "JAPAN": "Japan",
}


def decade(y: str) -> str:
    y = (y or "")[:4]
    if not y.isdigit():
        return "Not stated"
    d = int(y) // 10 * 10
    return f"{d}s"


def build(master: Path, export_date: str) -> dict:
    rows = [r for r in csv.DictReader(open(master, encoding="utf-8-sig")) if r.get("VID", "").strip()]
    n = len(rows)

    def flag(r):
        return FLAGS.get(r["Flag of fishing vessel"].strip(), "Other")

    def active(r):
        return not r.get("Reason for deletion", "").strip()

    def count(keyfn):
        c = Counter(keyfn(r) for r in rows)
        return dict(sorted(c.items(), key=lambda kv: -kv[1]))

    by_flag_status = {}
    for r in rows:
        f = flag(r)
        by_flag_status.setdefault(f, {"active": 0, "deleted": 0})
        by_flag_status[f]["active" if active(r) else "deleted"] += 1

    by_flag_type = {}
    for r in rows:
        f = flag(r)
        g = TYPE_GROUPS.get(r["Type of vessel"].strip(), "Other fishing vessels")
        by_flag_type.setdefault(f, {})
        by_flag_type[f][g] = by_flag_type[f].get(g, 0) + 1

    by_flag_hint = {}
    for r in rows:
        f = flag(r)
        h = HINTS.get(r.get("class_hint", "")[:3], HINTS[""])
        by_flag_hint.setdefault(f, {})
        by_flag_hint[f][h] = by_flag_hint[f].get(h, 0) + 1

    deletion_reasons = count(lambda r: r["Reason for deletion"].strip() or "On the register (not deleted)")
    prev_flags = count(lambda r: PREV_FLAG_GROUPS.get(r["Previous flag (if any)"].strip().upper(), "Other country"))
    built = dict(sorted(count(lambda r: decade(r["When the vessel was built"])).items()))
    ais = count(lambda r: "Matched to an AIS identity" if r.get("match_method", "").strip() not in ("", "UNMATCHED") else "No AIS identity found")
    tranship = count(lambda r: {"Yes": "Yes", "No": "No"}.get(r["Authorized to tranship on the high seas"].strip(), "Not stated"))
    charter = sum(1 for r in rows if r.get("Name of charterer", "").strip())
    type_counts = {VESSEL_TYPES.get(k, k): v for k, v in count(lambda r: r["Type of vessel"].strip()).items()}

    return {
        "meta": {
            "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "builder": "tracker/build_registry_data.py",
            "source": "WCPFC Record of Fishing Vessels (public register, vessels.wcpfc.int), export of " + export_date + ", flags Kiribati, Nauru and Tuvalu; AIS identity match by fleet/vessel_master.py",
            "register_export_date": export_date,
            "n_vessels": n,
            "what": "Counts of vessels on the register by flag, type, status, owner-address hint, build decade, previous flag and AIS match. No vessel, owner or master names.",
            "notes": [
                "The export lists every vessel the three flag states have submitted, including vessels since deleted; 'deleted' rows carry the reason the flag state gave.",
                "Vessel types follow the register's own codes (FAO classification): purse seiners (SP, SPT), longliners (LL, LLT), pole-and-line (LP), fish carriers (FO), bunker vessels (VOB), other (FX).",
                "The owner-address hint is a text pattern on the owner, operator and charterer fields. It is a hint about where the operator is based, not a finding about residence. Residence is the condition that decides whether a vessel's catch is a Kiribati export under balance-of-payments rules.",
                "AIS match: whether the register row could be tied to a ship-tracking identity by call sign or IMO number; unmatched vessels still fish, they are simply not seen in the fleet page.",
            ],
            "vessel_type_codes": VESSEL_TYPES,
        },
        "by_flag_status": by_flag_status,
        "by_flag_type_group": by_flag_type,
        "by_flag_address_hint": by_flag_hint,
        "by_vessel_type": type_counts,
        "deletion_reasons": deletion_reasons,
        "previous_flag": prev_flags,
        "built_decade": built,
        "ais_match": ais,
        "authorized_to_tranship_high_seas": tranship,
        "n_with_charterer_recorded": charter,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--export-date", required=True)
    a = ap.parse_args(argv)
    res = build(Path(a.master), a.export_date)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"registry.json: {res['meta']['n_vessels']} vessels -> {a.out}")
    print(json.dumps(res["by_flag_status"]), json.dumps(res["by_flag_type_group"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
