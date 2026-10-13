"""Fish-only mirror pull: what partners report importing *from* the subject.

    python -m comtrade_mirror.cli fish --country kiribati
    python -m comtrade_mirror.cli fish --monthly-years 2022 2026 --annual-years 2010 2025

Why a separate mode. The full mirror account needs both sides of every
product and costs days of the free-tier quota. Fish alone, mirror side only,
is cheap: one call per period (annual or monthly), a handful more when a
period hits the 500-record cap. That buys a decade of history, with reporter
detail, for the one product group where the mirror is not a check on customs
but a signal in its own right - the landed value of tuna caught in Kiribati's
EEZ, against which the BOP fishing-licence line can be compared.

Only the mirror side is pulled. Kiribati's own customs returns do not carry
the catch of foreign-flagged vessels, so the self side would be near-empty by
construction and would cost as much again.

HS scope: chapter 03 (fish, live/fresh/frozen/fillets) and heading 1604
(prepared or preserved fish, incl. canned tuna). Reported at HS6, so the
tuna lines can be separated downstream.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .client import ComtradeClient, TruncatedResponse
from .config import Config
from .extract import _counterparts

log = logging.getLogger(__name__)

FISH_PREFIXES = ["03????", "1604??"]
# Finer rungs used only when a period exceeds the record cap.
FISH_HEADINGS = [f"03{h:02d}??" for h in range(1, 9)] + ["1604??"]

# Product groups. `side` says which flow of the subject country the group
# describes: "export" = what partners import FROM the subject (mirror flow M);
# "import" = what partners export TO the subject (mirror flow X), in which
# case the subject's own import returns (self flow M) are pulled as well.
PRODUCT_GROUPS = {
    "fish":  {"prefixes": FISH_PREFIXES, "headings": FISH_HEADINGS, "side": "export"},
    "rice":  {"prefixes": ["1006??"], "headings": ["1006??"], "side": "import"},
    "sugar": {"prefixes": ["1701??"], "headings": ["1701??"], "side": "import"},
}

TUNA = {"030341", "030342", "030343", "030344", "030345", "030346", "030349",
        "030487", "160414"}


def _pull_period(client: ComtradeClient, cfg: Config, *, period: str,
                 freq: str, prefixes=FISH_PREFIXES, headings=FISH_HEADINGS,
                 flow: str = "M", reporter=None, partner=None) -> list[dict]:
    """All reporters' imports from the subject, fish HS6, one period.

    Ladder: whole scope in one call -> one call per heading -> per heading
    per reporter. Each rung is only climbed for the slice that overflowed.
    """
    if reporter is None and partner is None:
        partner = cfg.code
    common = dict(partner_code=partner, period=period, flow_code=flow, freq_code=freq)
    try:
        return client.get_data(reporter_code=reporter, cmd_code=",".join(prefixes),
                               **common)
    except TruncatedResponse:
        log.info("%s: fish scope over the cap, splitting by heading", period)

    rows: list[dict] = []
    reporters: list[int] | None = None
    for head in headings:
        try:
            rows += client.get_data(reporter_code=reporter, cmd_code=head, **common)
            continue
        except TruncatedResponse:
            log.info("%s %s: over the cap, splitting by reporter", period, head)
        if reporter is not None:
            raise TruncatedResponse(f"{period} {head}: single reporter over the cap")
        if reporters is None:
            reporters = _counterparts(client, reporter_code=None,
                                      partner_code=cfg.code, period=period,
                                      flow_code=flow, split_dim="reporter") \
                if freq == "M" else _counterparts_annual(client, cfg, period, flow)
        for rc in reporters:
            try:
                rows += client.get_data(reporter_code=rc, cmd_code=head, **common)
            except TruncatedResponse:
                # One reporter, one heading, >500 HS6 lines is not possible
                # (a heading has < 60 subheadings); surface it rather than guess.
                raise
    return rows


def _counterparts_annual(client: ComtradeClient, cfg: Config, period: str,
                         flow: str = "M") -> list[int]:
    rows = client.get_data(reporter_code=None, partner_code=cfg.code, period=period,
                           flow_code=flow, cmd_code="TOTAL", freq_code="A")
    return sorted({int(r["reporterCode"]) for r in rows
                   if r.get("reporterCode") not in (None, 0, "0")})


def _frame(rows: list[dict], freq: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df[df["aggrLevel"].astype(int) == 6] if "aggrLevel" in df else df
    keep = ["side", "period", "reporterCode", "reporterDesc", "partnerCode", "partnerDesc",
            "cmdCode", "cmdDesc", "primaryValue", "netWgt", "qty", "qtyUnitAbbr"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df["cmdCode"] = df["cmdCode"].astype(str).str.zfill(6)
    df["freq"] = freq
    df["year"] = df["period"].astype(str).str[:4].astype(int)
    df["is_tuna"] = df["cmdCode"].isin(TUNA)
    df["value_usd_m"] = pd.to_numeric(df["primaryValue"], errors="coerce") / 1e6
    return df


def run_fish(cfg: Config, *, monthly_years, annual_years):
    return run_products(cfg, product="fish", monthly_years=monthly_years,
                        annual_years=annual_years)


def run_products(cfg: Config, *, product: str, monthly_years: tuple[int, int] | None,
                 annual_years: tuple[int, int] | None) -> dict[str, pd.DataFrame]:
    """Mirror pull for one product group; for import groups also the subject's own side.

    Outputs keep the fish file names (fish_mirror_*.csv) under
    data/out/<country>/<product>/ so downstream scripts work unchanged; for
    import groups an extra fish_self_*.csv carries the subject's own returns.
    """
    grp = PRODUCT_GROUPS[product]
    mirror_flow = "M" if grp["side"] == "export" else "X"
    client = ComtradeClient(cfg)
    out = cfg.out_dir / product
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    kw = dict(prefixes=grp["prefixes"], headings=grp["headings"])

    def pull(period, freq):
        got = _pull_period(client, cfg, period=period, freq=freq, flow=mirror_flow, **kw)
        if grp["side"] == "import":
            own = _pull_period(client, cfg, period=period, freq=freq, flow="M",
                               reporter=cfg.code, partner=None, **kw)
            # Kiribati's own returns come back with a partner=World total row
            # next to the partner rows; keep only the partner rows.
            own = [r for r in own if str(r.get("partnerCode")) not in ("0", "None")]
            for r in own:
                r["side"] = "self"
        else:
            own = []
        for r in got:
            r["side"] = "mirror"
        return got + own

    if annual_years:
        rows = []
        for y in range(annual_years[0], annual_years[1] + 1):
            got = pull(str(y), "A")
            log.info("annual %s: %d rows (calls left %d)", y, len(got),
                     client.calls_remaining)
            rows += got
        ann = _frame(rows, "A")
        if "side" in ann:
            ann[ann.side == "self"].to_csv(out / "fish_self_annual_detail.csv", index=False)
            ann = ann[ann.side == "mirror"]
        ann.to_csv(out / "fish_mirror_annual_detail.csv", index=False)
        result["annual_detail"] = ann
        if not ann.empty:
            by_year = (ann.groupby(["year", "is_tuna"])["value_usd_m"].sum()
                       .unstack(fill_value=0).rename(columns={True: "tuna", False: "other_fish"}))
            for c in ("tuna", "other_fish"):
                if c not in by_year: by_year[c] = 0.0
            by_year["all_fish"] = by_year["tuna"] + by_year["other_fish"]
            by_year["n_reporters"] = ann.groupby("year")["reporterCode"].nunique()
            by_year.reset_index().to_csv(out / "fish_mirror_annual.csv", index=False)
            result["annual"] = by_year.reset_index()
            rep = (ann.groupby(["year", "reporterDesc"])["value_usd_m"].sum()
                   .unstack("year", fill_value=0))
            rep.to_csv(out / "fish_mirror_annual_by_reporter.csv")
            result["annual_by_reporter"] = rep

    if monthly_years:
        rows = []
        for y in range(monthly_years[0], monthly_years[1] + 1):
            for m in range(1, 13):
                p = f"{y}{m:02d}"
                got = pull(p, "M")
                log.info("monthly %s: %d rows (calls left %d)", p, len(got),
                         client.calls_remaining)
                rows += got
        mon = _frame(rows, "M")
        if "side" in mon:
            mon[mon.side == "self"].to_csv(out / "fish_self_monthly_detail.csv", index=False)
            mon = mon[mon.side == "mirror"]
        mon.to_csv(out / "fish_mirror_monthly_detail.csv", index=False)
        result["monthly_detail"] = mon
        if not mon.empty:
            bym = (mon.groupby(["period", "is_tuna"])["value_usd_m"].sum()
                   .unstack(fill_value=0).rename(columns={True: "tuna", False: "other_fish"}))
            for c in ("tuna", "other_fish"):
                if c not in bym: bym[c] = 0.0
            bym["all_fish"] = bym["tuna"] + bym["other_fish"]
            bym["n_reporters"] = mon.groupby("period")["reporterCode"].nunique()
            bym.reset_index().to_csv(out / "fish_mirror_monthly.csv", index=False)
            result["monthly"] = bym.reset_index()

    log.info("fish outputs in %s; calls remaining today %d", out, client.calls_remaining)
    return result
