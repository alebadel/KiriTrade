#!/usr/bin/env python3
"""
vessel_master.py -- KiriTrade GPS layer, stage 1: the vessel master table.

Pulls:
  1. WCPFC Record of Fishing Vessels (public CSV export) for Kiribati, Nauru,
     Tuvalu -- current records AND the history view (deleted records included),
     which is where reflagging shows up.
  2. Global Fishing Watch (GFW) vessel identity for the same flags, with
     ownership and WCPFC authorization records.

Merges them on IRCS, then IMO, then normalized name, and writes
vessel_master.csv with a `class_hint` column suggesting the K1-K4 ownership
class from owner/operator address strings. The hint is a suggestion only --
the ownership_class column is left blank for manual determination
(residence is stated as a condition, never as fact).

KIR and TUV run open ship registries, so a flag search on GFW returns
thousands of merchant vessels; GFW also assigns a type to every AIS identity
(including TANKER, CARGO, and GEAR = net buoys). The merge with the register
happens FIRST, so register vessels always keep their GFW link; after the
merge, GFW-only rows are kept only when tuna-chain relevant -- ship type
FISHING/CARRIER/SUPPORT, a real fishing gear (seines, longlines,
pole-and-line, ...), or a WCPFC authorization -- and a breakdown of dropped
rows is printed. Use --all-types to keep everything.

GFW responses are cached in out\\gfw_raw_<FLAG>.json and reruns reuse the
cache instead of re-crawling the API. Use --refresh-gfw to force a new pull.

Usage (from the GPS folder, where KEY.txt lives):
    python vessel_master.py                  # KIR + NRU + TUV
    python vessel_master.py --flags KIR      # one flag only
    python vessel_master.py --skip-gfw       # RFV only (no API calls)
    python vessel_master.py --skip-rfv-pull  # reuse out\\rfv_current.csv on disk

Outputs (in .\\out\\):
    rfv_current.csv, rfv_with_deleted.csv   raw RFV exports
    gfw_raw_<FLAG>.json                     raw GFW responses (keep: schema may drift)
    vessel_master.csv                       the merged table
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

# ---------------------------------------------------------------- constants
RFV_EXPORT = "https://vessels.wcpfc.int/browse-rfv/export"
GFW_BASE = "https://gateway.api.globalfishingwatch.org/v3"
GFW_DATASET = "public-global-vessel-identity:latest"
UA = {"User-Agent": "KiriTrade-research/0.1 (IMF Kiribati desk; contact via GFW account)"}

# WCPFC RFV flag_in_use[] option values (read off the browse form, Oct 2026)
RFV_FLAG_IDS = {"KIR": 113, "NRU": 162, "TUV": 217, "MHL": 136, "CHN": 46}

# GFW ship types kept among GFW-only rows (tuna supply chain)
KEEP_SHIPTYPES = {"FISHING", "CARRIER", "SUPPORT"}
# gear values that mark a fishing vessel even when the ship type is OTHER/NA
FISH_GEAR_PAT = re.compile(
    r"SEIN|LONGLIN|POLE_AND_LINE|TROLL|GILLNET|TRAWL|SQUID|JIGGER|HARPOON|"
    r"DREDGE|FISHING", re.I)

# address keywords -> ownership class hint (suggestions only)
RESIDENT_PAT = re.compile(r"TARAWA|KIRIBATI|BETIO", re.I)
FOREIGN_PAT = re.compile(
    r"CHINA|ZHEJIANG|SHANDONG|DALIAN|TAIWAN|KAOHSIUNG|KOREA|BUSAN|JAPAN|"
    r"SPAIN|USA|UNITED STATES|PHILIPPINES|MANILA", re.I)


def norm_name(s):
    """Uppercase, strip everything but A-Z0-9 -- for name matching."""
    return re.sub(r"[^A-Z0-9]", "", str(s).upper()) if pd.notna(s) else ""


def find_col(df, *keywords, exclude=()):
    """First column whose lowercase name contains all keywords (and no exclude)."""
    for c in df.columns:
        lc = c.lower()
        if all(k in lc for k in keywords) and not any(x in lc for x in exclude):
            return c
    return None


# ------------------------------------------------- friends' crosswalk (optional)
def load_friends(friends_dir):
    """MMSI/IMO/callsign -> physical_id maps from the kiribati_vessel_data
    transfer. Optional; returns None silently when the folder is absent."""
    d = Path(friends_dir)
    if not (d / "tracking_metadata.csv").exists():
        return None
    meta = pd.read_csv(d / "tracking_metadata.csv", dtype=str, encoding_errors="replace")
    ali = pd.read_csv(d / "tracking_aliases.csv", dtype=str, encoding_errors="replace")
    look = pd.read_csv(d / "vessel_lookup.csv", dtype=str, encoding_errors="replace")
    phys_a = find_col(ali, "physical")
    common = [c for c in meta.columns if c in ali.columns and c != phys_a]
    if not phys_a or not common:
        print("friends data found but join columns unclear -- skipping that join")
        return None
    m = meta.merge(ali[[common[0], phys_a]].drop_duplicates(), on=common[0], how="left")
    phys_l = find_col(look, "physical")
    keep = [c for c in (find_col(look, "public"), find_col(look, "company"),
                        find_col(look, "jv")) if c]
    if phys_l and keep:
        m = m.merge(look[[phys_l] + keep].rename(columns={phys_l: phys_a}),
                    on=phys_a, how="left")
    maps = {"mmsi": {}, "imo": {}, "call": {}}
    c_mmsi, c_imo, c_call = (find_col(m, "mmsi"), find_col(m, "imo"),
                             find_col(m, "call"))
    for _, r in m.iterrows():
        for kind, col, nrm in (("mmsi", c_mmsi, str.strip), ("imo", c_imo, str.strip),
                               ("call", c_call, norm_name)):
            if col and pd.notna(r[col]):
                v = nrm(str(r[col]))
                if v and v.lower() not in ("nan", "none"):
                    maps[kind].setdefault(v, r)
    print(f"friends crosswalk loaded: {len(m)} tracking identities, "
          f"keys mmsi={len(maps['mmsi'])}, imo={len(maps['imo'])}, call={len(maps['call'])}")
    return maps, phys_a, keep


def attach_friends(row, friends):
    """Best-effort link of one master row to the friends' physical_id."""
    row["friends_match"] = ""
    if not friends:
        return
    maps, phys_col, keep = friends
    cands = (("mmsi", str(row.get("gfw_mmsi") or "").strip()),
             ("imo", str(row.get("gfw_imo") or row.get("_imo") or "").strip()),
             ("call", norm_name(row.get("gfw_callsign") or row.get("_callsign") or "")))
    for kind, v in cands:
        if v and v.lower() not in ("nan", "none") and v in maps[kind]:
            r = maps[kind][v]
            row["friends_physical_id"] = r.get(phys_col)
            for c in keep:
                row[f"friends_{c}"] = r.get(c)
            row["friends_match"] = kind
            return


