"""Raw extraction: the subject country's own reports, and the mirror reports.

The raw layer holds Comtrade observations and metadata only. No averaging, no
imputation, no mirror adjustment, no filling of gaps with zeros. A month that
was never reported must stay absent so that later stages can tell "reported
nothing" apart from "did not report".
"""
from __future__ import annotations

import logging

import pandas as pd

from .client import ComtradeClient, TruncatedResponse
from .config import ALL_PARTNERS, Config

log = logging.getLogger(__name__)

# Columns we insist on carrying through from the API, when present.
KEEP = [
    "typeCode", "freqCode", "refPeriodId", "refYear", "refMonth", "period",
    "reporterCode", "reporterISO", "reporterDesc",
    "partnerCode", "partnerISO", "partnerDesc",
    "partner2Code", "partner2Desc",
    "classificationCode", "classificationSearchCode", "isOriginalClassification",
    "cmdCode", "cmdDesc", "aggrLevel", "isLeaf",
    "flowCode", "flowDesc",
    "customsCode", "customsDesc", "motCode", "motDesc",
    "qtyUnitCode", "qtyUnitAbbr", "qty", "isQtyEstimated",
    "altQtyUnitCode", "altQty",
    "netWgt", "isNetWgtEstimated", "grossWgt",
    "cifvalue", "fobvalue", "primaryValue",
    "isReported", "isAggregate", "legacyEstimationFlag",
]

HS_CHAPTERS = [f"{c:02d}" for c in range(1, 100)]


def _counterparts(client: ComtradeClient, *, reporter_code, partner_code,
                  period: str, flow_code: str, split_dim: str) -> list[int]:
    """One cheap TOTAL call to learn which counterparts actually traded.

    Costs a single request and returns at most a couple of hundred codes, which
    is far cheaper than guessing at the full 254-country reporter list.
    """
    rows = client.get_data(
        reporter_code=reporter_code,
        partner_code=partner_code,
        period=period,
        flow_code=flow_code,
        cmd_code="TOTAL",
    )
    field = "partnerCode" if split_dim == "partner" else "reporterCode"
    codes = set()
    for r in rows:
        v = r.get(field)
        if v not in (None, 0, "0"):      # 0 is World, an aggregate of the rest
            codes.add(int(v))
    return sorted(codes)


def _fetch_by_prefix(
    client: ComtradeClient,
    *,
    reporter_code,
    partner_code,
    period: str,
    flow_code: str,
    prefixes: list[str] | None = None,
) -> list[dict]:
    """Subdivide by commodity WITHOUT losing HS6, using Comtrade's wildcards.

    `cmdCode=84????` returns the 6-digit leaves of chapter 84 (aggrLevel 6,
    isLeaf true) - unlike `cmdCode=84`, which returns the chapter aggregate.
    Wildcards may be comma-joined, so a batch of chapters costs one call.

    Used only when the country dimension is exhausted (both reporter and
    partner already fixed). Descends chapter -> heading -> subheading by
    appending a digit whenever a single prefix is still at the cap.
    """
    if prefixes is None:
        # Asking for all 99 chapters is the same query that just truncated, so
        # go straight to halves rather than spending a call to be told again.
        log.info("still truncated with both countries fixed; splitting %s %s "
                 "by HS chapter wildcard", period, flow_code)
        kw0 = dict(reporter_code=reporter_code, partner_code=partner_code,
                   period=period, flow_code=flow_code)
        mid0 = len(HS_CHAPTERS) // 2
        return (_fetch_by_prefix(client, prefixes=HS_CHAPTERS[:mid0], **kw0)
                + _fetch_by_prefix(client, prefixes=HS_CHAPTERS[mid0:], **kw0))

    cmd = ",".join(p + "?" * (6 - len(p)) for p in prefixes)
    try:
        return client.get_data(
            reporter_code=reporter_code,
            partner_code=partner_code,
            period=period,
            flow_code=flow_code,
            cmd_code=cmd,
        )
    except TruncatedResponse:
        pass

    kw = dict(reporter_code=reporter_code, partner_code=partner_code,
              period=period, flow_code=flow_code)

    if len(prefixes) > 1:
        mid = len(prefixes) // 2
        return (_fetch_by_prefix(client, prefixes=prefixes[:mid], **kw)
                + _fetch_by_prefix(client, prefixes=prefixes[mid:], **kw))

    # One prefix is still too broad: go one digit deeper (chapter -> heading).
    prefix = prefixes[0]
    if len(prefix) >= 6:
        raise TruncatedResponse(
            f"HS code {prefix} alone for reporter={reporter_code} "
            f"partner={partner_code} {period} {flow_code} exceeds the "
            f"{client.cfg.max_records}-record cap. Nothing left to subdivide; "
            f"use COMTRADE_TIER=premium or the bulk download."
        )
    return _fetch_by_prefix(
        client, prefixes=[prefix + str(d) for d in range(10)], **kw
    )


