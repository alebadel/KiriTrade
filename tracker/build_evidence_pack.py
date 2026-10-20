#!/usr/bin/env python3
"""Build the agents' evidence pack: aggregates and public standards text only. No Kiribati official figures, no names."""
import json, sys, shutil
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; SITE = ROOT/"site_publish"
def main(out):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    inp = json.load(open(SITE/"data/nowcast_inputs.json"))
    base = json.load(open(SITE/"data/nowcast_baseline.json"))
    fleet = json.load(open(SITE/"data/fleet.json"))
    kb = json.load(open(ROOT/"standards_docs/_KB/key_passages_curated.json"))
    (out/"01_partner_series_monthly.json").write_text(json.dumps(inp["monthly"],indent=0))
    (out/"02_fleet_aggregates.json").write_text(json.dumps({
        "kir_flag_fishing_hours_by_address_pattern_by_year":inp["kir_flag_hours_by_address_hint_category"],
        "register_counts":inp["register_counts"],"ais_chain_facts_three_registers":fleet["chain_facts"],
        "ais_chain_facts_kiribati_register":fleet["chain_facts_kir"],
        "how_to_read":"address_resident_pattern = owner/operator address on the register is in Kiribati; address_foreign_pattern = abroad; unclassified = register gives no usable address. Hours are windowed to register tenure. This is a hint about residence of the operator, not a finding."},indent=1))
    import csv
    rows=list(csv.reader(open(ROOT/"data/out/pna_crosscheck_tuna_by_origin.csv")))
    (out/"03_partner_imports_by_flag_state_annual_usd_m.json").write_text(json.dumps({"header":rows[0][1:],"rows":{r[0]:[round(float(x),1) for x in r[1:]] for r in rows[1:]},
        "note":"Partner-reported imports of tuna by origin as coded by importers (flag of catching vessel). Not any country's own export statistics."},indent=1))
    (out/"04_baseline_nowcast_and_scorecard.json").write_text(json.dumps({"scorecard":base["scorecard"],"baseline":base["nowcast"],"meta":base["meta"]},indent=1))
    (out/"05_standards_extracts.json").write_text(json.dumps(kb["topics"],indent=1))
    (out/"00_README.md").write_text("""# Evidence pack (Tier 2: partner series + fleet aggregates + standards texts)
Comparable-island panel registry: EMPTY. Hold-out step: SKIPPED (no panel countries yet). Your principles therefore rest on the standards extracts and your own knowledge.
Not provided, by design: Kiribati's own returns, the statistical office's or the central bank's figures, balance of payments data, vessel or company names.
Series: tuna HS 030341-030349, 030487, 160414, USD m, as reported by partner (importing) countries, months labelled by period of import.
Thailand publishes with a lag; its months from 2026-06 are not yet published. Non-Thai partners: 2026-06 and 2026-07 are partial; 2026-08 onward are absent.
Target months: 2026-06 .. 2026-11 (2026-11 is a projection).
""")
    print("pack ->", out, sorted(p.name for p in out.iterdir()))
main(sys.argv[1] if len(sys.argv)>1 else ROOT/"GPS/ensemble/evidence_20261020")
