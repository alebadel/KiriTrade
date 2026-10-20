#!/usr/bin/env python3
"""Validate agent draws and aggregate deterministically. Usage:
  ensemble_tools.py validate DRAWS_DIR   -> prints accepted/rejected, writes DRAWS_DIR/_accepted.json
  ensemble_tools.py aggregate DRAWS_DIR OUT_JSON
"""
import json, re, sys, statistics as st
from pathlib import Path
TARGETS = ["2026-06","2026-07","2026-08","2026-09","2026-10","2026-11"]
EVID = {"00","01","02","03","04","05"}
BANNED = re.compile(r"\b(MV|M/V|FV|F/V|Ltd|Pte|Co\.|Corp|Pacific Fishing|Kiribati Fish|MFMRD|NSO)\b|\bNational Statistics Office\b|\bBank of Kiribati\b", re.I)
OFFICIAL = re.compile(r"(official|NSO|national statistics|central bank).{0,40}(figure|export|data|statistic)", re.I)

def check(d):
    errs = []
    P = d.get("principles")
    if not isinstance(P, list) or not (3 <= len(P) <= 10): errs.append("principles count"); P = P if isinstance(P, list) else []
    ids = {p.get("id") for p in P if isinstance(p, dict)}
    for p in P:
        if not all(isinstance(p.get(k), str) and p.get(k) for k in ("id","statement","source","uncertainty")): errs.append("principle fields")
    M = d.get("months")
    if not isinstance(M, list) or [m.get("period") for m in M] != TARGETS: errs.append("months/periods"); return errs
    for m in M:
        try:
            t,a,b,lo,hi = (float(m[k]) for k in ("total","component_a","component_b","lo80","hi80"))
        except Exception: errs.append(f"{m.get('period')}: numeric fields"); continue
        if abs(a+b-t) > 0.011: errs.append(f"{m['period']}: A+B!=total")
        if not (0 <= t <= 40 and a >= -0.01 and b >= -0.01 and a <= t+0.01): errs.append(f"{m['period']}: range")
        if not (lo <= t <= hi): errs.append(f"{m['period']}: interval order")
        r = m.get("rationale","")
        if not isinstance(r,str) or len(r.split()) > 90 or not r: errs.append(f"{m['period']}: rationale")
        if not set(m.get("principles_used",[])) or not set(m["principles_used"]) <= ids: errs.append(f"{m['period']}: principle refs")
        if not set(m.get("evidence_refs",[])) or not set(m["evidence_refs"]) <= EVID: errs.append(f"{m['period']}: evidence refs")
    blob = json.dumps(d)
    if BANNED.search(blob): errs.append("name pattern")
    if OFFICIAL.search(blob): errs.append("official-figure reference")
    return errs

def validate(dd):
    acc, rej = [], {}
    for f in sorted(Path(dd).glob("draw_*.json")):
        try: d = json.load(open(f))
        except Exception as e: rej[f.name] = [f"json: {e}"]; continue
        e = check(d)
        (rej.__setitem__(f.name, e) if e else acc.append(f.name))
    Path(dd,"_accepted.json").write_text(json.dumps({"accepted":acc,"rejected":rej},indent=1))
    print(f"accepted {len(acc)}, rejected {len(rej)}"); [print(" ",k,v) for k,v in rej.items()]
    return acc

def q(xs, p):
    xs = sorted(xs); k = (len(xs)-1)*p; f = int(k); c = min(f+1, len(xs)-1)
    return xs[f] + (xs[c]-xs[f])*(k-f)

def aggregate(dd, out):
    acc = validate(dd)
    draws = [json.load(open(Path(dd)/f)) for f in acc]
    rows = []
    for i, per in enumerate(TARGETS):
        row = {"period": per}
        for k in ("total","component_a","component_b"):
            xs = [float(d["months"][i][k]) for d in draws]
            row[k] = {"mean": round(st.mean(xs),3), "sd": round(st.pstdev(xs),3), "p10": round(q(xs,.1),3), "p50": round(q(xs,.5),3), "p90": round(q(xs,.9),3)}
        sh = [d["months"][i]["component_a"]/d["months"][i]["total"] for d in draws if d["months"][i]["total"] > 0]
        row["share_a"] = {"mean": round(st.mean(sh),3), "p10": round(q(sh,.1),3), "p90": round(q(sh,.9),3)}
        row["own_lo80_mean"] = round(st.mean(float(d["months"][i]["lo80"]) for d in draws),3)
        row["own_hi80_mean"] = round(st.mean(float(d["months"][i]["hi80"]) for d in draws),3)
        rows.append(row)
    pr = {}
    for d in draws:
        for p in d["principles"]: pr.setdefault(p["statement"].strip(), []).append(p["source"])
    plist = sorted(({"statement":s,"n_agents":len(v)} for s,v in pr.items()), key=lambda x:-x["n_agents"])
    res = {"n_accepted": len(acc), "n_rejected": len(json.load(open(Path(dd)/"_accepted.json"))["rejected"]), "months": rows, "principles": plist, "audits": [d.get("audit","") for d in draws]}
    Path(out).write_text(json.dumps(res, indent=1)); print("wrote", out)

if __name__ == "__main__":
    if sys.argv[1] == "validate": validate(sys.argv[2])
    else: aggregate(sys.argv[2], sys.argv[3])
