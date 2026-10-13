"""HTTP client for the UN Comtrade API.

Design priorities, in order:
  1. Never silently truncate. A response at the record cap is treated as an
     error condition, not a result.
  2. Never spend a call twice. Every successful response is cached on disk,
     keyed by the full parameter set, so re-runs and crashes are cheap.
  3. Never exceed the daily quota - and never waste it. A 429 is a refusal,
     not a served request, so it is not charged against the budget.
  4. Never hide why a call failed. A 4xx response body is surfaced in the
     exception, because it is the only thing that names the bad parameter.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from datetime import date
from pathlib import Path

import requests

from .config import Config

log = logging.getLogger(__name__)


class TruncatedResponse(RuntimeError):
    """Raised when a query returned exactly the record cap: split it finer."""


class QuotaExhausted(RuntimeError):
    """The daily call allowance is spent - ours locally, or Comtrade's."""


class BadRequest(RuntimeError):
    """Comtrade rejected the query itself. Retrying cannot help."""


class ComtradeClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self._last_call = 0.0
        self._budget_path = cfg.cache_dir / f"quota_{date.today().isoformat()}.json"
        self._calls_today = self._load_budget()
        self._throttled = 0

    # ---------------------------------------------------------------- quota
    def _load_budget(self) -> int:
        if self._budget_path.exists():
            return json.loads(self._budget_path.read_text()).get("calls", 0)
        return 0

    def _spend(self) -> None:
        self._calls_today += 1
        self._budget_path.write_text(json.dumps({"calls": self._calls_today}))

    @staticmethod
    def _retry_after(resp) -> float:
        """Seconds Comtrade asks us to wait. It says so in the header or body."""
        hdr = resp.headers.get("Retry-After")
        if hdr:
            try:
                return float(hdr)
            except ValueError:
                pass
        m = re.search(r"[Tt]ry again in (\d+) second", resp.text or "")
        return float(m.group(1)) if m else 1.0

    @property
    def calls_remaining(self) -> int:
        return max(0, self.cfg.calls_per_day - self._calls_today)

    # ---------------------------------------------------------------- cache
    def _cache_path(self, url: str, params: dict) -> Path:
        safe = {k: v for k, v in sorted(params.items()) if k != "subscription-key"}
        digest = hashlib.sha256(
            (url + json.dumps(safe, sort_keys=True)).encode()
        ).hexdigest()[:24]
        return self.cfg.cache_dir / f"{digest}.json"

    # ------------------------------------------------------------- requests
    def get(self, url: str, params: dict, *, use_cache: bool = True) -> dict:
        """One GET, cached, retried, quota-counted. Returns parsed JSON."""
        cache = self._cache_path(url, params)
        if use_cache and cache.exists():
            log.debug("cache hit %s", cache.name)
            return json.loads(cache.read_text())

        if self.calls_remaining <= 0:
            raise QuotaExhausted(
                f"Local budget of {self.cfg.calls_per_day} calls/day is spent. "
                "Cached results are still readable; resume tomorrow or raise "
                "COMTRADE_CALLS_PER_DAY if your key allows more."
            )

        headers = {"Accept": "application/json"}
        if self.cfg.subscription_key:
            # Comtrade sits behind Azure APIM; both header spellings are honoured.
            headers["Ocp-Apim-Subscription-Key"] = self.cfg.subscription_key
            headers["subscription-key"] = self.cfg.subscription_key

        last_err: Exception | None = None
        attempt = -1
        throttle_waits = 0
        while attempt < self.cfg.max_retries - 1:
            attempt += 1
            gap = time.time() - self._last_call
            if gap < self.cfg.min_seconds_between_calls:
                time.sleep(self.cfg.min_seconds_between_calls - gap)
            try:
                self._last_call = time.time()
                r = self.session.get(
                    url, params=params, headers=headers, timeout=self.cfg.timeout
                )
                # A 429 was refused, not served: it does not consume the daily
                # allowance, so it must not consume our local budget either.
                # Charging throttle retries against the budget is what burned a
                # 480-call day less than halfway through the mirror pull.
                if r.status_code == 429:
                    self._throttled += 1
                    throttle_waits += 1
                    if throttle_waits > self.cfg.max_throttle_waits:
                        raise requests.HTTPError(
                            f"429 from Comtrade {throttle_waits} times in a row; "
                            f"giving up on this query. Raise "
                            f"min_seconds_between_calls in config.py."
                        )
                    wait = self._retry_after(r) + 0.5
                    log.info("rate limited; waiting %.1fs (throttled %d so far)",
                             wait, self._throttled)
                    time.sleep(wait)
                    attempt -= 1      # a refused call is not a failed attempt
                    continue
                self._spend()
                if 500 <= r.status_code < 600:
                    raise requests.HTTPError(f"{r.status_code}: {r.text[:300]}")
                if r.status_code in (401, 403):
                    body = r.text or ""
                    # Comtrade returns 403 for two unrelated things: the daily
                    # call allowance being spent, and the key not covering the
                    # endpoint. Telling them apart matters - one means "come
                    # back later", the other means "your setup is wrong".
                    if "quota" in body.lower():
                        m = re.search(r"replenished in ([0-9:]+)", body)
                        when = f" Replenishes in {m.group(1)}." if m else ""
                        raise QuotaExhausted(
                            f"Comtrade's own daily call quota is spent.{when}\n"
                            f"Everything fetched so far is cached, so re-running "
                            f"after that resumes where this stopped without "
                            f"re-spending calls.\nBody: {body[:200]}"
                        )
                    raise PermissionError(
                        f"{r.status_code} from Comtrade.\nURL  : {r.url}\n"
                        f"Body : {body[:400]}\n"
                        f"If this says the subscription does not cover the "
                        f"endpoint: a free key is not entitled to the premium "
                        f"'data/v1/get' path; set COMTRADE_TIER=free."
                    )
                if 400 <= r.status_code < 500:
                    # A malformed query will never succeed on retry. Surface the
                    # response body, which is the only thing that names the
                    # offending parameter.
                    raise BadRequest(
                        f"{r.status_code} from Comtrade.\nURL  : {r.url}\n"
                        f"Body : {r.text[:600]}"
                    )
                payload = r.json()
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                backoff = (2 ** attempt) + random.random()
                log.warning("call failed (%s), retrying in %.1fs", exc, backoff)
                time.sleep(backoff)
                continue

            cache.write_text(json.dumps(payload))
            return payload

        raise RuntimeError(f"Comtrade request failed after retries: {last_err}")

    # ----------------------------------------------------------- data query
    def get_data(
        self,
        *,
        reporter_code: int | str | None,
        partner_code: int | str | None,
        period: str,
        flow_code: str,
        cmd_code: str | None = None,
        type_code: str = "C",
        freq_code: str = "M",
        cl_code: str = "HS",
        extra: dict | None = None,
    ) -> list[dict]:
        """Fetch one slice of trade data. Raises TruncatedResponse at the cap."""
        url = f"{self.cfg.base_data_url}/{type_code}/{freq_code}/{cl_code}"
        params = {
            "period": period,
            "flowCode": flow_code,
            "cmdCode": cmd_code or self.cfg.cmd_code,
            "partner2Code": 0,          # pin: avoids second-partner row explosion
            "customsCode": "C00",       # pin: TOTAL customs procedure
            "motCode": 0,               # pin: TOTAL mode of transport
            "includeDesc": "true",
        }
        # A None code means "every one of them", and the only way to express
        # that is to leave the parameter out entirely: Comtrade rejects the
        # literal string "all" with 400 "The field <x> is invalid".
        if reporter_code is not None:
            params["reporterCode"] = reporter_code
        if partner_code is not None:
            params["partnerCode"] = partner_code
        if extra:
            params.update(extra)

        payload = self.get(url, params)
        rows = payload.get("data") or []
        if len(rows) >= self.cfg.max_records:
            raise TruncatedResponse(
                f"{len(rows)} rows returned for reporter={reporter_code} "
                f"partner={partner_code} period={period} flow={flow_code} "
                f"cmd={params['cmdCode']}, at or above the "
                f"{self.cfg.max_records}-record cap for the '{self.cfg.tier}' "
                f"tier. Subdividing rather than accepting it."
            )
        return rows

    def get_availability(
        self,
        *,
        reporter_code: int | str,
        period: str | None = None,
        type_code: str = "C",
        freq_code: str = "M",
        cl_code: str = "HS",
    ) -> list[dict]:
        """Which reporter-period datasets actually exist. Cheap; call first."""
        url = f"{self.cfg.availability_url}/{type_code}/{freq_code}/{cl_code}"
        params = {"reporterCode": reporter_code}
        if period:
            params["period"] = period
        return self.get(url, params).get("data") or []
