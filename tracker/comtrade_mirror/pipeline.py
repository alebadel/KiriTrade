"""End-to-end orchestration, and the validation gate for step J."""
from __future__ import annotations

import json
import logging

import pandas as pd

from . import aggregate, diagnostics, extract, mirror, references
from .client import ComtradeClient
from .config import Config

log = logging.getLogger(__name__)


def _save(df: pd.DataFrame, path):
    """Parquet when an engine is installed (preserves dtypes), CSV otherwise."""
    try:
        df.to_parquet(path.with_suffix(".parquet"), index=False)
    except Exception:
        df.to_csv(path.with_suffix(".csv"), index=False)


def run(cfg: Config, *, use_reporter_list: bool = False, offline_raw: pd.DataFrame | None = None):
    """Extract -> raw -> mirror pairs -> metrics -> quarterly tables.

    `offline_raw` bypasses the network and is what the test harness uses.
    """
    cfg.raw_dir.mkdir(parents=True, exist_ok=True)

    if offline_raw is not None:
        raw = offline_raw
        avail = pd.DataFrame()
    else:
        client = ComtradeClient(cfg)
        refs = references.load_references(cfg, client)

        avail = extract.available_periods(client, cfg, cfg.periods)
        periods = (
            sorted(avail["period"].unique().tolist())
            if not avail.empty and "period" in avail.columns
            else cfg.periods
        )
        log.info("%d of %d requested months are available", len(periods), len(cfg.periods))

        reporters = (
            references.reporter_codes(refs, exclude=cfg.code) if use_reporter_list else None
        )

        self_df = extract.pull_self(client, cfg, periods)
        mirror_df = extract.pull_mirror(client, cfg, periods, reporters=reporters)
        raw = pd.concat([self_df, mirror_df], ignore_index=True)
        log.info("API calls spent today: %d; throttle waits: %d",
                 client._calls_today, client._throttled)

    raw = extract.dedupe_raw(raw)
    _save(raw, cfg.raw_dir / "raw_observations")

    norm = mirror.normalise(raw, cfg)
    pairs = mirror.build_pairs(norm)
    metrics = diagnostics.add_metrics(pairs)
    _save(metrics, cfg.interim_dir / "mirror_metrics")

    tables = aggregate.quarterly_tables(metrics)
    tables["forensic_flags"] = diagnostics.forensic_flags(metrics)
    tables["coverage"] = diagnostics.coverage_report(
        metrics, sorted(metrics["period"].unique().tolist())
    )

    for name, t in tables.items():
        t.to_csv(cfg.out_dir / f"{name}.csv", index=False)

    checks = validate(cfg, raw, metrics, tables)
    (cfg.out_dir / "validation.json").write_text(json.dumps(checks, indent=2, default=str))
    return {"raw": raw, "metrics": metrics, "tables": tables, "checks": checks,
            "availability": avail}


def validate(cfg: Config, raw: pd.DataFrame, metrics: pd.DataFrame, tables: dict) -> dict:
    """The seven checks from section J, run automatically on every pass."""
    checks: dict[str, dict] = {}

    # 1 & 2 & 3 - directions map correctly and both sides landed in each direction.
    dirs = metrics["direction"].unique().tolist()
    checks["directions_present"] = {
        "ok": set(dirs) <= {"export", "import"} and bool(dirs),
        "detail": dirs,
    }
    for direction in ("export", "import"):
        sub = metrics[metrics["direction"] == direction]
        checks[f"{direction}_has_both_sides"] = {
            "ok": bool(sub["value_self"].notna().any() and sub["value_mirror"].notna().any()),
            "detail": {
                "self_rows": int(sub["value_self"].notna().sum()),
                "mirror_rows": int(sub["value_mirror"].notna().sum()),
            },
        }

    # 4 - month-to-quarter sums.
    mq = aggregate.check_month_to_quarter(metrics, tables["quarterly_total"])
    checks["month_to_quarter_sums"] = {
        "ok": bool(mq["ok"].all()) if not mq.empty else False,
        "detail": mq.to_dict("records"),
    }

    # 5 - HS codes and descriptions preserved at 6 digits.
    codes = metrics["cmd_code"].astype(str)
    checks["hs6_preserved"] = {
        "ok": bool((codes.str.len() == 6).all()) and bool(metrics["cmd_desc"].notna().any()),
        "detail": {"bad_length": int((codes.str.len() != 6).sum())},
    }

    # 6 - missing observations were not converted to zero.
    zeros_self = int((metrics["value_self"] == 0).sum())
    zeros_mirror = int((metrics["value_mirror"] == 0).sum())
    checks["no_silent_zeros"] = {
        "ok": zeros_self == 0 and zeros_mirror == 0,
        "detail": {
            "explicit_zero_self": zeros_self,
            "explicit_zero_mirror": zeros_mirror,
            "na_self": int(metrics["value_self"].isna().sum()),
            "na_mirror": int(metrics["value_mirror"].isna().sum()),
            "note": "NaN means not reported; 0 would mean reported as zero.",
        },
    }

    # 7 - no duplicate or pre-aggregated rows survived into the pair layer.
    key = ["period", "direction", "counterpart_code", "cmd_code"]
    dup = int(metrics.duplicated(subset=key).sum())
    world = 0
    if "partnerCode" in raw.columns:
        world = int((pd.to_numeric(raw["partnerCode"], errors="coerce") == 0).sum())
    checks["no_double_counting"] = {
        "ok": dup == 0 and world == 0,
        "detail": {"duplicate_pair_keys": dup, "world_partner_rows_in_raw": world},
    }

    checks["_summary"] = {
        "ok": all(v["ok"] for k, v in checks.items() if not k.startswith("_")),
        "country": cfg.name,
        "n_raw_rows": int(len(raw)),
        "n_pair_rows": int(len(metrics)),
    }
    return checks
