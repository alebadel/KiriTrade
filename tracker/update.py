#!/usr/bin/env python3
"""Daily refresh of the Kiribati tracker from the UN Comtrade API (Agent B).

    python tracker/update.py                  # live: needs COMTRADE_API_KEY (+ COMTRADE_TIER) in the environment
    python tracker/update.py --offline        # no network: rebuild site/data/*.json from the committed files
    python tracker/update.py --dry-run        # print the plan and the API call budget; write nothing
    python tracker/update.py --offline --dry-run

What a live run does, in order
  1. Load tracker/panel.json (written by Agent A). If it is missing, a stub panel is built
     from the always-include list in the shared brief and a warning is printed.
  2. Ask Comtrade's data-availability service (getDa) which datasets exist for Kiribati
     (296) and for every panel reporter, monthly (C/M/HS) and annual (C/A/HS). These rows
     are the LIVE input of the "percent complete" charts (coverage_method "comtrade_getDa").
     Availability is never served from the disk cache.
  3. Pull partner-reported ("mirror") HS6 monthly data - reporter = all, partner = 296, both
     flows - for the rolling window (last 24 months) and for any older month whose
     lastReleased changed since the last run. tracker/data/state.json remembers the
     lastReleased stamp of every reporter-period, so an unchanged month costs 0 calls (it is
     served from the disk cache under tracker/data/cache, which GitHub Actions restores).
     Pull Kiribati's own returns for months that are new or re-released. Pull partners'
     ANNUAL fish data for the last 3 years and, on the premium tier, annual all-goods data.
  4. Merge with the committed history. A month is never dropped; the newer pull wins for the
     same reporter-period-flow. Write raw_observations.parquet and the fish CSVs in the
     layout Agent A's builder reads.
  5. Build site/data/{coverage,series,manifest}.json with Agent A's build_site_data.py and
     national_accounts/peers/products.json with Agent E's build_products.py.
  6. Validate: the pipeline's seven section-J checks on the merged raw data plus the JSON
     contract checks. If anything fails the run exits 2 and NOTHING is promoted into
     tracker/data or site/data, so a bad run never publishes.

Exit codes: 0 ok, 2 validation failed, 3 set-up problem (no key, missing builder), 4 error.

Environment: COMTRADE_API_KEY (secret), COMTRADE_TIER ("free" default | "premium"),
TRACKER_DATA_DIR (default tracker/data), COMTRADE_CALLS_PER_DAY (optional local guard).
No key file is read in GitHub Actions; locally a git-ignored .env or COMTRADE_API.txt next to
the comtrade_mirror package still works (see comtrade_mirror/config.py).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent          # site/tracker
SITE = HERE.parent                               # site/  (the GitHub Pages repo root)
DEFAULT_DATA_DIR = HERE / "data"
DEFAULT_OUT_DIR = SITE / "data"
COUNTRY = "kiribati"
SUBJECT = 296
HIST_START = "2017-01"                           # first month of the committed history
ANNUAL_START = 2010
WINDOW_MONTHS = 24
ANNUAL_YEARS = 3
FISH_PREFIXES = ("03", "1604")
SHIPS_HS2 = {"88", "89"}

# Always-include list from the shared brief (used only when panel.json is missing).
ALWAYS_INCLUDE = {
    36: ("Australia", "AUS"), 554: ("New Zealand", "NZL"), 242: ("Fiji", "FJI"),
    156: ("China", "CHN"), 392: ("Japan", "JPN"), 764: ("Thailand", "THA"),
    410: ("Rep. of Korea", "KOR"), 702: ("Singapore", "SGP"), 842: ("USA", "USA"),
    490: ("Other Asia, nes", "TWN"), 608: ("Philippines", "PHL"), 360: ("Indonesia", "IDN"),
    458: ("Malaysia", "MYS"), 699: ("India", "IND"), 344: ("China, Hong Kong SAR", "HKG"),
    170: ("Colombia", "COL"),
}

# Rough calls per unit, used only for the budget estimate printed by --dry-run.
EST_CALLS = {
    "free":    {"mirror_month_flow": 6, "self_month_flow": 15, "fish_year": 3, "annual_year_flow": 12},
    "premium": {"mirror_month_flow": 1, "self_month_flow": 1, "fish_year": 1, "annual_year_flow": 1},
}

log = logging.getLogger("update")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def pstr(p) -> str:
    """Comtrade period as a plain string: 202607 / '202607' / 202607.0 / '2026-07' -> '202607'."""
    s = str(p).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.replace("-", "")


def ym_dash(p) -> str:
    s = pstr(p)
    return f"{s[:4]}-{s[4:6]}" if len(s) >= 6 else s


def month_add(m: str, k: int) -> str:
    """'2026-07' + k months."""
    y, mm = int(m[:4]), int(m[5:7])
    i = y * 12 + (mm - 1) + k
    return f"{i // 12}-{i % 12 + 1:02d}"


def month_range(a: str, b: str) -> list[str]:
    out, m = [], a
    while m <= b:
        out.append(m)
        m = month_add(m, 1)
    return out


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(d: dt.datetime) -> str:
    return d.isoformat().replace("+00:00", "Z")


def sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# State: what we knew after the last successful run
# --------------------------------------------------------------------------- #
class State:
    """tracker/data/state.json

    availability[reporter][freq][period] = lastReleased stamp seen at the last successful run
    fp[freq:period]                      = fingerprint of the panel's stamps for that period
    pulled[kind:freq:period]             = {"fingerprint", "pulled_at", "n_rows"} for pulled slices
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.d: dict = {"version": 1, "availability": {}, "fp": {}, "pulled": {}, "last_run": None}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.d.update(loaded)
            except (OSError, ValueError) as exc:
                log.warning("state file %s unreadable (%s); starting fresh", self.path, exc)

    # availability stamps -------------------------------------------------
    def stamp(self, code: int, freq: str, period: str):
        return self.d["availability"].get(str(code), {}).get(freq, {}).get(period)

    def set_stamp(self, code: int, freq: str, period: str, stamp) -> None:
        self.d["availability"].setdefault(str(code), {}).setdefault(freq, {})[period] = stamp

    # fingerprints -----------------------------------------------------------
    def fp(self, freq: str, period: str):
        return self.d["fp"].get(f"{freq}:{period}")

    def set_fp(self, freq: str, period: str, fp: str) -> None:
        self.d["fp"][f"{freq}:{period}"] = fp

    # pulls ------------------------------------------------------------------
    def pulled(self, key: str):
        return self.d["pulled"].get(key)

    def set_pulled(self, key: str, fp: str, n_rows: int, when: str) -> None:
        self.d["pulled"][key] = {"fingerprint": fp, "pulled_at": when, "n_rows": int(n_rows)}

    def save(self, path: Path | None = None) -> Path:
        p = Path(path or self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.d, indent=1, sort_keys=True), encoding="utf-8")
        return p


