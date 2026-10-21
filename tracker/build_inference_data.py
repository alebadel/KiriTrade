#!/usr/bin/env python3
"""Build data/inference.json from a folder of agent draws (the "bridge" runs).

Each draw is one agent's JSON answer to tracker/agents/bridge_prompt.md: numbered principles, a note on
how it used the official figures, and one bridge per period that walks from the raw partner-reported
tuna figure to the agent's estimate of true exports in six signed layers.

This script is the only place where numbers are aggregated: it validates every draw (layer order,
reconciliation, banned words), computes the mean, median, 10th/90th percentiles, minimum and maximum
of every layer and of the end value across accepted draws, and writes the result with the agents'
principles and official-use notes. Rejected draws are listed with the reason. No agent arithmetic is
published.

Usage:
  python tracker/build_inference_data.py --draws <folder> --out data/inference.json \
      --run-id bridge-v2-20261020 --run-date 2026-10-20 [--prompt tracker/agents/bridge_prompt.md]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import statistics as st
import sys
from pathlib import Path

LAYERS = [
    {"id": "L1_valuation", "label": "Freight and insurance (CIF to FOB)", "short": "Freight and\ninsurance\n(CIF→FOB)",
     "description": "Importers value goods at their own border, including freight and insurance. Exports are valued at the exporter's border. The layer removes the difference."},
    {"id": "L2_nonresident_operated", "label": "Catch of vessels run by non-resident operators", "short": "Catch of\nnon-resident\noperators",
     "description": "Fish caught by a Kiribati-flagged vessel whose operator is resident elsewhere is not a Kiribati export: the sale is between two non-residents. The layer removes it. Access fees such operators pay are income, not goods, and are not part of the bridge."},
    {"id": "L3_other_origin_coding", "label": "Resident catch coded to another origin", "short": "Resident catch\ncoded to\nanother origin",
     "description": "Fish caught by Kiribati-resident operators that importers did not code as Kiribati-origin, for example from vessels under another flag or coded to the country of landing or processing. The layer adds it."},
    {"id": "L4_unrecorded_routes", "label": "Resident sales by routes the partner series does not capture", "short": "Resident sales\nby routes\nnot recorded",
     "description": "Fish sold by residents to non-residents at sea, to partners that do not report, landed in third countries, or under product codes outside the tuna series. The layer adds it."},
    {"id": "L5_treatment", "label": "Treatment: processing, merchanting, re-exports", "short": "Treatment\n(processing,\nre-exports)",
     "description": "Goods sent for processing without a change of ownership, merchanting, fish consumed at home and re-exports change what counts as a good. The layer adds or removes accordingly."},
    {"id": "L6_other", "label": "Other adjustments named by the agent", "short": "Other",
     "description": "Anything else the agent judged material, named in its rationale; zero when nothing."},
]
LAYER_IDS = [l["id"] for l in LAYERS]
BANNED = re.compile(r"\b(misreport\w*|under-?report\w*|evasion|fraud\w*)\b", re.I)


def q(values, p):
    v = sorted(values)
    if not v:
        return None
    k = (len(v) - 1) * p
    a = int(k)
    b = min(a + 1, len(v) - 1)
    return v[a] + (v[b] - v[a]) * (k - a)


def stats(values):
    v = [float(x) for x in values]
    return {"mean": round(st.mean(v), 3), "sd": round(st.pstdev(v), 3) if len(v) > 1 else 0.0,
            "p10": round(q(v, .1), 3), "p50": round(q(v, .5), 3), "p90": round(q(v, .9), 3),
            "min": round(min(v), 3), "max": round(max(v), 3), "n": len(v)}


def validate(d: dict) -> str | None:
    if BANNED.search(json.dumps(d)):
        return "banned word: " + BANNED.search(json.dumps(d)).group(0)
    if not isinstance(d.get("bridges"), list) or not d["bridges"]:
        return "no bridges"
    for b in d["bridges"]:
        if [l.get("id") for l in b.get("layers", [])] != LAYER_IDS:
            return f"layer ids wrong in {b.get('period')}"
        s = b["start"] + sum(l["value"] for l in b["layers"])
        if abs(s - b["true_exports"]) > 0.015:
            return f"does not reconcile in {b.get('period')}: {s:.2f} vs {b['true_exports']}"
        for l in b["layers"]:
            if not (l["lo80"] <= l["value"] <= l["hi80"]):
                return f"layer range not ordered: {b.get('period')} {l['id']}"
        if not (b["true_lo80"] <= b["true_exports"] <= b["true_hi80"]):
            return f"end range not ordered in {b.get('period')}"
    if not isinstance(d.get("principles"), list) or len(d["principles"]) < 3:
        return "fewer than 3 principles"
    return None


def build(draws_dir: Path, run_id: str, run_date: str, prompt_path: Path | None, evidence: list[str], official_by_period: dict,
          model: str = "", effort: str = "") -> dict:
    files = sorted(p for p in draws_dir.glob("draw_*.json"))
    accepted, rejected = [], []
    for p in files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rejected.append({"draw": p.stem, "reason": f"invalid JSON: {e}"})
            continue
        why = validate(d)
        if why:
            rejected.append({"draw": p.stem, "reason": why})
        else:
            accepted.append((p.stem, d))
    if not accepted:
        raise SystemExit("no accepted draws")

    periods = sorted({b["period"] for _, d in accepted for b in d["bridges"]})
    out_periods = []
    for per in periods:
        bridges = [(name, b) for name, d in accepted for b in d["bridges"] if b["period"] == per]
        start = bridges[0][1]["start"]
        layers = []
        for i, lid in enumerate(LAYER_IDS):
            vals = [b["layers"][i]["value"] for _, b in bridges]
            layers.append(dict({"id": lid}, **stats(vals),
                               own_lo_mean=round(st.mean(b["layers"][i]["lo80"] for _, b in bridges), 3),
                               own_hi_mean=round(st.mean(b["layers"][i]["hi80"] for _, b in bridges), 3),
                               confidence_counts={c: sum(1 for _, b in bridges if b["layers"][i].get("confidence") == c) for c in ("stated in a source", "observed in data", "inferred")}))
        ends = [b["true_exports"] for _, b in bridges]
        end = dict(stats(ends), own_lo_mean=round(st.mean(b["true_lo80"] for _, b in bridges), 3),
                   own_hi_mean=round(st.mean(b["true_hi80"] for _, b in bridges), 3), values=[round(v, 2) for v in ends])
        out_periods.append({
            "period": per, "start": {"value": start, "label": "Partner-reported tuna, sum of monthly returns (CIF)"},
            "layers": layers, "end": end,
            "share_of_start": {"mean": round(end["mean"] / start, 3), "p10": round(end["p10"] / start, 3), "p90": round(end["p90"] / start, 3)},
            "official": official_by_period.get(per, {}),
            "rationales": [{"agent": name, "layer": l["id"], "value": l["value"], "lo80": l["lo80"], "hi80": l["hi80"], "text": l.get("rationale", ""), "confidence": l.get("confidence")} for name, b in bridges for l in b["layers"]],
        })

    principles = [dict(agent=name, **{k: p.get(k) for k in ("id", "statement", "source", "uncertainty")}) for name, d in accepted for p in d["principles"]]
    official_use = [{"agent": name, "text": d.get("official_use", "")} for name, d in accepted]
    audits = [{"agent": name, "text": d.get("audit", "")} for name, d in accepted]
    prompt_hash = hashlib.sha256(prompt_path.read_bytes()).hexdigest()[:12] if prompt_path and prompt_path.exists() else None
    return {
        "meta": {
            "run_id": run_id, "run_date": run_date,
            "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "builder": "tracker/build_inference_data.py",
            "n_agents": len(accepted), "n_rejected": len(rejected), "rejected": rejected,
            "agent": {"model": model, "effort": effort,
                      "what": "Each agent is one fresh session of the model named here, with no memory of the other sessions, given the evidence files and the instructions and allowed to read nothing else."},
            "prompt": str(prompt_path) if prompt_path else None, "prompt_sha256_12": prompt_hash,
            "evidence": evidence,
            "what": "Thirty independent AI agents, each given the same evidence pack and the same instructions, each walked from the raw partner-reported tuna figure to its own estimate of Kiribati's true tuna exports (FOB value of fish that Kiribati-resident operators sold to non-residents) in six signed layers. This file holds the aggregates across agents, their principles and their notes; no agent did arithmetic that is published.",
            "notes": [
                "Spread across agents (10th to 90th percentile, min, max) is disagreement given identical evidence. It is not a standard error and not a confidence interval; shared blind spots do not appear in it.",
                "own_lo_mean and own_hi_mean are the averages of the 80% ranges the agents themselves gave for each layer and for the end value; they are wider than the spread across agents.",
                "The official figures were in the evidence pack as evidence of what the compiler recorded; they were not the target. Each agent's note on how it used them is in official_use.",
                "Residence and ownership are conditions in the agents' reasoning, never findings about any vessel or company. No names appear in the pack or in this file.",
            ],
        },
        "layers": LAYERS,
        "periods": out_periods,
        "principles": principles,
        "official_use": official_use,
        "audits": audits,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-date", required=True)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--evidence", default="partner series (01); fleet aggregates (02); partner imports by flag state (03); standards extracts (05); Kiribati official statistics (06)")
    ap.add_argument("--official", default=None, help="JSON file: {period: {bop_goods_exports: .., customs_exports_kiribati_tuna: ..}}")
    ap.add_argument("--model", default="", help="model name the agents ran on, as it should appear on the site")
    ap.add_argument("--effort", default="", help="reasoning effort setting the agents ran with")
    a = ap.parse_args(argv)
    official = json.loads(Path(a.official).read_text(encoding="utf-8")) if a.official else {}
    res = build(Path(a.draws), a.run_id, a.run_date, Path(a.prompt) if a.prompt else None, [s.strip() for s in a.evidence.split(";")], official,
                model=a.model, effort=a.effort)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    m = res["meta"]
    print(f"inference.json: {m['n_agents']} accepted, {m['n_rejected']} rejected -> {a.out}")
    for p in res["periods"]:
        print(f"  {p['period']}: start {p['start']['value']:.2f} -> end mean {p['end']['mean']:.2f} (p10 {p['end']['p10']:.2f}, p90 {p['end']['p90']:.2f}); "
              + ", ".join(f"{l['id'][:2]} {l['mean']:+.1f}" for l in p["layers"]))
    for r in m["rejected"]:
        print("  rejected:", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