# ---------------------------------------------------------------- RFV pull
def pull_rfv(flags, out_dir):
    frames = {}
    for deleted, fname in ((0, "rfv_current.csv"), (1, "rfv_with_deleted.csv")):
        params = [("flag_in_use[]", RFV_FLAG_IDS[f]) for f in flags]
        if deleted:
            params.append(("vessel_version_status_deleted", 1))
        print(f"RFV export (deleted={deleted}) ...", flush=True)
        r = requests.get(RFV_EXPORT, params=params, headers=UA, timeout=180)
        r.raise_for_status()
        if b"<html" in r.content[:400].lower():
            raise RuntimeError(
                "RFV export returned HTML, not CSV. Download manually from "
                "https://vessels.wcpfc.int/browse-rfv (CSV button, flags "
                f"{flags}) and save as out\\{fname}, then rerun with --skip-rfv-pull")
        path = out_dir / fname
        path.write_bytes(r.content)
        df = pd.read_csv(path, dtype=str, encoding_errors="replace")
        print(f"  {fname}: {len(df)} rows, {len(df.columns)} cols")
        frames[fname] = df
        time.sleep(2)
    return frames["rfv_current.csv"], frames["rfv_with_deleted.csv"]


def looks_like_rfv(df, fname):
    """Sanity check: the file on disk must actually be a WCPFC RFV export."""
    cols = " ".join(c.lower() for c in df.columns)
    if not any(k in cols for k in ("ircs", "vessel", "win", "flag")):
        sys.exit(
            f"out\\{fname} does not look like a WCPFC RFV export "
            f"(columns: {list(df.columns)[:5]} ...). A wrong file was probably "
            "moved into out\\. Re-download from https://vessels.wcpfc.int/browse-rfv "
            "and replace it, then rerun with --skip-rfv-pull.")