# --------------------------------------------------------------------------- #
# Availability index (getDa rows)
# --------------------------------------------------------------------------- #
class AvailIndex:
    def __init__(self, rows: list[dict] | None = None):
        self.rows: list[dict] = []
        self.idx: dict[tuple[int, str, str], dict] = {}
        for r in rows or []:
            self.add(r)

    def add(self, r: dict) -> None:
        try:
            code = int(r.get("reporterCode"))
        except (TypeError, ValueError):
            return
        p = pstr(r.get("period") or r.get("refPeriodId") or "")
        if not p:
            return
        freq = str(r.get("freqCode") or ("A" if len(p) == 4 else "M")).upper()
        if freq == "M" and len(p) >= 6:
            p = p[:6]
        elif freq == "A":
            p = p[:4]
        lr = r.get("lastReleased") or r.get("lastUpdated") or None
        rec = {"lastReleased": str(lr)[:10] if lr else None,
               "checksum": r.get("datasetChecksum"),
               "totalRecords": r.get("totalRecords"),
               "classification": r.get("classificationCode")}
        self.idx[(code, freq, p)] = rec
        self.rows.append(r)

    def stamp(self, code: int, freq: str, period: str):
        rec = self.idx.get((code, freq, period))
        if rec is None:
            return None
        return rec["lastReleased"] or rec["checksum"] or (str(rec["totalRecords"]) if rec["totalRecords"] is not None else "published")

    def periods(self, code: int, freq: str) -> list[str]:
        return sorted(p for (c, f, p) in self.idx if c == code and f == freq)

    def all_periods(self, codes, freq: str) -> set[str]:
        codes = set(codes)
        return {p for (c, f, p) in self.idx if f == freq and c in codes}

    def fingerprint(self, period: str, freq: str, codes) -> tuple[str, int]:
        parts = []
        for c in sorted(set(codes)):
            s = self.stamp(c, freq, period)
            if s is not None:
                parts.append(f"{c}:{s}")
        return sha("|".join(parts)), len(parts)

    def panel_rows(self, codes) -> list[dict]:
        codes = {int(c) for c in codes}
        out = []
        for r in self.rows:
            try:
                if int(r.get("reporterCode")) in codes:
                    out.append(r)
            except (TypeError, ValueError):
                pass
        return out


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
def load_panel(path: Path) -> tuple[dict, bool]:
    if path.exists():
        panel = json.loads(path.read_text(encoding="utf-8"))
        if panel.get("members"):
            return panel, False
        log.warning("%s has no members; using the stub panel", path)
    else:
        log.warning("%s not found (Agent A writes it); using a stub panel from the always-include list "
                    "with equal weights. Re-run after panel.json exists.", path)
    n = len(ALWAYS_INCLUDE)
    members = [{"code": c, "name": nm, "iso3": iso3, "label": nm, "w_exports": 1.0 / n, "w_imports": 1.0 / n,
                "share_exports_all_reporters": None, "share_imports_all_reporters": None,
                "always_include": True, "meets_threshold": False}
               for c, (nm, iso3) in ALWAYS_INCLUDE.items()]
    stub = {"meta": {"generated_at": iso(utc_now()), "source": "stub (always-include list, equal weights)",
                     "notes": ["STUB panel: tracker/panel.json was missing when update.py ran. Weights are equal, "
                               "not trade-based. Agent A's build_site_data.py writes the real panel."]},
            "subject": {"code": SUBJECT, "name": "Kiribati"},
            "reference_window": {"start": 2023, "end": 2025}, "threshold_share": 0.005,
            "n_panel": n, "members": members, "stub": True}
    return stub, True


def panel_codes(panel: dict) -> list[int]:
    return sorted(int(m["code"]) for m in panel["members"])


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
@dataclass
class Plan:
    window: list[str]                                  # YYYYMM, newest first
    mirror: list[str] = field(default_factory=list)    # months to pull, newest first
    mirror_reason: dict = field(default_factory=dict)
    changed_reporters: dict = field(default_factory=dict)   # month -> set of panel codes re-released
    baseline: list[str] = field(default_factory=list)  # months whose fingerprint is recorded without a pull
    self_months: list[str] = field(default_factory=list)
    self_reason: dict = field(default_factory=dict)
    fish_years: list[int] = field(default_factory=list)
    annual_years: list[int] = field(default_factory=list)
    skipped_no_publisher: list[str] = field(default_factory=list)
    est: dict = field(default_factory=dict)


def rolling_window(today: dt.date, n: int) -> list[str]:
    end = month_add(f"{today.year}-{today.month:02d}", -1)       # last fully elapsed month
    return [pstr(month_add(end, -i)) for i in range(n)]         # newest first


def make_plan(avail: AvailIndex | None, state: State, codes: list[int], raw_self_months: set[str],
              today: dt.date, args, tier: str, raw_mirror_months: set[str] | None = None) -> Plan:
    plan = Plan(window=rolling_window(today, args.window_months))
    if avail is None:                       # offline: nothing to pull
        return plan
    wset = set(plan.window)
    hist0 = pstr(HIST_START)
    raw_mirror_months = raw_mirror_months or set()
    backfill_budget = max(0, args.backfill)

    # -- mirror months ------------------------------------------------------------------
    candidates = sorted(set(plan.window) | {p for p in avail.all_periods(codes, "M") if p >= hist0}, reverse=True)
    for p in candidates:
        fp, n_pub = avail.fingerprint(p, "M", codes)
        prev_pull = state.pulled(f"mirror:M:{p}")
        prev_fp = state.fp("M", p)
        if n_pub == 0:
            plan.skipped_no_publisher.append(p)
            continue
        if p in wset or p > plan.window[0]:          # window, or newer than the window (early publisher)
            if prev_pull is None:
                plan.mirror.append(p); plan.mirror_reason[p] = "window: not pulled before"
            elif prev_pull["fingerprint"] != fp:
                plan.mirror.append(p); plan.mirror_reason[p] = "window: a panel partner re-released"
        else:
            if prev_pull is None and p not in raw_mirror_months and backfill_budget > 0:
                backfill_budget -= 1                              # gradual backfill of partner-only months
                plan.mirror.append(p); plan.mirror_reason[p] = "backfill: older month with no partner data in the history"
            elif prev_fp is None:
                plan.baseline.append(p)                           # first sight: record, do not pull
            elif prev_fp != fp and not args.window_only:
                plan.mirror.append(p); plan.mirror_reason[p] = "older month re-released since last run"
        changed = set()
        for c in codes:
            now, before = avail.stamp(c, "M", p), state.stamp(c, "M", p)
            if before is not None and now != before:
                changed.add(c)
        if changed:
            plan.changed_reporters[p] = changed

    # -- Kiribati's own months --------------------------------------------------------
    for p in sorted(avail.periods(SUBJECT, "M"), reverse=True):
        if p < hist0:
            continue
        now, before = avail.stamp(SUBJECT, "M", p), state.stamp(SUBJECT, "M", p)
        if p not in raw_self_months:
            plan.self_months.append(p); plan.self_reason[p] = "new Kiribati month"
        elif before is not None and now != before:
            plan.self_months.append(p); plan.self_reason[p] = "Kiribati re-released the month"

    # -- annual ---------------------------------------------------------------------
    for y in range(today.year - args.annual_years, today.year + 1):
        fp, n_pub = avail.fingerprint(str(y), "A", codes)
        if n_pub == 0:
            continue
        prev = state.pulled(f"fish:A:{y}")
        if prev is None or prev["fingerprint"] != fp:
            plan.fish_years.append(y)
        want_annual = (args.annual_all_goods == "yes") or (args.annual_all_goods == "auto" and tier == "premium")
        prev = state.pulled(f"annual:A:{y}")
        if want_annual and (prev is None or prev["fingerprint"] != fp):
            plan.annual_years.append(y)

    e = EST_CALLS["premium" if tier == "premium" else "free"]
    plan.est = {
        "getDa": 2 if tier == "premium" else 2 + 12,
        "mirror": len(plan.mirror) * 2 * e["mirror_month_flow"],
        "self": len(plan.self_months) * 2 * e["self_month_flow"],
        "fish_annual": len(plan.fish_years) * e["fish_year"],
        "annual_all_goods": len(plan.annual_years) * 2 * e["annual_year_flow"],
    }
    plan.est["total"] = sum(plan.est.values())
    return plan


def describe_plan(plan: Plan, tier: str, offline: bool) -> str:
    lines = [f"Plan ({'OFFLINE, no API calls' if offline else 'live, tier=' + tier}):",
             f"  rolling window      : {ym_dash(plan.window[-1])} .. {ym_dash(plan.window[0])} ({len(plan.window)} months)"]
    if offline:
        lines.append("  nothing is pulled; site/data/*.json are rebuilt from the committed files")
        return "\n".join(lines)
    lines.append(f"  mirror months to pull: {len(plan.mirror)}")
    for p in plan.mirror[:40]:
        lines.append(f"      {ym_dash(p)}  {plan.mirror_reason[p]}"
                     + (f"  (re-released: {sorted(plan.changed_reporters[p])})" if p in plan.changed_reporters else ""))
    if len(plan.mirror) > 40:
        lines.append(f"      ... and {len(plan.mirror) - 40} more")
    lines.append(f"  Kiribati months to pull: {len(plan.self_months)} {[ym_dash(p) for p in plan.self_months[:12]]}")
    lines.append(f"  fish annual years   : {plan.fish_years}")
    lines.append(f"  annual all-goods    : {plan.annual_years}")
    lines.append(f"  baseline only (recorded, not pulled): {len(plan.baseline)} months; "
                 f"no panel publisher: {len(plan.skipped_no_publisher)} months")
    lines.append("  estimated API calls : " + ", ".join(f"{k} {v}" for k, v in plan.est.items()))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Client wrapper: fresh availability, cache bypass for re-released months, run cap
