"""Offline smoke test: run the whole pipeline on hand-built fixtures.

No API key and no network needed. Run it first to confirm the install works:

    python tests/test_offline.py

The fixtures encode the exact hazards section J asks us to rule out:
  * a product Kiribati reports and partners confirm (matched pair)
  * a product only partners report (the ornamental-fish case)
  * a product only Kiribati reports
  * a Partner=World row and an aggregate row that must be dropped
  * a duplicate row that must not be double counted
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Tracker copy: `pipeline.run` writes raw_observations.parquet and the quarterly
# CSVs into the data root. Point the data root at a scratch folder so this
# fixture run can never overwrite the committed history in tracker/data/.
os.environ["TRACKER_DATA_DIR"] = tempfile.mkdtemp(prefix="kir_test_offline_")
os.environ.setdefault("COMTRADE_NO_SETTINGS_FILES", "1")   # never read key files here

from comtrade_mirror.config import Config          # noqa: E402
from comtrade_mirror.pipeline import run           # noqa: E402

KIR = 296
AUS, USA, JPN = 36, 842, 392


def row(side, period, reporter, partner, flow, cmd, value, **kw):
    d = {
        "side": side, "period": period, "reporterCode": reporter,
        "partnerCode": partner, "flowCode": flow, "cmdCode": cmd,
        "primaryValue": value, "classificationCode": "H6",
        "cmdDesc": f"desc {cmd}", "reporterDesc": f"R{reporter}",
        "partnerDesc": f"P{partner}", "netWgt": value / 10,
        "qty": value / 100, "qtyUnitAbbr": "kg", "isAggregate": False,
        "partner2Code": 0, "customsCode": "C00", "motCode": 0,
    }
    d.update(kw)
    return d


def fixture() -> pd.DataFrame:
    r = [
        # --- matched export pair: copra to Australia, Jan + Feb -------------
        row("self",   "202501", KIR, AUS, "X", "120300", 500_000),
        row("mirror", "202501", AUS, KIR, "M", "120300", 560_000),   # CIF wedge
        row("self",   "202502", KIR, AUS, "X", "120300", 400_000),
        row("mirror", "202502", AUS, KIR, "M", "120300", 448_000),

        # --- mirror-only: ornamental fish, two partners, three months ------
        row("mirror", "202501", USA, KIR, "M", "030110", 90_000),
        row("mirror", "202502", USA, KIR, "M", "030110", 85_000),
        row("mirror", "202504", USA, KIR, "M", "030110", 110_000),
        row("mirror", "202502", JPN, KIR, "M", "030110", 40_000),

        # --- self-only export -----------------------------------------------
        row("self",   "202501", KIR, JPN, "X", "160414", 75_000),

        # --- imports: matched, with a mirror-only import line ---------------
        row("self",   "202501", KIR, AUS, "M", "271019", 1_200_000),
        row("mirror", "202501", AUS, KIR, "X", "271019", 1_150_000),
        row("mirror", "202501", JPN, KIR, "X", "870323", 300_000),

        # --- hazards that must be removed -----------------------------------
        row("self",   "202501", KIR, 0,   "X", "120300", 9_999_999),      # World
        row("self",   "202501", KIR, AUS, "X", "TOTAL",  9_999_999),      # total
        row("mirror", "202501", AUS, KIR, "M", "1203",   9_999_999,
            isAggregate=True),                                            # HS4 agg
        row("self",   "202501", KIR, AUS, "X", "120300", 500_000),        # dup
    ]
    return pd.DataFrame(r)


def main() -> int:
    cfg = Config(country="kiribati", years=(2025,), tier="free")
    res = run(cfg, offline_raw=fixture())
    m, t, checks = res["metrics"], res["tables"], res["checks"]

    print("=== validation ===")
    for name, c in checks.items():
        if not name.startswith("_"):
            print(f"[{'PASS' if c['ok'] else 'FAIL'}] {name}  {c['detail']}")

    print("\n=== mirror pairs ===")
    cols = ["period", "direction", "counterpart_name", "cmd_code",
            "value_self", "value_mirror", "sym_pct_diff", "mirror_only", "self_only"]
    print(m[cols].to_string(index=False))

    print("\n=== forensic flags ===")
    print(t["forensic_flags"].to_string(index=False))

    print("\n=== quarterly balance ===")
    print(t["quarterly_balance"].to_string(index=False))

    # ---- explicit assertions ------------------------------------------------
    assert len(res["raw"]) == 12, f"dedupe left {len(res['raw'])} raw rows, expected 12"
    fish = m[(m.cmd_code == "030110")]
    assert fish["mirror_only"].all(), "ornamental fish must be mirror-only"
    assert fish["value_self"].isna().all(), "unreported must be NaN, never 0"
    flags = t["forensic_flags"]
    fish_flag = flags[flags.cmd_code == "030110"].iloc[0]
    assert fish_flag["flag"] == "investigate", fish_flag.to_dict()
    assert fish_flag["n_months"] == 3 and fish_flag["n_partners"] == 2
    copra = m[(m.cmd_code == "120300") & (m.period == "202501")].iloc[0]
    assert copra["value_self"] == 500_000, "duplicate row was double counted"
    assert bool(copra["within_cif_fob_band"]), "12% wedge should sit in the CIF band"
    assert checks["_summary"]["ok"], "validation gate failed"

    print("\nAll assertions passed.")
    return 0


def test_offline_pipeline():
    """pytest entry point (the script form above still works)."""
    assert main() == 0


if __name__ == "__main__":
    raise SystemExit(main())