# ---------------------------------------------------------------- GFW pull
def gfw_token():
    txt = Path("KEY.txt").read_text(encoding="utf-8", errors="replace")
    m = re.search(r'API_TOKEN\s*=\s*"([^"]+)"', txt)
    if not m:
        sys.exit("KEY.txt found but no API_TOKEN=\"...\" line in it.")
    return m.group(1).strip()


def gfw_get(session, path, params):
    for attempt in range(3):
        r = session.get(GFW_BASE + path, params=params, timeout=120)
        if r.status_code == 429:           # rate limited: back off and retry
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 401:
            sys.exit("GFW returned 401 -- token rejected. Check KEY.txt.")
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def pull_gfw_flag(session, flag, out_dir):
    """All identity records for one flag, paginated; returns list of entries."""
    entries, since = [], None
    base_params = {
        "datasets[0]": GFW_DATASET,
        "includes[0]": "OWNERSHIP",
        "includes[1]": "AUTHORIZATIONS",
        "includes[2]": "MATCH_CRITERIA",
        "where": f'flag = "{flag}"',
        "limit": 50,
    }
    while True:
        params = dict(base_params)
        if since:
            params["since"] = since
        js = gfw_get(session, "/vessels/search", params)
        batch = js.get("entries", [])
        entries.extend(batch)
        total = js.get("total", len(entries))
        print(f"  GFW {flag}: {len(entries)}/{total}", flush=True)
        since = js.get("since")
        if not batch or not since or len(entries) >= total:
            break
        time.sleep(1)
    (out_dir / f"gfw_raw_{flag}.json").write_text(
        json.dumps(entries, indent=1), encoding="utf-8")
    return entries


def first(lst):
    return lst[0] if isinstance(lst, list) and lst else {}


def gfw_entry_to_row(e):
    """Tolerant flattening of one GFW identity entry."""
    reg = first(e.get("registryInfo"))
    srep = first(e.get("selfReportedInfo"))
    comb = first(e.get("combinedSourcesInfo"))
    owners = e.get("registryOwners") or []
    auths = e.get("registryPublicAuthorizations") or []
    gear = set()
    v = reg.get("geartypes")
    if isinstance(v, str):
        gear.add(v)
    elif isinstance(v, list):
        gear.update(str(x) for x in v)
    for g in (comb.get("geartypes") or []):
        gear.add(str(g.get("name")) if isinstance(g, dict) else str(g))
    gear = sorted(g for g in gear if g and g.lower() not in ("none", "nan"))
    stypes = set()
    for src in (reg, srep):
        v = src.get("shiptypes") or src.get("shiptype")
        if isinstance(v, str):
            stypes.add(v)
        elif isinstance(v, list):
            for x in v:
                stypes.add(x.get("name") if isinstance(x, dict) else str(x))
    for x in (comb.get("shiptypes") or []):
        stypes.add(x.get("name") if isinstance(x, dict) else str(x))
    stypes = sorted(str(s).upper() for s in stypes
                    if s and str(s).lower() not in ("none", "nan"))
    wcpfc_auth = any("WCPFC" in str(a.get("sourceCode", "")).upper() for a in auths)
    own = first(owners)
    return {
        "gfw_vessel_id": srep.get("id") or comb.get("vesselId"),
        "gfw_shipname": reg.get("shipname") or srep.get("shipname"),
        "gfw_flag": reg.get("flag") or srep.get("flag"),
        "gfw_mmsi": reg.get("ssvid") or srep.get("ssvid"),
        "gfw_imo": reg.get("imo") or srep.get("imo"),
        "gfw_callsign": reg.get("callsign") or srep.get("callsign"),
        "gfw_geartypes": ";".join(gear) if gear else None,
        "gfw_shiptypes": ";".join(stypes) if stypes else None,
        "gfw_owner": own.get("name"),
        "gfw_owner_flag": own.get("flag"),
        "gfw_n_owners": len(owners),
        "gfw_wcpfc_authorized": wcpfc_auth,
        "gfw_first_seen": (reg.get("transmissionDateFrom")
                           or srep.get("transmissionDateFrom")),
        "gfw_last_seen": (reg.get("transmissionDateTo")
                          or srep.get("transmissionDateTo")),
        "_norm_name": norm_name(reg.get("shipname") or srep.get("shipname")),
        "_callsign": norm_name(reg.get("callsign") or srep.get("callsign")),
        "_imo": str(reg.get("imo") or srep.get("imo") or "").strip(),
    }