# --------------------------------------------------------------------------- #
def make_client(cfg, refresh_periods, max_calls: int | None, session=None):
    from comtrade_mirror.client import ComtradeClient, QuotaExhausted

    class TrackerClient(ComtradeClient):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.refresh = set(refresh_periods)
            self.max_calls = max_calls
            self.run_calls = 0
            self.cache_hits = 0
            self._fresh_done: set[str] = set()
            if session is not None:               # tests inject a fake API; no pacing needed
                self.session = session
                self.cfg.min_seconds_between_calls = 0.0

        def get(self, url, params, *, use_cache: bool = True):
            cache = self._cache_path(url, params)
            period = pstr(params.get("period", "")) if params.get("period") is not None else ""
            if "/getDa/" in url:
                use_cache = False                       # availability must be today's answer
            elif period and period in self.refresh and cache.name not in self._fresh_done:
                use_cache = False                       # a partner re-released this month
            hit = use_cache and cache.exists()
            if hit:
                self.cache_hits += 1
            elif self.max_calls is not None and self.run_calls >= self.max_calls:
                raise QuotaExhausted(f"--max-calls {self.max_calls} reached for this run; "
                                     "everything fetched so far is cached, tomorrow's run continues.")
            before = self._calls_today
            out = super().get(url, params, use_cache=use_cache)
            self.run_calls += self._calls_today - before
            if not use_cache:
                self._fresh_done.add(cache.name)
            return out

    return TrackerClient(cfg)


# --------------------------------------------------------------------------- #
# Pulls
# --------------------------------------------------------------------------- #
def _getda(client, reporters: list[int], freq: str, periods: list[str] | None, idx: "AvailIndex") -> set[int]:
    """One getDa call for a list of reporters; falls back to one call per reporter on a 400.
    Returns the reporters that appeared in the answer. Raises TruncatedResponse at the record cap."""
    from comtrade_mirror.client import BadRequest, TruncatedResponse
    period = ",".join(periods) if periods else None
    got: set[int] = set()

    def take(rows):
        for r in rows:
            r = dict(r); r.setdefault("freqCode", freq); idx.add(r)
            try:
                got.add(int(r.get("reporterCode")))
            except (TypeError, ValueError):
                pass
        return rows

    try:
        rows = take(client.get_availability(reporter_code=",".join(str(c) for c in reporters), freq_code=freq, period=period))
        if len(rows) >= client.cfg.max_records:
            raise TruncatedResponse(f"getDa {freq} returned {len(rows)} rows, at the {client.cfg.max_records} cap")
    except BadRequest as exc:
        log.warning("batched getDa %s rejected (%s); asking reporter by reporter", freq, str(exc).splitlines()[0])
        for c in reporters:
            rows = take(client.get_availability(reporter_code=c, freq_code=freq, period=period))
            if len(rows) >= client.cfg.max_records:
                raise TruncatedResponse(f"getDa {freq} reporter {c} returned {len(rows)} rows, at the cap")
    return got


def fetch_availability(client, codes: list[int], today: dt.date | None = None) -> AvailIndex:
    """getDa for Kiribati and every panel reporter, monthly and annual, from 2010 / 2017-01 on.

    One batched call per frequency (all reporters, period list). If the answer is at the record cap
    (possible on the free tier, 500 rows) it is re-asked in 12-period chunks. Never served from the
    disk cache, so the "percent complete" charts always show today's answer."""
    from comtrade_mirror.client import TruncatedResponse
    today = today or utc_now().date()
    idx = AvailIndex()
    want = [SUBJECT] + [c for c in codes if c != SUBJECT]
    last = month_add(f"{today.year}-{today.month:02d}", 0)
    spans = {"M": [pstr(m) for m in month_range(HIST_START, last)],
             "A": [str(y) for y in range(ANNUAL_START, today.year + 1)]}
    for freq, periods in spans.items():
        try:
            _getda(client, want, freq, periods, idx)
        except TruncatedResponse as exc:
            log.info("%s; re-asking in 12-period chunks", str(exc).splitlines()[0])
            idx = AvailIndex([r for r in idx.rows if str(r.get("freqCode", "")).upper() != freq])
            for i in range(0, len(periods), 12):
                _getda(client, want, freq, periods[i:i + 12], idx)
        for code in want:
            log.info("getDa %s %s: %d datasets, latest %s", code, freq, len(idx.periods(code, freq)),
                     (idx.periods(code, freq) or ["-"])[-1])
    return idx


def _by_prefix_annual(client, cfg, *, reporter, year: str, flow: str, prefixes: list[str]) -> list[dict]:
    """HS-chapter wildcard split for an annual slice (extract._fetch_by_prefix is monthly only)."""
    from comtrade_mirror.client import TruncatedResponse
    cmd = ",".join(p + "?" * (6 - len(p)) for p in prefixes)
    try:
        return client.get_data(reporter_code=reporter, partner_code=cfg.code, period=year,
                               flow_code=flow, cmd_code=cmd, freq_code="A")
    except TruncatedResponse:
        if len(prefixes) > 1:
            mid = len(prefixes) // 2
            return (_by_prefix_annual(client, cfg, reporter=reporter, year=year, flow=flow, prefixes=prefixes[:mid])
                    + _by_prefix_annual(client, cfg, reporter=reporter, year=year, flow=flow, prefixes=prefixes[mid:]))
        if len(prefixes[0]) >= 6:
            raise
        return _by_prefix_annual(client, cfg, reporter=reporter, year=year, flow=flow,
                                 prefixes=[prefixes[0] + str(d) for d in range(10)])


def pull_annual_all_goods(client, cfg, year: int, flow: str) -> list[dict]:
    """reporter = all, partner = Kiribati, HS6, one year, one flow; splits by reporter then HS chapter."""
    from comtrade_mirror import extract, fish
    from comtrade_mirror.client import TruncatedResponse
    y = str(year)
    try:
        return client.get_data(reporter_code=None, partner_code=cfg.code, period=y, flow_code=flow, freq_code="A")
    except TruncatedResponse:
        log.info("annual %s %s over the cap; splitting by reporter", y, flow)
    rows: list[dict] = []
    for rc in fish._counterparts_annual(client, cfg, y, flow):
        try:
            rows += client.get_data(reporter_code=rc, partner_code=cfg.code, period=y, flow_code=flow, freq_code="A")
        except TruncatedResponse:
            rows += _by_prefix_annual(client, cfg, reporter=rc, year=y, flow=flow, prefixes=extract.HS_CHAPTERS)
    return rows


@dataclass
class PullResult:
    mirror: pd.DataFrame = field(default_factory=pd.DataFrame)
    mirror_months: list[str] = field(default_factory=list)
    self_: pd.DataFrame = field(default_factory=pd.DataFrame)
    self_months: list[str] = field(default_factory=list)
    fish_annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    fish_years: list[int] = field(default_factory=list)
    annual: pd.DataFrame = field(default_factory=pd.DataFrame)
    annual_years: list[int] = field(default_factory=list)
    partial: bool = False
    stopped_reason: str | None = None