def _fetch_split(
    client: ComtradeClient,
    *,
    reporter_code,
    partner_code,
    period: str,
    flow_code: str,
    split_dim: str | None = None,
    counterparts: list[int] | None = None,
) -> list[dict]:
    """Fetch a slice at HS6, subdividing until nothing comes back truncated.

    The free tier caps a response at 500 rows with no "there is more" signal, so
    a response *at* the cap is assumed truncated and never accepted.

    Subdivision goes along the country dimension first, because it is the one
    that cannot cost us detail. When the commodity dimension must be split, it
    is split with wildcards (`84????`), never with bare chapter codes: asking
    for `cmdCode=01,02,...` does NOT return the HS6 lines within those chapters,
    it returns the chapters themselves at aggrLevel 2, isLeaf false, silently
    replacing product detail with chapter totals - the one thing this pipeline
    exists to preserve.

    The ladder: everything at once -> the counterparts that actually traded,
    halved recursively -> a single counterpart -> and, when even one country
    pair is too big, the commodity dimension via `NN????` wildcards, which do
    keep HS6 (see `_fetch_by_prefix`).
    """
    try:
        return client.get_data(
            reporter_code=reporter_code,
            partner_code=partner_code,
            period=period,
            flow_code=flow_code,
            cmd_code=None,          # AG6: HS6 detail, always
        )
    except TruncatedResponse:
        pass

    # Which country dimension is still open to subdivision?
    if split_dim is None:
        if partner_code is None:
            split_dim = "partner"
        elif reporter_code is None:
            split_dim = "reporter"
        else:
            # Both countries fixed - subdivide the commodity dimension instead.
            return _fetch_by_prefix(
                client, reporter_code=reporter_code, partner_code=partner_code,
                period=period, flow_code=flow_code,
            )

    if counterparts is None:
        counterparts = _counterparts(
            client, reporter_code=reporter_code, partner_code=partner_code,
            period=period, flow_code=flow_code, split_dim=split_dim,
        )
        log.info("truncated; splitting %s %s across %d %ss",
                 period, flow_code, len(counterparts), split_dim)

    if len(counterparts) <= 1:
        # A single counterpart still over the cap: subdivide by commodity.
        log.info("single %s %s for %s %s is over the cap; splitting by HS "
                 "chapter wildcard", split_dim, counterparts, period, flow_code)
        return _fetch_by_prefix(
            client, reporter_code=reporter_code, partner_code=partner_code,
            period=period, flow_code=flow_code,
        )

    mid = len(counterparts) // 2
    rows: list[dict] = []
    for half in (counterparts[:mid], counterparts[mid:]):
        code = ",".join(str(c) for c in half)
        rows.extend(
            _fetch_split(
                client,
                reporter_code=code if split_dim == "reporter" else reporter_code,
                partner_code=code if split_dim == "partner" else partner_code,
                period=period,
                flow_code=flow_code,
                split_dim=split_dim,
                counterparts=half,
            )
        )
    return rows


