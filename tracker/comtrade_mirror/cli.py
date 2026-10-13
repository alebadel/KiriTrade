"""Command line entry point.

    python -m comtrade_mirror.cli check
    python -m comtrade_mirror.cli availability --country kiribati
    python -m comtrade_mirror.cli run --country kiribati --years 2024
    python -m comtrade_mirror.cli run --country tuvalu --years 2023 2024 --reporter-list
    python -m comtrade_mirror.cli fish --country kiribati --monthly-years 2022 2026 --annual-years 2010 2025
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from .client import ComtradeClient
from .config import COUNTRIES, Config
from .pipeline import run


def _cfg(a) -> Config:
    return Config(country=a.country, years=tuple(a.years), tier=a.tier)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="comtrade-mirror")
    p.add_argument("command", choices=["check", "availability", "run", "countries", "fish"])
    p.add_argument("--country", default="kiribati")
    p.add_argument("--years", nargs="+", type=int, default=[2024])
    p.add_argument("--tier", default=None, choices=["free", "premium"])
    p.add_argument("--reporter-list", action="store_true",
                   help="Loop an explicit reporter list instead of reporterCode=all")
    p.add_argument("--monthly-years", nargs=2, type=int, default=[2022, 2026],
                   metavar=("FIRST", "LAST"), help="fish mode: monthly span")
    p.add_argument("--annual-years", nargs=2, type=int, default=[2010, 2025],
                   metavar=("FIRST", "LAST"), help="fish mode: annual span")
    p.add_argument("--no-monthly", action="store_true", help="fish mode: skip monthly")
    p.add_argument("--no-annual", action="store_true", help="fish mode: skip annual")
    p.add_argument("--products", default="fish", choices=["fish", "rice", "sugar"],
                   help="fish mode: product group (rice and sugar pull both sides)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if a.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    if a.tier is None:
        a.tier = Config().tier

    if a.command == "countries":
        for slug, m in sorted(COUNTRIES.items()):
            print(f"{slug:15s} {m['m49']:>4}  {m['iso3']}  {m['name']}")
        return 0

    cfg = _cfg(a)

    if a.command == "check":
        client = ComtradeClient(cfg)
        print(f"tier              : {cfg.tier}   (from COMTRADE_TIER, or TIER= in COMTRADE_API.txt/.env)")
        print(f"data endpoint     : {cfg.base_data_url}")
        print(f"record cap/call   : {cfg.max_records}")
        print(f"key configured    : {'yes' if cfg.subscription_key else 'NO'}")
        print(f"calls remaining   : {client.calls_remaining}/{cfg.calls_per_day}")
        if not cfg.subscription_key:
            print("\nNo key found: put PRIMARY_KEY=... in COMTRADE_API.txt (or set COMTRADE_API_KEY).")
            return 1
        rows = client.get_availability(reporter_code=cfg.code)
        print(f"availability rows : {len(rows)} for {cfg.name} ({cfg.code})")
        return 0

    if a.command == "availability":
        client = ComtradeClient(cfg)
        df = pd.DataFrame(client.get_availability(reporter_code=cfg.code))
        if df.empty:
            print(f"No monthly HS availability records for {cfg.name}.")
            return 0
        cols = [c for c in ("period", "classificationCode", "publicationDate",
                            "isOriginalClassification", "datasetChecksum")
                if c in df.columns]
        print(df[cols].sort_values("period").to_string(index=False))
        return 0

    if a.command == "fish":
        from .fish import run_products, PRODUCT_GROUPS
        res = run_products(cfg, product=a.products,
                           monthly_years=None if a.no_monthly else tuple(a.monthly_years),
                           annual_years=None if a.no_annual else tuple(a.annual_years))
        side = PRODUCT_GROUPS[a.products]["side"]
        what = (f"Partner-reported {a.products} imports from {cfg.name}" if side == "export"
                else f"Partner-reported {a.products} exports to {cfg.name}")
        if "annual" in res:
            print(f"\n{what}, USD millions (annual data):")
            print(res["annual"].round(2).to_string(index=False))
        if "monthly" in res:
            m = res["monthly"]
            m["year"] = m["period"].astype(str).str[:4]
            print("\nMonthly data summed by year, USD millions:")
            print(m.groupby("year")[["tuna", "other_fish", "all_fish"]].sum()
                  .round(2).to_string())
        print(f"\nOutputs written to {cfg.out_dir / a.products}")
        return 0

    res = run(cfg, use_reporter_list=a.reporter_list)
    checks = res["checks"]
    print(f"\n{cfg.name}: {checks['_summary']['n_raw_rows']} raw rows -> "
          f"{checks['_summary']['n_pair_rows']} mirror pairs")
    for name, c in checks.items():
        if name.startswith("_"):
            continue
        print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {name}")
    flags = res["tables"]["forensic_flags"]
    if not flags.empty:
        inv = flags[flags["flag"] == "investigate"]
        print(f"\n{len(inv)} product-direction pairs flagged for investigation")
        if not inv.empty:
            print(inv.head(15).to_string(index=False))
    print(f"\nOutputs written to {cfg.out_dir}")
    return 0 if checks["_summary"]["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