def execute(plan: Plan, client, cfg) -> PullResult:
    from comtrade_mirror import extract, fish
    from comtrade_mirror.client import QuotaExhausted
    res = PullResult()

    def stop(exc, step):
        log.warning("%s: stopping (%s)", step, str(exc).splitlines()[0])
        res.partial = True
        res.stopped_reason = f"{step}: {str(exc).splitlines()[0]}"

    frames = []
    for p in plan.mirror:
        try:
            df = extract.pull_mirror(client, cfg, [p])
        except QuotaExhausted as exc:
            stop(exc, f"mirror {ym_dash(p)}"); break
        frames.append(df); res.mirror_months.append(p)
        log.info("mirror %s: %d rows (run calls %d, cache hits %d)", ym_dash(p), len(df), client.run_calls, client.cache_hits)
    frames = [f for f in frames if len(f)]
    res.mirror = _nonzero(extract.dedupe_raw(pd.concat(frames, ignore_index=True)), "mirror") if frames else pd.DataFrame()

    frames = []
    for p in plan.self_months:
        if res.partial:
            break
        try:
            df = extract.pull_self(client, cfg, [p])
        except QuotaExhausted as exc:
            stop(exc, f"self {ym_dash(p)}"); break
        frames.append(df); res.self_months.append(p)
        log.info("Kiribati %s: %d rows (run calls %d)", ym_dash(p), len(df), client.run_calls)
    frames = [f for f in frames if len(f)]
    res.self_ = _nonzero(extract.dedupe_raw(pd.concat(frames, ignore_index=True)), "self") if frames else pd.DataFrame()

    rows_all = []
    for y in plan.fish_years:
        if res.partial:
            break
        try:
            rows = fish._pull_period(client, cfg, period=str(y), freq="A", flow="M")
        except QuotaExhausted as exc:
            stop(exc, f"fish annual {y}"); break
        for r in rows:
            r["side"] = "mirror"
        rows_all += rows; res.fish_years.append(y)
        log.info("fish annual %s: %d rows (run calls %d)", y, len(rows), client.run_calls)
    res.fish_annual = fish._frame(rows_all, "A") if rows_all else pd.DataFrame()

    frames = []
    for y in plan.annual_years:
        if res.partial:
            break
        try:
            rows = pull_annual_all_goods(client, cfg, y, "M") + pull_annual_all_goods(client, cfg, y, "X")
        except QuotaExhausted as exc:
            stop(exc, f"annual all-goods {y}"); break
        frames.append(extract._frame(rows, "mirror")); res.annual_years.append(y)
        log.info("annual all-goods %s: %d rows (run calls %d)", y, len(rows), client.run_calls)
    frames = [f for f in frames if len(f)]
    res.annual = _nonzero(extract.dedupe_raw(pd.concat(frames, ignore_index=True)), "annual") if frames else pd.DataFrame()
    return res


def _nonzero(df: pd.DataFrame, what: str) -> pd.DataFrame:
    """Rows published with a zero or missing value carry no amount; they are dropped from a pull so the
    pipeline's 'no silent zeros' gate keeps meaning 'absent = not reported'. The count is logged."""
    if not len(df) or "primaryValue" not in df.columns:
        return df
    v = pd.to_numeric(df["primaryValue"], errors="coerce")
    n = int((v.isna() | (v == 0)).sum())
    if n:
        log.info("%s pull: %d rows with zero or missing value dropped", what, n)
    return df[v.notna() & (v != 0)].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Merging with the committed history
# --------------------------------------------------------------------------- #
def align_to(new: pd.DataFrame, old: pd.DataFrame) -> pd.DataFrame:
    """Give `new` the columns and (where possible) the dtypes of `old`."""
    new = new.copy()
    for c in old.columns:
        if c not in new.columns:
            new[c] = None
        od = old[c].dtype
        try:
            if pd.api.types.is_bool_dtype(od):
                new[c] = new[c].map(lambda v: bool(v) if isinstance(v, (bool, int)) or (isinstance(v, float) and v == v) else False).astype(bool)
            elif pd.api.types.is_integer_dtype(od):
                v = pd.to_numeric(new[c], errors="coerce")
                new[c] = v.astype("int64") if v.notna().all() else v.astype("Int64")
            elif pd.api.types.is_float_dtype(od):
                new[c] = pd.to_numeric(new[c], errors="coerce").astype("float64")
            else:
                new[c] = new[c].map(lambda v: None if v is None or (isinstance(v, float) and v != v) else str(v)).astype(object)
        except (TypeError, ValueError):
            pass
    extra = [c for c in new.columns if c not in old.columns]
    return new[list(old.columns) + extra]


def _sort_raw(df: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in ("side", "period", "flowCode", "reporterCode", "partnerCode", "cmdCode") if k in df.columns]
    return df.sort_values(keys, kind="mergesort").reset_index(drop=True)


def merge_raw(old: pd.DataFrame, pulls: PullResult, changed_reporters: dict, today_iso: str) -> tuple[pd.DataFrame, dict]:
    """Newer pull wins for the same reporter-period-flow; nothing else is touched."""
    from comtrade_mirror import extract
    old = old.copy()
    old["period"] = old["period"].map(pstr)
    drop = pd.Series(False, index=old.index)
    is_mirror = old["side"].astype(str) == "mirror"
    old_rep = pd.to_numeric(old["reporterCode"], errors="coerce").fillna(-1).astype(int)
    new_frames = []
    if len(pulls.mirror):
        nm = pulls.mirror.copy(); nm["period"] = nm["period"].map(pstr)
        present = set(zip(nm["period"], nm["flowCode"].astype(str), pd.to_numeric(nm["reporterCode"]).astype(int)))
        keys = list(zip(old["period"], old["flowCode"].astype(str), old_rep))
        drop |= is_mirror & pd.Series([k in present for k in keys], index=old.index)
        new_frames.append(nm)
    for p in pulls.mirror_months:                       # re-released and now absent -> withdrawn
        ch = changed_reporters.get(p, set())
        if ch:
            drop |= is_mirror & (old["period"] == p) & old_rep.isin(list(ch))
    if pulls.self_months:
        drop |= (~is_mirror) & old["period"].isin(pulls.self_months)
    if len(pulls.self_):
        ns = pulls.self_.copy(); ns["period"] = ns["period"].map(pstr)
        new_frames.append(ns)
    kept = old[~drop]
    stats = {"old_rows": int(len(old)), "replaced_rows": int(drop.sum()), "new_rows": 0}
    if new_frames:
        new = pd.concat(new_frames, ignore_index=True)
        new["pulled_at"] = today_iso
        if "pulled_at" not in kept.columns:
            kept = kept.assign(pulled_at=None)
        new = align_to(new, kept)
        merged = pd.concat([new, kept], ignore_index=True)
        stats["new_rows"] = int(len(new))
    else:
        merged = kept
    merged = extract.dedupe_raw(merged) if len(merged) else merged
    merged = _sort_raw(merged)
    stats["merged_rows"] = int(len(merged))
    return merged, stats


def merge_fish_detail(old: pd.DataFrame, pulls: PullResult, changed_reporters: dict) -> tuple[pd.DataFrame, dict]:
    """Monthly fish detail is a subset of the all-goods mirror pull (verified identical to the owner's
    fish-only pull for every overlapping month), so it is refreshed from the same rows."""
    from comtrade_mirror import fish
    old = old.copy()
    old["period"] = old["period"].map(pstr)
    stats = {"old_rows": int(len(old)), "replaced_rows": 0, "new_rows": 0}
    if not len(pulls.mirror):
        stats["merged_rows"] = int(len(old))
        return old.sort_values(["period", "reporterCode", "cmdCode"], kind="mergesort").reset_index(drop=True), stats
    nm = pulls.mirror
    nm_m = nm[nm["flowCode"].astype(str) == "M"].copy()
    nm_m["period"] = nm_m["period"].map(pstr)
    cmd = nm_m["cmdCode"].astype(str).str.zfill(6)
    derived = fish._frame(nm_m[cmd.str.startswith(FISH_PREFIXES)].to_dict("records"), "M")
    present = set(zip(nm_m["period"], pd.to_numeric(nm_m["reporterCode"]).astype(int)))
    for p in pulls.mirror_months:
        present |= {(p, c) for c in changed_reporters.get(p, set())}
    keys = list(zip(old["period"], pd.to_numeric(old["reporterCode"], errors="coerce").fillna(-1).astype(int)))
    drop = pd.Series([k in present for k in keys], index=old.index)
    kept = old[~drop]
    stats["replaced_rows"] = int(drop.sum())
    if len(derived):
        derived = derived[[c for c in old.columns if c in derived.columns]]
        merged = pd.concat([derived, kept], ignore_index=True)
        stats["new_rows"] = int(len(derived))
    else:
        merged = kept
    merged = merged.sort_values(["period", "reporterCode", "cmdCode"], kind="mergesort").reset_index(drop=True)
    stats["merged_rows"] = int(len(merged))
    return merged, stats


def fish_monthly_summary(detail: pd.DataFrame) -> pd.DataFrame:
    """Same arithmetic as comtrade_mirror/fish.py (fish_mirror_monthly.csv)."""
    d = detail.copy()
    d["is_tuna"] = d["is_tuna"].astype(bool)
    bym = (d.groupby(["period", "is_tuna"])["value_usd_m"].sum()
           .unstack(fill_value=0).rename(columns={True: "tuna", False: "other_fish"}))
    for c in ("tuna", "other_fish"):
        if c not in bym:
            bym[c] = 0.0
    bym["all_fish"] = bym["tuna"] + bym["other_fish"]
    bym["n_reporters"] = d.groupby("period")["reporterCode"].nunique()
    return bym.reset_index()[["period", "other_fish", "tuna", "all_fish", "n_reporters"]]