def _frame(rows: list[dict], side: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    keep = [c for c in KEEP if c in df.columns]
    df = df[keep].copy()
    df["side"] = side              # "self" or "mirror"
    df["period"] = df["period"].astype(str)
    return df


def available_periods(
    client: ComtradeClient, cfg: Config, periods: list[str] | None = None
) -> pd.DataFrame:
    """Step 1 - establish the real time span. Do not assume monthly continuity."""
    rows = client.get_availability(reporter_code=cfg.code)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if "period" in df.columns:
        df["period"] = df["period"].astype(str)
        if periods:
            df = df[df["period"].isin(periods)]
    return df


def pull_self(client: ComtradeClient, cfg: Config, periods: list[str]) -> pd.DataFrame:
    """Step 2 - the subject country as reporter, every partner kept separately."""
    frames = []
    for period in periods:
        for flow in ("X", "M"):
            rows = _fetch_split(
                client,
                reporter_code=cfg.code,
                partner_code=ALL_PARTNERS,
                period=period,
                flow_code=flow,
            )
            log.info("self %s %s: %d rows", period, flow, len(rows))
            frames.append(_frame(rows, "self"))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def pull_mirror(
    client: ComtradeClient,
    cfg: Config,
    periods: list[str],
    reporters: list[int] | None = None,
    batch_size: int = 40,
) -> pd.DataFrame:
    """Step 3 - every other reporter, with the subject country as partner.

    `reporters=None` omits reporterCode entirely, which is how Comtrade is asked
    for every reporter at once; `_fetch_split` then discovers and subdivides the
    reporters that actually traded if that response is truncated.
    """
    frames = []
    for period in periods:
        # A mirror reporter's IMPORT is the subject's export; and vice versa.
        for flow in ("M", "X"):
            if reporters is None:
                groups = [ALL_PARTNERS]
            else:
                groups = [
                    ",".join(str(c) for c in reporters[i : i + batch_size])
                    for i in range(0, len(reporters), batch_size)
                ]
            for group in groups:
                rows = _fetch_split(
                    client,
                    reporter_code=group,
                    partner_code=cfg.code,
                    period=period,
                    flow_code=flow,
                )
                frames.append(_frame(rows, "mirror"))
            log.info("mirror %s %s: %d rows", period, flow,
                     sum(len(f) for f in frames[-len(groups):]))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def dedupe_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Drop pre-aggregated and duplicate rows before anything is summed."""
    if df.empty:
        return df
    out = df.copy()
    n0 = len(out)

    # Partner=World would double count against the bilateral rows.
    if "partnerCode" in out.columns:
        out = out[pd.to_numeric(out["partnerCode"], errors="coerce") != 0]

    # Keep leaf HS6 only. NOTE: do NOT filter on `isAggregate` here. On this API
    # that flag marks a UN-estimated/aggregated *value*, not a broader HS level:
    # Kiribati's own H5 months come back with isAggregate=true and
    # isReported=false throughout, so filtering on it deletes the entire self
    # side of the comparison. `aggrLevel` is the field that means HS depth.
    if "cmdCode" in out.columns:
        out = out[out["cmdCode"].astype(str).str.upper() != "TOTAL"]
    if "aggrLevel" in out.columns and out["aggrLevel"].notna().any():
        out = out[pd.to_numeric(out["aggrLevel"], errors="coerce") == 6]
    elif "cmdCode" in out.columns:
        out = out[out["cmdCode"].astype(str).str.len() == 6]

    key = [
        c for c in
        ("side", "period", "reporterCode", "partnerCode", "flowCode",
         "cmdCode", "classificationCode", "customsCode", "motCode")
        if c in out.columns
    ]
    out = out.drop_duplicates(subset=key, keep="first")
    log.info("dedupe_raw: %d -> %d rows", n0, len(out))
    if n0 and len(out) / n0 < 0.25:
        log.warning(
            "dedupe_raw discarded %.0f%% of raw rows. If the extractor ever "
            "requests chapter codes instead of AG6, the API returns HS2 "
            "aggregates that this filter removes - check the raw cmdCode mix "
            "before trusting these results.",
            100 * (1 - len(out) / n0),
        )
    return out.reset_index(drop=True)
