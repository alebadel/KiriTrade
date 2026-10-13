"""A fake Comtrade API for testing update.py's live path with no network.

The sandbox cannot reach comtradeapi.un.org, so this stands in for it. It
serves getDa and data responses built from the committed history
(raw_observations.parquet), plus whatever extra months the test injects.
It is a drop-in for `requests.Session` (only `.get` is used by the client).
"""
from __future__ import annotations

import json
from urllib.parse import parse_qsl, urlsplit

import pandas as pd


class FakeResponse:
    def __init__(self, status: int, payload, url: str):
        self.status_code = status
        self._payload = payload
        self.url = url
        self.headers = {}
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class FakeComtrade:
    """Holds a table of HS6 rows (same columns as the raw parquet) and an availability table."""

    def __init__(self, raw: pd.DataFrame, released: dict[tuple[int, str, str], str] | None = None,
                 max_records: int = 250_000):
        self.raw = raw.copy()
        self.raw["period"] = self.raw["period"].astype(str)
        self.released = dict(released or {})     # (reporter, freq, period) -> lastReleased
        self.max_records = max_records
        self.calls: list[tuple[str, dict]] = []
        self.fail_next: int = 0                  # inject HTTP 500s

    # -- helpers for the test -------------------------------------------------
    def availability_rows(self, reporter: int, freq: str) -> list[dict]:
        out = []
        for (rc, f, p), lr in sorted(self.released.items()):
            if rc == reporter and f == freq:
                out.append({"reporterCode": rc, "freqCode": f, "period": p, "lastReleased": lr,
                            "classificationCode": "H6", "totalRecords": 1000})
        return out

    def add_rows(self, rows: pd.DataFrame) -> None:
        rows = rows.copy(); rows["period"] = rows["period"].astype(str)
        self.raw = pd.concat([self.raw, rows], ignore_index=True)

    # -- requests.Session API ---------------------------------------------------
    def get(self, url, params=None, headers=None, timeout=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if self.fail_next > 0:
            self.fail_next -= 1
            return FakeResponse(500, "boom", url)
        if headers is None or not (headers.get("Ocp-Apim-Subscription-Key") or headers.get("subscription-key")):
            return FakeResponse(401, "no key", url)
        parts = urlsplit(url).path.strip("/").split("/")
        if "getDa" in parts:
            freq = parts[-2]
            reps = str(params.get("reporterCode", ""))
            rows = []
            for r in reps.split(","):
                if r.strip():
                    rows += self.availability_rows(int(r), freq)
            return FakeResponse(200, {"data": rows, "count": len(rows)}, url)
        if parts[-3] != "C":
            return FakeResponse(400, "bad path", url)
        freq = parts[-2]
        period = str(params.get("period"))
        periods = set(period.split(","))
        flow = params.get("flowCode")
        cmd = str(params.get("cmdCode", "AG6"))
        df = self.raw
        if freq == "M":
            df = df[df["period"].isin(periods)]
        else:
            df = df[df["period"].str[:4].isin(periods) & (df["freqCode"] == "A")] if "freqCode" in df else df.iloc[0:0]
        df = df[df["flowCode"] == flow]
        if "reporterCode" in params:
            codes = {int(c) for c in str(params["reporterCode"]).split(",")}
            df = df[df["reporterCode"].isin(codes)]
        else:
            df = df[df["reporterCode"] != 296] if "partnerCode" in params else df
        if "partnerCode" in params:
            codes = {int(c) for c in str(params["partnerCode"]).split(",")}
            df = df[df["partnerCode"].isin(codes)]
        if cmd == "TOTAL":
            g = df.groupby(["period", "reporterCode", "partnerCode", "flowCode"], as_index=False)["primaryValue"].sum()
            g["cmdCode"] = "TOTAL"; g["aggrLevel"] = 0
            rows = g.to_dict("records")
        elif cmd == "AG6":
            rows = df.to_dict("records")
        else:
            pats = [c.strip() for c in cmd.split(",")]
            def ok(code):
                code = str(code).zfill(6)
                return any(all(pc == "?" or pc == cc for pc, cc in zip(p, code)) and len(p) == 6 for p in pats)
            rows = df[df["cmdCode"].map(ok)].to_dict("records")
        rows = rows[: self.max_records]
        return FakeResponse(200, {"data": json.loads(pd.DataFrame(rows).to_json(orient="records")) if rows else []}, url)