def fish_annual_tables(detail: pd.DataFrame, old_annual: pd.DataFrame | None,
                       old_by_rep: pd.DataFrame | None, old_detail: pd.DataFrame | None,
                       years: list[int]):
    """Replace the pulled years in fish_mirror_annual.csv / _by_reporter.csv / _detail.csv; keep the rest."""
    d = detail.copy()
    d["year"] = d["year"].astype(int)
    d = d[d["year"].isin(years)]
    # annual by year
    by_year = (d.groupby(["year", "is_tuna"])["value_usd_m"].sum()
               .unstack(fill_value=0).rename(columns={True: "tuna", False: "other_fish"}))
    for c in ("tuna", "other_fish"):
        if c not in by_year:
            by_year[c] = 0.0
    by_year["all_fish"] = by_year["tuna"] + by_year["other_fish"]
    by_year["n_reporters"] = d.groupby("year")["reporterCode"].nunique()
    by_year = by_year.reset_index()[["year", "other_fish", "tuna", "all_fish", "n_reporters"]]
    if old_annual is not None and len(old_annual):
        oa = old_annual[~old_annual["year"].astype(int).isin(years)]
        by_year = pd.concat([oa, by_year], ignore_index=True)
    by_year = by_year.sort_values("year").reset_index(drop=True)
    # by reporter (wide: reporterDesc x year)
    if old_by_rep is not None and len(old_by_rep):
        rep = old_by_rep.set_index(old_by_rep.columns[0]).copy()
        rep.index.name = "reporterDesc"
    else:
        rep = pd.DataFrame(index=pd.Index([], name="reporterDesc"))
    for y in years:
        col = d[d["year"] == y].groupby("reporterDesc")["value_usd_m"].sum()
        rep = rep.reindex(rep.index.union(col.index))
        rep[str(y)] = col.reindex(rep.index).fillna(0.0)
    rep = rep.fillna(0.0)
    rep = rep[sorted(rep.columns, key=lambda c: int(str(c)[:4]))]
    rep = rep.sort_index()
    # detail
    if old_detail is not None and len(old_detail):
        od = old_detail[~old_detail["year"].astype(int).isin(years)]
        det = pd.concat([od, d[[c for c in od.columns if c in d.columns]]], ignore_index=True)
    else:
        det = d
    det = det.sort_values(["year", "reporterCode", "cmdCode"], kind="mergesort").reset_index(drop=True)
    return by_year, rep.reset_index(), det


def annual_summary(annual_raw: pd.DataFrame) -> pd.DataFrame:
    d = annual_raw.copy()
    d["year"] = d["period"].map(pstr).str[:4].astype(int)
    d["hs2"] = d["cmdCode"].astype(str).str.zfill(6).str[:2]
    d["value_usd_m"] = pd.to_numeric(d["primaryValue"], errors="coerce") / 1e6
    d["ex_ships"] = d["value_usd_m"].where(~d["hs2"].isin(SHIPS_HS2), 0.0)
    g = (d.groupby(["year", "flowCode", "reporterCode", "reporterDesc"], dropna=False)
         .agg(value_usd_m=("value_usd_m", "sum"), value_ex_ships_aircraft_usd_m=("ex_ships", "sum"),
              n_hs6=("cmdCode", "nunique")).reset_index())
    g["direction"] = g["flowCode"].map({"M": "export", "X": "import"})
    g["note"] = g["direction"].map({"export": "partner's imports from Kiribati = Kiribati exports",
                                    "import": "partner's exports to Kiribati = Kiribati imports (lower bound)"})
    return g.sort_values(["year", "direction", "value_usd_m"], ascending=[True, True, False]).reset_index(drop=True)


def availability_csv(old: pd.DataFrame | None, avail: AvailIndex | None) -> pd.DataFrame | None:
    """Refresh tracker/data/availability_kiribati.csv (period,year,month,classification,totalRecords)."""
    if avail is None:
        return old
    rows = []
    for (c, f, p), rec in avail.idx.items():
        if c == SUBJECT and f == "M" and p >= pstr(HIST_START):
            rows.append({"period": p, "year": int(p[:4]), "month": int(p[4:6]),
                         "classification": rec.get("classification"), "totalRecords": rec.get("totalRecords")})
    new = pd.DataFrame(rows)
    if old is not None and len(old):
        old = old.copy(); old["period"] = old["period"].map(pstr)
        old = old[~old["period"].isin(set(new["period"]))] if len(new) else old
        new = pd.concat([old, new], ignore_index=True)
    return new.sort_values("period").reset_index(drop=True) if len(new) else old


# --------------------------------------------------------------------------- #
# Build + validate + promote
# --------------------------------------------------------------------------- #
def _read_csv(p: Path, **kw) -> pd.DataFrame | None:
    return pd.read_csv(p, **kw) if p.exists() else None