def fleet_relevant(row):
    """True for tuna-chain identities: ship type FISHING/CARRIER/SUPPORT, a
    real fishing gear, or a WCPFC authorization. False for tankers, cargo
    ships, bunkers, passenger vessels and AIS net buoys ('GEAR')."""
    if row.get("gfw_wcpfc_authorized"):
        return True
    types = set(str(row.get("gfw_shiptypes") or "").split(";"))
    if types & KEEP_SHIPTYPES:
        return True
    return bool(FISH_GEAR_PAT.search(str(row.get("gfw_geartypes") or "")))


# ---------------------------------------------------------------- merge
def classify_hint(row):
    blob = " ".join(str(row.get(c, "")) for c in row.index
                    if any(k in c.lower() for k in ("owner", "operator", "address", "charter")))
    res, forn = bool(RESIDENT_PAT.search(blob)), bool(FOREIGN_PAT.search(blob))
    if res and not forn:
        return "K1? resident-address owner/operator"
    if forn and res:
        return "K1/K2? mixed addresses (JV pattern)"
    if forn:
        return "K2? foreign-address owner/operator"
    return ""


def build_master(rfv, gfw_rows, friends=None):
    gfw = pd.DataFrame(gfw_rows)
    c_name = find_col(rfv, "vessel", "name") or find_col(rfv, "name")
    c_ircs = find_col(rfv, "ircs") or find_col(rfv, "call")
    c_imo = find_col(rfv, "imo")
    rfv = rfv.copy()
    rfv["_norm_name"] = rfv[c_name].map(norm_name) if c_name else ""
    rfv["_callsign"] = rfv[c_ircs].map(norm_name) if c_ircs else ""
    rfv["_imo"] = rfv[c_imo].astype(str).str.strip() if c_imo else ""

    merged, used = [], set()
    gfw_by = {k: {} for k in ("_callsign", "_imo", "_norm_name")}
    for i, g in gfw.iterrows():
        for k in gfw_by:
            v = g.get(k)
            if v and v not in ("", "NAN", "NONE", "nan"):
                gfw_by[k].setdefault(v, i)

    for _, r in rfv.iterrows():
        hit, how = None, ""
        for k, label in (("_callsign", "IRCS"), ("_imo", "IMO"), ("_norm_name", "name")):
            v = r.get(k)
            if v and v in gfw_by[k]:
                hit, how = gfw_by[k][v], label
                break
        row = r.to_dict()
        row["match_method"] = how or "UNMATCHED"
        if hit is not None:
            row.update(gfw.loc[hit].to_dict())
            used.add(hit)
        attach_friends(row, friends)
        row["class_hint"] = classify_hint(pd.Series(row))
        row["ownership_class"] = ""          # K1-K4: filled by hand
        merged.append(row)

    for i, g in gfw.iterrows():              # GFW-only (AIS seen, not on RFV)
        if i not in used:
            row = g.to_dict()
            row["match_method"] = "GFW_ONLY"
            attach_friends(row, friends)
            row["class_hint"] = ""
            row["ownership_class"] = ""
            merged.append(row)

    out = pd.DataFrame(merged).drop(columns=["_norm_name", "_callsign", "_imo"],
                                    errors="ignore")
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flags", default="KIR,NRU,TUV",
                    help="comma list from KIR,NRU,TUV,MHL,CHN")
    ap.add_argument("--skip-gfw", action="store_true")
    ap.add_argument("--skip-rfv-pull", action="store_true",
                    help="reuse out\\rfv_current.csv already on disk")
    ap.add_argument("--refresh-gfw", action="store_true",
                    help="re-pull GFW even when out\\gfw_raw_<FLAG>.json exists")
    ap.add_argument("--all-types", action="store_true",
                    help="keep open-registry merchant ships in the master too")
    ap.add_argument("--friends-dir", default="kiribati_vessel_data_2026_10_13",
                    help="optional folder with tracking_metadata/aliases + vessel_lookup")
    args = ap.parse_args()
    flags = [f.strip().upper() for f in args.flags.split(",") if f.strip()]
    out_dir = Path("out"); out_dir.mkdir(exist_ok=True)

    if args.skip_rfv_pull:
        rfv = pd.read_csv(out_dir / "rfv_current.csv", dtype=str,
                          encoding_errors="replace")
    else:
        rfv, rfv_hist = pull_rfv(flags, out_dir)
    looks_like_rfv(rfv, "rfv_current.csv")

    gfw_rows = []
    if not args.skip_gfw:
        s = None
        for f in flags:
            cache = out_dir / f"gfw_raw_{f}.json"
            if cache.exists() and not args.refresh_gfw:
                entries = json.loads(cache.read_text(encoding="utf-8"))
                print(f"  GFW {f}: {len(entries)} identities from cache ({cache.name})")
            else:
                if s is None:
                    s = requests.Session()
                    s.headers.update({"Authorization": f"Bearer {gfw_token()}", **UA})
                entries = pull_gfw_flag(s, f, out_dir)
            gfw_rows += [gfw_entry_to_row(e) for e in entries]

    friends = load_friends(args.friends_dir)

    # merge FIRST (register vessels always keep their GFW link) ...
    master = build_master(rfv, gfw_rows, friends)

    # ... THEN drop non-tuna-chain GFW-only rows (open-registry noise)
    if len(master) and not args.all_types and "match_method" in master:
        gfw_only = master["match_method"] == "GFW_ONLY"
        keep = ~gfw_only | master.apply(fleet_relevant, axis=1)
        dropped = master[~keep]
        if len(dropped):
            print(f"GFW type filter (GFW-only rows): kept "
                  f"{int((gfw_only & keep).sum())} tuna-chain identities of "
                  f"{int(gfw_only.sum())} (WCPFC auth / FISHING-CARRIER-SUPPORT / "
                  f"fishing gear); dropped {len(dropped)}:")
            for t, n in Counter(
                    dropped["gfw_shiptypes"].fillna("UNKNOWN")).most_common(10):
                print(f"    {n:6d}  {t}")
        master = master[keep]

    master.to_csv(out_dir / "vessel_master.csv", index=False, encoding="utf-8-sig")

    n = len(master)
    m = (master["match_method"].isin(["IRCS", "IMO", "name"])).sum()
    fr_txt = ""
    if friends is not None and "friends_match" in master:
        fr_txt = f", {(master['friends_match'] != '').sum()} linked to friends' physical_id"
    print(f"\nvessel_master.csv written: {n} rows "
          f"({m} RFV-GFW matched, "
          f"{(master['match_method'] == 'UNMATCHED').sum()} RFV-only, "
          f"{(master['match_method'] == 'GFW_ONLY').sum()} GFW-only{fr_txt})")
    print("Columns to review by hand: class_hint (suggestion), ownership_class (blank).")


if __name__ == "__main__":
    main()
