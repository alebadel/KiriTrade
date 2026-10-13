"""Official reference tables. Never hand-type a label or a country code."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from .client import ComtradeClient
from .config import REFERENCE_URLS, Config

log = logging.getLogger(__name__)

# HS chapters used as the splitting axis when a query hits the record cap.
HS_CHAPTERS = [f"{c:02d}" for c in range(1, 100)]


def _fetch_reference(cfg: Config, client: ComtradeClient, name: str) -> pd.DataFrame:
    path = cfg.cache_dir / f"ref_{name}.json"
    if path.exists():
        payload = json.loads(path.read_text())
    else:
        payload = client.get(REFERENCE_URLS[name], {})
        path.write_text(json.dumps(payload))
    rows = payload.get("results", payload.get("data", payload))
    return pd.DataFrame(rows)


def load_references(cfg: Config, client: ComtradeClient) -> dict[str, pd.DataFrame]:
    """Reporters, partners, flows, units, field dictionary, HS codes."""
    out = {}
    for name in ("reporters", "partners", "flows", "units", "items"):
        try:
            out[name] = _fetch_reference(cfg, client, name)
        except Exception as exc:  # references are helpful, not load-bearing
            log.warning("could not load reference %r: %s", name, exc)
            out[name] = pd.DataFrame()
    return out


def reporter_codes(refs: dict[str, pd.DataFrame], exclude: int | None = None) -> list[int]:
    """Every country that reports to Comtrade, minus the subject country."""
    df = refs.get("reporters", pd.DataFrame())
    col = next((c for c in ("reporterCode", "id", "code") if c in df.columns), None)
    if col is None:
        return []
    codes = pd.to_numeric(df[col], errors="coerce").dropna().astype(int).tolist()
    # Drop aggregate/"world" pseudo-reporters and the subject itself.
    return sorted({c for c in codes if c > 0 and c != exclude})


def label_maps(refs: dict[str, pd.DataFrame]) -> dict[int, str]:
    df = refs.get("partners", pd.DataFrame())
    code_col = next((c for c in ("PartnerCode", "id", "code") if c in df.columns), None)
    name_col = next(
        (c for c in ("PartnerDesc", "text", "partnerDesc") if c in df.columns), None
    )
    if not code_col or not name_col:
        return {}
    return {
        int(r[code_col]): str(r[name_col])
        for _, r in df.iterrows()
        if str(r[code_col]).lstrip("-").isdigit()
    }