def validate_outputs(stage: dict, merged_raw: pd.DataFrame, old_raw: pd.DataFrame, fish_old: pd.DataFrame,
                     fish_new: pd.DataFrame, old_manifest: dict | None, live: bool, today: dt.date, cfg) -> list[str]:
    """Return a list of failure messages (empty = pass)."""
    from comtrade_mirror import aggregate, diagnostics, mirror, pipeline
    fails: list[str] = []
    # 1. the pipeline's seven section-J checks on the merged raw observations
    try:
        norm = mirror.normalise(merged_raw, cfg)
        metrics = diagnostics.add_metrics(mirror.build_pairs(norm))
        qt = aggregate._agg(aggregate.add_sector(metrics), ["quarter", "direction"])
        checks = pipeline.validate(cfg, merged_raw, metrics, {"quarterly_total": qt})
        for k, v in checks.items():
            if not k.startswith("_") and not v["ok"]:
                fails.append(f"pipeline check failed: {k}: {json.dumps(v['detail'], default=str)[:300]}")
        stage["validation"] = checks
    except Exception as exc:  # noqa: BLE001
        fails.append(f"pipeline validation raised: {exc!r}")
    # 2. history preserved
    old_slices = set(zip(old_raw["side"].astype(str), old_raw["period"].map(pstr)))
    new_slices = set(zip(merged_raw["side"].astype(str), merged_raw["period"].map(pstr)))
    lost = sorted(old_slices - new_slices)
    if lost:
        fails.append(f"history lost: {len(lost)} side-month slices disappeared, e.g. {lost[:5]}")
    if len(merged_raw) < 0.9 * len(old_raw):
        fails.append(f"merged raw has {len(merged_raw)} rows, less than 90% of the {len(old_raw)} committed rows")
    if len(fish_old):
        lost_f = sorted(set(fish_old["period"].map(pstr)) - set(fish_new["period"].map(pstr)))
        if lost_f:
            fails.append(f"fish detail lost months: {lost_f[:5]}")
    # 3. JSON contract
    j = stage["json"]
    for name in ("coverage", "series", "manifest"):
        if name not in j:
            fails.append(f"{name}.json not produced")
    cov, ser, man = j.get("coverage"), j.get("series"), j.get("manifest")
    if cov:
        for tbl in ("monthly", "quarterly", "annual"):
            rows = cov.get(tbl, [])
            per = [r["period"] for r in rows]
            if per != sorted(per) or len(set(per)) != len(per):
                fails.append(f"coverage.{tbl} periods not ascending/unique")
            for r in rows:
                for k in ("share_count", "share_w_exports", "share_w_imports"):
                    v = r.get(k)
                    if v is not None and not (-1e-6 <= v <= 1 + 0.005):   # weights are rounded to 3 dp
                        fails.append(f"coverage.{tbl} {r['period']} {k}={v} outside [0,1]"); break
                if r.get("n_published", 0) > r.get("n_panel", 0):
                    fails.append(f"coverage.{tbl} {r['period']} n_published > n_panel")
        if live and cov.get("meta", {}).get("method") != "comtrade_getDa":
            fails.append("live run but coverage method is not comtrade_getDa")
    if ser:
        per = [r["period"] for r in ser.get("monthly", [])]
        if per != sorted(per) or len(set(per)) != len(per):
            fails.append("series.monthly periods not ascending/unique")
        bad = [k for k in ser.get("keys", {}) if "balance" in k.lower()]
        if bad:
            fails.append(f"series carries a trade-balance key (never shown): {bad}")
    if man:
        g = man.get("meta", {}).get("generated_at", "")
        if not g.startswith(today.isoformat()):
            fails.append(f"manifest.generated_at {g!r} is not today ({today})")
        if man.get("last_update_mode") not in ("live_comtrade", "offline_rebuild"):
            fails.append(f"manifest.last_update_mode invalid: {man.get('last_update_mode')}")
        if old_manifest:
            o = (old_manifest.get("data_through") or {}).get("monthly")
            n = (man.get("data_through") or {}).get("monthly")
            if o and n and n < o:
                fails.append(f"data_through.monthly went backwards: {o} -> {n}")
    return fails


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def prune_cache(cache_dir: Path, keep_days: int = 7) -> int:
    """Remove old quota_YYYY-MM-DD.json counters (the data cache itself is kept)."""
    n = 0
    cutoff = dt.date.today() - dt.timedelta(days=keep_days)
    for p in cache_dir.glob("quota_*.json"):
        try:
            d = dt.date.fromisoformat(p.stem.split("_", 1)[1])
        except ValueError:
            continue
        if d < cutoff:
            p.unlink(missing_ok=True); n += 1
    return n


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def build_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="no API calls; rebuild the JSON from the committed files")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the call budget; write nothing")
    ap.add_argument("--data-dir", default=os.environ.get("TRACKER_DATA_DIR") or str(DEFAULT_DATA_DIR),
                    help="tracker data root (raw/, out/, cache/, state.json); default tracker/data or $TRACKER_DATA_DIR")
    ap.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="where the site JSON goes (default site/data)")
    ap.add_argument("--panel", default=str(HERE / "panel.json"))
    ap.add_argument("--state", default=None, help="state file (default <data-dir>/state.json)")
    ap.add_argument("--report", default=None, help="run report (default <data-dir>/run_report.json)")
    ap.add_argument("--window-months", type=int, default=WINDOW_MONTHS)
    ap.add_argument("--annual-years", type=int, default=ANNUAL_YEARS)
    ap.add_argument("--window-only", action="store_true", help="ignore re-releases of months older than the window")
    ap.add_argument("--backfill", type=int, default=4,
                    help="per run, also pull up to N months older than the window that have partner datasets but no "
                         "partner rows in the history (the months Kiribati never reported); 0 disables")
    ap.add_argument("--annual-all-goods", choices=["auto", "yes", "no"], default="auto",
                    help="annual all-goods mirror pull (auto = premium tier only)")
    ap.add_argument("--max-calls", type=int, default=None, help="cap on API calls this run (default 450 free / 2500 premium)")
    ap.add_argument("--rebuild-panel", action="store_true", help="recompute panel.json with build_panel()")
    ap.add_argument("--skip-products", action="store_true", help="do not run Agent E's build_products.py")
    ap.add_argument("--today", default=None, help="override today's date (YYYY-MM-DD), for tests")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def run_update(args: argparse.Namespace, session=None) -> int:
    t0 = time.time()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    data_dir = Path(args.data_dir).resolve()
    out_dir = Path(args.out).resolve()
    state_path = Path(args.state) if args.state else data_dir / "state.json"
    report_path = Path(args.report) if args.report else data_dir / "run_report.json"
    today = dt.date.fromisoformat(args.today) if args.today else utc_now().date()
    now = utc_now()
    live = not args.offline
    os.environ["TRACKER_DATA_DIR"] = str(data_dir)
    sys.path.insert(0, str(HERE))

    report: dict = {"started_at": iso(now), "today": today.isoformat(), "mode": "live_comtrade" if live else "offline_rebuild",
                    "dry_run": bool(args.dry_run), "status": "running", "steps": {}, "failures": []}

    def finish(rc: int, status: str) -> int:
        report["status"] = status
        report["finished_at"] = iso(utc_now())
        report["seconds"] = round(time.time() - t0, 1)
        report["exit_code"] = rc
        if not args.dry_run:
            try:
                _write_json(report_path, report)
            except OSError as exc:
                log.warning("could not write run report: %s", exc)
        log.info("done: %s (exit %d, %.1fs)", status, rc, time.time() - t0)
        return rc

    # -- imports (owner's package, Agent A, Agent E) --------------------------------------
    try:
        from comtrade_mirror import extract  # noqa: F401
        from comtrade_mirror.config import Config
    except Exception as exc:  # noqa: BLE001
        log.error("cannot import the vendored comtrade_mirror package: %s", exc)
        return finish(3, "setup_error")
    try:
        import build_site_data as bsd
    except Exception as exc:  # noqa: BLE001
        log.error("tracker/build_site_data.py (Agent A) is missing or broken: %s", exc)
        return finish(3, "setup_error")
    try:
        import build_products as bp
    except Exception as exc:  # noqa: BLE001
        bp = None
        log.warning("tracker/build_products.py (Agent E) not importable: %s - national_accounts/peers/products.json "
                    "will not be refreshed", exc)

    cfg = Config(country=COUNTRY, years=tuple(range(today.year - 2, today.year + 1)))
    tier = cfg.tier
    if live and not cfg.subscription_key:
        log.error("live mode needs COMTRADE_API_KEY in the environment (GitHub secret). "
                  "Use --offline to rebuild from the committed files without a key.")
        return finish(3, "setup_error")
    max_calls = args.max_calls if args.max_calls is not None else (2500 if tier == "premium" else 450)
    report["tier"] = tier
    report["data_dir"] = str(data_dir)

    # -- committed inputs ---------------------------------------------------------------
    raw_path = data_dir / "raw" / COUNTRY / "raw_observations.parquet"
    fish_dir = data_dir / "out" / COUNTRY / "fish"
    if not raw_path.exists():
        log.error("committed history missing: %s", raw_path)
        return finish(3, "setup_error")
    raw_old = pd.read_parquet(raw_path)
    raw_old["period"] = raw_old["period"].map(pstr)
    fish_old = _read_csv(fish_dir / "fish_mirror_monthly_detail.csv", dtype={"cmdCode": str, "period": str})
    if fish_old is None:
        fish_old = pd.DataFrame(columns=["side", "period", "reporterCode", "reporterDesc", "partnerCode", "partnerDesc",
                                         "cmdCode", "cmdDesc", "primaryValue", "netWgt", "qty", "qtyUnitAbbr",
                                         "freq", "year", "is_tuna", "value_usd_m"])
    fish_annual_old = _read_csv(fish_dir / "fish_mirror_annual.csv")
    fish_by_rep_old = _read_csv(fish_dir / "fish_mirror_annual_by_reporter.csv")
    fish_annual_det_old = _read_csv(fish_dir / "fish_mirror_annual_detail.csv", dtype={"cmdCode": str, "period": str})
    avail_csv_old = _read_csv(data_dir / "availability_kiribati.csv", dtype={"period": str})
    annual_raw_path = data_dir / "raw" / COUNTRY / "raw_annual_observations.parquet"
    annual_old = pd.read_parquet(annual_raw_path) if annual_raw_path.exists() else pd.DataFrame()
    old_manifest = None
    if (out_dir / "manifest.json").exists():
        try:
            old_manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        except ValueError:
            old_manifest = None

    panel, panel_is_stub = load_panel(Path(args.panel))
    codes = panel_codes(panel)
    state = State(state_path)
    log.info("panel: %d partners%s; history: %d raw rows, %d months; fish detail %d rows",
             len(codes), " (STUB)" if panel_is_stub else "", len(raw_old), raw_old["period"].nunique(), len(fish_old))

    # -- step 2: availability -------------------------------------------------------------
    avail: AvailIndex | None = None
    client = None
    raw_self_months = set(raw_old.loc[raw_old["side"].astype(str) == "self", "period"])
    if live:
        try:
            client = make_client(cfg, refresh_periods=(), max_calls=max_calls, session=session)
            avail = fetch_availability(client, codes, today)
        except Exception as exc:  # noqa: BLE001
            log.error("availability (getDa) failed: %s", exc)
            report["failures"].append(f"getDa: {exc}")
            return finish(4, "error")
        report["steps"]["availability"] = {"datasets": len(avail.rows), "calls": client.run_calls,
                                           "kiribati_latest_month": (avail.periods(SUBJECT, "M") or [None])[-1]}

    # -- plan ------------------------------------------------------------------------------
    raw_mirror_months = set(raw_old.loc[raw_old["side"].astype(str) == "mirror", "period"])
    plan = make_plan(avail, state, codes, raw_self_months, today, args, tier, raw_mirror_months)
    print(describe_plan(plan, tier, offline=not live))
    report["plan"] = {"window": [ym_dash(p) for p in plan.window], "mirror": [ym_dash(p) for p in plan.mirror],
                      "mirror_reason": {ym_dash(k): v for k, v in plan.mirror_reason.items()},
                      "self": [ym_dash(p) for p in plan.self_months], "fish_years": plan.fish_years,
                      "annual_years": plan.annual_years, "estimated_calls": plan.est}
    if args.dry_run:
        return finish(0, "dry_run")

    # -- step 3: pulls -------------------------------------------------------------------------
    pulls = PullResult()
    if live:
        # Slices that must come from the API, not the disk cache: anything a panel partner
        # re-released, and anything never pulled by a successful run (a cached answer from an
        # earlier day could predate the publication). Backfill months and first-time annual
        # pulls may use the cache.
        client.refresh = ({p for p in plan.mirror if "backfill" not in plan.mirror_reason[p]}
                          | set(plan.self_months)
                          | {str(y) for y in plan.fish_years if state.pulled(f"fish:A:{y}")}
                          | {str(y) for y in plan.annual_years if state.pulled(f"annual:A:{y}")})
        try:
            pulls = execute(plan, client, cfg)
        except Exception as exc:  # noqa: BLE001
            log.error("pull failed: %s\n%s", exc, traceback.format_exc())
            report["failures"].append(f"pull: {exc}")
            return finish(4, "error")
        report["steps"]["pulls"] = {"api_calls": client.run_calls, "cache_hits": client.cache_hits,
                                    "calls_remaining_today": client.calls_remaining,
                                    "mirror_months": [ym_dash(p) for p in pulls.mirror_months],
                                    "mirror_rows": int(len(pulls.mirror)),
                                    "self_months": [ym_dash(p) for p in pulls.self_months], "self_rows": int(len(pulls.self_)),
                                    "fish_years": pulls.fish_years, "fish_annual_rows": int(len(pulls.fish_annual)),
                                    "annual_years": pulls.annual_years, "annual_rows": int(len(pulls.annual)),
                                    "partial": pulls.partial, "stopped_reason": pulls.stopped_reason}

    # -- step 4: merge --------------------------------------------------------------------------
    today_iso = today.isoformat()
    merged_raw, raw_stats = merge_raw(raw_old, pulls, plan.changed_reporters, today_iso)
    fish_new, fish_stats = merge_fish_detail(fish_old, pulls, plan.changed_reporters)
    report["steps"]["merge"] = {"raw": raw_stats, "fish_detail": fish_stats}
    fish_annual_new, fish_by_rep_new, fish_annual_det_new = fish_annual_old, fish_by_rep_old, fish_annual_det_old
    if len(pulls.fish_annual):
        fish_annual_new, fish_by_rep_new, fish_annual_det_new = fish_annual_tables(
            pulls.fish_annual, fish_annual_old, fish_by_rep_old, fish_annual_det_old, pulls.fish_years)
    annual_new = annual_old
    if len(pulls.annual):
        a_old = annual_old.copy()
        if len(a_old):
            a_old["period"] = a_old["period"].map(pstr)
            a_old = a_old[~a_old["period"].isin({str(y) for y in pulls.annual_years})]
            annual_new = pd.concat([align_to(pulls.annual.assign(pulled_at=today_iso), a_old.assign(pulled_at=a_old.get("pulled_at"))), a_old], ignore_index=True)
        else:
            annual_new = pulls.annual.assign(pulled_at=today_iso)
        annual_new = _sort_raw(annual_new)
    avail_csv_new = availability_csv(avail_csv_old, avail)

    # -- step 5: build with Agent A (+ E) ----------------------------------------------------------
    stage_root = Path(tempfile.mkdtemp(prefix="kir_update_stage_"))
    stage_data = stage_root / "data"
    stage_out = stage_root / "site_data"
    try:
        raw_c = bsd.clean_raw(merged_raw)
        fish_c = bsd.clean_fish_detail(fish_new)
        kir = set(bsd.kiribati_months_from(raw_c, avail_csv_new))
        if avail is not None:
            kir |= {ym_dash(p) for p in avail.periods(SUBJECT, "M") if p >= pstr(HIST_START)}
        kir = sorted(kir)
        if args.rebuild_panel or panel_is_stub:
            try:
                panel = bsd.build_panel(raw_c)
                codes = panel_codes(panel)
                log.info("panel rebuilt with build_panel(): %d members", len(codes))
            except Exception as exc:  # noqa: BLE001
                log.warning("build_panel failed (%s); keeping the loaded panel", exc)
        last_month = max([raw_c["period"].max(), fish_c["period"].max() if len(fish_c) else raw_c["period"].max()]
                         + ([ym_dash(p) for p in (avail.all_periods(codes, "M") | set(avail.periods(SUBJECT, "M"))) if p >= pstr(HIST_START)] if avail else []))
        last_month = min(last_month, ym_dash(plan.window[0]))      # never beyond the last elapsed month
        months = month_range(HIST_START, last_month)
        years = list(range(ANNUAL_START, int(last_month[:4]) + 1))
        if avail is not None:
            coverage = bsd.coverage_from_availability(avail.panel_rows(codes), panel, kir, months=months, years=years)
            mode = "live_comtrade"
        else:
            ships = None
            for cand in (HERE / "data" / "static_e" / "data" / "out" / COUNTRY / "ships_hs6_annual_2.csv",
                         data_dir / "out" / COUNTRY / "ships_hs6_annual_2.csv"):
                if cand.exists():
                    ships = pd.read_csv(cand); break
            coverage = bsd.coverage_from_data(raw_c, panel, fish_c, kir, months=months, years=years,
                                              fish_annual_by_reporter=fish_by_rep_new, ships_annual=ships)
            mode = "offline_rebuild"
        series = bsd.series_from_data(raw_c, fish_c, coverage, kir, fish_annual=fish_annual_new,
                                      fish_annual_by_reporter=fish_by_rep_new)
        files_info = {"raw": {"path": str(raw_path), "rows": int(len(merged_raw))},
                      "fish_detail": {"path": str(fish_dir / "fish_mirror_monthly_detail.csv"), "rows": int(len(fish_new))}}
        extra = ([f"Live refresh from the UN Comtrade API on {today_iso} (GitHub Actions, tier {tier}). "
                  f"API calls this run: {client.run_calls}; cache hits: {client.cache_hits}."] if live else
                 [f"Offline rebuild on {today_iso} from the committed tracker/data files (no API calls)."])
        if pulls.partial:
            extra.append(f"This run stopped early ({pulls.stopped_reason}); the next scheduled run continues from the cache.")
        manifest = bsd.build_manifest(panel, coverage, series, kir, last_update_mode=mode, as_of=today_iso,
                                      inputs_info=files_info, extra_notes=extra)
        manifest["last_update_mode"] = mode
        if live:
            manifest["meta"]["notes"] = [n for n in manifest["meta"]["notes"] if not n.startswith("Offline inputs were produced")]
        last_change = (old_manifest or {}).get("live_run", {}).get("last_data_change")
        data_changed = bool(raw_stats["new_rows"] or fish_stats["new_rows"] or len(pulls.fish_annual) or len(pulls.annual))
        manifest["live_run"] = {
            "mode": mode, "checked_at": iso(now), "today": today_iso, "tier": tier if live else None,
            "status": "partial" if pulls.partial else "complete",
            "api_calls": client.run_calls if live else 0, "cache_hits": client.cache_hits if live else 0,
            "months_refreshed": [ym_dash(p) for p in pulls.mirror_months],
            "kiribati_months_refreshed": [ym_dash(p) for p in pulls.self_months],
            "fish_annual_years_refreshed": pulls.fish_years, "annual_all_goods_years_refreshed": pulls.annual_years,
            "rows_added": raw_stats["new_rows"], "rows_replaced": raw_stats["replaced_rows"],
            "last_data_change": iso(now) if data_changed else last_change,
            "schedule": "daily at 06:17 UTC (.github/workflows/update.yml) and on manual dispatch",
            "coverage_method": coverage["meta"].get("method"),
            "panel_is_stub": panel_is_stub,
        }
        manifest["coverage_method"] = coverage["meta"].get("method")
        written = bsd.write_all(stage_out, manifest, coverage, series, panel, panel_path=stage_root / "panel.json")
        log.info("Agent A build: %s", [p.name for p in written])
        stage = {"json": {"coverage": coverage, "series": series, "manifest": manifest}}

        # staged data files (layout = tracker/data)
        (stage_data / "raw" / COUNTRY).mkdir(parents=True, exist_ok=True)
        (stage_data / "out" / COUNTRY / "fish").mkdir(parents=True, exist_ok=True)
        data_written: list[tuple[Path, Path]] = []        # (staged, destination)
        if live and data_changed:
            p = stage_data / "raw" / COUNTRY / "raw_observations.parquet"
            merged_raw.to_parquet(p, index=False, compression="zstd")
            data_written.append((p, raw_path))
            fd = stage_data / "out" / COUNTRY / "fish"
            fish_new.to_csv(fd / "fish_mirror_monthly_detail.csv", index=False)
            fish_monthly_summary(fish_new).to_csv(fd / "fish_mirror_monthly.csv", index=False)
            data_written += [(fd / "fish_mirror_monthly_detail.csv", fish_dir / "fish_mirror_monthly_detail.csv"),
                             (fd / "fish_mirror_monthly.csv", fish_dir / "fish_mirror_monthly.csv")]
            if len(pulls.fish_annual):
                fish_annual_new.to_csv(fd / "fish_mirror_annual.csv", index=False)
                fish_by_rep_new.to_csv(fd / "fish_mirror_annual_by_reporter.csv", index=False)
                fish_annual_det_new.to_csv(fd / "fish_mirror_annual_detail.csv", index=False)
                data_written += [(fd / "fish_mirror_annual.csv", fish_dir / "fish_mirror_annual.csv"),
                                 (fd / "fish_mirror_annual_by_reporter.csv", fish_dir / "fish_mirror_annual_by_reporter.csv"),
                                 (fd / "fish_mirror_annual_detail.csv", fish_dir / "fish_mirror_annual_detail.csv")]
            if len(pulls.annual):
                p = stage_data / "raw" / COUNTRY / "raw_annual_observations.parquet"
                annual_new.to_parquet(p, index=False, compression="zstd")
                s = stage_data / "out" / COUNTRY / "annual_mirror_by_reporter.csv"
                annual_summary(annual_new).to_csv(s, index=False)
                data_written += [(p, annual_raw_path), (s, data_dir / "out" / COUNTRY / "annual_mirror_by_reporter.csv")]
        if live and avail_csv_new is not None:
            p = stage_data / "availability_kiribati.csv"
            avail_csv_new.to_csv(p, index=False)
            data_written.append((p, data_dir / "availability_kiribati.csv"))
        # Agent E needs the merged data in pipeline layout: stage what changed, link the rest
        for src in (raw_path, fish_dir / "fish_mirror_monthly_detail.csv", fish_dir / "fish_mirror_annual.csv",
                    fish_dir / "fish_mirror_annual_by_reporter.csv"):
            dst = stage_data / src.relative_to(data_dir)
            if not dst.exists() and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

        # Agent E
        e_written = {}
        if bp is not None and not args.skip_products:
            try:
                e_written = bp.write_all(stage_out, inputs_root=None, pipeline_root=stage_root)
                for k, p in e_written.items():
                    stage["json"][k] = json.loads(Path(p).read_text(encoding="utf-8"))
                log.info("Agent E build: %s", sorted(e_written))
            except Exception as exc:  # noqa: BLE001
                log.warning("build_products.write_all failed (%s); keeping the previous national_accounts/peers/products.json", exc)
                report["failures"].append(f"build_products (non-fatal): {exc}")
                e_written = {}
        report["steps"]["build"] = {"agent_a": [p.name for p in written], "agent_e": sorted(e_written),
                                    "months": [months[0], months[-1]], "kiribati_months": len(kir),
                                    "coverage_method": coverage["meta"].get("method")}

        # -- step 6: validate ----------------------------------------------------------------------
        fails = validate_outputs(stage, merged_raw, raw_old, fish_old, fish_new, old_manifest, live, today, cfg)
        for name in ("national_accounts", "peers", "products"):
            if name not in stage["json"] and not (out_dir / f"{name}.json").exists() and bp is not None:
                fails.append(f"{name}.json missing from {out_dir} and not produced by build_products.py")
        for name in ("text", "literature"):
            if not (out_dir / f"{name}.json").exists():
                log.warning("%s.json (Agent D) not found in %s", name, out_dir)
        report["validation"] = {"ok": not fails, "failures": fails,
                                "pipeline_checks": {k: v["ok"] for k, v in stage.get("validation", {}).items() if not k.startswith("_")}}
        if fails:
            for f in fails:
                log.error("VALIDATION: %s", f)
            report["failures"] += fails
            log.error("nothing promoted; the published data are unchanged")
            return finish(2, "validation_failed")

        # -- promote ----------------------------------------------------------------------------------
        out_dir.mkdir(parents=True, exist_ok=True)
        for p in written:
            if p.name != "panel.json":
                shutil.copy2(p, out_dir / p.name)
        for k, p in e_written.items():
            shutil.copy2(p, out_dir / Path(p).name)
        if args.rebuild_panel or panel_is_stub:
            shutil.copy2(stage_root / "panel.json", Path(args.panel))
        for src, dst in data_written:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        # state (only after a successful promote)
        if avail is not None:
            when = iso(now)
            for p in pulls.mirror_months:
                fp, _ = avail.fingerprint(p, "M", codes)
                state.set_pulled(f"mirror:M:{p}", fp, int((pulls.mirror["period"].map(pstr) == p).sum()) if len(pulls.mirror) else 0, when)
                state.set_fp("M", p, fp)
                for c in codes:
                    state.set_stamp(c, "M", p, avail.stamp(c, "M", p))
            for p in plan.baseline:
                fp, _ = avail.fingerprint(p, "M", codes)
                state.set_fp("M", p, fp)
                for c in codes:
                    state.set_stamp(c, "M", p, avail.stamp(c, "M", p))
            for p in pulls.self_months:
                st = avail.stamp(SUBJECT, "M", p)
                state.set_pulled(f"self:M:{p}", st or "", int((pulls.self_["period"].map(pstr) == p).sum()) if len(pulls.self_) else 0, when)
                state.set_stamp(SUBJECT, "M", p, st)
            for p in avail.periods(SUBJECT, "M"):          # baseline for months already in the history
                if state.stamp(SUBJECT, "M", p) is None and p in raw_self_months:
                    state.set_stamp(SUBJECT, "M", p, avail.stamp(SUBJECT, "M", p))
            for y in pulls.fish_years:
                fp, _ = avail.fingerprint(str(y), "A", codes)
                state.set_pulled(f"fish:A:{y}", fp, int((pulls.fish_annual["year"].astype(int) == y).sum()) if len(pulls.fish_annual) else 0, when)
            for y in pulls.annual_years:
                fp, _ = avail.fingerprint(str(y), "A", codes)
                state.set_pulled(f"annual:A:{y}", fp, int((pulls.annual["period"].map(pstr) == str(y)).sum()) if len(pulls.annual) else 0, when)
            for c in codes:
                for y in avail.periods(c, "A"):
                    state.set_stamp(c, "A", y, avail.stamp(c, "A", y))
            state.d["last_run"] = {"at": when, "today": today_iso, "api_calls": client.run_calls, "tier": tier,
                                   "status": "partial" if pulls.partial else "complete"}
            state.save()
            pruned = prune_cache(cfg.cache_dir)
            if pruned:
                log.info("pruned %d old quota counters from the cache", pruned)
        report["promoted"] = {"site_json": sorted({p.name for p in written if p.name != 'panel.json'} | {Path(p).name for p in e_written.values()}),
                              "data_files": [str(d.relative_to(data_dir)) for _, d in data_written],
                              "state": str(state_path) if avail is not None else None}
        log.info("promoted %d JSON files to %s and %d data files to %s", len(report["promoted"]["site_json"]), out_dir,
                 len(data_written), data_dir)
        return finish(0, "partial" if pulls.partial else "ok")
    except Exception as exc:  # noqa: BLE001
        log.error("build failed: %s\n%s", exc, traceback.format_exc())
        report["failures"].append(f"build: {exc}")
        return finish(4, "error")
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


def main(argv=None) -> int:
    return run_update(build_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
